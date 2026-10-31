import { useEffect, useMemo, useState } from "react";
import { Icon, Notice, PageHeading } from "../components/ui";
import MapView from "../components/MapView";
import { facilitiesApi, journeysApi } from "../services/api";

function formatDistance(meters) {
  if (!Number.isFinite(meters)) return "Road distance unavailable";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km by road` : `${Math.round(meters)} m by road`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "Road time unavailable";
  const minutes = Math.max(1, Math.round(seconds / 60));
  return minutes >= 60 ? `${Math.floor(minutes / 60)} hr ${minutes % 60} min by road` : `${minutes} min by road`;
}

function directionsUrl(origin, destination) {
  const from = `${origin.latitude},${origin.longitude}`;
  const to = `${destination.latitude},${destination.longitude}`;
  return `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(from)}&destination=${encodeURIComponent(to)}&travelmode=driving`;
}

export default function NearbyFacilities({ routeContext, authenticated, onNavigate }) {
  const [activeJourney, setActiveJourney] = useState(null);
  const [activeJourneyError, setActiveJourneyError] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [category, setCategory] = useState("all");
  const [radiusM, setRadiusM] = useState(5000);
  const [facilityResult, setFacilityResult] = useState(null);

  useEffect(() => {
    if (!authenticated) return undefined;
    let active = true;
    journeysApi.active()
      .then((journey) => { if (active) setActiveJourney(journey?.active ? journey : null); })
      .catch((requestError) => { if (active) setActiveJourneyError(requestError.message); });
    return () => { active = false; };
  }, [authenticated]);

  const locationOptions = useMemo(() => {
    const options = [];
    if (routeContext?.origin && Number.isFinite(routeContext.origin.latitude) && Number.isFinite(routeContext.origin.longitude)) {
      options.push({ id: "planned-origin", label: `Route Planner — Start: ${routeContext.origin.display_name}`, ...routeContext.origin });
    }
    if (routeContext?.destination && Number.isFinite(routeContext.destination.latitude) && Number.isFinite(routeContext.destination.longitude)) {
      options.push({ id: "planned-destination", label: `Route Planner — Destination: ${routeContext.destination.display_name}`, ...routeContext.destination });
    }
    if (activeJourney?.route?.geometry?.coordinates?.length) {
      const start = activeJourney.route.geometry.coordinates[0];
      const end = activeJourney.route.geometry.coordinates.at(-1);
      if (Array.isArray(start) && start.length >= 2) options.push({
        id: "journey-origin",
        label: `Active journey — Start: ${activeJourney.origin}`,
        latitude: start[1],
        longitude: start[0],
        display_name: activeJourney.origin,
      });
      if (Array.isArray(end) && end.length >= 2) options.push({
        id: "journey-destination",
        label: `Active journey — Destination: ${activeJourney.destination}`,
        latitude: end[1],
        longitude: end[0],
        display_name: activeJourney.destination,
      });
    }
    return options;
  }, [activeJourney, routeContext]);

  const reference = locationOptions.find((location) => location.id === referenceId) || locationOptions[0];
  const requestKey = reference ? `${reference.id}:${reference.latitude}:${reference.longitude}:${category}:${radiusM}` : "";
  const resultIsCurrent = facilityResult?.key === requestKey;
  const facilities = resultIsCurrent ? facilityResult.items : [];
  const loading = Boolean(requestKey && !resultIsCurrent);
  const error = resultIsCurrent ? facilityResult.error : "";
  const routingNote = resultIsCurrent ? facilityResult.routingNote : "";
  const providerNote = resultIsCurrent ? facilityResult.providerNote : "";
  const categoryCounts = resultIsCurrent ? facilityResult.categoryCounts : null;

  useEffect(() => {
    if (!reference) return undefined;
    let active = true;
    const key = `${reference.id}:${reference.latitude}:${reference.longitude}:${category}:${radiusM}`;
    facilitiesApi.nearby(reference.latitude, reference.longitude, category, radiusM)
      .then((result) => {
        if (!active) return;
        setFacilityResult({
          key,
          items: result.items || [],
          categoryCounts: result.category_counts || null,
          error: "",
          routingNote: result.routing_note || "",
          providerNote: [result.coverage_note, result.operating_status_note].filter(Boolean).join(" "),
        });
      })
      .catch((requestError) => {
        if (!active) return;
        setFacilityResult({ key, items: [], error: requestError.message, routingNote: "", providerNote: "" });
      });
    return () => { active = false; };
  }, [category, radiusM, reference]);

  const categoryTabs = [
    { value: "all", label: "All facilities" },
    { value: "police", label: "Police stations" },
    { value: "hospitals", label: "Hospitals" },
  ];

  return <>
    <PageHeading eyebrow="NEARBY HELP" title="Nearby Facilities" description="Find mapped police stations and hospitals near a selected Route Planner location. Listings and current operating status are not independently verified." action={<span className="status-chip status-chip--lavender"><Icon name="pin" size={14}/> OpenStreetMap + Delhi Police data</span>}/>
    {!locationOptions.length ? <section className="panel facilities-empty">
      <Icon name="route" size={25}/>
      <h2>Plan a route to choose a search location</h2>
      <p>Nearby Facilities uses the exact start or destination coordinates selected in Route Planner. It does not request device location permission.</p>
      {activeJourneyError && <Notice kind="warning">Could not check for a saved active journey: {activeJourneyError}</Notice>}
      <button className="button button--primary" type="button" onClick={() => onNavigate("routes")}>Open Route Planner</button>
    </section> : <>
      {activeJourneyError && <Notice kind="warning">Your active journey could not be loaded: {activeJourneyError}. Planned Route Planner locations are still available.</Notice>}
      <section className="panel facilities-controls">
        <div className="facilities-location-control">
          <label htmlFor="facility-reference">Search near</label>
          <select id="facility-reference" value={reference?.id || ""} onChange={(event) => setReferenceId(event.target.value)}>
            {locationOptions.map((location) => <option key={location.id} value={location.id}>{location.label}</option>)}
          </select>
        </div>
        <div className="facilities-filter" role="group" aria-label="Facility category">
          {categoryTabs.map((tab) => <button key={tab.value} type="button" className={category === tab.value ? "is-active" : ""} aria-pressed={category === tab.value} onClick={() => setCategory(tab.value)}>{tab.label}</button>)}
        </div>
        <div className="facilities-location-control facilities-radius-control">
          <label htmlFor="facility-radius">Search radius</label>
          <select id="facility-radius" value={radiusM} onChange={(event) => setRadiusM(Number(event.target.value))}>
            <option value={2000}>2 km</option><option value={5000}>5 km</option><option value={10000}>10 km</option>
          </select>
        </div>
        {reference && <p className="form-helper">Reference: {reference.display_name || reference.label} · results are sorted by road distance where a route is available.</p>}
      </section>
      <div className="facilities-layout">
        <section className="panel facilities-map-panel">
          <div className="panel-heading"><div><p className="eyebrow">FACILITY MAP</p><h2>{reference?.display_name || reference?.label}</h2></div>{loading && <span className="status-chip status-chip--lavender" role="status">Searching…</span>}</div>
          {reference && <MapView center={[reference.latitude, reference.longitude]} startPoint={[reference.latitude, reference.longitude]} startLabel={reference.display_name || reference.label} facilities={facilities} className="facilities-map"/>}
          {routingNote && <p className="form-helper">{routingNote}</p>}
        </section>
        <section className="panel facilities-results">
          <div className="panel-heading"><div><p className="eyebrow">OPENSTREETMAP LISTINGS</p><h2>{category === "all" ? "Nearby facilities" : category === "police" ? "Nearby police stations" : "Nearby hospitals"}</h2>{category === "all" && categoryCounts && <small>{categoryCounts.police} police stations · {categoryCounts.hospitals} hospitals</small>}</div><span className="status-chip">{facilities.length} found</span></div>
          {providerNote && <p className="facilities-disclaimer">{providerNote}</p>}
          {error && <Notice kind="error">{error}</Notice>}
          {loading && <p className="muted-copy" role="status">Searching mapped facilities and estimating road distances…</p>}
          {!loading && !error && !facilities.length && <div className="facilities-empty-state"><Icon name="pin" size={21}/><strong>No mapped facilities found within {(radiusM / 1000).toFixed(0)} km.</strong><p>Try a different route location or expand the search radius. OpenStreetMap coverage may be incomplete; no results do not confirm that no facility exists nearby.</p>{radiusM < 10000 && <button className="button button--secondary" type="button" onClick={() => setRadiusM(10000)}>Search within 10 km</button>}</div>}
          {!loading && facilities.length > 0 && <div className="facility-list">{facilities.map((facility) => <article className="facility-card" key={facility.id}>
            <div className={`facility-icon ${facility.kind === "police" ? "facility-icon--police" : "facility-icon--hospital"}`}><Icon name={facility.kind === "police" ? "shield" : "hospital"} size={18}/></div>
            <div className="facility-card__body">
              <strong>{facility.name || `${facility.kind === "police" ? "Police facility" : "Hospital"} — name not listed`}</strong>
              <span>{facility.kind === "police" ? "Police station / facility" : "Hospital"}</span>
              <p>{facility.address || "Street address not listed in OpenStreetMap."}</p>
              <small>{facility.location_source} · operating status unverified</small>
              <div className="facility-metrics">
                {facility.road_distance_m !== null ? <span>{formatDistance(facility.road_distance_m)}</span> : <span>{(facility.straight_line_distance_m / 1000).toFixed(1)} km straight-line · road route unavailable</span>}
                <span>{formatDuration(facility.road_duration_s)}</span>
              </div>
              <div className="facility-actions">
                <a className="button button--secondary" href={directionsUrl(reference, facility)} target="_blank" rel="noreferrer">Get directions <Icon name="arrow" size={14}/></a>
                <a className="facility-source" href={facility.source_url} target="_blank" rel="noreferrer">View OSM record</a>
              </div>
            </div>
          </article>)}</div>}
        </section>
      </div>
    </>}
    <p className="facilities-disclaimer">Listings and map locations come from OpenStreetMap contributors; they may be incomplete or out of date. Call before travelling if confirmation is needed. For immediate emergencies in India, use 112.</p>
  </>;
}
