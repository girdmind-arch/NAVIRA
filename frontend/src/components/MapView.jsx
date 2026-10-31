import { useEffect, useId, useRef, useState } from "react";
import { loadMappls } from "../services/mapplsLoader";
import { ROUTE_COLORS } from "./routeColors";

const ACTIVE_ROUTE_COLOR = "#00C48C";
const TRAFFIC_COLORS = { heavy: "#d9363e", moderate: "#e99a24", light: "#28966f" };

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/** GeoJSON [lng, lat] pairs → Mappls {lat, lng} points. */
function routePath(geometry) {
  const coords = geometry?.coordinates || geometry?.geometry?.coordinates;
  if (!Array.isArray(coords)) return [];
  return coords
    .filter((point) => Array.isArray(point) && point.length >= 2 && Number.isFinite(+point[0]) && Number.isFinite(+point[1]))
    .map((point) => ({ lat: +point[1], lng: +point[0] }));
}

const validPoint = (point) => Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1]);

function MapplsCanvas({ mapCenter, zoom, marker, startPoint, endPoint, startLabel, endLabel, routes, activeRoute, onRouteSelect, facilities, trafficPoints, pedestrianNetwork, onMapSelect, travelledPath, className }) {
  const domId = "navira-map-" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const mapRef = useRef(null);
  const sdkRef = useRef(null);
  const layersRef = useRef([]);
  const handlersRef = useRef({ onRouteSelect, onMapSelect });
  const [status, setStatus] = useState("loading");
  const [message, setMessage] = useState("");
  handlersRef.current = { onRouteSelect, onMapSelect };
  const [centerLat, centerLng] = mapCenter;

  // Create the map once.
  useEffect(() => {
    let cancelled = false;
    let loadTimer;
    loadMappls().then((mappls) => {
      if (cancelled) return;
      sdkRef.current = mappls;
      const map = new mappls.Map(domId, { center: { lat: centerLat, lng: centerLng }, zoom, zoomControl: true, location: false, search: false, traffic: false });
      mapRef.current = map;
      loadTimer = setTimeout(() => {
        if (!cancelled) { setStatus("error"); setMessage("The MapmyIndia map did not finish loading. The key may not be allowed for this website, or the quota may be used up."); }
      }, 20000);
      map.addListener?.("load", () => {
        clearTimeout(loadTimer);
        if (cancelled) return;
        map.addListener?.("click", (event) => {
          const point = event?.lngLat || event?.latLng;
          const lat = typeof point?.lat === "function" ? point.lat() : point?.lat;
          const lng = typeof point?.lng === "function" ? point.lng() : point?.lng;
          if (Number.isFinite(lat) && Number.isFinite(lng)) handlersRef.current.onMapSelect?.({ latitude: lat, longitude: lng });
        });
        setStatus("ready");
      });
    }).catch((error) => {
      if (!cancelled) { setStatus("error"); setMessage(error.message); }
    });
    return () => {
      cancelled = true;
      clearTimeout(loadTimer);
      try { mapRef.current?.remove?.(); } catch { /* map already gone */ }
      mapRef.current = null;
      layersRef.current = [];
    };
    // The map is created once; later changes are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domId]);

  // Keep the view on the requested centre when there is nothing to fit.
  useEffect(() => {
    if (status !== "ready" || !mapRef.current) return;
    if (routes.length || facilities.length) return;
    try { mapRef.current.setCenter?.({ lat: centerLat, lng: centerLng }); } catch { /* ignore */ }
  }, [status, centerLat, centerLng, routes.length, facilities.length]);

  // Draw routes, markers and overlays; redraw whenever they change.
  useEffect(() => {
    const mappls = sdkRef.current;
    const map = mapRef.current;
    if (status !== "ready" || !mappls || !map) return undefined;
    const layers = [];
    const add = (layer) => { if (layer) layers.push(layer); return layer; };
    const bounds = [];
    const pin = (point, kind, label, popupHtml) => add(new mappls.Marker({
      map, position: { lat: point[0], lng: point[1] },
      html: `<span class="navira-map-pin navira-map-pin--${kind}"><span></span></span>`, width: 22, height: 22, offset: [0, 0],
      popupHtml: popupHtml || (label ? `<div class="navira-popup">${escapeHtml(label)}</div>` : undefined),
    }));

    try {
      const lines = routes.map((route, index) => ({ route, index, path: routePath(route.geometry) }))
        .filter((item) => item.path.length > 1)
        .sort((a, b) => Number(a.index === activeRoute) - Number(b.index === activeRoute));
      for (const { index, path } of lines) {
        const active = index === activeRoute;
        const line = add(new mappls.Polyline({
          map, path, paths: path,
          strokeColor: active ? ACTIVE_ROUTE_COLOR : ROUTE_COLORS[index % ROUTE_COLORS.length],
          strokeOpacity: active ? 1 : 0.82, strokeWeight: active ? 6 : 4, lineCap: "round",
          popupHtml: `<div class="navira-popup">Route ${index + 1}${active ? " · selected" : ""}</div>`,
        }));
        line?.addListener?.("click", () => handlersRef.current.onRouteSelect?.(index));
        path.forEach((p) => bounds.push([p.lng, p.lat]));
      }
      if (travelledPath.length > 1) {
        const path = travelledPath.filter(validPoint).map(([lat, lng]) => ({ lat, lng }));
        add(new mappls.Polyline({ map, path, paths: path, strokeColor: "#27966f", strokeOpacity: 0.9, strokeWeight: 4, lineCap: "round" }));
      }
      for (const feature of (pedestrianNetwork?.features || []).slice(0, 400)) {
        const path = routePath(feature.geometry);
        if (path.length > 1) add(new mappls.Polyline({ map, path, paths: path, strokeColor: "#3c8d68", strokeOpacity: 0.6, strokeWeight: 2 }));
      }
      for (const point of trafficPoints) {
        const color = TRAFFIC_COLORS[point.level] || TRAFFIC_COLORS.light;
        const segment = (point.segment_coordinates || []).map((c) => ({ lat: c.latitude, lng: c.longitude }));
        if (segment.length > 1) add(new mappls.Polyline({ map, path: segment, paths: segment, strokeColor: color, strokeWeight: 8, strokeOpacity: 0.9 }));
        if (Number.isFinite(point.latitude) && Number.isFinite(point.longitude)) {
          add(new mappls.Marker({ map, position: { lat: point.latitude, lng: point.longitude }, html: `<span class="navira-traffic-dot" style="background:${color}"></span>`, width: 16, height: 16,
            popupHtml: `<div class="navira-popup">${escapeHtml(point.level)} traffic · ${escapeHtml(point.current_speed_kmh)} km/h</div>` }));
        }
      }
      for (const place of facilities) {
        if (!Number.isFinite(place.latitude) || !Number.isFinite(place.longitude)) continue;
        const detail = [place.kind, place.address, place.road_distance_m != null ? `${(place.road_distance_m / 1000).toFixed(1)} km by road` : ""].filter(Boolean).map(escapeHtml).join("<br/>");
        pin([place.latitude, place.longitude], place.kind === "hospital" ? "hospital" : "police", null, `<div class="navira-popup"><strong>${escapeHtml(place.name || "Name not listed")}</strong><br/>${detail}</div>`);
        bounds.push([place.longitude, place.latitude]);
      }
      if (marker && Number.isFinite(marker.latitude) && Number.isFinite(marker.longitude)) {
        pin([marker.latitude, marker.longitude], "current", marker.label || "Selected location");
        bounds.push([marker.longitude, marker.latitude]);
      }
      const start = validPoint(startPoint) ? startPoint : lines[0]?.path[0] && [lines[0].path[0].lat, lines[0].path[0].lng];
      const lastPath = lines[0]?.path;
      const end = validPoint(endPoint) ? endPoint : lastPath?.length && [lastPath[lastPath.length - 1].lat, lastPath[lastPath.length - 1].lng];
      if (start) { pin(start, "start", startLabel || "Route start"); bounds.push([start[1], start[0]]); }
      if (end && (validPoint(endPoint) || lines.length)) { pin(end, "end", endLabel || "Route destination"); bounds.push([end[1], end[0]]); }

      if (bounds.length > 1) {
        new mappls.fitBounds({ map, cType: 0, bounds, options: { padding: 48, duration: 600, maxZoom: 15 } });
      }
    } catch (error) {
      // Defer the state update so React does not re-render synchronously inside this effect.
      queueMicrotask(() => { setStatus("error"); setMessage(`The map could not draw this view: ${error.message}`); });
    }

    layersRef.current = layers;
    return () => {
      for (const layer of layers) {
        try { mappls.remove?.({ map, layer }); } catch { /* already removed */ }
      }
    };
  }, [status, routes, activeRoute, marker, startPoint, endPoint, startLabel, endLabel, facilities, trafficPoints, pedestrianNetwork, travelledPath]);

  return <div className={"map-frame mappls-frame " + className}>
    <div id={domId} className="mappls-map leaflet-map" aria-label="Map"/>
    {status === "loading" && <div className="map-status" role="status">Loading MapmyIndia map…</div>}
    {status === "error" && <div className="map-status map-status--error" role="alert"><strong>Map unavailable</strong><span>{message}</span></div>}
    <div className="map-attribution-note">Map © MapmyIndia (Mappls)</div>
  </div>;
}

export default function MapView({ center, marker, startPoint, endPoint, startLabel, endLabel, routes = [], activeRoute, onRouteSelect, facilities = [], trafficPoints = [], pedestrianNetwork, onMapSelect, travelledPath = [], className = "", zoom = 13 }) {
  const mapCenter = validPoint(center) ? center : marker && Number.isFinite(marker.latitude) && Number.isFinite(marker.longitude) ? [marker.latitude, marker.longitude] : null;
  if (!mapCenter) return <div className={"map-frame map-location-prompt " + className}>Enter locations and request a route to load the map.</div>;
  return <MapplsCanvas mapCenter={mapCenter} zoom={zoom} marker={marker} startPoint={startPoint} endPoint={endPoint} startLabel={startLabel} endLabel={endLabel}
    routes={routes} activeRoute={activeRoute} onRouteSelect={onRouteSelect} facilities={facilities} trafficPoints={trafficPoints}
    pedestrianNetwork={pedestrianNetwork} onMapSelect={onMapSelect} travelledPath={travelledPath} className={className}/>;
}
