import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MapView from "./MapView.jsx";

const created = { polylines: [], markers: [], fits: [] };

function fakeMappls() {
  class Map {
    constructor(id, options) { this.id = id; this.options = options; this.listeners = {}; setTimeout(() => this.listeners.load?.(), 0); }
    addListener(event, fn) { this.listeners[event] = fn; }
    setCenter() {}
    remove() {}
  }
  class Polyline { constructor(options) { this.options = options; this.listeners = {}; created.polylines.push(this); } addListener(event, fn) { this.listeners[event] = fn; } }
  class Marker { constructor(options) { this.options = options; created.markers.push(this); } }
  class fitBounds { constructor(options) { created.fits.push(options); } }
  return { Map, Polyline, Marker, fitBounds, remove: vi.fn() };
}

vi.mock("../services/mapplsLoader", () => ({ loadMappls: vi.fn(() => Promise.resolve(fakeMappls())) }));

describe("MapView on MapmyIndia (Mappls)", () => {
  it("draws every route, highlights the selected one, and selects a route when its line is clicked", async () => {
    const onRouteSelect = vi.fn();
    const routes = [0, 1, 2].map((index) => ({ id: `route-${index + 1}`, geometry: { type: "LineString", coordinates: [[77.2, 28.6], [77.21 + index * 0.01, 28.61 + index * 0.01]] } }));
    render(<MapView center={[28.6, 77.2]} startPoint={[28.6, 77.2]} endPoint={[28.7, 77.3]} routes={routes} activeRoute={0} onRouteSelect={onRouteSelect}/>);

    await waitFor(() => expect(created.polylines).toHaveLength(3));
    const selected = created.polylines.find((line) => line.options.popupHtml.includes("Route 1 · selected"));
    expect(selected.options.strokeColor).toBe("#00C48C");
    expect(selected.options.strokeWeight).toBe(6);
    expect(selected.options.path[0]).toEqual({ lat: 28.6, lng: 77.2 });
    created.polylines.find((line) => line.options.popupHtml.includes("Route 2<")).listeners.click();
    expect(onRouteSelect).toHaveBeenCalledWith(1);
    expect(created.markers.map((m) => m.options.html)).toEqual(expect.arrayContaining([expect.stringContaining("--start"), expect.stringContaining("--end")]));
    expect(created.fits.length).toBeGreaterThan(0);
    expect(screen.getByText("Map © MapmyIndia (Mappls)")).toBeInTheDocument();
  });

  it("shows a clear error when MapmyIndia cannot load", async () => {
    const { loadMappls } = await import("../services/mapplsLoader");
    loadMappls.mockRejectedValueOnce(new Error("The map uses MapmyIndia (Mappls), which is not configured yet."));
    render(<MapView center={[28.6, 77.2]}/>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Map unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("not configured yet");
  });
});
