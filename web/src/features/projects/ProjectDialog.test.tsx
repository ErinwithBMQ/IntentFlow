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
});
