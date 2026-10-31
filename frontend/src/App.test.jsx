import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import App from "./App.jsx";
import NearbyFacilities from "./pages/NearbyFacilities.jsx";
import { contactsApi, facilitiesApi, journeysApi, newsApi, routesApi } from "./services/api";

vi.mock("./services/api", () => ({
  getToken: () => null,
  setToken: vi.fn(),
  authApi: {
    session: vi.fn().mockResolvedValue({ id: 1, email: "test@example.com", name: "Test" }),
    login: vi.fn().mockResolvedValue({ user: { id: 1, email: "test@example.com", name: "Test" } }),
    register: vi.fn().mockResolvedValue({ user: { id: 1, email: "test@example.com", name: "Test" } }),
    logout: vi.fn().mockResolvedValue(null),
  },
  profileApi: { get: vi.fn().mockResolvedValue({ id: 1, email: "test@example.com", name: "Test" }), update: vi.fn() },
  contactsApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
  journeysApi: { active: vi.fn().mockResolvedValue({ active: false }), history: vi.fn().mockResolvedValue([]), plan: vi.fn(), start: vi.fn(), complete: vi.fn() },
  syntheticDemoApi: { get: vi.fn().mockResolvedValue({}) },
  backendApi: { emergencyResources: vi.fn().mockResolvedValue({ country: "India", number: "112" }), routeSafetyDataStatus: vi.fn().mockResolvedValue({ status: "insufficient_data", route_matched_verified_incidents: 0, aggregate_statistics: 5 }) },
  facilitiesApi: {
    nearby: vi.fn().mockResolvedValue({
      items: [],
      routing_note: "Road distance and time are unavailable.",
      operating_status_note: "Facility locations are not independently verified.",
    }),
  },
  safetyApi: { status: vi.fn().mockResolvedValue({ status: "ok", service: "navira-safety" }), shares: vi.fn().mockResolvedValue({ items: [] }), createShare: vi.fn().mockResolvedValue({ token: "a".repeat(64), id: "share-id", expires_at: new Date().toISOString() }), revokeShare: vi.fn().mockResolvedValue(null), recordSOS: vi.fn().mockResolvedValue({ status: "recorded" }), sosEvents: vi.fn().mockResolvedValue({ items: [] }), publicShare: vi.fn().mockResolvedValue({ latitude: 28.6, longitude: 77.2, created_at: new Date().toISOString(), expires_at: new Date().toISOString() }) },
  reportsApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn().mockResolvedValue({}) },
  newsApi: { candidates: vi.fn().mockResolvedValue({ items: [] }), coverage: vi.fn().mockResolvedValue({ target: { from_year: 2016, to_year: 2025 }, years_with_candidates: [] }), discover: vi.fn().mockResolvedValue({ groups: [] }), routeLocalityEvidence: vi.fn().mockResolvedValue({ groups: [], route_locality_context: { route_localities: [], sample_count: 0, resolved_sample_count: 0 } }) },
  routesApi: {
    suggest: vi.fn().mockImplementation((query) => Promise.resolve({ items: [{ query, display_name: query, latitude: 28.6, longitude: 77.2, provider: "Nominatim", place_type: "place" }] })),
    compare: vi.fn().mockResolvedValue({ alternatives: [], provider_status: "provider_configured", provider: "OSRM" }),
    walking: vi.fn().mockResolvedValue({ alternatives: [], provider_status: "unavailable", provider: "OpenStreetMap pilot pedestrian network", error: "outside pilot coverage", limitations: ["No automatic switch to the driving-route provider was made."] }),
    localityReports: vi.fn().mockResolvedValue({ items: [], status: "insufficient_data", notice: "Place-name match only." }),
    pedestrianNetwork: vi.fn().mockResolvedValue({ features: [], returned: 0, networks: [] }),
    traffic: vi.fn().mockResolvedValue({ status: "unconfigured" }),
    weather: vi.fn().mockResolvedValue({ status: "unconfigured", message: "Set OPENWEATHER_API_KEY on the backend." }),
    infrastructure: vi.fn().mockResolvedValue({ status: "unavailable", streetlights_mapped: null, footpaths_mapped: null, working_status: "unavailable" }),
  },
}));

afterEach(() => {
  cleanup();
  window.location.hash = "#/home";
  window.localStorage.removeItem("navira-theme");
  document.documentElement.dataset.theme = "rose-quartz";
});

describe("NAVIRA dashboard shell", () => {
  it("shows NAVIRA branding and the workspace destinations without backend status or data tools", async () => {
    render(<App/>);
    expect(await screen.findByText("Welcome to NAVIRA")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Navigate freely. Move confidently." })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Girl walking through a pink city along a winding path" })).toHaveClass("girl-illustration");
    expect(screen.getByRole("link", { name: /Journey Companion/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Nearby Places|NCRB/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/NCRB Data · Delhi City/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /ML & Data|Agent Monitoring/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/BACKEND STATUS/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Weather/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Safety Intelligence/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nearby Facilities" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Road Infrastructure" })).not.toBeInTheDocument();
  }, 15000);

  it("shows the sign-in landing page to users without a valid session", async () => {
    const { authApi } = await import("./services/api");
    authApi.session.mockRejectedValueOnce(new Error("Please sign in to continue"));
    render(<App/>);
    expect(await screen.findByRole("img", { name: /girl walking along a winding path/i })).toHaveAttribute("src", "/home-hero-journey.webp");
    expect(screen.getByText("Safer steps. Brighter tomorrows.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Onboarding page/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Get Started/ }));
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Navigate freely. Move confidently." })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Girl walking along a winding path through a soft pink city landscape" })).toHaveAttribute("src", "/home-hero-journey.webp");
    expect(screen.getByRole("tab", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByText(/not emergency dispatch or a guarantee of safety/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Route Planner" })).not.toBeInTheDocument();
  });

  it("directs an existing email from account creation to sign-in", async () => {
    const { authApi } = await import("./services/api");
    authApi.session.mockRejectedValueOnce(new Error("Please sign in to continue"));
    authApi.register.mockRejectedValueOnce(new Error("An account with this email already exists. Please sign in instead."));
    render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: /Get Started/ }));
    fireEvent.click(await screen.findByRole("tab", { name: "Create account" }));
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Account Owner" } });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "strong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("An account with this email already exists. Please sign in with your existing password.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Sign in" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(authApi.register).toHaveBeenCalledWith("owner@example.com", "strong-password", "Account Owner");
  });

  it("uses the saved theme illustration in onboarding and the landing page", async () => {
    const { authApi } = await import("./services/api");
    window.localStorage.setItem("navira-theme", "sage-green");
    authApi.session.mockRejectedValueOnce(new Error("Please sign in to continue"));
    render(<App/>);

    expect(await screen.findByRole("img", { name: /girl walking along a winding path/i })).toHaveAttribute("src", "/journey-girl-sage-green.webp");
    fireEvent.click(screen.getByRole("button", { name: /Get Started/ }));
    expect(await screen.findByRole("heading", { name: "Navigate freely. Move confidently." })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Girl walking along a winding path through a soft pink city landscape" })).toHaveAttribute("src", "/journey-girl-sage-green.webp");
  });

  it("revokes the signed-in session and returns to the sign-in landing page", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Profile & Settings" }));
    fireEvent.click(await screen.findByRole("button", { name: /Sign out/ }));
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeInTheDocument();
  });

  it("keeps the SOS confirmation available from Location Sharing and the global action", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Location Sharing" }));
    expect(screen.getByRole("heading", { name: "Location Sharing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Share a temporary location" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Need urgent help?" })).toBeInTheDocument();
    expect(screen.getByText("Call emergency services")).toBeInTheDocument();
    expect(screen.queryByText("Record SOS & open dialer")).not.toBeInTheDocument();
    expect(screen.queryByText(/Record an SOS request in NAVIRA/)).not.toBeInTheDocument();
    expect(screen.queryByText(/NAVIRA records your button press/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Open SOS confirmation/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /EMERGENCY SOS/i }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Record an SOS request and open your phone?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("switches between all seven themes and persists the current selection", async () => {
    render(<App/>);
    await screen.findByText("Welcome to NAVIRA");
    const themeTrigger = screen.getByRole("button", { name: "App theme: Rose Quartz" });
    expect(document.documentElement).toHaveAttribute("data-theme", "rose-quartz");
    fireEvent.click(themeTrigger);
    const themeNames = ["Pearl White", "Midnight Black", "Lavender Mist", "Ocean Blue", "Sage Green", "Rose Quartz", "Warm Sand"];
    const themeIllustrations = [
      "/journey-girl-pearl-white.webp",
      "/journey-girl-midnight-black.webp",
      "/journey-girl-lavender-mist.webp",
      "/journey-girl-ocean-blue.webp",
      "/journey-girl-sage-green.webp",
      "/home-hero-journey.webp",
      "/journey-girl-warm-sand.webp",
    ];
    for (const [index, name] of themeNames.entries()) {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(name) }));
      expect(document.documentElement).toHaveAttribute("data-theme", name.toLowerCase().replaceAll(" ", "-"));
      expect(window.localStorage.getItem("navira-theme")).toBe(name.toLowerCase().replaceAll(" ", "-"));
      expect(screen.getByRole("img", { name: "Girl walking through a pink city along a winding path" })).toHaveAttribute("src", themeIllustrations[index]);
      if (index < themeNames.length - 1) {
        fireEvent.click(screen.getByRole("button", { name: new RegExp(`App theme: ${name}`) }));
        expect(screen.getByRole("group", { name: "Choose an app theme" })).toBeInTheDocument();
      }
    }
    expect(screen.queryByRole("group", { name: "Choose an app theme" })).not.toBeInTheDocument();
  });

  it("shows helplines as native dialer links and labels their categories", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Location Sharing" }));

    expect(screen.getByRole("heading", { name: "Emergency Helplines" })).toBeInTheDocument();
    const numbers = ["112", "108", "181", "1091", "1930", "1098"];
    for (const number of numbers) {
      expect(screen.getByRole("link", { name: `Call ${number}`, exact: true })).toHaveAttribute("href", `tel:${number}`);
      expect(screen.getByRole("link", { name: new RegExp(`Call ${number},`) })).toHaveAttribute("href", `tel:${number}`);
    }
    expect(document.querySelectorAll(".helpline-card")).toHaveLength(numbers.length);
    expect(screen.getAllByRole("link", { name: "Official information" })).toHaveLength(numbers.length);
    expect(screen.getAllByRole("link", { name: "Official information" }).map((link) => link.getAttribute("href"))).toEqual([
      "https://112.gov.in/",
      "https://nhm.gov.in/",
      "https://wcd.gov.in/",
      "https://delhipolice.gov.in/",
      "https://cybercrime.gov.in/Webform/Helpline.aspx",
      "https://missionshakti.wcd.gov.in/",
    ]);
    expect(screen.getByText(/state\/UT response and referral arrangements may vary/i)).toBeInTheDocument();
  });

  it("shows account trusted contacts read-only in Emergency & SOS", async () => {
    contactsApi.list.mockResolvedValueOnce([
      { id: "contact-1", name: "Trusted Person", phone: "+1 555 0100" },
      { id: "contact-2", name: "Invalid Number", phone: "12" },
      { id: "contact-3", name: "Malformed Number", phone: "call 1234567" },
    ]);
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Location Sharing" }));

    expect(await screen.findByText("Trusted Person")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+1 555 0100" })).toHaveAttribute("href", "tel:+15550100");
    expect(screen.getByRole("link", { name: "Call Trusted Person" })).toHaveAttribute("href", "tel:+15550100");
    expect(screen.getByText(/12 · Cannot dial this number/)).toBeInTheDocument();
    expect(screen.getByText(/call 1234567 · Cannot dial this number/)).toBeInTheDocument();
    expect(screen.getAllByText(/Cannot dial this number/)).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Call Invalid Number" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Call Malformed Number" })).not.toBeInTheDocument();
    expect(contactsApi.list).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Save contact" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("directs users to Profile & Settings when no trusted contacts exist", async () => {
    contactsApi.list.mockResolvedValueOnce([]);
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Location Sharing" }));

    expect(await screen.findByText(/No trusted contacts added yet\. Add contacts in/)).toBeInTheDocument();
    const profileLink = screen.getAllByRole("link", { name: "Profile & Settings" }).find((link) => link.getAttribute("href") === "#/profile");
    expect(profileLink).toBeInTheDocument();
  });

  it("opens the route planner from sidebar navigation", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Route Planner" }));
    expect(screen.getByRole("heading", { name: "Route Planner" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Compare car, motorcycle & walking/ })).toBeInTheDocument();
    expect(screen.queryByText(/Walking routes in mapped pilot areas|WALKING · PILOT MAP|Limited coverage|Find walking path · Pilot map/i)).not.toBeInTheDocument();
  });

  it("requires precise place suggestions and submits their full coordinates", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Route Planner" }));
    fireEvent.change(screen.getByLabelText("Starting location", { selector: "#route-origin" }), { target: { value: "Bijnor, Uttar Pradesh" } });
    fireEvent.click(await screen.findByRole("option", { name: /Bijnor, Uttar Pradesh/ }));
    fireEvent.change(screen.getByLabelText("Destination location", { selector: "#route-destination" }), { target: { value: "AIIMS Delhi" } });
    fireEvent.click(await screen.findByRole("option", { name: /AIIMS Delhi/ }));
    fireEvent.click(screen.getByRole("button", { name: /Compare car, motorcycle & walking/ }));

    expect(await screen.findByText("No route options returned")).toBeInTheDocument();
    expect(routesApi.suggest).toHaveBeenCalledWith("Bijnor, Uttar Pradesh");
    expect(routesApi.compare).toHaveBeenCalledWith(
      "Bijnor, Uttar Pradesh",
      "AIIMS Delhi",
      expect.objectContaining({ latitude: 28.6, longitude: 77.2 }),
      expect.objectContaining({ latitude: 28.6, longitude: 77.2 }),
      "car",
    );
  });

  it("uses the selected Route Planner origin coordinates for nearby facilities", async () => {
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Route Planner" }));
    fireEvent.change(screen.getByLabelText("Starting location", { selector: "#route-origin" }), { target: { value: "Bijnor, Uttar Pradesh" } });
    fireEvent.click(await screen.findByRole("option", { name: /Bijnor, Uttar Pradesh/ }));
    fireEvent.change(screen.getByLabelText("Destination location", { selector: "#route-destination" }), { target: { value: "AIIMS Delhi" } });
    fireEvent.click(await screen.findByRole("option", { name: /AIIMS Delhi/ }));
    fireEvent.click(screen.getByRole("button", { name: /Compare car, motorcycle & walking/ }));
    await screen.findByText("No route options returned");

    fireEvent.click(screen.getByRole("link", { name: "Nearby Facilities" }));
    expect(await screen.findByText("No mapped facilities found within 5 km.")).toBeInTheDocument();
    expect(facilitiesApi.nearby).toHaveBeenCalledWith(28.6, 77.2, "all", 5000);
  });

  it("shows mapped facility details and directions from the selected coordinates", async () => {
    facilitiesApi.nearby.mockResolvedValueOnce({
      items: [{
        id: "osm-node-8",
        name: "Central Hospital",
        kind: "hospital",
        latitude: 28.61,
        longitude: 77.21,
        address: "Main Road, Delhi",
        location_source: "OSM mapped node",
        operating_status: "unverified",
        source_url: "https://www.openstreetmap.org/node/8",
        straight_line_distance_m: 1400,
        road_distance_m: 2100,
        road_duration_s: 420,
      }],
      routing_note: "OSRM road estimates are available.",
      operating_status_note: "Operating status is not independently verified.",
    });
    render(<NearbyFacilities
      routeContext={{ origin: { display_name: "Origin locality", latitude: 28.6, longitude: 77.2 } }}
      authenticated={false}
      onNavigate={vi.fn()}
    />);

    expect(await screen.findByText("Central Hospital")).toBeInTheDocument();
    expect(screen.getByText("Main Road, Delhi")).toBeInTheDocument();
    expect(screen.getByText("OSM mapped node · operating status unverified")).toBeInTheDocument();
    expect(screen.getByText("2.1 km by road")).toBeInTheDocument();
    expect(screen.getByText("7 min by road")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Get directions/ })).toHaveAttribute(
      "href",
      "https://www.google.com/maps/dir/?api=1&origin=28.6%2C77.2&destination=28.61%2C77.21&travelmode=driving",
    );
    expect(screen.getByRole("link", { name: "View OSM record" })).toHaveAttribute(
      "href",
      "https://www.openstreetmap.org/node/8",
    );
  });

  it("shows a clear message when a location cannot be geocoded", async () => {
    routesApi.compare.mockRejectedValueOnce(new Error("We couldn't find the starting location. Try adding a city or state."));
    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Route Planner" }));
    fireEvent.change(screen.getByLabelText("Starting location", { selector: "#route-origin" }), { target: { value: "Unknown place" } });
    fireEvent.click(await screen.findByRole("option", { name: /Unknown place/ }));
    fireEvent.change(screen.getByLabelText("Destination location", { selector: "#route-destination" }), { target: { value: "Delhi" } });
    fireEvent.click(await screen.findByRole("option", { name: /Delhi/ }));
    fireEvent.click(screen.getByRole("button", { name: /Compare car, motorcycle & walking/ }));

    expect(await screen.findAllByText(/We couldn't find the starting location/)).not.toHaveLength(0);
  });

  it("explains the travel-time recommendation and reuses the selected route in Journey Companion", async () => {
    newsApi.candidates.mockResolvedValueOnce({ items: [{ id: "pilot-news-1", canonical_url: "https://example.org/delhi-report", publisher: "example.org", headline: "Woman reports phone snatching in CR Park", incident_type_normalized: "snatching", event_date_start: "2022-05-30", published_at: "2022-05-30", locality: "CR Park", location_precision: "locality", event_status: "reported", review_status: "needs_review" }] });
    newsApi.coverage.mockResolvedValueOnce({ target: { from_year: 2016, to_year: 2025 }, years_with_candidates: [2021, 2022, 2025] });
    newsApi.discover.mockResolvedValueOnce({ groups: [{ status: "available", locality_search_term: "CR Park", returned: 1, items: [{ url: "https://example.org/live-crime-story", title: "Police investigate robbery in CR Park", publisher: "example.org", published_at: "2026-10-29T12:00:00Z", headline_category_candidate: "robbery_or_snatching", review_status: "needs_review", location_precision: "unverified_mention_match" }] }] });
    const plannedRoute = {
      id: "route-b",
      distance_m: 5200,
      duration_s: 1200,
      geometry: { type: "LineString", coordinates: [[77.2, 28.6], [77.3, 28.7]] },
    };
    routesApi.compare.mockResolvedValueOnce({
      alternatives: [
        { id: "route-a", distance_m: 4000, duration_s: 900, geometry: { type: "LineString", coordinates: [[77.2, 28.6], [77.25, 28.65]] } },
        plannedRoute,
        { id: "route-c", distance_m: 3500, duration_s: 1500, geometry: { type: "LineString", coordinates: [[77.2, 28.6], [77.22, 28.63], [77.3, 28.7]] } },
      ],
      recommendation: { route_id: "route-a", basis: "Lowest provider-estimated travel time; safety evidence is unavailable." },
      provider: "OSRM",
      provider_status: "provider_configured",
      limitations: [],
      evidence_context: {
        route_specific_news: { status: "unavailable", reason: "No verified geocoded incidents are available." },
        historical_official_statistics: { years: [2020, 2024], records: [{ year: 2024, count: 456 }], geography: "Delhi City metropolitan aggregate", geographic_precision: "Delhi City metropolitan aggregate", source: "https://example.test/ncrb", version: "Crime in India 2024", retrieved_at: "2026-10-28" },
      },
    });
    journeysApi.plan.mockResolvedValue({ id: 10 });
    journeysApi.active.mockResolvedValue({ active: false });

    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Route Planner" }));
    fireEvent.change(screen.getByLabelText("Starting location", { selector: "#route-origin" }), { target: { value: "Origin" } });
    fireEvent.click(await screen.findByRole("option", { name: /Origin/ }));
    fireEvent.change(screen.getByLabelText("Destination location", { selector: "#route-destination" }), { target: { value: "Destination" } });
    fireEvent.click(await screen.findByRole("option", { name: /Destination/ }));
    fireEvent.click(screen.getByRole("button", { name: /Compare car, motorcycle & walking/ }));

    expect(await screen.findByRole("heading", { name: "Your Journey at a Glance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Crime & News Alerts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Historical Crime Statistics" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Live Traffic" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Weather Updates" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Road Infrastructure" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Overall Route Assessment" })).toBeInTheDocument();
    expect(screen.getByText("456")).toBeInTheDocument();
    expect(await screen.findByText(/Live infrastructure data is unavailable/)).toBeInTheDocument();
    expect(routesApi.infrastructure).toHaveBeenCalledWith([[77.2, 28.6], [77.25, 28.65]], 100);
    expect(screen.getByLabelText("Infrastructure corridor width")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View Incident Details"));
    expect(await screen.findByText("Recent crime-news reports along this route")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View Crime Trends"));
    expect(screen.getByText(/City-level totals do not represent crime on this road/)).toBeInTheDocument();
    expect(screen.getByText("Fastest route")).toBeInTheDocument();
    expect(screen.getByText("Shortest route")).toBeInTheDocument();
    expect(screen.getByText("Alternative route")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select Route 3, route-c" })).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("article", { name: "Route 1 evidence · route-a" })).toHaveAttribute("aria-current", "true");
    expect(screen.queryByText("Route risk score")).not.toBeInTheDocument();
    journeysApi.active.mockResolvedValue({ active: true, id: 10, origin: "Origin", destination: "Destination", route_id: "route-b", route: plannedRoute, status: "in_progress" });
    fireEvent.click(screen.getByRole("button", { name: "Select Route 2, route-b" }));
    expect(await screen.findByRole("heading", { name: "Origin → Destination" })).toBeInTheDocument();
    expect(journeysApi.plan).toHaveBeenLastCalledWith(expect.objectContaining({
      route_id: "route-b",
      route: expect.objectContaining({ id: "route-b", geometry: plannedRoute.geometry, source: "OSRM", origin_location: expect.objectContaining({ latitude: 28.6 }), destination_location: expect.objectContaining({ latitude: 28.6 }) }),
    }));
    expect(journeysApi.start).toHaveBeenCalledWith(10);
    expect(screen.getByRole("heading", { name: "Planned route and GPS track" })).toBeInTheDocument();
    expect(screen.getByText(/route-b/)).toBeInTheDocument();
  }, 15000);

  it("shows live traffic level, delay, and updated route time for the selected route", async () => {
    routesApi.compare.mockResolvedValueOnce({
      alternatives: [{ id: "route-1", duration_s: 600, distance_m: 5000, geometry: { coordinates: [[77, 28], [77.1, 28.1]] } }],
      provider_status: "provider_configured",
      provider: "OSRM",
      resolved_locations: { origin: { latitude: 28, longitude: 77 }, destination: { latitude: 28.1, longitude: 77.1 } },
    });
    routesApi.traffic.mockResolvedValueOnce({ status: "available", provider: "TomTom", retrieved_at: new Date().toISOString(), stale_after_seconds: 180, level: "moderate", estimated_delay_s: 120, estimated_travel_time_s: 720, base_travel_time_s: 600, coverage: { sampled: 2, requested: 2 }, points: [{ current_speed_kmh: 20, provider_observed_at: "2026-10-29T07:00:00Z" }], method_note: "Sample estimate." });

    render(<App/>);
    fireEvent.click(await screen.findByRole("link", { name: "Route Planner" }));
    fireEvent.change(screen.getByLabelText("Starting location", { selector: "#route-origin" }), { target: { value: "Delhi" } });
    fireEvent.click(await screen.findByRole("option", { name: /Delhi/ }));
    fireEvent.change(screen.getByLabelText("Destination location", { selector: "#route-destination" }), { target: { value: "AIIMS Delhi" } });
    fireEvent.click(await screen.findByRole("option", { name: /AIIMS Delhi/ }));
    fireEvent.click(screen.getByRole("button", { name: /Compare car, motorcycle & walking/ }));

    expect(await screen.findByRole("heading", { name: "Live Traffic" })).toBeInTheDocument();
    expect(await screen.findByText(/moderate/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("View Traffic Details"));
    expect(screen.getByText(/Estimated delay: 2 min · estimated travel time: 12 min/)).toBeInTheDocument();
    expect(screen.getByText(/Provider observation timestamp:/)).toBeInTheDocument();
    expect(screen.getByText(/Response retrieved by NAVIRA:/)).toBeInTheDocument();
    expect(routesApi.traffic).toHaveBeenCalledWith([[77, 28], [77.1, 28.1]], 600, 5000);
  });
});
