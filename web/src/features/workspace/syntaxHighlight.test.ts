import { describe, expect, it } from "vitest";

import { tokenizeLine } from "./syntaxHighlight";

describe("tokenizeLine", () => {
  it("highlights common code tokens without changing their text", () => {
    const source = 'const answer = "done"; // result';
    const tokens = tokenizeLine(source, "typescript");

    expect(tokens.map((token) => token.text).join("")).toBe(source);
    expect(tokens).toEqual(expect.arrayContaining([
      { kind: "keyword", text: "const" },
      { kind: "string", text: '"done"' },
      { kind: "comment", text: "// result" },
    ]));
  });

  it("keeps comment markers inside strings as string content", () => {
    expect(tokenizeLine('const url = "https://example.com";', "javascript"))
      .toContainEqual({ kind: "string", text: '"https://example.com"' });
  });

  it("leaves plain text untouched", () => {
    expect(tokenizeLine("IntentFlow workspace", "text"))
      .toEqual([{ kind: "plain", text: "IntentFlow workspace" }]);
  });
});
