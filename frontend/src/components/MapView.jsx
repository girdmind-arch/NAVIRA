import { Fragment, useEffect } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, Tooltip, CircleMarker, GeoJSON, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ROUTE_COLORS } from "./routeColors";

const pinIcon = L.divIcon({ className: "navira-map-pin", html: '<span></span>', iconSize: [22, 22], iconAnchor: [11, 11] });
const startIcon = L.divIcon({ className: "navira-map-pin navira-map-pin--start", html: '<span></span>', iconSize: [22, 22], iconAnchor: [11, 11] });
const endIcon = L.divIcon({ className: "navira-map-pin navira-map-pin--end", html: '<span></span>', iconSize: [22, 22], iconAnchor: [11, 11] });
function Recenter({ center }) {
  const map = useMap();
  useEffect(() => { if (center && Number.isFinite(center[0]) && Number.isFinite(center[1])) map.setView(center, Math.max(map.getZoom(), 13)); }, [center, map]);
  return null;
}

function FitRoute({ routes }) {
  const map = useMap();
  useEffect(() => {
    const points = routes.flatMap((route) => routeCoordinates(route.geometry));
    if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [28, 28], maxZoom: 15 });
  }, [map, routes]);
  return null;
}

function FitFacilities({ facilities, marker, startPoint, endPoint }) {
  const map = useMap();
  useEffect(() => {
    if (!facilities.length && !marker) return;
    const points = facilities
      .filter((place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude))
      .map((place) => [place.latitude, place.longitude]);
    for (const point of [marker && [marker.latitude, marker.longitude], startPoint, endPoint]) {
      if (point && Number.isFinite(point[0]) && Number.isFinite(point[1])) points.push(point);
    }
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [34, 34], maxZoom: 15 });
  }, [endPoint, facilities, map, marker, startPoint]);
  return null;
}

function MapClick({ onSelect }) {
  useMapEvents({ click(event) { if (onSelect) onSelect({ latitude: event.latlng.lat, longitude: event.latlng.lng }); } });
  return null;
}

function routeCoordinates(geometry) {
  const coords = geometry?.coordinates || geometry?.geometry?.coordinates;
  if (!Array.isArray(coords)) return [];
  return coords.map((point) => Array.isArray(point) && point.length >= 2 ? [point[1], point[0]] : null).filter(Boolean);
}

export default function MapView({ center, marker, startPoint, endPoint, startLabel, endLabel, routes = [], activeRoute, onRouteSelect, facilities = [], trafficPoints = [], pedestrianNetwork, onMapSelect, travelledPath = [], className = "", zoom = 13 }) {
  const mapCenter = center || (marker ? [marker.latitude, marker.longitude] : null);
  const lines = routes.map((route, index) => ({ route, index, points: routeCoordinates(route.geometry) }))
    .filter((item) => item.points.length > 1)
    .sort((left, right) => Number(left.index === activeRoute) - Number(right.index === activeRoute));
  if (!mapCenter) return <div className={"map-frame map-location-prompt " + className}>Enter locations and request a route to load the map.</div>;
  return <div className={"map-frame " + className}>
    <MapContainer center={mapCenter} zoom={zoom} scrollWheelZoom className="leaflet-map">
      <Recenter center={mapCenter}/><FitRoute routes={routes}/><FitFacilities facilities={facilities} marker={marker} startPoint={startPoint} endPoint={endPoint}/><MapClick onSelect={onMapSelect}/>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {pedestrianNetwork?.features?.length > 0 && <GeoJSON data={pedestrianNetwork} style={{ color: "#3c8d68", weight: 2, opacity: .7, dashArray: "4 4" }} />}
      {lines.map(({ route, index, points }) => <Polyline
        key={route.id || index}
        positions={points}
        pathOptions={{ className: index === activeRoute ? "navira-route-line navira-route-line--active" : "navira-route-line", color: index === activeRoute ? "#00C48C" : ROUTE_COLORS[index % ROUTE_COLORS.length], weight: index === activeRoute ? 5 : 4, opacity: index === activeRoute ? 1 : .82, lineCap: "round", lineJoin: "round" }}
        eventHandlers={onRouteSelect ? { click: () => onRouteSelect(index) } : undefined}
      ><Tooltip sticky>{`Route ${index + 1}${index === activeRoute ? " · selected" : ""}`}</Tooltip></Polyline>)}
      {travelledPath.length > 1 && <Polyline positions={travelledPath} pathOptions={{ color: "#27966f", weight: 4, opacity: .85, dashArray: "7 8" }} />}
      {trafficPoints.map((point, index) => {
        const color = point.level === "heavy" ? "#d9363e" : point.level === "moderate" ? "#e99a24" : "#28966f";
        const segment = (point.segment_coordinates || []).map((coordinate) => [coordinate.latitude, coordinate.longitude]);
        return <Fragment key={`traffic-${index}`}>
          {segment.length > 1 && <Polyline positions={segment} pathOptions={{ color, weight: 8, opacity: .9 }} />}
          <CircleMarker center={[point.latitude, point.longitude]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: .95 }}>
            <Popup>{point.level[0].toUpperCase() + point.level.slice(1)} traffic · {point.current_speed_kmh} km/h (free flow {point.free_flow_speed_kmh} km/h){point.road_closure ? " · closure reported" : ""}</Popup>
          </CircleMarker>
        </Fragment>;
      })}
      {marker && Number.isFinite(marker.latitude) && Number.isFinite(marker.longitude) && <Marker position={[marker.latitude, marker.longitude]} icon={pinIcon}><Popup>{marker.label || "Selected location"}</Popup></Marker>}
      {startPoint && <Marker position={startPoint} icon={startIcon}><Popup>{startLabel || "Route start"}</Popup></Marker>}
      {endPoint && <Marker position={endPoint} icon={endIcon}><Popup>{endLabel || "Route destination"}</Popup></Marker>}
      {routes.length > 0 && lines.length > 0 && !startPoint && !endPoint && <><Marker position={lines[0].points[0]} icon={startIcon}><Popup>Route origin</Popup></Marker><Marker position={lines[0].points[lines[0].points.length - 1]} icon={endIcon}><Popup>Route destination</Popup></Marker></>}
      {facilities.map((place) => <Marker key={place.id} position={[place.latitude, place.longitude]} icon={pinIcon}><Popup><strong>{place.name || "Name not listed in OpenStreetMap"}</strong><br/>{place.kind}{place.address && <><br/>{place.address}</>}{place.road_distance_m != null && <><br/>{(place.road_distance_m / 1000).toFixed(1)} km by road</>}{place.road_duration_s != null && <><br/>{Math.round(place.road_duration_s / 60)} min estimated by road</>}</Popup></Marker>)}
    </MapContainer>
    <div className="map-attribution-note">Map data © OpenStreetMap contributors</div>
  </div>;
}
