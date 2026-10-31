import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import SafetyCenter from "./SafetyCenter.jsx";
import { backendApi, safetyApi } from "../services/api";

vi.mock("../services/api", () => ({
  backendApi: { emergencyResources: vi.fn().mockResolvedValue({ country: "India", number: "112", dial_uri: "tel:112", status_note: "Dial action only." }) },
  contactsApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
  safetyApi: {
    status: vi.fn().mockResolvedValue({ status: "ok" }),
    contacts: vi.fn().mockResolvedValue({ items: [] }),
    shares: vi.fn().mockResolvedValue({ items: [] }),
    sosEvents: vi.fn().mockResolvedValue({ items: [] }),
    recordSOS: vi.fn().mockResolvedValue({ status: "recorded" }),
  },
}));

afterEach(cleanup);

describe("SafetyCenter emergency API integration", () => {
  it("loads emergency resources and records SOS before the user opens the dialer", async () => {
    render(<SafetyCenter pendingSOS={true}/>);


    expect(await screen.findByText("112")).toBeInTheDocument();
    expect(backendApi.emergencyResources).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: /Open SOS confirmation/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));

    expect(await screen.findByText(/Your SOS request was recorded by NAVIRA/)).toBeInTheDocument();
    expect(safetyApi.recordSOS).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: /Open SOS confirmation/ })).toBeInTheDocument();
  });

  it("shows an error and does not claim the backend recorded SOS when the request fails", async () => {
    safetyApi.recordSOS.mockRejectedValueOnce(new Error("Backend unavailable"));
    render(<SafetyCenter pendingSOS={true}/>);

    fireEvent.click(await screen.findByRole("button", { name: /Open SOS confirmation/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));

    expect(await screen.findByText(/could not record the SOS request: Backend unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/Your SOS request was recorded by NAVIRA/)).not.toBeInTheDocument();
  });
});
