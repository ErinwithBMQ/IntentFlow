import { afterEach, describe, expect, it, vi } from "vitest";

import { getHealth } from "./api";

describe("getHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the backend health payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ status: "ok", service: "intentflow-server", version: "0.1.0" }),
          { status: 200 },
        ),
      ),
    );

    await expect(getHealth()).resolves.toEqual({
      status: "ok",
      service: "intentflow-server",
      version: "0.1.0",
    });
  });

  it("reports a failed backend request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    await expect(getHealth()).rejects.toThrow("请求失败：503");
  });
});

