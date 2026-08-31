import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CodeWorkspace, type OpenWorkspaceFile } from "./CodeWorkspace";

const openFile: OpenWorkspaceFile = {
  key: "src/main.js",
  path: "src/main.js",
  state: "ready",
  file: {
    path: "src/main.js",
    content: "const value = 1;\n",
    size: 17,
    language: "javascript",
  },
  draft: "const value = 2;\n",
  revision: 1,
  saving: false,
  saveError: "",
  error: "",
};

describe("CodeWorkspace", () => {
  it("renders an editable draft with automatic-save status and no action toolbar", () => {
    const html = renderToStaticMarkup(
      <CodeWorkspace
        files={[openFile]}
        activeFileKey={openFile.key}
        editable
        onSelectFile={() => undefined}
        onCloseFile={() => undefined}
        onChangeFile={() => undefined}
      />,
    );

    expect(html).toContain("等待自动保存…");
    expect(html).not.toContain("撤销未保存");
    expect(html).not.toContain("重新测试");
    expect(html).toContain('aria-label="src/main.js 编辑器"');
    expect(html).toContain("syntax-token--keyword");
    expect(html).toContain("const value = 2;");
  });
});
