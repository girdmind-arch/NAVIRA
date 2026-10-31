import { useEffect, useState } from "react";
import { safetyApi } from "../services/api";

export default function PublicLocationShare({ token }) {
  const [location, setLocation] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    safetyApi.publicShare(token)
      .then((result) => { if (!cancelled) setLocation(result); })
      .catch((requestError) => { if (!cancelled) setError(requestError.message); });
    return () => { cancelled = true; };
  }, [token]);

  const mapUrl = location
    ? `https://www.openstreetmap.org/?mlat=${location.latitude}&mlon=${location.longitude}#map=17/${location.latitude}/${location.longitude}`
    : "";

  return <main className="public-share-page"><section className="public-share-card">
    <p className="eyebrow">NAVIRA · TEMPORARY LOCATION SHARE</p>
    <h1>{error ? "Location link unavailable" : location ? "Shared location" : "Loading location…"}</h1>
    {error && <p>{error}</p>}
    {location && <>
      <p>This is one location snapshot shared with you. It is not live tracking.</p>
      <p>Shared {new Date(location.created_at).toLocaleString()} · Expires {new Date(location.expires_at).toLocaleString()}</p>
      {location.accuracy != null && <p>Device-reported accuracy: about {Math.round(location.accuracy)} m.</p>}
      <a className="button button--primary" href={mapUrl} target="_blank" rel="noreferrer">Open location map</a>
      {location.notice && <p>{location.notice}</p>}
    </>}
    <p>If someone may be in immediate danger in India, call 112.</p>
  </section></main>;
}
