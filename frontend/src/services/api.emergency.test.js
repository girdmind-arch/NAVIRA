import { afterEach, describe, expect, it, vi } from "vitest";
import { backendApi, safetyApi } from "./api.js";

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("emergency backend API calls", () => {
  it("loads emergency resources from the configured same-origin API path", async () => {
    const payload = { country: "India", number: "112", dial_uri: "tel:112" };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);

    await expect(backendApi.emergencyResources()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/emergency/resources", expect.any(Object));
  });

  it("posts SOS to the private endpoint and returns the backend receipt", async () => {
    const payload = { status: "recorded", notice: "No contacts were notified." };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);

    await expect(safetyApi.recordSOS()).resolves.toEqual(payload);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/safety/sos");
    expect(options.method).toBe("POST");
    expect(options.body).toBe("{}");
    expect(options.headers.get("Authorization")).toMatch(/^Bearer [a-f0-9]{64}$/);
  });
});
