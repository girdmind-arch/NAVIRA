import { useEffect, useState } from "react";
import { backendApi, routesApi } from "../services/api";
import MapView from "./MapView";
import { Notice } from "./ui";

function PlaceField({ id, label, value, setValue, selected, setSelected }) {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const query = value.trim();
    if (query.length < 3 || selected) return undefined;
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      routesApi.suggest(query)
        .then((result) => {
          if (!active) return;
          const items = result.items || [];
          setSuggestions(items);
          setError(items.length ? "" : "No matching places. Try adding a locality or city.");
        })
        .catch((requestError) => {
          if (active) {
            setSuggestions([]);
            setError(`Location suggestions unavailable: ${requestError.message}`);
          }
        })
        .finally(() => { if (active) setLoading(false); });
    }, 400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [selected, value]);

  return <div className="location-search">
    <label htmlFor={id}>{label}</label>
    <div className="input-with-icon"><span className={`location-dot location-dot--${id.endsWith("origin") ? "start" : "end"}`}/><input id={id} autoComplete="off" role="combobox" aria-autocomplete="list" value={value} onChange={(event) => { setValue(event.target.value); setSelected(null); setSuggestions([]); setError(""); }} placeholder={id.endsWith("origin") ? "Search a locality, landmark, or address" : "Search your destination"} minLength={2} maxLength={200} required/></div>
    {selected && <small className="form-helper">Selected location: {selected.display_name}</small>}
    {!selected && value.trim().length >= 3 && loading && <small className="form-helper" role="status">Searching OpenStreetMap places…</small>}
    {!selected && value.trim().length >= 3 && error && !loading && <small className="form-helper location-search__message">{error}</small>}
    {!selected && suggestions.length > 0 && <div className="location-suggestions" role="listbox" aria-label={`${label} suggestions`}>{suggestions.map((place, index) => <button type="button" role="option" key={`${place.latitude}-${place.longitude}-${index}`} onClick={() => { setValue(place.display_name); setSelected(place); setSuggestions([]); setError(""); }}><strong>{place.display_name}</strong><small>{place.place_type || place.provider}</small></button>)}</div>}
  </div>;
}

export default function WalkingPilot() {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [originPlace, setOriginPlace] = useState(null);
  const [destinationPlace, setDestinationPlace] = useState(null);
  const [result, setResult] = useState(null);
  const [reports, setReports] = useState(null);
  const [reportError, setReportError] = useState("");
  const [network, setNetwork] = useState(null);
  const [networkError, setNetworkError] = useState("");
  const [networkLoading, setNetworkLoading] = useState(false);
  const [evidence, setEvidence] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    backendApi.routeSafetyDataStatus().then((data) => { if (active) setEvidence(data); })
      .catch((requestError) => { if (active) setError(requestError.message); });
    return () => { active = false; };
  }, []);

  const route = result?.alternatives?.[0];
  const coordinates = route?.geometry?.coordinates;
  useEffect(() => {
    if (!Array.isArray(coordinates) || coordinates.length < 2) return undefined;
    let active = true;
    const longitudes = coordinates.map((point) => point[0]);
    const latitudes = coordinates.map((point) => point[1]);
    const padding = .004;
    const bbox = [Math.min(...longitudes) - padding, Math.min(...latitudes) - padding, Math.max(...longitudes) + padding, Math.max(...latitudes) + padding];
    if (bbox[2] - bbox[0] > .1 || bbox[3] - bbox[1] > .1) {
      const timer = window.setTimeout(() => { if (active) { setNetwork(null); setNetworkLoading(false); setNetworkError("This walking route is outside the pilot map query size."); } }, 0);
      return () => { active = false; window.clearTimeout(timer); };
    }
    const timer = window.setTimeout(() => {
      if (!active) return;
      setNetwork(null);
      setNetworkLoading(true);
      setNetworkError("");
      routesApi.pedestrianNetwork(bbox)
        .then((data) => { if (active) setNetwork(data); })
        .catch((requestError) => { if (active) setNetworkError(requestError.message); })
        .finally(() => { if (active) setNetworkLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [coordinates]);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setResult(null);
    setReports(null);
    setReportError("");
    setNetwork(null);
    if (!originPlace || !destinationPlace) {
      setError("Select an exact starting place and destination from the suggestions.");
      return;
    }
    setBusy(true);
    try {
      const [walkingResult, reportResult] = await Promise.all([
        routesApi.walking(originPlace.display_name, destinationPlace.display_name),
        routesApi.localityReports(originPlace.display_name, destinationPlace.display_name).catch((requestError) => {
          setReportError(requestError.message);
          return null;
        }),
      ]);
      setResult(walkingResult);
      setReports(reportResult);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  const start = result?.resolved_locations?.origin || originPlace;
  const end = result?.resolved_locations?.destination || destinationPlace;
  const startPoint = start ? [start.latitude, start.longitude] : null;
  const endPoint = end ? [end.latitude, end.longitude] : null;
  const alternatives = result?.alternatives || [];

  return <section className="panel route-context-panel walking-pilot-panel">
    <div className="panel-heading"><div><p className="eyebrow">WALKING · OPENROUTESERVICE</p><h2>Foot-walking directions</h2></div><span className="status-chip status-chip--amber">Verify ground access</span></div>
    <p className="form-helper">Directions come from openrouteservice’s foot-walking profile. OSM coverage and tags may omit sidewalks, crossings, accessibility details, or current restrictions; check local conditions.</p>
    <form className="stack-form" onSubmit={submit}>
      <PlaceField id="walking-origin" label="Starting location" value={origin} setValue={setOrigin} selected={originPlace} setSelected={setOriginPlace}/>
      <PlaceField id="walking-destination" label="Destination location" value={destination} setValue={setDestination} selected={destinationPlace} setSelected={setDestinationPlace}/>
      <button className="button button--secondary" type="submit" disabled={busy}>{busy ? "Finding walking directions…" : "Find walking route"}</button>
    </form>
    {error && <Notice kind="error">{error}</Notice>}
    {evidence && <p className="route-disclaimer">Route safety evidence: {evidence.status === "available" ? `${evidence.route_matched_verified_incidents} reviewed incident-to-segment matches` : "insufficient data for a route-level safety estimate"}. NCRB city totals and locality-only reports do not create a safety score.</p>}
    {alternatives.length > 0 && route && <>
      <div className="route-layout">
        <div className="panel map-panel"><div className="panel-heading"><div><p className="eyebrow">OPENROUTESERVICE · OSM MAP</p><h3>Walking route</h3></div></div>
          <MapView center={startPoint || undefined} startPoint={startPoint} endPoint={endPoint} startLabel={start?.display_name} endLabel={end?.display_name} routes={alternatives} activeRoute={0} pedestrianNetwork={network} className="route-map"/>
          {networkLoading && <p className="form-helper" role="status">Loading pedestrian map context…</p>}
          {network?.returned > 0 && <p className="form-helper">Green dashed lines show {network.returned} OSM ways with pedestrian-related tags; mapped access is not field-verified.</p>}
          {networkError && <p className="form-helper">Pedestrian map context unavailable: {networkError}</p>}
          <p className="form-helper">Map © OpenStreetMap contributors. The dashed green local pilot overlay is incomplete map context and does not determine the openrouteservice route.</p>
        </div>
        <div className="panel route-options-panel"><p className="eyebrow">WALK ESTIMATE</p><h3>{Math.round(route.duration_s / 60)} min · {(route.distance_m / 1000).toFixed(1)} km</h3>
          {result.snap_gaps_m && <p className="form-helper">Nearest mapped-node offsets: origin {Math.round(result.snap_gaps_m.origin)} m; destination {Math.round(result.snap_gaps_m.destination)} m. Estimated at {result.walking_speed_mps} m/s.</p>}
          {result.limitations?.map((item) => <p className="form-helper" key={item}>{item}</p>)}
        </div>
      </div>
      <div className="route-news-result"><strong>Source-reported endpoint context</strong><p>Text matches use selected origin/destination locality names only. Reports are not snapped to the walking route and do not imply risk.</p>
        {reportError && <p>Locality context unavailable: {reportError}</p>}
        {reports?.items?.length ? reports.items.map((item) => <article key={`${item.id}-${item.source_url}`}><strong>{item.category || "Reported incident"} · {item.locality}{item.landmark ? ` · ${item.landmark}` : ""}</strong><p>{item.event_date || "Date unavailable"} · {item.status} · {item.review_status}</p><p>{item.summary}</p><a href={item.source_url} target="_blank" rel="noreferrer">Open source: {item.source_title || item.source_url}</a></article>) : reports && <p>No imported report matched these endpoint place names. This does not mean no incidents occurred.</p>}
      </div>
    </>}
    {result && alternatives.length === 0 && <Notice kind="warning">No pilot walking path is available: {result.error || "the selected locations are outside connected pedestrian-map coverage."}</Notice>}
  </section>;
}
