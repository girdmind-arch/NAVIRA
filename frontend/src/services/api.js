const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const TOKEN_KEY = "navira-session-token";

export function getToken() { return localStorage.getItem(TOKEN_KEY); }
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.auth !== false && getToken() && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${getToken()}`);
  const fetchOptions = { ...options };
  delete fetchOptions.auth;

  let response;
  try {
    response = await fetch(API_BASE + path, { credentials: "same-origin", ...fetchOptions, headers });
  } catch {
    throw new Error("NAVIRA could not reach the backend. Start the API and try again.");
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (Array.isArray(payload.detail)) {
        detail = payload.detail.map((item) => `${item.loc?.slice(-1)[0] || "Input"}: ${item.msg}`).join(" ");
      }
    } catch { /* use the status message when the response is not JSON */ }
    throw new Error(detail);
  }

  if (response.status === 204) return null;
  return response.json();
}

export function request(path, method = "GET", body, options = {}) {
  return api(path, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    ...options,
  });
}

export const authApi = {
  session: () => request("/api/auth/session"),
  login: (email, password) => request("/api/auth/login", "POST", { email, password }, { auth: false }),
  register: (email, password, name) => request("/api/auth/register", "POST", { email, password, name }, { auth: false }),
  logout: () => request("/api/auth/logout", "POST"),
};

export const profileApi = {
  get: () => request("/api/profile"),
  update: (profile) => request("/api/profile", "PUT", profile),
};

export const contactsApi = {
  list: () => request("/api/contacts"),
  create: (contact) => request("/api/contacts", "POST", contact),
  update: (id, contact) => request(`/api/contacts/${id}`, "PUT", contact),
  remove: (id) => request(`/api/contacts/${id}`, "DELETE"),
};

export const journeysApi = {
  plan: (journey) => request("/api/journeys/plan", "POST", journey),
  active: () => request("/api/journeys/active"),
  start: (id) => request(`/api/journeys/${id}/start`, "POST"),
  complete: (id) => request(`/api/journeys/${id}/complete`, "POST"),
  history: () => request("/api/journeys/history"),
};

export const backendApi = {
  emergencyResources: () => api("/api/v1/emergency/resources"),
  routeSafetyDataStatus: () => api("/api/v1/routes/safety-data-status"),
};

export const syntheticDemoApi = {
  get: () => api("/api/v1/demo/synthetic-data", { auth: false }),
};

export const facilitiesApi = {
  nearby: (latitude, longitude, category = "all", radiusM = 5000) => api(
    `/api/v1/facilities/nearby?latitude=${encodeURIComponent(latitude)}&longitude=${encodeURIComponent(longitude)}&category=${encodeURIComponent(category)}&radius_m=${encodeURIComponent(radiusM)}`,
  ),
};

const SAFETY_KEY = "navira.safety.workspace-key.v1";

function getSafetyAuthorization() {
  let key = window.localStorage.getItem(SAFETY_KEY);
  if (!key) {
    if (!window.crypto?.getRandomValues) {
      throw new Error("This browser cannot create a secure private safety workspace.");
    }
    const bytes = new Uint8Array(32);
    window.crypto.getRandomValues(bytes);
    key = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    window.localStorage.setItem(SAFETY_KEY, key);
  }
  return { Authorization: `Bearer ${key}` };
}

function safetyRequest(path, method = "GET", body, options = {}) {
  return api(path, {
    method,
    ...options,
    headers: getSafetyAuthorization(),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

const safetyApi = {
  status: () => safetyRequest("/api/v1/safety/status"),
  shares: () => safetyRequest("/api/v1/safety/shares"),
  createShare: (location) => safetyRequest("/api/v1/safety/shares", "POST", location),
  revokeShare: (id) => safetyRequest(`/api/v1/safety/shares/${encodeURIComponent(id)}`, "DELETE"),
  recordSOS: () => safetyRequest("/api/v1/safety/sos", "POST", {}, { keepalive: true }),
  sosEvents: () => safetyRequest("/api/v1/safety/sos"),
  publicShare: (token) => api(`/api/v1/safety/shares/public/${encodeURIComponent(token)}`),
};

export { safetyApi };

const pendingTrafficRequests = new Map();

export const routesApi = {
  suggest: (query) => api(`/api/v1/geocoding/search?q=${encodeURIComponent(query)}`),
  compare: (origin, destination, originLocation, destinationLocation, mode = "car") =>
    request("/api/v1/routes/compare", "POST", {
      origin,
      destination,
      ...(mode === "car" ? {} : { mode }),
      origin_location: originLocation,
      destination_location: destinationLocation,
    }),
  walking: (origin, destination, originLocation, destinationLocation) => request("/api/v1/routes/walking", "POST", {
    origin,
    destination,
    ...(originLocation ? { origin_location: originLocation } : {}),
    ...(destinationLocation ? { destination_location: destinationLocation } : {}),
  }),
  localityReports: (origin, destination) => request("/api/v1/routes/locality-reports", "POST", { origin, destination }),
  pedestrianNetwork: (bbox) => {
    const params = new URLSearchParams({ bbox: bbox.join(","), limit: "2000" });
    return api(`/api/v1/map/pedestrian-network?${params}`);
  },
  mapInfrastructure: (bbox, options = {}) => {
    const params = new URLSearchParams({ bbox: bbox.join(",") });
    return api(`/api/v1/map/infrastructure?${params}`, options);
  },
  traffic: (coordinates, duration_s, distance_m) => {
    const key = JSON.stringify([coordinates, duration_s, distance_m]);
    const pending = pendingTrafficRequests.get(key);
    if (pending) return pending;
    const requestPromise = request("/api/v1/routes/traffic", "POST", { coordinates, duration_s, distance_m })
      .finally(() => pendingTrafficRequests.delete(key));
    pendingTrafficRequests.set(key, requestPromise);
    return requestPromise;
  },
  weather: (coordinates) => request("/api/v1/routes/weather", "POST", { coordinates }),
  infrastructure: (coordinates, corridor_m) => request("/api/v1/routes/infrastructure", "POST", { coordinates, ...(corridor_m == null ? {} : { corridor_m }) }),
};

export const reportsApi = {
  list: async () => {
    const result = await api("/api/v1/community/hazards");
    return result.items || [];
  },
  create: (report) => request("/api/v1/community/hazards", "POST", {
    category: report.category,
    description: report.description,
    approximate_geography: report.approximate_geography,
    expires_days: report.expires_days || 7,
  }),
};

export const newsApi = {
  candidates: (filters = {}) => {
    const query = new URLSearchParams();
    if (filters.locality) query.set("locality", filters.locality);
    if (filters.year) query.set("year", filters.year);
    return api(`/api/v1/news/candidates${query.size ? `?${query}` : ""}`);
  },
  coverage: () => api("/api/v1/news/coverage"),
  discover: (localities) => request("/api/v1/news/discover", "POST", { localities }),
  routeLocalityEvidence: (geometry) => request("/api/v1/routes/locality-news", "POST", { geometry }),
};

export function getApiBase() { return API_BASE || window.location.origin; }
