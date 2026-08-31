from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.workspaces import DEFAULT_IGNORED_NAMES

ProjectTemplate = Literal["empty", "web"]
PROJECT_NAME_PATTERN = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+$")


class ProjectRecord(BaseModel):
    id: str
    name: str
    root_path: str = ""
    relative_path: str = ""
    test_command: list[str] | None = None
    build_command: list[str] | None = None
    ignored_names: list[str] = Field(default_factory=lambda: sorted(DEFAULT_IGNORED_NAMES))
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""


class ProjectRegistrationError(ValueError):
    """Raised when a local directory cannot be registered as a project."""


class ProjectRegistry:
    def __init__(
        self,
        database_path: Path,
        repository_root: Path,
        *,
        runtime_root: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.repository_root = repository_root.resolve()
        self.runtime_root = (runtime_root or repository_root / "runtime-data").resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def list(self) -> list[ProjectRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY last_opened_at DESC, created_at DESC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, project_id: str) -> ProjectRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_active(self) -> ProjectRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT projects.*
                FROM app_settings
                JOIN projects ON projects.id = app_settings.value
                WHERE app_settings.key = 'active_project_id'
                """
            ).fetchone()
        if row is not None:
            return self._from_row(row)
        projects = self.list()
        return projects[0] if projects else None

    def register(self, root_path: str | Path) -> ProjectRecord:
        root = self._validate_root(root_path)
        root_key = self._path_key(root)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM projects WHERE root_key = ?",
                (root_key,),
            ).fetchone()
            if existing is not None:
                project = self._from_row(existing)
                self._activate(connection, project.id)
                return self.get(project.id) or project

            now = _now()
            project = ProjectRecord(
                id=f"project-{uuid4().hex[:12]}",
                name=root.name,
                root_path=str(root),
                relative_path=self._relative_path(root),
                test_command=self._detect_test_command(root),
                build_command=self._detect_build_command(root),
                created_at=now,
                updated_at=now,
                last_opened_at=now,
            )
            connection.execute(
                """
                INSERT INTO projects (
                  id, name, relative_path, root_path, root_key,
                  test_command_json, build_command_json, ignored_names_json,
                  created_at, updated_at, last_opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.id,
                    project.name,
                    project.relative_path,
                    project.root_path,
                    root_key,
                    _json_or_none(project.test_command),
                    _json_or_none(project.build_command),
                    json.dumps(project.ignored_names, ensure_ascii=False),
                    now,
                    now,
                    now,
                ),
            )
            self._activate(connection, project.id, now=now)
        return project

    def create(
        self,
        parent_path: str | Path,
        name: str,
        template: ProjectTemplate,
    ) -> ProjectRecord:
        parent = Path(parent_path).expanduser().resolve(strict=True)
        if not parent.is_dir():
            raise ProjectRegistrationError("父目录不存在或不是文件夹")
        if _is_within(self.runtime_root, parent):
            raise ProjectRegistrationError("不能在 IntentFlow 的运行目录中创建项目")
        normalized_name = name.strip()
        if (
            not normalized_name
            or normalized_name in {".", ".."}
            or not PROJECT_NAME_PATTERN.fullmatch(normalized_name)
        ):
            raise ProjectRegistrationError("项目名称包含 Windows 不允许的字符")
        target = parent / normalized_name
        if target.exists():
            raise ProjectRegistrationError("目标文件夹已经存在")
        try:
            target.mkdir()
            if template == "web":
                self._write_web_template(target, normalized_name)
            else:
                (target / "README.md").write_text(
                    f"# {normalized_name}\n",
                    encoding="utf-8",
                )
        except OSError as error:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise ProjectRegistrationError(f"创建项目失败：{error}") from error
        return self.register(target)

    def activate(self, project_id: str) -> ProjectRecord:
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        with self._lock, self._connect() as connection:
            self._activate(connection, project_id)
        return self.get(project_id) or project

    def update(
        self,
        project_id: str,
        *,
        name: str,
        test_command: list[str] | None,
        build_command: list[str] | None,
        ignored_names: list[str],
    ) -> ProjectRecord:
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        normalized_name = name.strip()
        if not normalized_name:
            raise ProjectRegistrationError("项目名称不能为空")
        clean_ignored = sorted(
            {
                item.strip()
                for item in ignored_names
                if item.strip() and "/" not in item and "\\" not in item
            }
            | set(DEFAULT_IGNORED_NAMES)
        )
        clean_test = _validate_command(test_command)
        clean_build = _validate_command(build_command)
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET name = ?, test_command_json = ?, build_command_json = ?,
                    ignored_names_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_name,
                    _json_or_none(clean_test),
                    _json_or_none(clean_build),
                    json.dumps(clean_ignored, ensure_ascii=False),
                    now,
                    project_id,
                ),
            )
        updated = self.get(project_id)
        if updated is None:
            raise KeyError(project_id)
        return updated

    def require_root(self, project_id: str) -> Path:
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        return self._validate_root(project.root_path)

    def _validate_root(self, root_path: str | Path) -> Path:
        try:
            path_text = str(root_path).strip().strip('"')
            root = Path(path_text).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ProjectRegistrationError("项目文件夹不存在或无法访问") from error
        if not root.is_dir():
            raise ProjectRegistrationError("项目路径必须指向文件夹")
        if _is_within(self.runtime_root, root):
            raise ProjectRegistrationError("不能把 IntentFlow 的运行数据目录登记为项目")
        if not os.access(root, os.R_OK | os.W_OK):
            raise ProjectRegistrationError("项目文件夹必须可读写")
        try:
            next(root.iterdir(), None)
        except OSError as error:
            raise ProjectRegistrationError("项目文件夹无法读取") from error
        return root

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  relative_path TEXT NOT NULL DEFAULT '',
                  root_path TEXT,
                  root_key TEXT,
                  test_command_json TEXT,
                  build_command_json TEXT,
                  ignored_names_json TEXT,
                  created_at TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL DEFAULT '',
                  last_opened_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(projects)")
            }
            additions = {
                "root_path": "TEXT",
                "root_key": "TEXT",
                "test_command_json": "TEXT",
                "build_command_json": "TEXT",
                "ignored_names_json": "TEXT",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "last_opened_at": "TEXT NOT NULL DEFAULT ''",
            }
            for column, declaration in additions.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE projects ADD COLUMN {column} {declaration}")

            now = _now()
            rows = connection.execute("SELECT * FROM projects").fetchall()
            for row in rows:
                root_text = row["root_path"] or ""
                if not root_text and row["relative_path"]:
                    root_text = str(
                        (self.repository_root / Path(row["relative_path"])).resolve()
                    )
                root = Path(root_text) if root_text else self.repository_root
                ignored = row["ignored_names_json"] or json.dumps(
                    sorted(DEFAULT_IGNORED_NAMES), ensure_ascii=False
                )
                test_command = row["test_command_json"]
                build_command = row["build_command_json"]
                if root_text and not test_command:
                    test_command = _json_or_none(self._detect_test_command(root))
                if root_text and not build_command:
                    build_command = _json_or_none(self._detect_build_command(root))
                connection.execute(
                    """
                    UPDATE projects
                    SET root_path = ?, root_key = ?, test_command_json = ?,
                        build_command_json = ?, ignored_names_json = ?,
                        created_at = ?, updated_at = ?, last_opened_at = ?
                    WHERE id = ?
                    """,
                    (
                        root_text,
                        self._path_key(root) if root_text else "",
                        test_command,
                        build_command,
                        ignored,
                        row["created_at"] or now,
                        row["updated_at"] or now,
                        row["last_opened_at"] or now,
                        row["id"],
                    ),
                )

    def _activate(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        *,
        now: str | None = None,
    ) -> None:
        timestamp = now or _now()
        connection.execute(
            "UPDATE projects SET last_opened_at = ? WHERE id = ?",
            (timestamp, project_id),
        )
        connection.execute(
            """
            INSERT INTO app_settings (key, value) VALUES ('active_project_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (project_id,),
        )

    def _relative_path(self, root: Path) -> str:
        try:
            return root.relative_to(self.repository_root).as_posix()
        except ValueError:
            return ""

    @staticmethod
    def _path_key(root: Path) -> str:
        value = os.path.normcase(str(root.resolve()))
        return value.casefold()

    def _from_row(self, row: sqlite3.Row) -> ProjectRecord:
        root_text = row["root_path"] or ""
        if not root_text and row["relative_path"]:
            root_text = str((self.repository_root / Path(row["relative_path"])).resolve())
        return ProjectRecord(
            id=row["id"],
            name=row["name"],
            root_path=root_text,
            relative_path=row["relative_path"],
            test_command=_load_command(row["test_command_json"]),
            build_command=_load_command(row["build_command_json"]),
            ignored_names=_load_ignored(row["ignored_names_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_opened_at=row["last_opened_at"],
        )

    @staticmethod
    def _detect_test_command(root: Path) -> list[str] | None:
        package = _read_package_json(root)
        scripts = package.get("scripts") if package else None
        script = str(scripts.get("test", "")) if isinstance(scripts, dict) else ""
        node = shutil.which("node")
        vitest = root / "node_modules" / "vitest" / "vitest.mjs"
        if script and "vitest" in script and node and vitest.is_file():
            return [node, str(vitest), "run", "--root", "{workspace}"]
        if script:
            return ["npm", "test"]

        python = _project_python(root)
        if python and any((root / name).exists() for name in ("pyproject.toml", "pytest.ini")):
            return [str(python), "-m", "pytest", "{workspace}"]
        return None

    @staticmethod
    def _detect_build_command(root: Path) -> list[str] | None:
        package = _read_package_json(root)
        scripts = package.get("scripts") if package else None
        script = str(scripts.get("build", "")) if isinstance(scripts, dict) else ""
        node = shutil.which("node")
        vite = root / "node_modules" / "vite" / "bin" / "vite.js"
        if script and "vite build" in script and node and vite.is_file():
            return [node, str(vite), "build", "{workspace}"]
        if script:
            return ["npm", "run", "build"]
        return None

    @staticmethod
    def _write_web_template(root: Path, name: str) -> None:
        (root / "src").mkdir()
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": _package_name(name),
                    "private": True,
                    "version": "0.0.0",
                    "scripts": {"test": "node --test", "build": "node build.mjs"},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "index.html").write_text(
            """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>IntentFlow Web Project</title>
    <link rel="stylesheet" href="./src/style.css" />
  </head>
  <body>
    <main id="app"></main>
    <script type="module" src="./src/main.js"></script>
  </body>
</html>
""",
            encoding="utf-8",
        )
        (root / "src" / "main.js").write_text(
            """const app = document.querySelector("#app");

app.innerHTML = `
  <section class="card">
    <span>IntentFlow Starter</span>
    <h1>开始描述你想构建的功能</h1>
    <p>这个项目使用原生 HTML、CSS 和 JavaScript，无需安装依赖。</p>
  </section>
`;
""",
            encoding="utf-8",
        )
        (root / "src" / "style.css").write_text(
            """* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: grid;
  place-items: center;
  font-family: system-ui, sans-serif;
  background: #f5f3ee;
  color: #202521;
}
.card {
  width: min(560px, calc(100vw - 40px));
  padding: 48px;
  border: 1px solid #deddd7;
  border-radius: 18px;
  background: #fffefa;
  box-shadow: 0 18px 60px rgb(38 44 40 / 10%);
}
.card span {
  color: #3b6cff;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.card h1 {
  margin: 14px 0 10px;
  font-size: clamp(28px, 6vw, 48px);
  line-height: 1.08;
}
.card p { margin: 0; color: #68706b; line-height: 1.7; }
""",
            encoding="utf-8",
        )
        (root / "build.mjs").write_text(
            """import { cp, mkdir, rm } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await mkdir("dist/src", { recursive: true });
await cp("index.html", "dist/index.html");
await cp("src", "dist/src", { recursive: true });
console.log("Built dist/");
""",
            encoding="utf-8",
        )
        (root / "app.test.mjs").write_text(
            """import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("starter page contains an app root", async () => {
  const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
  assert.match(html, /id="app"/);
});
""",
            encoding="utf-8",
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def choose_directory() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as error:
        raise ProjectRegistrationError("系统文件夹选择器不可用，请改用手动路径") from error

    root: tk.Tk | None = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(title="选择 IntentFlow 项目文件夹", mustexist=True)
    except (OSError, RuntimeError, tk.TclError) as error:
        raise ProjectRegistrationError("系统文件夹选择器不可用，请改用手动路径") from error
    finally:
        if root is not None:
            with suppress(tk.TclError):
                root.destroy()
    return selected or None


def _read_package_json(root: Path) -> dict[str, object] | None:
    try:
        payload = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _project_python(root: Path) -> Path | None:
    candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        Path(sys.executable),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _validate_command(command: list[str] | None) -> list[str] | None:
    if command is None:
        return None
    clean = [part.strip() for part in command if part.strip()]
    if not clean:
        return None
    if len(clean) > 32 or any(len(part) > 1_000 for part in clean):
        raise ProjectRegistrationError("命令配置过长")
    return clean


def _load_command(payload: str | None) -> list[str] | None:
    if not payload:
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


def _load_ignored(payload: str | None) -> list[str]:
    if payload:
        try:
            value = json.loads(payload)
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                return sorted(set(value) | set(DEFAULT_IGNORED_NAMES))
        except json.JSONDecodeError:
            pass
    return sorted(DEFAULT_IGNORED_NAMES)


def _json_or_none(value: list[str] | None) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value else None


def _is_within(parent: Path, target: Path) -> bool:
    try:
        target.relative_to(parent)
        return True
    except ValueError:
        return False


def _package_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", name.casefold()).strip("-._")
    return normalized or "intentflow-project"


def _now() -> str:
    return datetime.now(UTC).isoformat()
