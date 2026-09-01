import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProjectDialog } from "./ProjectDialog";

describe("ProjectDialog", () => {
  it("shows the required first-project onboarding without a close button", () => {
    const html = renderToStaticMarkup(
      <ProjectDialog
        open
        required
        project={null}
        busy={false}
        error=""
        onClose={() => undefined}
        onPickExisting={() => undefined}
        onPickParent={() => Promise.resolve(null)}
        onRegisterPath={() => undefined}
        onCreate={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(html).toContain("选择一个项目开始");
    expect(html).toContain("打开文件夹选择器");
    expect(html).toContain("手动输入绝对路径");
    expect(html).not.toContain('aria-label="关闭项目管理"');
  });

  it("separates project settings from command configuration", () => {
    const html = renderToStaticMarkup(
      <ProjectDialog
        open
        required={false}
        project={{
          id: "project-1",
          name: "demo",
          root_path: "E:\\demo",
          relative_path: "",
          test_command: null,
          build_command: null,
          lint_command: null,
          typecheck_command: null,
          ignored_names: ["node_modules"],
          prompt: "",
          created_at: "",
          updated_at: "",
          last_opened_at: "",
          ready: true,
        }}
        busy={false}
        error=""
        onClose={() => undefined}
        onPickExisting={() => undefined}
        onPickParent={() => Promise.resolve(null)}
        onRegisterPath={() => undefined}
        onCreate={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(html).toContain("项目设置");
    expect(html).toContain("命令配置");
  });
});
