import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WalkingPilot from "./WalkingPilot";
import { backendApi, routesApi } from "../services/api";

vi.mock("../services/api", () => ({
  backendApi: { routeSafetyDataStatus: vi.fn() },
  routesApi: { suggest: vi.fn(), walking: vi.fn(), compare: vi.fn(), localityReports: vi.fn(), pedestrianNetwork: vi.fn() },
}));
vi.mock("./MapView", () => ({ default: () => <div data-testid="pilot-map" /> }));

const place = (query) => ({ query, display_name: `${query}, Delhi`, latitude: 28.6, longitude: 77.2, provider: "Nominatim", place_type: "place" });

beforeEach(() => {
  vi.clearAllMocks();
  backendApi.routeSafetyDataStatus.mockResolvedValue({ status: "insufficient_data", route_matched_verified_incidents: 0, aggregate_statistics: 5 });
  routesApi.suggest.mockImplementation(async (query) => ({ items: [place(query)] }));
  routesApi.walking.mockResolvedValue({
    provider_status: "provider_configured",
    provider: "openrouteservice · foot-walking",
    alternatives: [{ id: "walk-1", distance_m: 720, duration_s: 600, geometry: { type: "LineString", coordinates: [[77.2, 28.6], [77.201, 28.601]] } }],
    resolved_locations: { origin: place("CR Park"), destination: place("AIIMS") },
    limitations: ["openrouteservice foot-walking directions are estimates."],
  });
  routesApi.localityReports.mockResolvedValue({ status: "candidate_context", items: [{ id: "e1", category: "reported incident", event_date: "2022-05-30", status: "reported", review_status: "needs_review", locality: "CR Park", summary: "Source-linked candidate.", source_url: "https://example.org/report", source_title: "Report" }] });
  routesApi.pedestrianNetwork.mockResolvedValue({ type: "FeatureCollection", features: [], returned: 0, networks: [] });
});

afterEach(() => cleanup());

async function chooseLocations(user) {
  await user.type(screen.getByLabelText("Starting location"), "CR Park");
  await user.click(await screen.findByRole("option", { name: /CR Park, Delhi/ }));
  await user.type(screen.getByLabelText("Destination location"), "AIIMS");
  await user.click(await screen.findByRole("option", { name: /AIIMS, Delhi/ }));
}

describe("WalkingPilot", () => {
  it("requests openrouteservice walking directions and labels endpoint reports as unverified context", async () => {
    const user = userEvent.setup();
    render(<WalkingPilot />);
    await chooseLocations(user);
    await user.click(screen.getByRole("button", { name: /Find walking route/ }));

    await waitFor(() => expect(routesApi.walking).toHaveBeenCalledWith("CR Park, Delhi", "AIIMS, Delhi"));
    expect(await screen.findByText("10 min · 0.7 km")).toBeInTheDocument();
    expect(screen.getByText(/openrouteservice foot-walking directions are estimates/)).toBeInTheDocument();
    expect(screen.getByText(/not snapped to the walking route/)).toBeInTheDocument();
    expect(await screen.findByText("reported incident · CR Park")).toBeInTheDocument();
    expect(routesApi.localityReports).toHaveBeenCalledWith("CR Park, Delhi", "AIIMS, Delhi");
  });

  it("reports unavailable walking directions without falling back to a road route", async () => {
    const user = userEvent.setup();
    routesApi.walking.mockResolvedValue({ provider_status: "unavailable", provider: "openrouteservice · foot-walking", alternatives: [], error: "no foot-walking route found", limitations: ["No automatic switch to the driving-route provider was made."] });
    render(<WalkingPilot />);
    await chooseLocations(user);
    await user.click(screen.getByRole("button", { name: /Find walking route/ }));

    expect(await screen.findByText(/No pilot walking path is available: no foot-walking route found/)).toBeInTheDocument();
    expect(routesApi.compare).not.toHaveBeenCalled();
  });
});
