# NAVIRA Frontend

Responsive React 19 + Vite application for NAVIRA, using React Leaflet for maps. The user-facing workspace includes route planning, emergency SOS and sharing, community reports, Journey Companion, and account settings. NCRB and ML/data processing remain backend capabilities; their tool dashboards are not part of the frontend.

From this folder:

```sh
cp .env.example .env
npm ci
npm run dev
```

Start FastAPI separately at `http://127.0.0.1:8000`. Vite runs at `http://127.0.0.1:5174` and proxies `/health` and `/api/*` to the backend, so leave `VITE_API_BASE_URL` blank during local development. Set `NAVIRA_BACKEND_URL` or `NAVIRA_FRONTEND_PORT` only when those defaults are occupied. Route forms accept place names or addresses; the backend converts them to coordinates using Nominatim before routing. The public Nominatim service requires an identifying User-Agent and is limited to low-volume use (at most one request per second); no API key is needed for the public default. Set `NAVIRA_GEOCODER_URL` for a compatible alternative. Location text is sent to the configured geocoder. Car routes use OSRM. Walking routes continue to use openrouteservice's `foot-walking` profile and require backend-only `OPENROUTESERVICE_API_KEY`; its current free Standard quota is 2,000 Directions requests per rolling 24 hours and 40 per minute. Motorcycle routes use Geoapify's documented `motorcycle` profile (not its separate scooter profile) and require backend-only `GEOAPIFY_API_KEY`. Geoapify's official free plan currently lists 3,000 credits/day, up to 5 requests/second, and signup without a payment card; a two-waypoint route generally costs 1 credit. When the Geoapify key is missing, the backend may use an OSRM driving route as a plainly labeled fallback; that route is not motorcycle-optimized. A configured Geoapify error returns unavailable rather than substituting a car route. Show Geoapify attribution next to Geoapify route results and retain OpenStreetMap tile attribution. Public OSRM and OSM tile services have usage limits and no availability guarantee. Render serves the frontend and API from the same origin. Never put provider credentials in frontend variables.

## Local synthetic route demo

The fictional route-context fixture is stored in `backend/data/fixtures/navira_synthetic_route_demo.json` and served by the separate read-only `/api/v1/demo/synthetic-data` endpoint. The route planner shows its crime-rate examples in a distinct synthetic-only panel, unrelated to the selected real route. The local `#/demo` walkthrough remains gated by Vite development mode and `VITE_NAVIRA_SYNTHETIC_DEMO=true`. Every display includes `SYNTHETIC DEMO — NOT REAL SAFETY DATA`; the example places have no coordinates, safety scores are null, and emergency placeholders are not dialable. The backend never ingests this fixture into evidence tables or uses it for scoring, training, or evaluation.

First-time visitors see the NAVIRA introduction and sign-in/sign-up forms. Returning sessions use the backend's 30-day `HttpOnly`, `SameSite=Lax` cookie; account passwords are never saved in the browser. Profile supports profile edits, account-scoped trusted contacts, and completed journey history. Route Planner saves the selected route and its geometry for signed-in users. It recommends the shortest provider-estimated travel time (distance as a tie-breaker), not a safer route: no verified geocoded incident records or approved locality boundaries are available for route-segment matching, and city-wide NCRB aggregates cannot distinguish between route options. The score is therefore shown as unavailable. GPS positions observed during an active journey are saved to browser session storage for map display and are not uploaded. Journey time remaining and arrival are estimates derived from the route provider's original duration, not live traffic updates. The Safety Center uses the existing per-browser safety workspace for sharing and SOS. There is no configured police/hospital locator endpoint in this frontend. Routes are not safety ratings and do not include live traffic. Map tile use follows the [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/), geocoding follows [Nominatim's usage policy](https://operations.osmfoundation.org/policies/nominatim/), and road routing uses the [OSRM route API](https://project-osrm.org/docs/v5.22.0/api/). Backend ML/data APIs remain available for trusted operators but are not exposed as frontend tools; do not expose unauthenticated ingestion/training endpoints to an untrusted network.

Quality checks:

```sh
npm run test
npm run lint
npm run build
```
