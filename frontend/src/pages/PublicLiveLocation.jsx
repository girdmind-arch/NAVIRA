import { useEffect, useState } from "react";
import { journeySafetyApi } from "../services/journeySafety";

const REFRESH_MS = 15000;

export default function PublicLiveLocation({ token }) {
  const [live, setLive] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = () => journeySafetyApi.live(token)
      .then((result) => { if (!cancelled) { setLive(result); setError(""); } })
      .catch((requestError) => { if (!cancelled) setError(requestError.message); });
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [token]);

  const hasFix = live && live.latitude != null && live.longitude != null;
  const mapUrl = hasFix
    ? `https://www.openstreetmap.org/?mlat=${live.latitude}&mlon=${live.longitude}#map=17/${live.latitude}/${live.longitude}`
    : "";

  return <main className="public-share-page"><section className="public-share-card">
    <p className="eyebrow">NAVIRA · SOS LIVE LOCATION</p>
    <h1>{error && !live ? "Live location unavailable" : live ? "SOS emergency location" : "Loading location…"}</h1>
    {error && <p>{error}</p>}
    {live && <>
      <p>SOS started {new Date(live.sos_created_at).toLocaleString()}.</p>
      {live.connection === "live" && <p>The phone is connected. This page refreshes every 15 seconds with the latest GPS position.</p>}
      {live.connection === "lost" && <p>NAVIRA has lost connection with the phone since {live.last_contact_at ? new Date(live.last_contact_at).toLocaleString() : "the SOS started"}. It may be out of network coverage. Showing the last known location.</p>}
      {live.connection === "journey_ended" && <p>The journey has ended, so location updates have stopped. Showing the last known location.</p>}
      {hasFix ? <>
        <p>Location recorded {new Date(live.location_recorded_at).toLocaleString()}{live.accuracy_m != null ? ` · accuracy about ${Math.round(live.accuracy_m)} m` : ""}.</p>
        <a className="button button--primary" href={mapUrl} target="_blank" rel="noreferrer">Open location map</a>
      </> : <p>No GPS position has been received from the phone yet.</p>}
    </>}
    <p>If someone may be in immediate danger in India, call 112.</p>
  </section></main>;
}
