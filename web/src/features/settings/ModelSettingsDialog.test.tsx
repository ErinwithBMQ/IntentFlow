import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ModelSettingsDialog } from "./ModelSettingsDialog";

describe("ModelSettingsDialog", () => {
  it("shows provider settings without exposing the stored API key", () => {
    const html = renderToStaticMarkup(
      <ModelSettingsDialog
        open
        settings={{
          base_url: "https://api.example.com/v1",
          models: ["model-a", "model-b"],
          active_model: "model-b",
          has_api_key: true,
        }}
        busy={false}
        error=""
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(html).toContain("模型配置");
    expect(html).toContain("已配置，留空表示保持不变");
    expect(html).toContain('type="password"');
    expect(html).not.toContain("api_key");
  });
});
