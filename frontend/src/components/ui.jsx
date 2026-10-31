const icons = {
  lotus: <><path d="M12 20c-3-4.4-2.8-9.8 0-15 2.8 5.2 3 10.6 0 15Z"/><path d="M11.4 19.3C6.6 18.5 3.5 15.8 2 11c5.1.4 8.2 3 9.4 8.3Z"/><path d="M12.6 19.3c4.8-.8 7.9-3.5 9.4-8.3-5.1.4-8.2 3-9.4 8.3Z"/><path d="M5 21h14"/></>,
  home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-6h6v6"/></>,
  route: <><circle cx="6" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M6 7v4a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v0"/></>,
  pin: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
  report: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="M12 8v4m0 4h.01"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  pulse: <><path d="M3 12h4l3-8 4 16 3-8h4"/></>,
  compass: <><circle cx="12" cy="12" r="9"/><path d="m15.8 8.2-2.5 5.1-5.1 2.5 2.5-5.1 5.1-2.5Z"/></>,
  shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
  close: <><path d="m6 6 12 12M18 6 6 18"/></>,
  chevron: <path d="m7 10 5 5 5-5"/>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
  phone: <path d="M22 16.9v3a2 2 0 0 1-2.2 2A19.8 19.8 0 0 1 11.2 19a19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.2-1.3a2 2 0 0 1 2.1-.5c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.8 2.1Z"/>,
  hospital: <><path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"/><path d="M10 7h4m-2-2v4m-3 5h.01M15 14h.01M10 18h.01M15 18h.01"/></>,
  arrow: <><path d="M5 12h14m-6-6 6 6-6 6"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  plus: <><path d="M12 5v14M5 12h14"/></>,
  logout: <><path d="M10 17l5-5-5-5m5 5H3"/><path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7"/></>,
};

export function Icon({ name, size = 20, className = "" }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icons[name] || icons.compass}</svg>;
}

export function BrandMark({ size = 40, className = "" }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 48 48" fill="none" role="img" aria-label="NAVIRA shield and N">
    <path d="M24 3.5 42 10.7v12.6c0 11.2-6.9 18.1-18 22.2C12.9 41.4 6 34.5 6 23.3V10.7L24 3.5Z" fill="var(--brand-mark-fill)" stroke="var(--brand-mark-stroke)" strokeWidth="1.8" strokeLinejoin="round"/>
    <path d="M15.5 33V15.5L32.5 33V15.5" stroke="var(--brand-mark-ink)" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="m24 7.8 1.1 2.1 2.1 1.1-2.1 1.1-1.1 2.1-1.1-2.1-2.1-1.1 2.1-1.1L24 7.8Z" fill="var(--brand-mark-star)"/>
    <path d="M27.8 27.8c2.6 1.2 2.8 3 .9 5" stroke="var(--brand-mark-path)" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>;
}

const girlIllustrations = {
  "rose-quartz": "/home-hero-journey.webp",
  "pearl-white": "/journey-girl-pearl-white.webp",
  "midnight-black": "/journey-girl-midnight-black.webp",
  "lavender-mist": "/journey-girl-lavender-mist.webp",
  "ocean-blue": "/journey-girl-ocean-blue.webp",
  "sage-green": "/journey-girl-sage-green.webp",
  "warm-sand": "/journey-girl-warm-sand.webp",
};

export function GirlIllustration({ className = "", alt = "Girl walking along a winding path", theme = "rose-quartz" }) {
  return <img className={`girl-illustration ${className}`.trim()} src={girlIllustrations[theme] || girlIllustrations["rose-quartz"]} alt={alt}/>;
}

export function SafeJourneyIllustration({ className = "" }) {
  return <svg className={className} viewBox="0 0 460 270" role="img" aria-labelledby="safe-journey-title">
    <title id="safe-journey-title">Safe Journey: a woman walking confidently along a guided route</title>
    <path d="M26 218c80-9 109-80 181-60 55 15 79 66 137 44 31-12 44-40 83-42" fill="none" stroke="var(--journey-route)" strokeWidth="8" strokeLinecap="round"/>
    <path d="M26 218c80-9 109-80 181-60 55 15 79 66 137 44 31-12 44-40 83-42" fill="none" stroke="var(--journey-route-line)" strokeWidth="2" strokeLinecap="round"/>
    <circle cx="30" cy="218" r="8" fill="var(--journey-marker)"/>
    <path d="M413 125c-12 0-21 9-21 21 0 16 21 35 21 35s21-19 21-35c0-12-9-21-21-21Z" fill="var(--journey-pin)"/>
    <circle cx="413" cy="146" r="6" fill="var(--journey-pin-center)"/>
    <path d="m354 52 3.1 6.3 6.9 3.1-6.9 3.1-3.1 6.3-3.1-6.3-6.9-3.1 6.9-3.1 3.1-6.3Z" fill="var(--journey-star)"/>
    <circle cx="224" cy="66" r="23" fill="var(--journey-skin)"/>
    <path d="M204 62c1-21 37-29 46-5-7-2-12-9-13-13-5 9-19 13-33 18Z" fill="var(--journey-hair)"/>
    <path d="M199 96c11-12 36-15 49-2l14 50-8 32-52-2-13-29 10-39Z" fill="var(--journey-clothes)"/>
    <path d="m205 101-26 24-11 34c-2 7 8 11 12 4l16-25 16-13" fill="none" stroke="var(--journey-skin)" strokeWidth="12" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="m246 104 22 21 19 9c7 3 12-6 6-10l-18-14-12-19" fill="none" stroke="var(--journey-skin)" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="m204 172-10 42-19 25c-5 7 5 13 11 7l27-23 13-39" fill="none" stroke="var(--journey-trousers)" strokeWidth="14" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="m245 173 10 39 23 23c6 6-2 14-9 9l-31-18-20-39" fill="none" stroke="var(--journey-trousers)" strokeWidth="14" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M170 241c-7 5-9 12-5 15h28c3-4 0-9-7-13" fill="var(--journey-shoes)"/>
    <path d="M267 241c-4 5-4 10 1 13h28c2-5-2-9-9-13" fill="var(--journey-shoes)"/>
    <path d="M197 105c-11 2-17 15-15 32l7 27 23-5 1-45c-3-7-9-10-16-9Z" fill="var(--journey-bag)"/>
    <path d="M202 109c-8 5-9 18-5 26" fill="none" stroke="var(--journey-bag-strap)" strokeWidth="3" strokeLinecap="round"/>
    <path d="m329 205 6 6 12-14" fill="none" stroke="var(--journey-route)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>;
}

export function Notice({ kind = "info", children }) {
  if (!children) return null;
  return <div className={"notice notice--" + kind} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function PageHeading({ eyebrow, title, description, action }) {
  return <div className="page-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p className="page-description">{description}</p>}</div>{action && <div className="page-heading__action">{action}</div>}</div>;
}

export function StatCard({ icon, label, value, tone = "blue", detail }) {
  return <article className="stat-card"><span className={"stat-card__icon tone-" + tone}><Icon name={icon} size={19}/></span><div><p>{label}</p><strong>{value}</strong>{detail && <small>{detail}</small>}</div></article>;
}

export function EmptyState({ icon = "compass", title, children, action }) {
  return <div className="empty-state"><span className="empty-state__icon"><Icon name={icon} size={22}/></span><h3>{title}</h3><p>{children}</p>{action}</div>;
}
