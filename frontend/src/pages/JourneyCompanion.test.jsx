import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import JourneyCompanion from "./JourneyCompanion.jsx";
import { journeysApi } from "../services/api";

vi.mock("../services/api", () => ({
  journeysApi: {
    active: vi.fn(),
    start: vi.fn(),
    complete: vi.fn(),
  },
}));

vi.mock("../components/MapView", () => ({ default: () => <div data-testid="route-map"/> }));

const inProgressJourney = {
  id: 42,
  origin: "Start point",
  destination: "Destination",
  route_id: "selected-route",
  status: "in_progress",
  started_at: "2026-10-31T10:00:00.000Z",
  route: {
    distance_m: 5000,
    duration_s: 900,
    geometry: { type: "LineString", coordinates: [[77.2, 28.6], [77.3, 28.7]] },
  },
};

const completedJourney = { ...inProgressJourney, status: "completed", completed_at: "2026-10-31T10:01:00.000Z" };
let watchSuccess;
let clearWatch;
let previousGeolocation;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (previousGeolocation === undefined) delete navigator.geolocation;
  else Object.defineProperty(navigator, "geolocation", { configurable: true, value: previousGeolocation });
});

describe("JourneyCompanion automatic tracking", () => {
  it("automatically starts a planned route and completes after three accurate arrival fixes", async () => {
    let currentTime = new Date("2026-10-31T10:00:00.000Z").getTime();
    vi.spyOn(Date, "now").mockImplementation(() => currentTime);
    previousGeolocation = navigator.geolocation;
    watchSuccess = null;
    clearWatch = vi.fn();
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        watchPosition: vi.fn((success) => { watchSuccess = success; return 7; }),
        clearWatch,
        getCurrentPosition: vi.fn(),
      },
    });
    journeysApi.active.mockResolvedValueOnce({ ...inProgressJourney, status: "planned", active: true });
    journeysApi.start.mockResolvedValueOnce(inProgressJourney);
    journeysApi.complete.mockResolvedValueOnce(completedJourney);

    render(<JourneyCompanion authenticated onNavigate={vi.fn()}/>);

    await waitFor(() => expect(journeysApi.start).toHaveBeenCalledWith(42));
    await waitFor(() => expect(watchSuccess).toBeTypeOf("function"));
    expect(screen.queryByRole("button", { name: /Start journey|Complete journey/i })).not.toBeInTheDocument();

    for (let sample = 0; sample < 3; sample += 1) {
      currentTime += 4001;
      await act(async () => {
        watchSuccess({ coords: { latitude: 28.7, longitude: 77.3, accuracy: 8 } });
      });
    }

    await waitFor(() => expect(journeysApi.complete).toHaveBeenCalledWith(42));
    expect(await screen.findByText(/Journey completed\. Your route is saved in journey history\./)).toBeInTheDocument();
    expect(clearWatch).toHaveBeenCalledWith(7);
  });
});
