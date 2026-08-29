import { describe, expect, it } from "vitest";

import {
  diffLineKind,
  languageFromPath,
  relatedFileDestination,
  workspaceFileKey,
} from "./workspaceState";

describe("workspace state helpers", () => {
  it("keeps project and run files separate", () => {
    expect(workspaceFileKey("project", "src/tasks.js")).toBe("project:src/tasks.js");
    expect(workspaceFileKey("run", "src/tasks.js")).toBe("run:src/tasks.js");
  });

  it("opens changed related files in Diff and unchanged files in code", () => {
    const changes = {
      changed_files: 1,
      additions: 2,
      deletions: 1,
      files: [
        {
          path: "src/tasks.js",
          status: "modified" as const,
          additions: 2,
          deletions: 1,
          viewable: true,
          unavailable_reason: null,
        },
      ],
    };

    expect(relatedFileDestination(changes, "src/tasks.js")).toBe("diff");
    expect(relatedFileDestination(changes, "src/main.js")).toBe("code");
  });

  it("classifies unified diff lines", () => {
    expect(diffLineKind("--- a/source.js")).toBe("header");
    expect(diffLineKind("+++ b/source.js")).toBe("header");
    expect(diffLineKind("@@ -1 +1 @@")).toBe("hunk");
    expect(diffLineKind("+new")).toBe("addition");
    expect(diffLineKind("-old")).toBe("deletion");
    expect(diffLineKind(" unchanged")).toBe("context");
  });

  it("infers the highlighting language from a file path", () => {
    expect(languageFromPath("src/App.tsx")).toBe("typescript");
    expect(languageFromPath("config/settings.yaml")).toBe("yaml");
    expect(languageFromPath("LICENSE")).toBe("text");
  });
});
