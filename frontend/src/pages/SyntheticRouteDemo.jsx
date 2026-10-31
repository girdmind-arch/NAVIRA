import { useEffect, useState } from "react";
import { BrandMark, Icon } from "../components/ui";
import { syntheticDemoApi } from "../services/api";

const modeLabels = { car: "Car", motorcycle: "Motorcycle", walking: "Walking" };

function ContextValue({ label, value, detail }) {
  return <div className="synthetic-context-value">
    <span>{label}</span>
    <strong>{value}</strong>
    {detail && <small>{detail}</small>}
    <small className="synthetic-field-label">Synthetic example</small>
  </div>;
}

function RouteCard({ route }) {
  const conditions = route.journey_conditions;
  const access = route.vehicle_access.allowed_modes.map((mode) => modeLabels[mode] || mode).join(", ");
  const traffic = conditions.traffic.status === "not_applicable_to_pedestrian_path"
    ? "Not applicable to this fictional walking path"
    : `${conditions.traffic.level} · ${conditions.traffic.estimated_delay_minutes} min illustrative delay`;
  return <article className="panel synthetic-route-card">
    <div className="synthetic-route-card__heading">
      <div><span className="status-chip status-chip--amber">{modeLabels[route.mode]}</span><h2>{route.route_label}</h2></div>
      <Icon name="route" size={21}/>
    </div>
    <div className="synthetic-route-stats">
      <div><small>Example distance</small><strong>{route.distance_km} km</strong></div>
      <div><small>Example travel time</small><strong>{route.estimated_minutes} min</strong></div>
    </div>
    <p className="synthetic-access"><strong>Fictional access rule:</strong> {access}. No actual traffic law or road access was checked.</p>
    <div className="synthetic-context-grid">
      <ContextValue label="Traffic" value={traffic}/>
      <ContextValue label="Weather" value={conditions.weather.condition} detail={`${conditions.weather.precipitation_probability_percent}% illustrative precipitation probability`}/>
      <ContextValue label="Lighting audit" value={`${conditions.lighting_audit.rating_0_to_3} / 3`} detail="Illustrative rating; no real audit"/>
      <ContextValue label="Visibility audit" value={`${conditions.visibility_audit.rating_0_to_3} / 3`} detail="Illustrative rating; no real audit"/>
      <ContextValue label="People activity" value={conditions.people_activity.level}/>
      <ContextValue label="Nearby help points" value={`${conditions.nearby_help.mapped_police_or_health_facilities}`} detail="Illustrative mapped count; no real facilities checked"/>
      <ContextValue label="Community reports" value={`${route.reported_information.community_reports} example reports`} detail={`${route.reported_information.verified_reports} verified in this fictional example`}/>
      <ContextValue label="Route safety score" value="Not available" detail="Synthetic observations cannot establish a real safety ranking"/>
    </div>
    <p className="synthetic-route-note">{route.reported_information.note}</p>
  </article>;
}

export default function SyntheticRouteDemo({ onBack }) {
  const [demo, setDemo] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    syntheticDemoApi.get()
      .then((data) => { if (active) setDemo(data); })
      .catch((requestError) => { if (active) setError(requestError.message); });
    return () => { active = false; };
  }, []);
  return <main className="synthetic-demo-page">
    <div className="synthetic-demo-banner" role="alert"><Icon name="report" size={18}/><strong>SYNTHETIC DEMO — NOT REAL SAFETY DATA</strong></div>
    <header className="synthetic-demo-header">
      <a className="brand" href="#/home" onClick={(event) => { event.preventDefault(); onBack(); }}><BrandMark size={40}/><span className="brand-copy"><strong>NAVIRA</strong><small>LOCAL DEMONSTRATION</small></span></a>
      <button className="button button--secondary" type="button" onClick={onBack}>Return to NAVIRA</button>
    </header>
    <section className="synthetic-demo-content">
      <div className="page-heading"><div><p className="eyebrow">OFFLINE UI WALKTHROUGH</p><h1>Compare example routes</h1><p className="page-description">A fictional scenario showing how route context can be presented when data providers are unavailable.</p></div><span className="status-chip status-chip--amber">No real route guidance</span></div>
      {!demo && <p role={error ? "alert" : "status"}>{error || "Loading synthetic demo examples…"}</p>}
      {demo && <>
      <section className="panel synthetic-scenario-panel" aria-labelledby="synthetic-scenario-title">
        <p className="eyebrow">FICTIONAL SCENARIO</p><h2 id="synthetic-scenario-title">{demo.scenario.origin} → {demo.scenario.destination}</h2>
        <p>{demo.scenario.city} · Evening example · no coordinates, real map locations, or actual roads.</p>
      </section>
      <section className="panel synthetic-scenario-panel" aria-labelledby="synthetic-crime-rates-title">
        <p className="eyebrow">SYNTHETIC CRIME-RATE EXAMPLES</p><h2 id="synthetic-crime-rates-title">Invented figures for display testing</h2>
        <p>These fictional areas and example rates do not describe real crime or real places.</p>
        <div className="synthetic-context-grid">{demo.synthetic_crime_rate_examples.map((example) => <ContextValue key={example.example_id} label={example.fictional_area} value={`${example.example_rate_per_10000_fictional_residents} per 10,000 fictional residents`} detail={`${example.example_reports} invented reports · fictional population ${Number(example.fictional_population).toLocaleString()}`}/>)}</div>
      </section>
      <div className="synthetic-route-grid">{demo.route_options.map((route) => <RouteCard key={route.route_id} route={route}/>)}</div>
      <section className="panel synthetic-emergency-panel">
        <div><p className="eyebrow">EMERGENCY UI PLACEHOLDERS</p><h2>No dialable numbers in demo</h2><p>These fictional contact labels test layout only. This demo cannot call, message, or alert anyone.</p></div>
        <div className="synthetic-contact-list">{demo.emergency_demo.trusted_contacts.map((contact) => <div key={contact.name}><Icon name="user" size={17}/><span>{contact.name}</span><strong>{contact.phone_display}</strong></div>)}</div>
      </section>
      <p className="synthetic-demo-footer-note">No route is ranked for safety. Every displayed condition is invented, and zero example reports do not indicate zero incidents. Real NAVIRA routes continue to show “insufficient evidence” whenever verified route-level evidence is unavailable.</p>
      </>}
    </section>
  </main>;
}
