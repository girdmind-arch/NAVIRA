import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import JourneySafetyMonitor from "./JourneySafetyMonitor.jsx";
import { journeySafetyApi } from "../services/journeySafety";
import { safetyApi } from "../services/api";

vi.mock("../services/api", () => ({
  safetyApi: { recordSOS: vi.fn(() => Promise.resolve({})) },
  contactsApi: { list: vi.fn(() => Promise.resolve([{ id: 1, name: "Mum", phone: "+919876543210" }])) },
}));

vi.mock("../services/journeySafety", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    journeySafetyApi: {
      heartbeat: vi.fn(() => Promise.resolve({ config: { ...actual.DEFAULT_SAFETY_CONFIG, safety_check_window_s: 90 }, active_sos: null })),
      sos: vi.fn(() => Promise.resolve({
        id: "s1", reason: "no_response_to_safety_checks", live_link: "https://navira.test/#/live/abc",
        message: "SOS EMERGENCY! I am in danger and need immediate help. My current location is: https://navira.test/#/live/abc. Please help me immediately!",
        notifications: { contacts: [{ contact_id: 1, name: "Mum", phone: "+919876543210", status: "not_configured" }], police: { status: "unavailable", detail: "No police-station alert integration is available, so the nearest police station was not notified." } },
      })),
      resolve: vi.fn(() => Promise.resolve({ status: "resolved" })),
    },
  };
});

const journey = { id: 9, status: "in_progress" };
const fixAt = (time) => ({ latitude: 28.6139, longitude: 77.209, accuracy: 15, timestamp: time });

async function advance(ms) {
  await act(async () => { vi.advanceTimersByTime(ms); });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date("2026-10-31T10:00:00Z"));
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: vi.fn() } });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

function renderWithFixes() {
  const view = render(<JourneySafetyMonitor journey={journey} fix={fixAt(Date.now())}/>);
  return {
    ...view,
    stayStill: async (minutes) => {
      for (let i = 0; i < minutes * 4; i += 1) {
        await advance(15000);
        view.rerender(<JourneySafetyMonitor journey={journey} fix={fixAt(Date.now())}/>);
      }
    },
  };
}

describe("JourneySafetyMonitor", () => {
  it("asks after 5 stationary minutes, sends 3 alerts, then triggers SOS once with honest statuses", async () => {
    const { stayStill } = renderWithFixes();
    await stayStill(4.75);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await stayStill(0.5);
    expect(screen.getByText("You've been stationary for 5 minutes. Are you safe?")).toBeTruthy();
    expect(screen.getByText(/SAFETY CHECK 1 OF 3/)).toBeTruthy();
    await advance(30000);
    expect(screen.getByText(/SAFETY CHECK 2 OF 3/)).toBeTruthy();
    await advance(30000);
    expect(screen.getByText(/SAFETY CHECK 3 OF 3/)).toBeTruthy();
    await advance(31000);
    expect(journeySafetyApi.sos).toHaveBeenCalledTimes(1);
    expect(journeySafetyApi.sos).toHaveBeenCalledWith(9, "no_response_to_safety_checks");
    expect(safetyApi.recordSOS).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Not sent automatically/)).toBeTruthy();
    expect(screen.getByText(/nearest police station was not notified/)).toBeTruthy();
    await advance(120000);
    expect(journeySafetyApi.sos).toHaveBeenCalledTimes(1);
  });

  it("cancels escalation when the user is safe and restarts the timer", async () => {
    const { stayStill } = renderWithFixes();
    await stayStill(5.25);
    fireEvent.click(screen.getByText("I'm Safe"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await advance(200000);
    expect(journeySafetyApi.sos).not.toHaveBeenCalled();
  });

  it("triggers SOS immediately on I Need Help", async () => {
    const { stayStill } = renderWithFixes();
    await stayStill(5.25);
    fireEvent.click(screen.getByText("I Need Help"));
    await advance(0);
    expect(journeySafetyApi.sos).toHaveBeenCalledWith(9, "user_requested_help");
  });

  it("shows an SOS raised by the server after missed heartbeats", async () => {
    journeySafetyApi.heartbeat.mockResolvedValueOnce({ active_sos: { id: "srv", reason: "connectivity_lost", message: "SOS EMERGENCY! ... Last known location", live_link: "https://navira.test/#/live/x", notifications: { contacts: [], police: { detail: "No police integration." } } } });
    render(<JourneySafetyMonitor journey={journey} fix={null}/>);
    await advance(0);
    expect(screen.getByText(/lost connection with this phone/)).toBeTruthy();
    expect(screen.queryByText(/switched off/i)).toBeNull();
  });
});
