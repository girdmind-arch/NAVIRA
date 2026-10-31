import { useEffect, useMemo, useRef, useState } from "react";
import { PageHeading, Notice, Icon } from "../components/ui";
import MapView from "../components/MapView";
import JourneySafetyMonitor from "../components/JourneySafetyMonitor";
import { journeysApi } from "../services/api";

function duration(value) {
  if (!Number.isFinite(value)) return "—";
  const minutes = Math.max(0, Math.round(value / 60));
  return minutes >= 60 ? `${Math.floor(minutes / 60)} hr ${minutes % 60} min` : `${minutes} min`;
}

function estimateArrival(seconds) {
  if (!Number.isFinite(seconds)) return "Unavailable";
  return new Date(Date.now() + seconds * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function locationErrorMessage(error) {
  if (error.code === 1) return "Location access is blocked. Allow location for this site in your browser settings, then choose Retry location.";
  if (error.code === 2) return "Your device could not determine a location. Turn on device location services, then choose Retry location.";
  if (error.code === 3) return "The location request timed out. Check your GPS signal and device location services, then choose Retry location.";
  return "Location is unavailable. Check your browser permission and device location services, then choose Retry location.";
}

function recordPosition(coords, journeyId, trackRef, setPosition, setTrack, setError) {
  const nextPosition = { latitude: coords.latitude, longitude: coords.longitude };
  setPosition(nextPosition);
  const nextTrack = [...trackRef.current, [coords.latitude, coords.longitude]].slice(-500);
  trackRef.current = nextTrack;
  setTrack(nextTrack);
  try {
    sessionStorage.setItem(`navira-track-${journeyId}`, JSON.stringify(nextTrack));
  } catch {
    setError("The browser could not save your GPS display track. Your planned route remains saved to your account.");
  }
}

function distanceToPointMeters(latitude, longitude, coordinates) {
  if (!Array.isArray(coordinates) || coordinates.length < 2) return null;
  const [destinationLongitude, destinationLatitude] = coordinates;
  const radians = (degrees) => degrees * Math.PI / 180;
  const dLatitude = radians(destinationLatitude - latitude);
  const dLongitude = radians(destinationLongitude - longitude);
  const a = Math.sin(dLatitude / 2) ** 2
    + Math.cos(radians(latitude)) * Math.cos(radians(destinationLatitude)) * Math.sin(dLongitude / 2) ** 2;
  return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

const ARRIVAL_RADIUS_METERS = 100;
const MAX_ARRIVAL_ACCURACY_METERS = 50;
const ARRIVAL_CONFIRMATIONS = 3;
const MIN_ARRIVAL_SAMPLE_GAP_MS = 4000;

export default function JourneyCompanion({ onNavigate, authenticated }) {
  const [journey, setJourney] = useState(null);
  const [error, setError] = useState("");
  const [locationIssue, setLocationIssue] = useState("");
  const [position, setPosition] = useState(null);
  const [track, setTrack] = useState([]);
  const [clock, setClock] = useState(0);
  const [safetyFix, setSafetyFix] = useState(null);
  const trackRef = useRef([]);
  const arrivalFixes = useRef(0);
  const lastArrivalFixAt = useRef(0);
  const completionPending = useRef(false);

  useEffect(() => {
    if (!authenticated) return undefined;
    let active = true;
    journeysApi.active().then(async (result) => {
      if (!active) return;
      const savedJourney = result.active ? result : null;
      setJourney(savedJourney);
      if (savedJourney?.status === "planned") {
        const startedJourney = await journeysApi.start(savedJourney.id);
        if (active) setJourney(startedJourney);
      }
      if (savedJourney) {
        try {
          const savedTrack = JSON.parse(sessionStorage.getItem(`navira-track-${savedJourney.id}`) || "[]");
          trackRef.current = savedTrack;
          setTrack(savedTrack);
        } catch {
          setError("Saved GPS track data could not be read; current tracking will continue without that previous path.");
          trackRef.current = [];
          setTrack([]);
        }
      }
    }).catch((requestError) => {
      if (active) setError(requestError.message);
    });
    return () => { active = false; };
  }, [authenticated]);

  useEffect(() => {
    if (journey?.status !== "in_progress") return undefined;
    arrivalFixes.current = 0;
    lastArrivalFixAt.current = 0;
    completionPending.current = false;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    if (!navigator.geolocation) {
      queueMicrotask(() => setLocationIssue("Location is unavailable in this browser. Journey timing continues without map tracking."));
      return () => clearInterval(timer);
    }
    const watch = navigator.geolocation.watchPosition(({ coords }) => {
      setLocationIssue("");
      recordPosition(coords, journey.id, trackRef, setPosition, setTrack, setError);
      setSafetyFix({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy, timestamp: Date.now() });
      const destination = journey.route?.geometry?.coordinates?.at(-1);
      const now = Date.now();
      if (!destination || coords.accuracy > MAX_ARRIVAL_ACCURACY_METERS) {
        arrivalFixes.current = 0;
        return;
      }
      const distance = distanceToPointMeters(coords.latitude, coords.longitude, destination);
      if (distance === null || distance > ARRIVAL_RADIUS_METERS) {
        arrivalFixes.current = 0;
        return;
      }
      if (now - lastArrivalFixAt.current >= MIN_ARRIVAL_SAMPLE_GAP_MS) {
        arrivalFixes.current += 1;
        lastArrivalFixAt.current = now;
      }
      if (arrivalFixes.current >= ARRIVAL_CONFIRMATIONS && !completionPending.current) {
        completionPending.current = true;
        journeysApi.complete(journey.id).then((completedJourney) => {
          setJourney(completedJourney);
          setPosition(null);
          setTrack([]);
          trackRef.current = [];
          try { sessionStorage.removeItem(`navira-track-${journey.id}`); } catch { /* session storage is optional */ }
          setLocationIssue("Journey completed after GPS confirmed arrival.");
        }).catch((requestError) => {
          completionPending.current = false;
          setError(`GPS confirmed arrival, but NAVIRA could not save journey completion: ${requestError.message}`);
        });
      }
    }, (locationError) => {
      arrivalFixes.current = 0;
      setPosition(null);
      setLocationIssue(locationErrorMessage(locationError));
    }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 });
    return () => { clearInterval(timer); navigator.geolocation.clearWatch(watch); };
  }, [journey?.id, journey?.status]);

  function retryLocation() {
    if (!navigator.geolocation || journey?.status !== "in_progress") return;
    setLocationIssue("Requesting your current location…");
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      setLocationIssue("");
      recordPosition(coords, journey.id, trackRef, setPosition, setTrack, setError);
    }, (locationError) => setLocationIssue(locationErrorMessage(locationError)), { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
  }

  const elapsed = useMemo(() => journey?.started_at
    ? Math.max(0, Math.floor((clock - new Date(journey.started_at).getTime()) / 1000))
    : 0, [journey, clock]);
  const demoEstimate = journey?.route?.provider_status === "demo_synthetic" || journey?.route_id?.startsWith("synthetic-");
  const estimatedDuration = demoEstimate ? null : journey?.route?.duration_s;
  const remaining = Number.isFinite(estimatedDuration) && journey?.status === "in_progress"
    ? Math.max(0, estimatedDuration - elapsed)
    : null;
  const route = journey?.route ? [journey.route] : [];
  const routeStart = journey?.route?.geometry?.coordinates?.[0];
  const center = position
    ? [position.latitude, position.longitude]
    : Array.isArray(routeStart) ? routeStart.slice().reverse() : undefined;

  const liveStatus = journey?.status === "completed"
    ? "journey completed"
    : journey?.status !== "in_progress"
      ? journey?.status?.replace("_", " ") || "No active journey"
      : position ? "GPS tracking" : locationIssue ? "GPS unavailable" : "Requesting GPS";
  return <>
    <PageHeading eyebrow="JOURNEY COMPANION" title="Your planned journey" description="Selecting a route starts Journey Companion automatically. Live GPS tracking begins when you allow location access." action={<span className={`status-chip ${position || journey?.status === "completed" ? "status-chip--green" : "status-chip--amber"}`}>{liveStatus}</span>}/>
    {!authenticated ? <section className="panel map-empty"><strong>Sign in to use Journey Companion</strong><p>Your saved routes and journey history are private to your account.</p><button className="button button--primary" onClick={() => onNavigate("profile")}>Sign in</button></section> : !journey ? <section className="panel map-empty"><strong>No planned route yet</strong><p>Plan a route first; Journey Companion will use the route you choose.</p><button className="button button--primary" onClick={() => onNavigate("routes")}>Open Route Planner <Icon name="arrow" size={16}/></button></section> : <>
      <div className="journey-layout">
        <section className="panel journey-start-panel">
          <div className="panel-heading"><div><p className="eyebrow">SAVED ROUTE · {journey.route_id}</p><h2>{journey.origin} → {journey.destination}</h2></div><span className="soft-icon tone-lavender"><Icon name="compass" size={19}/></span></div>
          <div className="journey-preview__stats"><div><small>{demoEstimate ? "Travel-time estimate" : "Estimated total travel time"}</small><strong>{demoEstimate ? "Demo only" : duration(estimatedDuration)}</strong></div><div><small>Distance</small><strong>{Number.isFinite(journey.route?.distance_m) ? `${(journey.route.distance_m / 1000).toFixed(1)} km` : "—"}</strong></div></div>
          {journey.status === "in_progress" && <div className="journey-preview__stats"><div><small>Elapsed journey time</small><strong>{duration(elapsed)}</strong></div><div><small>Estimated time remaining</small><strong>{remaining === null ? "Unavailable" : duration(remaining)}</strong></div></div>}
          {journey.status === "in_progress" && <div className="journey-arrival"><span><small>Estimated arrival</small><strong>{remaining === null ? "Unavailable" : estimateArrival(remaining)}</strong></span><small>Based on the original provider travel-time estimate and recorded start time. This is not a live traffic ETA.</small></div>}
          {journey.status === "planned" && <div className="journey-arrival"><span><small>Estimated arrival if you leave now</small><strong>{estimatedDuration === null || !Number.isFinite(estimatedDuration) ? "Unavailable" : estimateArrival(estimatedDuration)}</strong></span><small>Based on the provider's original travel-time estimate; it does not include live traffic.</small></div>}
          <p className="muted-copy">{journey.status === "completed" ? "Journey completed. Your route is saved in journey history." : journey.status === "in_progress" ? position ? demoEstimate ? "Live GPS updates are active. No travel-time estimate is available for this demo route." : "Live GPS updates are active. NAVIRA completes this journey after three accurate fixes near the destination." : locationIssue || "Requesting location permission. Tracking will begin when you allow location access." : "This route will start automatically when Journey Companion opens."}</p>
          {journey.started_at && <p className="form-helper">Journey started: {new Date(journey.started_at).toLocaleString()}</p>}
          {journey.status !== "completed" && <div className="modal-actions"><button className="button button--secondary" onClick={() => onNavigate("routes")}>Change route</button></div>}
        </section>
        <section className="panel journey-map-panel">
          <div className="panel-heading"><div><p className="eyebrow">ROUTE & POSITION</p><h2>{journey.status === "in_progress" ? "Planned route and GPS track" : "Planned route"}</h2></div></div>
          <MapView center={center} routes={route} activeRoute={0} marker={position ? { ...position, label: "Current GPS position" } : undefined} travelledPath={track} className="journey-map"/>
          <p className="muted-copy"><span className="journey-legend-planned"/> Purple line: planned route. <span className="journey-legend-travelled"/> Dashed green line: GPS positions observed by this browser during the active journey.</p>
          {journey.status === "in_progress" && (!position || locationIssue) && <div className="form-helper"><p>{locationIssue || "Requesting location permission. Live tracking is not active until a GPS position is received."}</p><button className="button button--secondary" type="button" onClick={retryLocation} disabled={!navigator.geolocation}>Retry location</button></div>}
          {journey.status === "in_progress" && !journey.route?.geometry?.coordinates?.length && <p className="form-helper">This route has no destination geometry, so automatic arrival detection is unavailable. GPS location will still be shown while tracking is active.</p>}
        </section>
      </div>
    </>}
    {authenticated && journey?.status === "in_progress" && <JourneySafetyMonitor key={journey.id} journey={journey} fix={safetyFix}/>}
    {error && <Notice kind="warning">{error}</Notice>}
    <div className="journey-shortcuts"><button className="shortcut-card" onClick={() => onNavigate("safety")}><span className="quick-icon tone-pink"><Icon name="shield" size={19}/></span><span><strong>Emergency SOS & sharing</strong><small>Manage a private location share.</small></span><Icon name="arrow" size={17}/></button><button className="shortcut-card" onClick={() => onNavigate("routes")}><span className="quick-icon tone-blue"><Icon name="route" size={19}/></span><span><strong>Route Planner</strong><small>Review or replace your saved route.</small></span><Icon name="arrow" size={17}/></button></div>
  </>;
}
