import { lazy, Suspense, useEffect, useState } from "react";
import { authApi, setToken } from "./services/api";
import { BrandMark, Icon } from "./components/ui";
import Home from "./pages/Home";
import RoutePlanner from "./pages/RoutePlanner";
import SafetyCenter from "./pages/SafetyCenter";
import CommunityReports from "./pages/CommunityReports";
import JourneyCompanion from "./pages/JourneyCompanion";
import ProfileSettings from "./pages/ProfileSettings";
import NearbyFacilities from "./pages/NearbyFacilities";
import PublicLocationShare from "./pages/PublicLocationShare";
import PublicLiveLocation from "./pages/PublicLiveLocation";
import Onboarding from "./pages/Onboarding";
import "./App.css";

const SyntheticRouteDemo = import.meta.env.DEV ? lazy(() => import("./pages/SyntheticRouteDemo")) : null;
const syntheticDemoEnabled = import.meta.env.DEV && import.meta.env.VITE_NAVIRA_SYNTHETIC_DEMO === "true";

const themeOptions = [
  { id: "pearl-white", name: "Pearl White", color: "#f6f1e9" },
  { id: "midnight-black", name: "Midnight Black", color: "#17171d" },
  { id: "lavender-mist", name: "Lavender Mist", color: "#d8c9f0" },
  { id: "ocean-blue", name: "Ocean Blue", color: "#b8d7f0" },
  { id: "sage-green", name: "Sage Green", color: "#8fa995" },
  { id: "rose-quartz", name: "Rose Quartz", color: "#e6b8c6" },
  { id: "warm-sand", name: "Warm Sand", color: "#e8d1b3" },
];
const THEME_STORAGE_KEY = "navira-theme";
const themeIds = new Set(themeOptions.map(({ id }) => id));

const pageItems = [
  { id: "home", label: "Home", icon: "home" },
  { id: "routes", label: "Route Planner", icon: "route" },
  { id: "safety", label: "Location Sharing", icon: "shield" },
  { id: "facilities", label: "Nearby Facilities", icon: "pin" },
  { id: "reports", label: "Community Reports", icon: "report" },
  { id: "journey", label: "Journey Companion", icon: "compass" },
  { id: "profile", label: "Profile & Settings", icon: "user" },
];

function getPageFromHash() {
  const requested = window.location.hash.replace(/^#\/?/, "").split("/")[0];
  if (requested === "demo") return "demo";
  return pageItems.some((page) => page.id === requested) ? requested : "home";
}

function getShareTokenFromHash() {
  return window.location.hash.match(/^#\/share\/([a-f0-9]{64})$/)?.[1] || null;
}

function getStoredTheme() {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return themeIds.has(savedTheme) ? savedTheme : "rose-quartz";
}

export default function App() {
  const [page, setPage] = useState(getPageFromHash);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [onboardingComplete, setOnboardingComplete] = useState(false);
  const [authNotice, setAuthNotice] = useState("");
  const [pendingSOS, setPendingSOS] = useState(false);
  const [routeContext, setRouteContext] = useState(null);
  const [shareToken, setShareToken] = useState(getShareTokenFromHash);
  const [theme, setTheme] = useState(getStoredTheme);
  const [themePickerOpen, setThemePickerOpen] = useState(false);

  function openSyntheticDemo() {
    window.location.hash = "/demo";
    setPage("demo");
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      getComputedStyle(document.documentElement).getPropertyValue("--page").trim(),
    );
  }, [theme]);

  function navigate(next) {
    if (!pageItems.some((item) => item.id === next)) return;
    window.location.hash = "/" + next;
    setPage(next);
    setMobileOpen(false);
  }

  useEffect(() => {
    const handleHash = () => {
      setPage(getPageFromHash());
      setShareToken(getShareTokenFromHash());
    };
    window.addEventListener("hashchange", handleHash);
    if (!window.location.hash) window.history.replaceState(null, "", "#/home");
    return () => window.removeEventListener("hashchange", handleHash);
  }, []);

  useEffect(() => {
    let active = true;
    authApi.session().then(() => {
      if (!active) return;
      setToken(null);
      setAuthenticated(true);
      setAuthChecking(false);
    }).catch((error) => {
      if (!active) return;
      setToken(null);
      setAuthenticated(false);
      setAuthNotice(error.message.includes("Please sign in") || error.message.includes("session has expired") ? "" : error.message);
      setAuthChecking(false);
    });
    return () => { active = false; };
  }, []);

  async function signOut() {
    try { await authApi.logout(); }
    catch (error) { setAuthNotice("Could not confirm sign out with the server: " + error.message); }
    setToken(null);
    setAuthenticated(false);
    setOnboardingComplete(true);
    window.location.hash = "/home";
    setPage("home");
  }

  const current = pageItems.find((item) => item.id === page) || pageItems[0];
  const selectedTheme = themeOptions.find(({ id }) => id === theme) || themeOptions[5];
  const themePicker = <div className={`theme-picker${themePickerOpen ? " is-open" : ""}`}>
    <button className="theme-picker__trigger" type="button" aria-label={`App theme: ${selectedTheme.name}`} aria-expanded={themePickerOpen} aria-controls="theme-options" onClick={() => setThemePickerOpen((open) => !open)}>
      <span className="theme-picker__swatch" style={{ "--swatch-color": selectedTheme.color }}/>
      <span className="theme-picker__label">{selectedTheme.name}</span>
      <Icon name="chevron" size={14}/>
    </button>
    {themePickerOpen && <div className="theme-picker__options" id="theme-options" role="group" aria-label="Choose an app theme">
      {themeOptions.map((option) => <button key={option.id} className="theme-picker__option" type="button" aria-pressed={theme === option.id} onClick={() => { setTheme(option.id); setThemePickerOpen(false); }}>
        <span className="theme-picker__swatch" style={{ "--swatch-color": option.color }}/>
        <span>{option.name}</span>
        {theme === option.id && <Icon name="check" size={15}/>}
      </button>)}
    </div>}
  </div>;
  if (shareToken) return <PublicLocationShare token={shareToken}/>;
  const liveToken = window.location.hash.match(/^#\/live\/([a-f0-9]{64})$/)?.[1];
  if (liveToken) return <PublicLiveLocation token={liveToken}/>;
  if (authChecking) return <div className="landing-shell"><header className="landing-header"><a className="brand landing-brand" href="#/home"><BrandMark size={42}/><span className="brand-copy"><strong>NAVIRA</strong><small>SAFER STEPS. BRIGHTER TOMORROWS.</small></span></a>{themePicker}</header><main className="landing-loading" role="status">Restoring your NAVIRA session…</main></div>;
  if (page === "demo") return syntheticDemoEnabled && SyntheticRouteDemo
    ? <Suspense fallback={<main className="synthetic-demo-loading" role="status">Loading local synthetic demo…</main>}><SyntheticRouteDemo onBack={() => navigate("home")}/></Suspense>
    : <main className="synthetic-demo-unavailable"><h1>Synthetic demo is disabled</h1><p>Enable it only in local development by setting <code>VITE_NAVIRA_SYNTHETIC_DEMO=true</code> in the frontend environment file, then restart Vite.</p><a className="button button--primary" href="#/home">Return to NAVIRA</a></main>;
  if (!authenticated && !onboardingComplete) return <Onboarding theme={theme} onGetStarted={() => { setOnboardingComplete(true); navigate("home"); }} showSyntheticDemo={syntheticDemoEnabled} onSyntheticDemo={openSyntheticDemo}/>;
  if (!authenticated) return <div className="landing-shell"><header className="landing-header"><a className="brand landing-brand" href="#/home"><BrandMark size={42}/><span className="brand-copy"><strong>NAVIRA</strong><small>SAFER STEPS. BRIGHTER TOMORROWS.</small></span></a>{themePicker}</header><main className="landing-content">{syntheticDemoEnabled && <button className="button button--secondary synthetic-demo-login-link" type="button" onClick={openSyntheticDemo}>Open local synthetic route demo</button>}<ProfileSettings theme={theme} authenticated={false} setAuthenticated={setAuthenticated} onAuthenticated={() => { setAuthNotice(""); setAuthenticated(true); navigate("home"); }} onSignOut={signOut} authNotice={authNotice}/></main><footer className="landing-footer">Safer steps. Brighter tomorrows.</footer></div>;
  const onQuickSOS = () => { navigate("safety"); setPendingSOS(true); };
  let content;
  switch (page) {
    case "routes": content = <RoutePlanner authenticated={authenticated} onRouteContext={setRouteContext} onNavigate={navigate}/>; break;
    case "safety": content = <SafetyCenter authenticated={authenticated} pendingSOS={pendingSOS} onSOSReady={setPendingSOS}/>; break;
    case "facilities": content = <NearbyFacilities routeContext={routeContext} authenticated={authenticated} onNavigate={navigate}/>; break;
    case "reports": content = <CommunityReports/>; break;
    case "journey": content = <JourneyCompanion onNavigate={navigate} authenticated={authenticated}/>; break;
    case "profile": content = <ProfileSettings theme={theme} authenticated={authenticated} setAuthenticated={setAuthenticated} onSignOut={signOut}/>; break;
    default: content = <Home theme={theme} onNavigate={navigate} authenticated={authenticated}/>;
  }

  const primaryPages = pageItems.filter((item) => item.id !== "profile");
  const systemPages = pageItems.filter((item) => item.id === "profile");
  const renderNav = (items) => items.map((item) => <a key={item.id} href={"#/" + item.id} className={page === item.id ? "console-nav__link is-active" : "console-nav__link"} aria-current={page === item.id ? "page" : undefined} onClick={(event) => { event.preventDefault(); navigate(item.id); }}><Icon name={item.icon} size={20}/><span>{item.label}</span>{page === item.id && <i/>}</a>);

  return <div className="app-shell console-shell">
    <aside className={mobileOpen ? "console-sidebar is-open" : "console-sidebar"}>
      <a className="brand console-brand" href="#/home" onClick={(event) => { event.preventDefault(); navigate("home"); }}><BrandMark size={40}/><span className="brand-copy"><strong>NAVIRA</strong><small>SAFER STEPS. BRIGHTER TOMORROWS.</small></span></a>
      <div className="console-workspace"><span className="workspace-avatar"><Icon name="shield" size={15}/></span><span><strong>My workspace</strong><small>Personal safety</small></span><Icon name="chevron" size={14}/></div>
      <nav className="console-nav" aria-label="Main navigation"><span className="console-nav__label">WORKSPACE</span>{renderNav(primaryPages)}<span className="console-nav__label console-nav__label--second">SYSTEM</span>{renderNav(systemPages)}</nav>
      <div className="sidebar-safety-note"><span className="sidebar-safety-note__icon"><Icon name="shield" size={16}/></span><strong>Your safety comes first</strong><p>Share your journey with someone you trust whenever you need to.</p><button onClick={() => navigate("safety")}>Open safety center <Icon name="arrow" size={13}/></button></div>
      <button className="sidebar-profile" onClick={() => navigate("profile")}><span className="avatar"><Icon name="user" size={16}/></span><span><strong>Account & settings</strong><small>Manage your profile</small></span><Icon name="chevron" size={14}/></button>
    </aside>
    <section className="console-main">
      <header className="console-topbar">
        <div className="console-topbar__title"><button className="mobile-menu-button icon-button" aria-label={mobileOpen ? "Close menu" : "Open menu"} aria-expanded={mobileOpen} onClick={() => setMobileOpen(!mobileOpen)}><Icon name={mobileOpen ? "close" : "menu"}/></button><span className="topbar-overline">NAVIRA / WORKSPACE</span><strong>{current.label}</strong></div>
        <div className="console-topbar__actions">{themePicker}<span className="console-context">JOURNEY AWARENESS</span><button className="top-sos" type="button" aria-label="Emergency SOS" onClick={onQuickSOS}><Icon name="shield" size={19}/><span className="visually-hidden">Emergency SOS</span></button><button className="avatar" aria-label="Open profile settings" onClick={() => navigate("profile")}><Icon name="user" size={17}/></button></div>
      </header>
      {mobileOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)}/>}
      <main className="main-content" key={page}>
        <div className="page-kicker"><span>WORKSPACE</span><i>/</i><strong>{current.label}</strong></div>
        {content}
      </main>
      <footer className="console-footer"><span>© NAVIRA · Journey awareness</span><span>Plan thoughtfully. Stay connected. Make informed journey decisions.</span></footer>
    </section>
  </div>;
}
