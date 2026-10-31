import { useEffect, useState } from "react";
import { GirlIllustration, Icon, PageHeading, Notice } from "../components/ui";
import MapView from "../components/MapView";
import { journeysApi, reportsApi } from "../services/api";

function readPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("Location is not available in this browser."));
    navigator.geolocation.getCurrentPosition((position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }), () => reject(new Error("Location access was not granted. You can allow it in your browser settings.")), { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
  });
}

export default function Home({ onNavigate, authenticated, theme }) {
  const [location, setLocation] = useState(null);
  const [reports, setReports] = useState(null);
  const [journey, setJourney] = useState(null);
  const [notice, setNotice] = useState("");
  const [reportsError, setReportsError] = useState("");
  const [journeyError, setJourneyError] = useState("");
  useEffect(() => {
    reportsApi.list().then(setReports).catch((error) => setReportsError(error.message));
  }, []);

  useEffect(() => {
    if (authenticated) journeysApi.active().then((value) => setJourney(value.active ? value : null)).catch((error) => setJourneyError(error.message));
  }, [authenticated]);

  async function previewLocation() {
    try { setLocation(await readPosition()); }
    catch (error) { setNotice(error.message); }
  }

  const actions = [
    { icon: "route", title: "Plan a route", text: "Compare available route options.", to: "routes", tone: "lavender" },
    { icon: "shield", title: "Emergency help", text: "Open your safety and location-sharing tools.", to: "safety", tone: "pink" },
    { icon: "compass", title: "Journey Companion", text: "Continue with your saved route.", to: "journey", tone: "blue" },
    { icon: "report", title: "View community reports", text: "Read or submit local reports.", to: "reports", tone: "mint" },
  ];

  return <>
    <PageHeading eyebrow="YOUR JOURNEY SPACE" title="Welcome to NAVIRA" description="Plan a route, manage your safety tools, and review public information with clear context." action={<span className="date-chip"><Icon name="shield" size={15}/> Evidence-aware tools</span>}/>
    <section className="welcome-banner"><div className="welcome-copy"><span className="welcome-kicker"><i/> SAFER STEPS. BRIGHTER TOMORROWS.</span><h2>Navigate freely. Move confidently.</h2><p>Move with confidence using thoughtful route options and tools that keep trusted people close.</p><button className="button button--primary" onClick={() => onNavigate("routes")}>Plan a Route <Icon name="arrow" size={17}/></button></div><div className="welcome-art"><GirlIllustration theme={theme} className="safe-journey-illustration" alt="Girl walking through a pink city along a winding path"/></div></section>
    <div className="section-heading"><div><p className="eyebrow">QUICK ACCESS</p><h2>What would you like to do?</h2></div><button className="text-button" onClick={() => onNavigate("safety")}>Safety center <Icon name="arrow" size={16}/></button></div>
    <div className="quick-grid">{actions.map((action) => <button key={action.to} className="quick-card" onClick={() => onNavigate(action.to)}><span className={"quick-icon tone-" + action.tone}><Icon name={action.icon} size={21}/></span><strong>{action.title}</strong><span>{action.text}</span><i><Icon name="arrow" size={16}/></i></button>)}</div>
    <div className="home-grid home-grid--lower"><section className="panel home-map-panel"><div className="panel-heading"><div><p className="eyebrow">MAP PREVIEW</p><h2>{location ? "Your selected area" : "Explore around you"}</h2></div>{location && <span className="status-chip status-chip--green"><i/> Location selected</span>}</div>{location ? <MapView center={[location.latitude, location.longitude]} marker={{ ...location, label: "Your current location" }} className="home-map"/> : <div className="map-empty"><div className="map-empty__illustration"><span className="map-ring ring-a"/><span className="map-ring ring-b"/><span className="map-pin"><Icon name="pin" size={23}/></span><i className="map-dot dot-a"/><i className="map-dot dot-b"/><i className="map-dot dot-c"/></div><strong>Location stays in this browser preview</strong><p>Choose this only to show your current position on the map.</p><button className="button button--secondary" onClick={previewLocation}>Preview my area</button></div>}</section>
      <section className="panel activity-panel"><div className="panel-heading"><div><p className="eyebrow">YOUR DASHBOARD</p><h2>At a glance</h2></div><span className="soft-icon"><Icon name="pulse" size={18}/></span></div><div className="glance-row"><span className="glance-icon tone-lavender"><Icon name="route" size={18}/></span><div><strong>Journey Companion</strong><small>{journey ? `${journey.status.replace("_", " ")}: ${journey.origin} → ${journey.destination}` : journeyError ? "Journey information unavailable" : "No active journey; plan a route to begin"}</small></div><button className="mini-action" onClick={() => onNavigate("journey")} aria-label="Open Journey Companion"><Icon name="arrow" size={16}/></button></div><div className="glance-row"><span className="glance-icon tone-blue"><Icon name="report" size={18}/></span><div><strong>Community reports</strong><small>{reports ? `${reports.length} active unverified report(s)` : reportsError ? "Report count unavailable" : "Loading report count…"}</small></div><button className="mini-action" onClick={() => onNavigate("reports")} aria-label="Open community reports"><Icon name="arrow" size={16}/></button></div></section>
    </div>
    {notice && <Notice kind="warning">{notice}</Notice>}
    {journeyError && <Notice kind="warning">Journey information could not be loaded: {journeyError}</Notice>}
    {reportsError && <Notice kind="warning">Community reports could not be loaded: {reportsError}</Notice>}
    <section className="safety-note"><span><Icon name="shield" size={18}/></span><p><strong>A helpful reminder</strong> Route comparisons are not safety ratings. NCRB totals are registered cases and do not indicate route-level risk.</p></section>
  </>;
}
