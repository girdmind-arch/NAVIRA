import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MapView from "./MapView.jsx";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: () => null,
  Popup: ({ children }) => children,
  Polyline: ({ children, eventHandlers, pathOptions }) => <button type="button" data-color={pathOptions.color} data-weight={pathOptions.weight} onClick={eventHandlers?.click}>{children}</button>,
  Tooltip: ({ children }) => children,
  useMap: () => ({ fitBounds: vi.fn(), getZoom: () => 13, setView: vi.fn() }),
  useMapEvents: vi.fn(),
}));

describe("MapView alternative routes", () => {
  it("renders each provider geometry and selects the route when its map line is clicked", () => {
    const onRouteSelect = vi.fn();
    const routes = [0, 1, 2].map((index) => ({
      id: `route-${index + 1}`,
      geometry: {
        type: "LineString",
        coordinates: [[77.2, 28.6], [77.21 + index * 0.01, 28.61 + index * 0.01]],
      },
    }));

    render(
      <MapView
        center={[28.6, 77.2]}
        startPoint={[28.6, 77.2]}
        endPoint={[28.7, 77.3]}
        routes={routes}
        activeRoute={0}
        onRouteSelect={onRouteSelect}
      />,
    );

    expect(screen.getByRole("button", { name: /Route 1 · selected/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Route 1 · selected/ })).toHaveAttribute("data-color", "#00C48C");
    expect(screen.getByRole("button", { name: /Route 1 · selected/ })).toHaveAttribute("data-weight", "5");
    expect(screen.getByRole("button", { name: "Route 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Route 3" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Route 2" }));

    expect(onRouteSelect).toHaveBeenCalledWith(1);
  });
});
