import { useEffect, useState } from "react";
import { PageHeading, Notice, EmptyState, Icon } from "../components/ui";
import MapView from "../components/MapView";
import { ROUTE_COLORS } from "../components/routeColors";
import { journeysApi, newsApi, routesApi, syntheticDemoApi } from "../services/api";

const EMPTY_ROUTES = [];

function formatDistance(meters) {
  if (typeof meters !== "number") return "—";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

function formatDuration(seconds) {
  if (typeof seconds !== "number") return "—";
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} hr ${minutes % 60} min` : `${minutes} min`;
}

function formatTimestamp(value) {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? "timestamp unavailable" : timestamp.toLocaleString();
}

function formatForecastTime(value) {
  if (typeof value !== "string") return "Forecast";
  const timestamp = new Date(`${value.replace(" ", "T")}Z`);
  return Number.isNaN(timestamp.getTime()) ? "Forecast" : timestamp.toLocaleTimeString([], { hour: "numeric" });
}

function getRouteTrafficKey(route, index) {
  const coordinates = route.geometry?.coordinates || [];
  return JSON.stringify([
    route.id || `route-${index + 1}`,
    route.duration_s,
    route.distance_m,
    coordinates.length,
    coordinates[0],
    coordinates[Math.floor(coordinates.length / 2)],
    coordinates.at(-1),
  ]);
}

function getTrafficAgeSeconds(entry, now) {
  if (!entry || !["available", "partial"].includes(entry.data?.status)) return null;
  const providerTimes = (entry.data?.points || [])
    .map((point) => Date.parse(point.provider_observed_at))
    .filter(Number.isFinite);
  const timestamp = providerTimes.length
    ? Math.min(...providerTimes)
    : Date.parse(entry.data?.retrieved_at);
  const validTimestamp = Number.isFinite(timestamp) ? timestamp : entry.receivedAt;
  return Math.max(0, Math.floor((now - validTimestamp) / 1000));
}

function LocationSearchField({ id, label, value, setValue, onSelect, selected, tone }) {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const query = value.trim();
    let active = true;
    if (query.length < 3 || selected) return () => { active = false; };
    const timer = window.setTimeout(() => {
      setLoading(true);
      routesApi.suggest(query)
        .then((result) => {
          if (!active) return;
          setSuggestions(result.items || []);
          setError(result.items?.length ? "" : "No matching places. Try adding a locality, city, and state.");
        })
        .catch((requestError) => {
          if (active) {
            setSuggestions([]);
            setError(`Location suggestions unavailable: ${requestError.message}`);
          }
        })
        .finally(() => { if (active) setLoading(false); });
    }, 400);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [selected, value]);

  return <div className="location-search">
    <label htmlFor={id}>{label}</label>
    <div className="input-with-icon"><span className={`location-dot location-dot--${tone}`}/><input id={id} autoComplete="off" role="combobox" aria-autocomplete="list" aria-expanded={suggestions.length > 0} aria-controls={`${id}-suggestions`} value={value} onChange={(event) => { setValue(event.target.value); onSelect(null); }} placeholder={label === "Starting location" ? "Search locality, street, landmark, or full address" : "Search destination, locality, street, or landmark"} minLength={2} maxLength={200} required/></div>
    {selected && <small className="form-helper">Selected location: {selected.display_name}</small>}
    {!selected && value.trim().length > 0 && value.trim().length < 3 && <small className="form-helper">Enter at least 3 characters to search for exact place suggestions.</small>}
    {!selected && value.trim().length >= 3 && loading && <small className="form-helper" role="status">Searching OpenStreetMap places…</small>}
    {!selected && value.trim().length >= 3 && error && !loading && <small className="form-helper location-search__message">{error}</small>}
    {!selected && value.trim().length >= 3 && suggestions.length > 0 && <div className="location-suggestions" id={`${id}-suggestions`} role="listbox" aria-label={`${label} suggestions`}>{suggestions.map((place, index) => <button type="button" role="option" aria-selected="false" key={`${place.latitude}-${place.longitude}-${index}`} onClick={() => { setValue(place.display_name); onSelect(place); setSuggestions([]); setError(""); setLoading(false); }}><strong>{place.display_name}</strong><small>{place.place_type}</small></button>)}</div>}
  </div>;
}

export default function RoutePlanner({ authenticated, onRouteContext, onNavigate }) {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [mode, setMode] = useState("car");
  const [originPlace, setOriginPlace] = useState(null);
  const [destinationPlace, setDestinationPlace] = useState(null);
  const [result, setResult] = useState(null);
  const [modeResults, setModeResults] = useState(null);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [trafficByRoute, setTrafficByRoute] = useState({});
  const [trafficLoadingKeys, setTrafficLoadingKeys] = useState({});
  const [trafficErrors, setTrafficErrors] = useState({});
  const [weatherByRoute, setWeatherByRoute] = useState({});
  const [weatherLoadingKeys, setWeatherLoadingKeys] = useState({});
  const [weatherErrors, setWeatherErrors] = useState({});
  const [clock, setClock] = useState(0);
  const [routeNewsData, setRouteNewsData] = useState(null);
  const [routeNewsError, setRouteNewsError] = useState("");
  const [newsLoading, setNewsLoading] = useState(false);
  const [infrastructureByRoute, setInfrastructureByRoute] = useState({});
  const [infrastructureLoadingKeys, setInfrastructureLoadingKeys] = useState({});
  const [infrastructureErrors, setInfrastructureErrors] = useState({});
  const [infrastructureCorridor, setInfrastructureCorridor] = useState(100);
  const [syntheticDemoData, setSyntheticDemoData] = useState(null);
  const [syntheticDemoError, setSyntheticDemoError] = useState("");

  useEffect(() => {
    if (typeof syntheticDemoApi?.get !== "function") return undefined;
    let active = true;
    syntheticDemoApi.get()
      .then((data) => { if (active) setSyntheticDemoData(data); })
      .catch((requestError) => { if (active) setSyntheticDemoError(requestError.message); });
    return () => { active = false; };
  }, []);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    setModeResults(null);
    setTrafficByRoute({});
    setTrafficLoadingKeys({});
    setTrafficErrors({});
    setWeatherByRoute({});
    setWeatherLoadingKeys({});
    setWeatherErrors({});
    setInfrastructureByRoute({});
    setInfrastructureLoadingKeys({});
    setInfrastructureErrors({});
    setRouteNewsData(null);
    setRouteNewsError("");
    setNewsLoading(false);
    if (!originPlace || !destinationPlace) {
      setError("Select an exact starting location and destination from the place suggestions before requesting a route.");
      setBusy(false);
      return;
    }
    try {
      const requestedModes = ["car", "motorcycle", "walking"];
      const modeEntries = await Promise.all(requestedModes.map(async (travelMode) => {
        try {
          const response = travelMode === "walking"
            ? await routesApi.walking(originPlace.display_name, destinationPlace.display_name, originPlace, destinationPlace)
            : await routesApi.compare(origin.trim(), destination.trim(), originPlace, destinationPlace, travelMode);
          return [travelMode, { ...response, mode: travelMode }];
        } catch (requestError) {
          return [travelMode, {
            mode: travelMode,
            alternatives: [],
            provider_status: "unavailable",
            provider: travelMode === "walking" ? "openrouteservice · foot-walking" : travelMode === "motorcycle" ? "Geoapify motorcycle routing" : "Car routing provider",
            error: requestError.message || "This travel mode could not be checked.",
            limitations: ["No route was returned for this mode; NAVIRA did not substitute another mode."],
          }];
        }
      }));
      const comparison = Object.fromEntries(modeEntries);
      setModeResults(comparison);
      const data = comparison[mode];
      setNewsLoading(true);
      setResult(data);
      setSelected(0);
      const routeOrigin = data.resolved_locations?.origin || originPlace;
      const routeDestination = data.resolved_locations?.destination || destinationPlace;
      onRouteContext?.({
        origin: { query: routeOrigin.query, display_name: routeOrigin.display_name, latitude: routeOrigin.latitude, longitude: routeOrigin.longitude },
        destination: { query: routeDestination.query, display_name: routeDestination.display_name, latitude: routeDestination.latitude, longitude: routeDestination.longitude },
        selectedRouteId: data.alternatives?.[0]?.id || null,
      });
      if (authenticated && data.alternatives?.[0]) {
        await journeysApi.plan({
          origin: originPlace.display_name,
          destination: destinationPlace.display_name,
          route_id: data.alternatives[0].id || "route-1",
          route: { ...data.alternatives[0], mode, source: data.provider, provider_status: data.provider_status, origin_location: routeOrigin, destination_location: routeDestination },
        });
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function selectRoute(routeOrIndex, index) {
    const selectedIndex = typeof routeOrIndex === "number" ? routeOrIndex : index;
    const route = typeof routeOrIndex === "number" ? routes[routeOrIndex] : routeOrIndex;
    if (!route || selectedIndex == null) return;
    setSelected(selectedIndex);
    setRouteNewsData(null);
    setRouteNewsError("");
    setNewsLoading(true);
    const routeOrigin = result.resolved_locations?.origin || originPlace;
    const routeDestination = result.resolved_locations?.destination || destinationPlace;
    onRouteContext?.({
      origin: { query: routeOrigin.query, display_name: routeOrigin.display_name, latitude: routeOrigin.latitude, longitude: routeOrigin.longitude },
      destination: { query: routeDestination.query, display_name: routeDestination.display_name, latitude: routeDestination.latitude, longitude: routeDestination.longitude },
      selectedRouteId: route.id || `route-${selectedIndex + 1}`,
    });
    if (!authenticated) return;
    setBusy(true);
    try {
      const savedJourney = await journeysApi.plan({
        origin: originPlace.display_name,
        destination: destinationPlace.display_name,
        route_id: route.id || `route-${selectedIndex + 1}`,
        route: {
          ...route,
          mode: result.mode || mode,
          source: result.provider,
          provider_status: result.provider_status,
          origin_location: routeOrigin,
          destination_location: routeDestination,
        },
      });
      await journeysApi.start(savedJourney.id);
      onNavigate?.("journey");
    } catch (requestError) {
      setError(`Route shown, but NAVIRA could not start it in Journey Companion: ${requestError.message}`);
    } finally {
      setBusy(false);
    }
  }

  function selectMode(travelMode) {
    setMode(travelMode);
    const nextResult = modeResults?.[travelMode] || null;
    setResult(nextResult);
    setSelected(0);
    setTrafficByRoute({});
    setTrafficLoadingKeys({});
    setTrafficErrors({});
    setWeatherByRoute({});
    setWeatherLoadingKeys({});
    setWeatherErrors({});
    setRouteNewsData(null);
    setRouteNewsError("");
    onRouteContext?.(null);
    const firstRoute = nextResult?.alternatives?.[0];
    if (firstRoute && nextResult.resolved_locations) {
      const routeOrigin = nextResult.resolved_locations.origin || originPlace;
      const routeDestination = nextResult.resolved_locations.destination || destinationPlace;
      onRouteContext?.({
        origin: { query: routeOrigin.query, display_name: routeOrigin.display_name, latitude: routeOrigin.latitude, longitude: routeOrigin.longitude },
        destination: { query: routeDestination.query, display_name: routeDestination.display_name, latitude: routeDestination.latitude, longitude: routeDestination.longitude },
        selectedRouteId: firstRoute.id || null,
      });
      if (authenticated) {
        journeysApi.plan({
          origin: routeOrigin.display_name,
          destination: routeDestination.display_name,
          route_id: firstRoute.id || "route-1",
          route: { ...firstRoute, mode: travelMode, source: nextResult.provider, provider_status: nextResult.provider_status, origin_location: routeOrigin, destination_location: routeDestination },
        }).catch((requestError) => setError(`Route shown, but could not save it for Journey Companion: ${requestError.message}`));
      }
    }
  }

  const routes = result?.alternatives || EMPTY_ROUTES;
  const activeRoute = routes[selected];
  const trafficKey = activeRoute ? getRouteTrafficKey(activeRoute, selected) : "";
  const activeTrafficEntry = trafficByRoute[trafficKey];
  const traffic = activeTrafficEntry?.data || null;
  const activeWeatherEntry = weatherByRoute[trafficKey];
  const routeWeather = activeWeatherEntry?.data || null;
  const weatherLocations = routeWeather?.locations || [];
  const primaryWeather = weatherLocations[0];
  const infrastructureKey = `${trafficKey}:${infrastructureCorridor}`;
  const infrastructureEntry = infrastructureByRoute[infrastructureKey];
  const infrastructure = infrastructureEntry?.data || null;
  const infrastructureLoading = Boolean(infrastructureLoadingKeys[infrastructureKey]);
  const infrastructureError = infrastructureErrors[infrastructureKey] || "";
  useEffect(() => {
    if (!activeRoute?.geometry?.coordinates || !trafficKey || infrastructureByRoute[infrastructureKey]) return undefined;
    let active = true;
    setInfrastructureLoadingKeys((current) => ({ ...current, [infrastructureKey]: true }));
    setInfrastructureErrors((current) => ({ ...current, [infrastructureKey]: "" }));
    routesApi.infrastructure(activeRoute.geometry.coordinates, infrastructureCorridor)
      .then((data) => { if (active) setInfrastructureByRoute((current) => ({ ...current, [infrastructureKey]: { data, receivedAt: Date.now() } })); })
      .catch((requestError) => { if (active) setInfrastructureErrors((current) => ({ ...current, [infrastructureKey]: requestError.message || "Route infrastructure could not be retrieved." })); })
      .finally(() => { if (active) setInfrastructureLoadingKeys((current) => ({ ...current, [infrastructureKey]: false })); });
    return () => {
      active = false;
      setInfrastructureLoadingKeys((current) => ({ ...current, [infrastructureKey]: false }));
    };
  }, [activeRoute, infrastructureByRoute, infrastructureCorridor, infrastructureKey, trafficKey]);
  useEffect(() => {
    if (!result || !activeRoute?.geometry) {
      setRouteNewsData(null);
      setNewsLoading(false);
      return undefined;
    }
    let active = true;
    setNewsLoading(true);
    setRouteNewsError("");
    setRouteNewsData(null);
    newsApi.routeLocalityEvidence(activeRoute.geometry)
      .then((data) => { if (active) setRouteNewsData(data); })
      .catch((requestError) => { if (active) setRouteNewsError(requestError.message); })
      .finally(() => { if (active) setNewsLoading(false); });
    return () => { active = false; };
  }, [result, activeRoute]);
  useEffect(() => {
    let cancelled = false;
    let running = false;
    if (!result || routes.length === 0 || result.mode === "walking") {
      return undefined;
    }
    const refreshTraffic = async () => {
      if (running || cancelled) return;
      running = true;
      const queue = routes.map((route, index) => ({ route, key: getRouteTrafficKey(route, index) }));
      setTrafficLoadingKeys((current) => ({ ...current, ...Object.fromEntries(queue.map(({ key }) => [key, true])) }));
      let next = 0;
      const loadNext = async () => {
        while (next < queue.length && !cancelled) {
          const { route, key } = queue[next++];
          const coordinates = route.geometry?.coordinates;
          try {
            if (!Array.isArray(coordinates) || coordinates.length < 2) {
              throw new Error("Live traffic needs this route's road geometry.");
            }
            const data = await routesApi.traffic(coordinates, route.duration_s, route.distance_m);
            if (!cancelled) {
              setTrafficByRoute((current) => ({ ...current, [key]: { data, receivedAt: Date.now() } }));
              setTrafficErrors((current) => ({ ...current, [key]: "" }));
            }
          } catch (requestError) {
            if (!cancelled) setTrafficErrors((current) => ({ ...current, [key]: requestError.message || "Live traffic could not be refreshed." }));
          } finally {
            if (!cancelled) setTrafficLoadingKeys((current) => ({ ...current, [key]: false }));
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(2, queue.length) }, loadNext));
      if (!cancelled) {
        setClock(Date.now());
        running = false;
      }
    };
    refreshTraffic();
    const refreshTimer = window.setInterval(refreshTraffic, 180000);
    const freshnessTimer = window.setInterval(() => setClock(Date.now()), 15000);
    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
      window.clearInterval(freshnessTimer);
    };
  }, [result, routes]);
  useEffect(() => {
    let cancelled = false;
    let running = false;
    if (!result || routes.length === 0) return undefined;
    const refreshWeather = async () => {
      if (running || cancelled) return;
      running = true;
      const queue = routes.map((route, index) => ({ route, key: getRouteTrafficKey(route, index) }));
      setWeatherLoadingKeys((current) => ({ ...current, ...Object.fromEntries(queue.map(({ key }) => [key, true])) }));
      let next = 0;
      const loadNext = async () => {
        while (next < queue.length && !cancelled) {
          const { route, key } = queue[next++];
          try {
            const coordinates = route.geometry?.coordinates;
            if (!Array.isArray(coordinates) || coordinates.length < 2) throw new Error("Weather needs this route’s road geometry.");
            const data = await routesApi.weather(coordinates);
            if (!cancelled) {
              setWeatherByRoute((current) => ({ ...current, [key]: { data, receivedAt: Date.now() } }));
              setWeatherErrors((current) => ({ ...current, [key]: "" }));
            }
          } catch (requestError) {
            if (!cancelled) setWeatherErrors((current) => ({ ...current, [key]: requestError.message || "Live weather could not be refreshed." }));
          } finally {
            if (!cancelled) setWeatherLoadingKeys((current) => ({ ...current, [key]: false }));
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(2, queue.length) }, loadNext));
      running = false;
    };
    refreshWeather();
    const refreshTimer = window.setInterval(refreshWeather, 600000);
    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
    };
  }, [result, routes]);
  const trafficAge = getTrafficAgeSeconds(activeTrafficEntry, clock);
  const trafficStale = trafficAge !== null && trafficAge > (traffic?.stale_after_seconds || 180);
  const point = (location) => location ? [location.latitude, location.longitude] : null;
  const originLocation = result?.resolved_locations?.origin;
  const destinationLocation = result?.resolved_locations?.destination;
  const originPoint = point(originLocation);
  const destinationPoint = point(destinationLocation);
  const official = result?.evidence_context?.historical_official_statistics;
  const sourceLinks = official?.source?.split(/\s*;\s*/).filter(Boolean) || [];
  const fastestIndex = routes.reduce((best, route, index) =>
    route.duration_s < routes[best].duration_s ? index : best, 0);
  const shortestIndex = routes.reduce((best, route, index) =>
    route.distance_m < routes[best].distance_m ? index : best, 0);

  function routeLabels(index) {
    const labels = [];
    if (result?.mode === "walking") return ["Pilot walking path"];
    if (routes[index]?.id === result?.recommendation?.route_id) labels.push("Recommended by travel time");
    if (index === fastestIndex) labels.push("Fastest route");
    if (index === shortestIndex) labels.push("Shortest route");
    if (labels.length === 0) labels.push("Alternative route");
    return labels;
  }

  return <>
    <PageHeading eyebrow="PLAN WITH CONTEXT" title="Route Planner" description="See the route conditions and evidence that matter before you travel." action={<span className="status-chip status-chip--lavender">Interactive map</span>}/>
    <div className="route-layout">
      <section className="panel route-controls">
        <div className="panel-heading"><div><p className="eyebrow">YOUR ROUTE</p><h2>Where are you going?</h2></div><span className="soft-icon"><span className="route-pulse"/></span></div>
        <form onSubmit={submit} className="stack-form">
          <label htmlFor="route-mode">Travel mode</label>
          <select id="route-mode" value={mode} onChange={(event) => selectMode(event.target.value)}>
            <option value="car">Car · road routing provider</option>
            <option value="walking">Walking · openrouteservice foot-walking</option>
            <option value="motorcycle">Motorcycle · Geoapify motorcycle profile</option>
          </select>
          {mode === "walking" && <p className="form-helper">Walking directions use openrouteservice's foot-walking profile and require backend-only OPENROUTESERVICE_API_KEY. Routes can be unavailable when the provider key, quota, or walkable network is unavailable. Sidewalk and crossing access is not field-verified.</p>}
          {mode === "motorcycle" && <p className="form-helper">With backend-only GEOAPIFY_API_KEY, NAVIRA requests Geoapify’s motorcycle profile (not its scooter profile). Without a key, it may show a clearly labeled OSRM car-profile fallback, which is not motorcycle-optimized. Configured provider errors remain unavailable.</p>}
          <LocationSearchField id="route-origin" label="Starting location" value={origin} setValue={setOrigin} onSelect={setOriginPlace} selected={originPlace} tone="start"/>
          <div className="route-connector"/>
          <LocationSearchField id="route-destination" label="Destination location" value={destination} setValue={setDestination} onSelect={setDestinationPlace} selected={destinationPlace} tone="end"/>
          <button className="button button--primary button--wide" type="submit" disabled={busy}>{busy ? <><span className="spinner"/> Comparing travel modes…</> : <>Compare car, motorcycle &amp; walking <span>→</span></>}</button>
        </form>
        <div className="route-privacy"><span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></svg></span><p>{mode === "walking" ? "Walking directions use the openrouteservice foot-walking profile. Map data may omit sidewalks, crossings, access restrictions, or current conditions." : mode === "motorcycle" ? "Geoapify motorcycle routing is used when configured. Without a key, an OSRM car-profile fallback may appear; it is not motorcycle-optimized. Follow posted signs and restrictions." : "Place searches use OpenStreetMap Nominatim and car routes use OSRM road-network geometry. Mapped access rules may be incomplete; follow current signs and local restrictions."}</p></div>
        {error && <Notice kind="error">{error}</Notice>}
      </section>
      <section className="route-results-area">
        <div className="panel map-panel">
          <div className="panel-heading panel-heading--map"><div><p className="eyebrow">{result?.mode === "walking" ? "WALKING ROUTE MAP" : result?.mode === "motorcycle" ? "MOTORCYCLE ROUTE MAP" : "CAR ROAD MAP"}</p><h2>{result?.provider || "Route map"}</h2></div>{result && <span className={result.provider_status === "provider_configured" ? "status-chip status-chip--green" : "status-chip status-chip--amber"}>{result.provider_status === "provider_fallback" ? "Car-profile fallback · not motorcycle-optimized" : result.provider_status === "provider_configured" ? (result.mode === "walking" ? "Foot-walking route · verify access" : result.mode === "motorcycle" ? "Geoapify motorcycle route · verify access" : "Car road route") : result.provider_status === "unconfigured" ? "Provider setup required" : "Routing unavailable"}</span>}</div>
          <MapView center={originPoint || undefined} startPoint={originPoint} endPoint={destinationPoint} startLabel={originLocation?.display_name} endLabel={destinationLocation?.display_name} routes={routes} activeRoute={selected} onRouteSelect={selectRoute} trafficPoints={traffic && !trafficStale ? traffic.points || [] : []} className="route-map"/>
          {result?.error && <Notice kind="warning">We found both locations, but couldn’t get a {result.mode === "walking" ? "walking path" : result.mode === "motorcycle" ? "motorcycle route" : "car road route"}: {result.error}</Notice>}
          {originLocation && destinationLocation && <p className="form-helper">Matched: {originLocation.display_name} → {destinationLocation.display_name}</p>}
          <p className="form-helper">{result?.mode === "motorcycle" && result?.provider_status === "provider_configured" ? <>Routing © <a href="https://www.geoapify.com/" target="_blank" rel="noreferrer">Geoapify</a>. Map © OpenStreetMap contributors. Geoapify route times are estimates, not live traffic; verify signs and restrictions before travel.</> : <>Map © OpenStreetMap contributors. {result?.mode === "walking" ? "openrouteservice foot-walking distance and duration are estimates; check sidewalk, crossing, accessibility, and current access conditions." : result?.provider_status === "provider_fallback" ? "This displayed line follows OSRM's car profile. It is not motorcycle-optimized and does not verify motorcycle access or restrictions." : result?.mode === "motorcycle" ? "Geoapify motorcycle route geometry and durations are estimates; verify signs and restrictions before travel." : "Road distances and times come from the car-routing provider and do not include live traffic."}</>}</p>
          <div className="map-legend route-map-legend">{routes.map((route, index) => <span key={route.id || index}><i style={{ background: selected === index ? "#5637bf" : ROUTE_COLORS[index % ROUTE_COLORS.length] }}/> Route {index + 1}{selected === index ? " · selected" : ""}</span>)}{traffic && !trafficStale && traffic.points?.length > 0 && <span className="traffic-legend"><i className="traffic-dot traffic-dot--light"/> Light <i className="traffic-dot traffic-dot--moderate"/> Moderate <i className="traffic-dot traffic-dot--heavy"/> Heavy</span>}<span className="legend-right">© OpenStreetMap</span></div>
        </div>
      </section>
    </div>
    {modeResults && <section className="panel route-options-panel mode-comparison-panel" aria-labelledby="mode-comparison-title">
      <div className="panel-heading"><div><p className="eyebrow">MODE COMPARISON</p><h2 id="mode-comparison-title">Available ways to travel</h2></div><span className="muted-copy">Select a mode to view its route and details</span></div>
      <div className="route-option-grid">{[
        ["car", "Car", "Mapped car-road access"],
        ["motorcycle", "Motorcycle", "Geoapify motorcycle profile or OSRM fallback"],
        ["walking", "Walking", "openrouteservice foot-walking"],
      ].map(([travelMode, title, accessLabel]) => {
        const modeResult = modeResults[travelMode];
        const modeRoutes = modeResult?.alternatives || [];
        const fastest = modeRoutes.reduce((best, route) => !best || route.duration_s < best.duration_s ? route : best, null);
        const status = modeRoutes.length ? modeResult?.provider_status === "provider_fallback" ? "OSRM car-profile fallback · not motorcycle-optimized" : travelMode === "walking" ? "Walking route found · access unverified" : travelMode === "motorcycle" ? "Geoapify motorcycle route found · access unverified" : "Car route found · mapped rules only" : modeResult?.provider_status === "unconfigured" ? "Unavailable · provider setup required" : "Unavailable · no valid route returned";
        return <button type="button" key={travelMode} className={`route-option mode-comparison-card ${mode === travelMode ? "route-option--selected" : ""}`} onClick={() => selectMode(travelMode)} aria-pressed={mode === travelMode}>
          <span className="route-option__top"><span className="route-number">{title}</span><span className="route-label">{modeRoutes.length ? `${modeRoutes.length} route${modeRoutes.length === 1 ? "" : "s"}` : "No route"}</span></span>
          <strong>{fastest ? formatDuration(fastest.duration_s) : "—"}</strong>
          <span>{fastest ? formatDistance(fastest.distance_m) : accessLabel}</span>
          <small>{status}</small>
          <small>{fastest ? modeResult?.provider_status === "provider_fallback" ? "Car-profile estimate only; motorcycle-specific access and restrictions are not checked." : `Fastest provider estimate; traffic may change this. ${modeRoutes.length > 1 ? "Other alternatives are shown after selecting this mode." : ""}` : modeResult?.error || "This route mode is not covered for the selected locations."}</small>
        </button>;
      })}</div>
      <p className="form-helper">Each mode is requested independently. An unavailable mode is not replaced with directions for another vehicle. Times and distances are provider estimates; live traffic and map restriction coverage can be incomplete.</p>
    </section>}
    {result && <section className="panel route-options-panel">
      <div className="panel-heading"><div><p className="eyebrow">AVAILABLE ROUTES</p><h2>{routes.length ? "Compare the returned options" : "No route options returned"}</h2></div><span className="muted-copy">Provider estimates · no live traffic</span></div>
      {routes.length ? <div className="route-option-grid">{routes.map((route, index) =>
        <button key={route.id || index} className={`route-option ${index === selected ? "route-option--selected" : ""}`} disabled={busy} onClick={() => selectRoute(route, index)} aria-pressed={index === selected} aria-label={`Select Route ${index + 1}, ${route.id || `route-${index + 1}`}`}>
          <span className="route-option__top"><span className="route-number">Route {index + 1} · {route.id || `route-${index + 1}`}</span><span className="route-option__labels">{routeLabels(index).map((label) => <span className={label === "Recommended by travel time" ? "recommended-badge" : "route-label"} key={label}>{label}</span>)}</span></span>
          <strong>{formatDuration(route.duration_s)}</strong><span>{formatDistance(route.distance_m)}</span>
          <small>{route.safety_assessment?.label || "Insufficient evidence"} · conditions shown below</small>
        </button>,
      )}</div> : <EmptyState title="No route was returned">Check the location text and routing provider.</EmptyState>}
      {routes.length === 1 && <p className="form-helper">{result.maximum_alternatives === 1 ? "NAVIRA requested a maximum of one route." : "The provider returned only one distinct route after duplicate and overlap filtering."} No alternative geometry was fabricated.</p>}
      {routes.length > 1 && <p className="form-helper">Showing all {routes.length} distinct valid options returned by {result.provider}. Select a card or click its line on the map to choose a route.</p>}
      {!authenticated && routes.length > 0 && <p className="form-helper">Sign in to save your selected route for Journey Companion.</p>}
      {result.limitations?.map((limitation) => <p className="form-helper" key={limitation}>{limitation}</p>)}
    </section>}
    {result && routes.length > 0 && <section className="panel route-recommendation route-dashboard" aria-labelledby="route-recommendation-title">
      <div className="panel-heading"><div><p className="eyebrow">ROUTE CONDITIONS</p><h2 id="route-recommendation-title">Your Journey at a Glance</h2></div><span className="status-chip status-chip--amber">Evidence-aware · not a safety guarantee</span></div>
      <div className="journey-glance">
        <div className="journey-glance__route"><span className="journey-glance__pin journey-glance__pin--start"/><div><small>STARTING LOCATION</small><strong>{originLocation?.display_name || originPlace?.display_name || origin}</strong></div><span className="journey-glance__connector"/><span className="journey-glance__pin journey-glance__pin--end"/><div><small>DESTINATION</small><strong>{destinationLocation?.display_name || destinationPlace?.display_name || destination}</strong></div></div>
        <div className="journey-glance__metrics"><div><Icon name="clock" size={17}/><span><small>EST. TIME</small><strong>{formatDuration(activeRoute?.duration_s)}</strong></span></div><div><Icon name="pulse" size={17}/><span><small>TRAFFIC</small><strong>{result.mode === "walking" ? "Not applicable" : traffic?.level ? `${traffic.level[0].toUpperCase()}${traffic.level.slice(1)}` : trafficLoadingKeys[trafficKey] ? "Loading" : "Unavailable"}</strong></span></div><div><span className="journey-glance__weather-icon" aria-hidden="true">{primaryWeather?.current?.icon?.includes("n") ? "☾" : "☼"}</span><span><small>WEATHER</small><strong>{primaryWeather ? `${primaryWeather.current.temperature_c}°C · ${primaryWeather.current.condition}` : weatherLoadingKeys[trafficKey] ? "Loading" : "Unavailable"}</strong></span></div><div><Icon name="shield" size={17}/><span><small>ASSESSMENT</small><strong>{activeRoute?.safety_assessment?.label || "Insufficient evidence"}</strong></span></div></div>
      </div>
      <div className="route-dashboard-heading"><div><h3>Route insights</h3><p>Key conditions for Route {selected + 1}. Choose another option above to compare.</p></div><span>{formatDistance(activeRoute?.distance_m)} · {formatDuration(activeRoute?.duration_s)}</span></div>
      <div className="route-disclaimer">Weather and traffic describe travel conditions. They are not measures of personal safety. Missing reports do not mean zero incidents.</div>
      <div className="route-evidence-options">{routes.filter((_, routeIndex) => routeIndex === selected).map((route) => {
        const index = selected;
        const key = getRouteTrafficKey(route, index);
        const trafficEntry = trafficByRoute[key];
        const routeTraffic = trafficEntry?.data;
        const age = getTrafficAgeSeconds(trafficEntry, clock);
        const stale = age !== null && age > (routeTraffic?.stale_after_seconds || 180);
        const loading = Boolean(trafficLoadingKeys[key]);
        const trafficErrorForRoute = trafficErrors[key] || "";
        const weatherEntry = weatherByRoute[key];
        const routeWeather = weatherEntry?.data;
        const weatherLocations = routeWeather?.locations || [];
        const weatherAge = weatherEntry ? Math.max(0, Math.floor((clock - weatherEntry.receivedAt) / 1000)) : null;
        const weatherStale = weatherAge !== null && weatherAge > (routeWeather?.stale_after_seconds || 600);
        const weatherLoading = Boolean(weatherLoadingKeys[key]);
        const weatherError = weatherErrors[key] || "";
        const routeRainChance = Math.max(0, ...weatherLocations.map((location) => location.rain_probability_percent || 0));
        const routeWeatherCondition = weatherLocations.map((location) => location.current?.condition || "").find((condition) => /rain|storm|snow/i.test(condition));
        const assessment = route.safety_assessment || {};
        const incidentEvidence = route.safety_evidence || {};
        const verifiedIncidentCount = incidentEvidence.matched_incidents;
        const crimeStatus = verifiedIncidentCount > 0 ? "Alerts Found" : verifiedIncidentCount === 0 && incidentEvidence.eligible_records_in_window > 0 ? "No Verified Alerts" : "Limited Data";
        const latestHistoryRecord = official?.records?.at(-1);
        const providerTimes = [...new Set((routeTraffic?.points || []).map((point) => point.provider_observed_at).filter(Boolean))];
        return <article className={`route-evidence-option ${selected === index ? "route-evidence-option--selected" : ""}`} key={route.id || index} aria-label={`Route ${index + 1} evidence · ${route.id || `route-${index + 1}`}`} aria-current={selected === index ? "true" : undefined}>
          <header className="route-evidence-option__heading"><div><small>SELECTED ROUTE · {formatDistance(route.distance_m)}</small><h3>Estimated journey: {formatDuration(route.duration_s)}</h3></div></header>
          <div className="route-evidence-grid">
            <section className="route-evidence-panel evidence-card evidence-card--crime">
              <div className="evidence-card__heading"><span className="evidence-card__icon"><Icon name="report" size={19}/></span><h4>Crime &amp; News Alerts</h4></div>
              <strong className="evidence-card__value">{verifiedIncidentCount == null ? "Limited data" : `${verifiedIncidentCount} verified ${verifiedIncidentCount === 1 ? "report" : "reports"}`}</strong>
              <p>{verifiedIncidentCount > 0 ? "Verified reports matched sampled route locations." : "Reports are incomplete; missing matches do not mean zero crime."}</p>
              <span className={`evidence-status ${verifiedIncidentCount > 0 ? "evidence-status--alert" : "evidence-status--neutral"}`}>{crimeStatus}</span>
              <details className="evidence-details">
                <summary>View Incident Details</summary>
              <h4>Verified route matches and news context</h4>
              {selected === index && <div className="route-news-candidates">
                <h5>Recent crime-news reports along this route</h5>
                <small>We reverse-geocode up to six evenly spaced points on the selected route and search GDELT/Google News for the resulting Delhi localities. Locality coverage is sampled, not a complete boundary overlay. News hits are candidate reports and still need verification.</small>
                {newsLoading && <p role="status">Finding route localities and searching recent reports…</p>}
                {routeNewsError && <p role="alert">Route-locality news search unavailable: {routeNewsError}</p>}
                {routeNewsData?.route_locality_context && <small>{routeNewsData.route_locality_context.resolved_sample_count} of {routeNewsData.route_locality_context.sample_count} sampled route points resolved to a locality name. Unresolved areas are coverage gaps, not zero-crime areas.</small>}
                {routeNewsData?.route_locality_context?.route_localities?.length > 0 && <div className="route-news-group"><strong>Localities sampled along route</strong><ul>{routeNewsData.route_locality_context.route_localities.map((locality) => <li key={locality.name}>{locality.name} · {locality.precision} label{locality.sample_distances_m.length > 1 ? "s" : ""} at {locality.sample_distances_m.map((distance) => `${(distance / 1000).toFixed(1)} km`).join(", ")}</li>)}</ul></div>}
                {routeNewsData?.route_locality_context?.route_localities?.length === 0 && !newsLoading && <p>No Delhi locality names could be resolved from this route’s sample points.</p>}
                {routeNewsData?.groups?.length === 0 && !newsLoading && !routeNewsError && <p>No route-locality article searches could be completed. This does not mean zero crime.</p>}
                {(routeNewsData?.groups || []).map((group) => <div className="route-news-group" key={group.locality_search_term}><strong>{group.locality_search_term}</strong><small>{group.provider} · {group.status === "stale" ? "Cached snapshot · stale" : group.status === "available" ? `${group.returned} article candidates` : group.status === "unavailable" ? "Search unavailable" : "No indexed matches"}</small>{group.fallback_reason && <small>{group.fallback_reason}</small>}{group.provider_error && <small>{group.provider_error}</small>}{group.items?.length > 0 && <ul>{group.items.map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> — {item.headline_category_candidate.replaceAll("_", " ")} · {item.publisher} · published {item.published_at ? formatTimestamp(item.published_at) : "date unavailable"} · unverified locality mention; review source.</li>)}</ul>}{group.status === "no_results" && <small>No indexed article matched this locality in the search window. This does not mean zero crime.</small>}</div>)}
                {routeNewsData?.official_press_release_evidence && <div className="route-news-archive">
                  <h5>Delhi Police press-release evidence by route police station</h5>
                  <small><a href={routeNewsData.official_press_release_evidence.archive_url} target="_blank" rel="noreferrer">Open official archive</a> · {routeNewsData.official_press_release_evidence.provider}{routeNewsData.official_press_release_evidence.cache_status === "stale_fallback" ? " · cached snapshot, stale" : ""} · checked {formatTimestamp(routeNewsData.official_press_release_evidence.retrieved_at)}</small>
                  {routeNewsData?.route_police_station_context && <>
                    <small>Route-to-station match: {routeNewsData.route_police_station_context.match_method || "not available"}. <a href={routeNewsData.route_police_station_context.source_url} target="_blank" rel="noreferrer">Official station-boundary source</a>{routeNewsData.route_police_station_context.cache_status === "stale" ? " · boundary cache is stale" : ""}</small>
                    {routeNewsData.route_police_station_context.notice && <small>{routeNewsData.route_police_station_context.notice}</small>}
                    {routeNewsData.route_police_station_context.provider_error && <small role="status">{routeNewsData.route_police_station_context.provider_error}</small>}
                    {routeNewsData.route_police_station_context.stations?.length > 0 && <ul>{routeNewsData.route_police_station_context.stations.map((station) => <li key={`${station.name}-${station.first_sample_distance_m}`}>{station.name}{station.district ? ` · ${station.district}` : ""} · about {(station.first_sample_distance_m / 1000).toFixed(1)} km from route start</li>)}</ul>}
                  </>}
                  {routeNewsData.official_press_release_evidence.coverage_note && <small>{routeNewsData.official_press_release_evidence.coverage_note}</small>}
                  {routeNewsData.official_press_release_evidence.notice && <small>{routeNewsData.official_press_release_evidence.notice}</small>}
                  {routeNewsData.official_press_release_evidence.provider_error && <small role="status">{routeNewsData.official_press_release_evidence.provider_error}</small>}
                  {(routeNewsData.official_press_release_evidence.groups || []).map((group) => <div className="route-news-group" key={`press-${group.police_station || group.locality}`}>
                    <strong>{group.police_station || group.locality}{group.district ? ` · ${group.district}` : ""}</strong><small>{group.returned ? `${group.returned} press-release candidates` : group.status === "unavailable" ? "Archive unavailable" : group.status === "stale" ? "No match in the stale cached snapshot" : "No matching entry in the fetched archive page"}</small>
                    {group.notice && <small>{group.notice}</small>}
                    {group.items?.length > 0 && <ul>{group.items.map((item) => <li key={item.id}>
                      <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> — {item.headline_category_candidate.replaceAll("_", " ")} · {item.police_station ? `P.S. ${item.police_station}` : "police station not listed"}{item.district ? ` · ${item.district} district` : ""} · {item.published_at || item.published_date_text || "date unavailable"}{item.source_link_precision === "archive_listing_only" ? " · archive listing link only" : " · record link"} · {item.review_status.replaceAll("_", " ")}.
                    </li>)}</ul>}
                  </div>)}
                </div>}
                {routeNewsData?.official_locality_counts && <small>{routeNewsData.official_locality_counts.reason} Available city aggregate years: {routeNewsData.official_locality_counts.available_city_aggregate_years.join(", ")}.</small>}
              </div>}
              </details>
            </section>
            <section className="route-evidence-panel evidence-card evidence-card--history">
              <div className="evidence-card__heading"><span className="evidence-card__icon"><Icon name="clock" size={19}/></span><h4>Historical Crime Statistics</h4></div>
              <strong className="evidence-card__value">{latestHistoryRecord?.count != null ? Number(latestHistoryRecord.count).toLocaleString() : "Unavailable"}</strong>
              <p>{latestHistoryRecord ? `${latestHistoryRecord.year} · Historical city-level crime trend.` : "No historical count is available for this view."}</p>
              <span className="evidence-status evidence-status--info">Historical Data</span>
              <details className="evidence-details">
                <summary>View Crime Trends</summary>
              <h4>Historical official statistics</h4>
              <p>{official?.geographic_precision || "Historical aggregate data"} · {official?.geography || "geography unavailable"}. City-level totals do not represent crime on this road.</p>
              {official?.records?.length > 0 && <small>{official.records.map((record) => `${record.year}: ${record.count.toLocaleString()} registered cases`).join(" · ")}</small>}
              {sourceLinks.map((source) => <a href={source} key={source} target="_blank" rel="noreferrer">Official source</a>)}
              {official && <small>Version {official.version || "not provided"} · retrieved {formatTimestamp(official.retrieved_at)}.</small>}
              </details>
            </section>
            <section className="route-evidence-panel evidence-card evidence-card--traffic">
              <div className="evidence-card__heading"><span className="evidence-card__icon"><Icon name="route" size={19}/></span><h4>Live Traffic</h4></div>
              <strong className="evidence-card__value">{result.mode === "walking" ? "Not applicable" : routeTraffic?.level ? `${routeTraffic.level[0].toUpperCase()}${routeTraffic.level.slice(1)} traffic` : loading && !routeTraffic ? "Loading traffic…" : "Unavailable"}</strong>
              <p>{routeTraffic?.estimated_delay_s != null ? `About ${formatDuration(routeTraffic.estimated_delay_s)} additional travel time.` : "Live traffic conditions along your route."}</p>
              <span className={`evidence-status ${routeTraffic && ["available", "partial"].includes(routeTraffic.status) && !stale ? "evidence-status--live" : "evidence-status--neutral"}`}>{result.mode === "walking" ? "Not applicable" : routeTraffic && ["available", "partial"].includes(routeTraffic.status) && !stale ? "Live" : stale ? "Stale data" : "Unavailable"}</span>
              <details className="evidence-details">
                <summary>View Traffic Details</summary>
              <h4>Live traffic details</h4>
              {trafficErrorForRoute && <p>{trafficErrorForRoute}</p>}
              {routeTraffic?.status === "unconfigured" && <p>Live traffic needs the backend <code>TOMTOM_API_KEY</code>.</p>}
              {routeTraffic && ["available", "partial"].includes(routeTraffic.status) && <>
                <p>{routeTraffic.coverage?.sampled}/{routeTraffic.coverage?.requested} TomTom route-point samples · {routeTraffic.provider}. {stale ? "This snapshot is stale and is not current." : "Live provider snapshot."}</p>
                <p>Response retrieved by NAVIRA: {formatTimestamp(routeTraffic.retrieved_at)}.</p>
                {providerTimes.length > 0 && <p>Provider observation timestamp: {providerTimes.map(formatTimestamp).join(", ")}.</p>}
                <p>Observed samples: {(routeTraffic.points || []).map((sample) => `${sample.current_speed_kmh} km/h${sample.road_closure ? " (closure reported)" : ""}${sample.confidence == null ? "" : ` · provider confidence ${sample.confidence}`}`).join(" · ") || "No flow points returned"}.</p>
                <p>Estimated delay: {formatDuration(routeTraffic.estimated_delay_s)} · estimated travel time: {formatDuration(routeTraffic.estimated_travel_time_s)}. This is a NAVIRA estimate from sampled current/free-flow speed ratios, not a provider travel-time observation.</p>
              </>}
              {routeTraffic?.status === "unavailable" && <p>No live traffic observations were available for this route.</p>}
              {loading && !routeTraffic && <p>Requesting current flow samples for this route.</p>}
              </details>
            </section>
            <section className="route-evidence-panel evidence-card evidence-card--weather weather-agent-panel">
              <div className="evidence-card__heading"><span className="evidence-card__icon"><span aria-hidden="true">☁</span></span><h4>Weather Updates</h4></div>
              <strong className="evidence-card__value">{primaryWeather ? `${primaryWeather.current.temperature_c}°C · ${primaryWeather.current.condition}` : weatherLoading ? "Loading weather…" : "Weather information is temporarily unavailable."}</strong>
              <p>{primaryWeather ? `Feels ${primaryWeather.current.feels_like_c}° · rain chance ${primaryWeather.rain_probability_percent ?? "—"}% · humidity ${primaryWeather.current.humidity_percent}% · wind ${primaryWeather.current.wind_speed_kmh} km/h` : weatherError || "Current weather and forecast for sampled route locations."}</p>
              {primaryWeather?.forecast?.length > 0 && <div className="weather-forecast weather-forecast--dashboard" aria-label="Three forecast periods">{primaryWeather.forecast.slice(0, 3).map((item) => <span key={`${item.time}-${item.temperature_c}`}><small>{formatForecastTime(item.time)}</small><b>{item.temperature_c}°</b><small>{item.condition}</small>{item.rain_probability > 0 && <small>Rain {item.rain_probability}%</small>}</span>)}</div>}
              {primaryWeather && <p className="weather-consideration">{routeRainChance >= 40 ? "Rain is forecast along sampled route points. Carry an umbrella and allow for wet conditions." : routeWeatherCondition ? `${routeWeatherCondition} reported along the route. Check conditions before leaving.` : "No high rain probability in the forecast preview. Recheck conditions before departure."}</p>}
              <span className={`evidence-status ${routeWeather?.status === "available" && !weatherStale ? "evidence-status--live" : "evidence-status--neutral"}`}>{routeWeather?.status === "available" && !weatherStale ? "Live" : weatherStale ? "Stale data" : routeWeather?.status === "partial" ? "Partial data" : "Unavailable"}</span>
              <details className="evidence-details">
                <summary>View Weather Details</summary>
              <h4><span aria-hidden="true">☁</span> 4. Weather Agent</h4>
              <strong className="weather-agent-status">{weatherLoading && !routeWeather ? "Loading route weather…" : routeWeather?.status === "unconfigured" ? "Not configured" : routeWeather?.status === "unavailable" || weatherError ? "Unavailable" : routeWeather?.status === "partial" ? "Partial conditions" : weatherStale ? "Weather snapshot is stale" : routeWeather?.status === "available" ? <><i/> LIVE · OpenWeatherMap</> : "Waiting for route"}</strong>
              {weatherError && <p role="status">{weatherError}</p>}
              {routeWeather?.status === "unconfigured" && <p>Live weather needs <code>OPENWEATHER_API_KEY</code> on the backend.</p>}
              {routeWeather?.message && routeWeather.status !== "unconfigured" && <p>{routeWeather.message}</p>}
              {weatherLocations[0]?.alerts_note && <small>{weatherLocations[0].alerts_note}</small>}
              {weatherLocations.map((location) => <div className="weather-location" key={`${location.route_position}-${location.latitude}-${location.longitude}`}>
                <small>{location.route_position} · {location.location}</small>
                <strong className="weather-temperature">{location.current.temperature_c}°C <span>{location.current.condition}</span></strong>
                <small>Feels {location.current.feels_like_c}° · humidity {location.current.humidity_percent}% · wind {location.current.wind_speed_kmh} km/h</small>
                {location.forecast?.length > 0 && <div className="weather-forecast" aria-label={`${location.route_position} forecast preview`}>{location.forecast.slice(0, 3).map((item) => <span key={`${item.time}-${item.temperature_c}`}><small>{formatForecastTime(item.time)}</small><b>{item.temperature_c}°</b><small>{item.condition}</small>{item.rain_probability > 0 && <small>Rain {item.rain_probability}%</small>}</span>)}</div>}
                {location.rain_probability_percent != null && <small>Highest rain probability in preview: {location.rain_probability_percent}%</small>}
              </div>)}
              {routeRainChance >= 40 && <p className="weather-consideration">Rain is forecast at one or more sampled route points; wet conditions may affect walking comfort and visibility.</p>}
              {routeRainChance < 40 && routeWeatherCondition && <p className="weather-consideration">{routeWeatherCondition} is currently reported at a sampled route point; check conditions again before leaving.</p>}
              {weatherLoading && !routeWeather && <p role="status">Checking current conditions and forecast at route locations…</p>}
              {routeWeather?.limitations?.map((limitation) => <small key={limitation}>{limitation}</small>)}
              </details>
            </section>
            <section className="route-evidence-panel evidence-card evidence-card--infrastructure">
              <div className="evidence-card__heading"><span className="evidence-card__icon"><Icon name="pin" size={19}/></span><h4>Road Infrastructure</h4></div>
              <strong className="evidence-card__value">{infrastructureLoading ? "Checking mapped features…" : infrastructure?.status === "available" ? `${infrastructure.streetlights_mapped} lights · ${infrastructure.footpaths_mapped} paths` : "Infrastructure unavailable"}</strong>
              <p>{infrastructureLoading ? `Searching OpenStreetMap within ${infrastructureCorridor} m of the selected route…` : infrastructure?.status === "available" ? `${infrastructure.mapped_feature_count} mapped features within ${infrastructure.corridor_m} m of route` : infrastructureError || "Live map coverage has not been retrieved."}</p>
              <label className="infrastructure-corridor-control">Search corridor <select aria-label="Infrastructure corridor width" value={infrastructureCorridor} onChange={(event) => setInfrastructureCorridor(Number(event.target.value))}><option value={50}>50 m</option><option value={100}>100 m</option><option value={250}>250 m</option><option value={500}>500 m</option></select></label>
              <span className="evidence-status evidence-status--neutral">{infrastructure?.status === "available" ? infrastructure.working_status_label : infrastructureLoading ? "Loading mapped data" : "Unavailable"}</span>
              <p className="infrastructure-summary">{infrastructureLoading ? "The map lookup is still in progress. Working condition and nighttime visibility are not verified." : infrastructure?.status === "available" ? infrastructure.streetlights_mapped || infrastructure.footpaths_mapped ? "Mapped features provide context only; working condition and nighttime visibility are not verified." : "No mapped features were returned in this corridor. OpenStreetMap coverage may be incomplete." : "Live infrastructure data is unavailable. Missing data does not mean no streetlights or footpaths exist."}</p>
              <small className="infrastructure-night-status">Night visibility: {infrastructure?.night_visibility_label || "Not assessed — no lighting audit or night-visibility measurement is available."}</small>
              <details className="evidence-details">
                <summary>View Details</summary>
                <h4>Route corridor and data coverage</h4>
                {infrastructure?.retrieved_at && <p>Retrieved: {formatTimestamp(infrastructure.retrieved_at)}</p>}
                <p>{infrastructureLoading ? "The route corridor lookup is in progress." : infrastructure?.coverage?.note || infrastructure?.reason || infrastructureError || "The live OpenStreetMap provider has not returned route corridor data."}</p>
                {infrastructure?.source_url && <p><a href={infrastructure.source_url} target="_blank" rel="noreferrer">OpenStreetMap source · © OpenStreetMap contributors</a></p>}
                {infrastructure?.streetlights?.length > 0 && <div><h4>Streetlights mapped (not inspected)</h4>{infrastructure.streetlights.slice(0, 12).map((item) => <p key={item.id}><a href={item.source_url} target="_blank" rel="noreferrer">{item.name || item.id}</a> · {item.distance_to_route_m} m from route · lit tag {item.lighting_tag || "not recorded"}</p>)}</div>}
                {infrastructure?.footpaths?.length > 0 && <div><h4>Pedestrian ways mapped</h4>{infrastructure.footpaths.slice(0, 12).map((item) => <p key={item.id}><a href={item.source_url} target="_blank" rel="noreferrer">{item.name || `${item.highway} · ${item.id}`}</a> · {item.distance_to_route_m} m · lighting tag {item.lighting_tag || "not recorded"}</p>)}</div>}
                {infrastructure?.lighting_tags_on_paths && <p>Way lighting tags: {infrastructure.lighting_tags_on_paths.lit_tagged} lit-tagged · {infrastructure.lighting_tags_on_paths.unlit_tagged} unlit-tagged · {infrastructure.lighting_tags_on_paths.limited_lighting_tagged} limited · {infrastructure.lighting_tags_on_paths.unrecorded} unrecorded. Tags do not confirm lamp operation.</p>}
                <h4>Official inspections and complaint sources</h4>
                {(infrastructure?.official_sources || []).map((source) => <p key={source.name}><a href={source.source_url} target="_blank" rel="noreferrer">{source.name} information</a> · {source.status === "unavailable" ? "route-level records unavailable" : source.status}{source.note ? ` — ${source.note}` : ""}{source.complaint_url ? <> · <a href={source.complaint_url} target="_blank" rel="noreferrer">complaints</a></> : null}</p>)}
                {!infrastructure && <><p><a href="https://pwd.delhi.gov.in/" target="_blank" rel="noreferrer">Delhi PWD</a> · inspection feed unavailable</p><p><a href="https://mcdonline.nic.in/portal/feedback" target="_blank" rel="noreferrer">MCD / MCD 311</a> · complaint counts unavailable</p><p><a href="https://www.ndmc.gov.in/ndmc/achievements_it.aspx" target="_blank" rel="noreferrer">NDMC smart infrastructure</a> · route inspection unavailable</p></>}
                {infrastructure?.limitations?.map((limitation) => <p key={limitation}>{limitation}</p>)}
              </details>
            </section>
            <section className="route-evidence-panel evidence-card evidence-card--assessment">
              <div className="evidence-card__heading"><span className="evidence-card__icon"><Icon name="shield" size={19}/></span><h4>Overall Route Assessment</h4></div>
              <strong className="evidence-card__value">{assessment.label || "Insufficient Evidence"}</strong>
              <p>{assessment.summary || "Available evidence does not support a route-level safety score."}</p>
              <div className="assessment-factors"><span>Crime &amp; News <b>{verifiedIncidentCount > 0 ? "Verified matches" : verifiedIncidentCount === 0 ? "No matches" : "Limited data"}</b></span><span>Traffic &amp; Weather <b>{routeTraffic?.level ? `${routeTraffic.level} traffic` : "Context only"}{routeRainChance >= 40 ? " · rain possible" : ""}</b></span><span>Infrastructure <b>{infrastructure?.status === "available" ? "Mapped only" : "Unavailable"}</b></span></div>
              <p className="assessment-recommendation"><strong>Suggested next step:</strong> {routeRainChance >= 40 ? "Carry weather protection and allow for wet conditions." : routeTraffic?.level === "heavy" ? "Allow extra time for current traffic conditions." : "Review the available evidence and recheck conditions before departure."}</p>
              <span className="evidence-status evidence-status--neutral">{assessment.status === "insufficient_evidence" || !assessment.status ? "Insufficient Evidence" : assessment.label || "Assessment available"}</span>
              <details className="evidence-details">
                <summary>View Full Assessment</summary>
                <h4>Assessment details</h4>
                <p>{assessment.summary || "A route-level safety percentage is withheld because the available data does not establish comparable exposure or complete route coverage."}</p>
              <ul>
                <li>Verified newspaper reports are observations, not a complete incident denominator.</li>
                <li>Historical official statistics are aggregate-only and cannot be assigned to this route.</li>
                <li>Traffic and provider-estimated travel time are context, not personal-safety indicators.</li>
                <li>Mapped infrastructure is unverified and is not used to calculate a safety assessment.</li>
              </ul>
              <small>Safety percentage: {assessment.estimated_safety_percentage ?? "Insufficient evidence"}. Missing evidence is not proof of safety.</small>
              {assessment.method && <p>Method: {assessment.method.name}. {assessment.method.reason}</p>}
              {assessment.limitations?.map((limitation) => <small key={limitation}>{limitation}</small>)}
              </details>
            </section>
            <section className="route-evidence-panel evidence-card evidence-card--synthetic-demo" aria-label="Synthetic crime-rate examples">
              <div className="synthetic-demo-banner synthetic-demo-banner--inline" role="alert"><Icon name="report" size={13}/><strong>SYNTHETIC DEMO — NOT REAL SAFETY DATA</strong></div>
              <div className="evidence-card__heading"><span className="evidence-card__icon"><Icon name="report" size={19}/></span><h4>Synthetic crime-rate examples</h4></div>
              <p>Fictional examples shown separately for interface demonstration. They are not mapped to this route or used in its assessment.</p>
              {syntheticDemoError && <small role="status">Synthetic examples unavailable: {syntheticDemoError}</small>}
              {!syntheticDemoData && !syntheticDemoError && <small role="status">Loading fictional examples…</small>}
              {syntheticDemoData?.synthetic_crime_rate_examples?.map((example) => <div className="synthetic-crime-example" key={example.example_id}>
                <strong>{example.fictional_area}</strong>
                <b>{example.example_rate_per_10000_fictional_residents} example reports per 10,000 fictional residents</b>
                <small>{example.example_reports} invented reports ÷ {Number(example.fictional_population).toLocaleString()} fictional residents · {example.period}</small>
              </div>)}
              <small>Invented counts and denominators; not actual crime rates. Changing the route or its locations does not change these examples.</small>
            </section>
          </div>
        </article>;
      })}</div>
    </section>}
    <Notice kind="info">Route times and reports have coverage limits. Weather and traffic are travel context, not safety ratings; review each card’s details and check local conditions before departure.</Notice>
  </>;
}
