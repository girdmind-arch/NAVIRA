# NAVIRA backend

FastAPI service for sourced aggregate statistics, news triage, localities, route comparison, and community reports. The optional text-classification model lives in the repository's separate `ml/` directory; backend privacy filtering, data access, and model persistence stay here.

## Run from the repository root

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m pip install -r ml\requirements.txt
python -m uvicorn backend.app.main:app --reload
~~~

Open http://127.0.0.1:8000/docs for the interactive API. `backend/app/main.py` registers the ML router in `backend/app/routers/ml.py`, which connects each endpoint to the adapter in `backend/app/services/ml.py` and the model implementation in `ml/news_classifier.py`. The ML and news-triage workflows are exposed by FastAPI:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/news/extract` | Extract candidate dates/localities and rule-based relevance from submitted text. |
| `POST` | `/api/v1/news/classify` | Classify text with the saved TF-IDF model, falling back to rules when no model is saved. |
| `POST` | `/api/v1/news/discover` | Search recent GDELT and Google News indexed crime-news candidates for one or two selected Delhi place names; results are unverified mentions, not confirmed incident locations. |
| `POST` | `/api/v1/models/evaluate` | Fit and score an in-memory model using supplied human-labelled examples; does not save it. |
| `POST` | `/api/v1/models/train` | Fit, save, and record a model run using supplied human-labelled examples. |
| `GET` | `/api/v1/models/runs` | Read saved training run metadata and evaluation metrics. |
| `POST` | `/api/v1/review/duplicates/detect` | Generate similarity candidates for human review; records are never merged. |
| `GET` | `/api/v1/review/duplicates` | List duplicate candidates awaiting review. |
| `POST` | `/api/v1/review/duplicates/{candidate_id}` | Record a human review decision. |

Training and evaluation accept JSON shaped as `{"records":[{"text":"...","label":1,"source_group":"source-a"}]}`. Labels must be explicit human labels (`1` relevant, `0` not relevant); at least 10 examples and two examples per class are required to train. Install `ml/requirements.txt` to enable fitting and persistence. All model outputs are triage candidates, never factual verification or crime-risk predictions. The NCRB Delhi City aggregate endpoint is `GET /api/v1/datasets/ncrb/delhi-city/crimes-against-women`.

Set optional environment variables in the process environment; `backend/.env.example` is a reference list and is not automatically loaded.

For Geoapify motorcycle directions, create a free Geoapify account and project, copy its API key, then set `GEOAPIFY_API_KEY` in the backend process environment before starting FastAPI (for example, in PowerShell: `$env:GEOAPIFY_API_KEY = "your-key"`). The official free plan currently provides 3,000 credits/day and up to 5 requests/second without a payment card. For Render, add `GEOAPIFY_API_KEY` under the service's environment variables; `render.yaml` declares it as a secret input. Never add the key to `frontend/.env`, any `VITE_*` variable, or committed files. If the key is omitted, motorcycle requests can use the explicitly labeled OSRM car-profile fallback.

Location suggestions are returned by `GET /api/v1/geocoding/search?q=...`; the client must select a full result before requesting a route. The selected display name and its exact longitude/latitude are sent to `POST /api/v1/routes/compare`, preserving locality-level coordinates. Nominatim requires an identifying User-Agent and applies a strict usage policy; its public service is for low-volume use only. Set `NAVIRA_GEOCODER_URL` for a compatible hosted or self-hosted service, and `NAVIRA_GEOCODER_USER_AGENT` to identify this deployment. Location text is sent to the selected geocoder.

`GET /api/v1/facilities/nearby?latitude=...&longitude=...&category=all` retrieves mapped police and hospital facilities around the selected route coordinates. It tries `NAVIRA_OVERPASS_URL` (default `overpass-api.de`) and then public Private.coffee and VK Maps Overpass instances. If Overpass is unavailable, police stations fall back to Delhi Police's official `PS_LOCATION` GIS layer; hospitals use Photon tag-filtered search, with bounded Nominatim search as a last fallback. Photon/Nominatim fallback coverage is partial and is labelled as such. Successful nearby results are cached in-process for 10 minutes; GIS station locations are cached for 24 hours. For `all`, results are balanced between police and hospital listings where available. The UI supports 2/5/10 km search radii. OSM features may be nodes or approximate area centers, addresses may be absent, and facility operation/status is not independently verified. In fallback mode, only straight-line distances are shown. Get Directions opens Google Maps with the selected reference and facility coordinates.

The car route adapter requests up to three real road-network alternatives from OSRM (`alternatives=3`), validates route geometry and metrics, and removes identical geometry responses; the road network may provide fewer. `NAVIRA_OSRM_BASE_URL` defaults to the OSRM public demonstration server (`https://router.project-osrm.org`), which has no availability guarantee and should be replaced by an eligible hosted or self-managed provider for production. A provider outage is surfaced as unavailable; no demo geometry or travel estimates are substituted. Route alternative distances, durations, and GeoJSON geometry are provider responses.

Walking route requests use openrouteservice's `foot-walking` Directions profile via the backend-only `OPENROUTESERVICE_API_KEY`. The key is never sent to the browser. The adapter validates GeoJSON geometry, distance, and duration, and maps missing keys, invalid credentials, exhausted quota, rate limits, and provider outages to explicit unavailable responses. The free Standard tier currently lists 2,000 Directions requests per rolling 24-hour window and 40 per minute. Walking routes are OSM-derived estimates and do not verify sidewalk continuity, crossings, accessibility, lighting, or current access.

Motorcycle route requests use Geoapify Routing API with the documented `mode=motorcycle` profile (distinct from `scooter`); configure backend-only `GEOAPIFY_API_KEY`. Geoapify's official pricing currently lists 3,000 credits/day, up to 5 requests/second, and signup without a credit card. A two-waypoint route generally costs 1 credit. If this key is missing, NAVIRA may return an OSRM `driving` profile route as a labeled fallback; it is not motorcycle-optimized and does not verify motorcycle access or restrictions. If a configured Geoapify request fails, NAVIRA returns an unavailable status rather than disguising a car route as motorcycle guidance. Geoapify route times are estimates, not live motorcycle traffic. Provider map restrictions may be incomplete; users must follow current signs and local rules. Display Geoapify attribution with Geoapify routes, alongside OpenStreetMap map attribution. This is route guidance only, not a safety rating or guarantee.

The bundled NCRB dataset contains official Delhi City metropolitan registered cases against women for 2020–2024; it is not locality or road-level data. News ingestion accepts incident coordinates or attempts to geocode the locality text for records marked `verified` with a precise location class (`street`, `address`, `building`, `premise`, or `landmark`). Verified ingestion requires the server-only `NAVIRA_EVIDENCE_REVIEW_TOKEN` in the `X-NAVIRA-EVIDENCE-REVIEW-TOKEN` header; do not expose this credential to the frontend. Broad city/town/neighbourhood matches are rejected for incident geocoding. Route matching still requires an eligible record with a source URL, incident date, coordinates, and a precision class. `NAVIRA_ROUTE_INCIDENT_RADIUS_M` (default 500) and `NAVIRA_ROUTE_INCIDENT_MAX_AGE_DAYS` (default 1095) control matching. Newspaper report matches are not a complete incident denominator, so NAVIRA does not derive a numeric risk score from them; missing evidence is shown as insufficient, not as zero incidents or safety.

SQLite and model artifacts are stored under `backend/` by default and can be relocated with `NAVIRA_DB_PATH` and `NAVIRA_MODEL_PATH`. See `backend/docs/data-and-privacy.md` for provenance and geographic scope notes.

## Route planner APIs

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/geocoding/search?q={query}&limit=5` | Search for up to five place suggestions after the user enters a query of at least two characters. |
| `POST` | `/api/v1/routes/compare` | Geocode the selected origin and destination, then return route alternatives and provider status. Body: `{"origin":"Delhi, India","destination":"AIIMS, New Delhi, India","mode":"motorcycle"}`. `mode` is optional and defaults to `car`; motorcycle uses backend `GEOAPIFY_API_KEY` when configured. Without it the response may use a clearly labeled OSRM car-profile fallback, not motorcycle-optimized. |
| `POST` | `/api/v1/routes/walking` | Geocode the supplied places and request directions from openrouteservice's `foot-walking` profile. Requires backend `OPENROUTESERVICE_API_KEY`; returns provider distance, duration, and geometry, or a clear unavailable/error status. |
| `POST` | `/api/v1/routes/traffic` | Accept `{"coordinates":[[77.2,28.6],[77.3,28.7]],"duration_s":1200,"distance_m":5000}`. Uses TomTom when `TOMTOM_API_KEY` is configured; otherwise returns an explicit unavailable/unconfigured status. |
| `POST` | `/api/v1/routes/infrastructure` | Accepts selected route coordinates and optional `corridor_m` (25–500 m; frontend offers 50/100/250/500 m). Returns live OSM mapped streetlights and pedestrian ways with coverage and retrieval times. Counts do not establish operational status; government inspection/complaint feeds and night visibility remain unavailable/unassessed. |
| `POST` | `/api/v1/routes/locality-news` | Accepts a selected route's GeoJSON LineString, samples Delhi Police station boundary polygons, reverse-geocodes at most six points for locality news, and exact-matches fetched press-release rows to crossed station names. Returns station evidence and coverage caveats. |
| `GET` | `/api/v1/routes/safety-data-status` | Reports reviewed incident/geolocation/pedestrian-segment coverage. `risk_estimate` stays `not_supported` until reviewed route-segment evidence exists. NCRB city totals are reported separately and are never mapped to routes. |
| `POST` | `/api/v1/routes/locality-reports` | Returns source-linked report candidates only when the selected origin/destination label exactly includes a stored locality/landmark; this is a text match, not route proximity. |
| `GET` | `/api/v1/map/pedestrian-network?bbox=west,south,east,north` | Serves locally stored OSM pilot GeoJSON for a WGS84 bbox no larger than 0.1 degrees. Returns OSM attribution/license and an incomplete-coverage caveat. |

## Reviewed route-safety imports

The Route Planner's **Newspaper incident evidence** panel uses `POST /api/v1/routes/locality-news`. Route samples are checked against Delhi Police station polygons from the official GSDL ArcGIS service; matched station names are compared exactly with the archive's Police Station field. Each archive item remains a `needs_review` press-release candidate and carries its source URL, title, issue date, category, and listed station/district. The endpoint reads the current SCRB New Press Releases listing, which is paginated; it does not crawl or import all 52,000+ archive entries. The ten-year date window only applies to records on the fetched listing page, so missing years and stations are coverage gaps, not zero-crime findings. Published station boundaries provide approximate route matching, not a legal jurisdiction determination. Press releases are selective communications, not registered FIR totals or locality crime rates. GDELT/Google News reports remain recent locality-search candidates. The loaded NCRB figures are Delhi City aggregates for 2020–2024 and are never assigned to route stations. See [`docs/news-candidate-coverage.md`](docs/news-candidate-coverage.md) for source and coverage limitations.

The plan's source-by-source access, format, coverage and import decisions are documented in [`NAVIRA_Delhi_Source_Import_Status.md`](../../../../outputs/NAVIRA_Delhi_Source_Import_Status.md) in the task workspace. At startup, NAVIRA seeds the NCRB city aggregate and imports the checked OSM GeoJSON fixture into SQLite idempotently. The four source-linked news candidates formerly bundled in the backend were removed; news candidate rows now require a separate explicit import or live discovery.

The separate read-only `GET /api/v1/demo/synthetic-data` endpoint serves `data/fixtures/navira_synthetic_route_demo.json`. It does not read or write SQLite, and no field is joined to a real origin, destination, route, official-statistics record, verified incident, or model dataset. Synthetic crime-rate examples use invented counts divided by fictional populations and must remain labeled `SYNTHETIC DEMO — NOT REAL SAFETY DATA`. They never affect route assessment, route recommendations, model training, or evaluation.

To import a locally prepared and reviewed JSON file, use `backend/scripts/import_route_safety.py`. The script performs no web requests, geocoding, or external uploads. First run `python -m backend.scripts.import_route_safety path\to\reviewed.json --dry-run`, inspect validation output, then omit `--dry-run` to write. Each dataset must contain source-level `name`, `reference`, `permission_basis`, and `geographic_precision`, and each record needs a stable `id` plus one or more canonical source URLs. Records with the same stable id are not duplicated on rerun; new article URLs are attached to the existing event. Sensitive places with coordinates are rejected. Keep only minimal redacted summaries/evidence spans and use `review_status=verified` only after human review. A successful CLI import is recorded in `route_safety_import_runs`. The OSM file was fetched from the API during this work and is stored under `backend/data/osm/`; `python -m backend.scripts.import_osm_pilot_network --dry-run` validates it and omitting the flag imports it locally.

`incident_events`, `incident_sources`, `place_observations`, `pedestrian_networks`, `pedestrian_segments`, and `incident_segment_matches` are separate from aggregate `official_stats`. Matching is never inferred from locality text alone. The app has no complete, reviewed pedestrian graph for the route-safety evidence pipeline and no street-audit point dataset is licensed/imported. openrouteservice route geometry is navigation context only; it does not provide the incident/exposure denominator or audited safety observations needed for route-level risk estimates, which remain unavailable by design.

The frontend uses `VITE_API_BASE_URL` when set and otherwise calls the same origin; local Vite proxies `/api/v1` to `NAVIRA_BACKEND_URL` (default `http://127.0.0.1:8000`). Nominatim is used for place lookup by default, with `NAVIRA_GEOCODER_URL` and `NAVIRA_GEOCODER_USER_AGENT` available for a compatible service. Configure `NAVIRA_OSRM_BASE_URL` for car geometry. Walking directions continue to use openrouteservice's `foot-walking` profile; configure `OPENROUTESERVICE_API_KEY` in the backend environment or Render secret. Motorcycle routing uses Geoapify's separate `motorcycle` profile; configure `GEOAPIFY_API_KEY` in the backend environment or Render secret. Geoapify's official free plan currently lists 3,000 credits/day, up to 5 requests/second, and no credit card; a two-waypoint route generally costs 1 credit. Add Geoapify attribution near route results and retain the map's OpenStreetMap attribution. If Geoapify is configured but unavailable, NAVIRA reports the failure; without a Geoapify key it may show an OSRM car-profile route clearly labeled as not motorcycle-optimized. TomTom remains used for live traffic only. Keep `OPENROUTESERVICE_API_KEY`, `GEOAPIFY_API_KEY`, and `TOMTOM_API_KEY` backend-only; never place them in Vite or browser variables. TomTom traffic still returns sampled flow, provider coverage and timestamps, and an estimated delay; partial coverage is labeled and no traffic values are inferred from OSRM duration.


## Emergency and location sharing

The Safety Center APIs are protected by a random 256-bit bearer key generated and kept in the browser's local storage. This provides a private per-browser guest workspace; it does not create a user account or verify identity. The API supports trusted contacts, expiring one-time location snapshots, revocation, and 24-hour SOS event records. Public share links are bearer secrets. NAVIRA does not send texts or place calls; the UI opens the device's messaging or dialer app for the user to complete. See `backend/docs/data-and-privacy.md` before using this with real contact/location data.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/safety/status` | Check the private safety workspace connection. |
| `GET`, `POST` | `/api/v1/safety/contacts` | List or save the browser owner's trusted contacts. |
| `DELETE` | `/api/v1/safety/contacts/{contact_id}` | Remove a trusted contact. |
| `GET`, `POST` | `/api/v1/safety/shares` | List active shares or create a one-hour location snapshot. |
| `GET` | `/api/v1/safety/shares/public/{token}` | View a location using its temporary bearer link. |
| `DELETE` | `/api/v1/safety/shares/{share_id}` | Revoke a location share. |
| `GET`, `POST` | `/api/v1/safety/sos` | List or create short-lived SOS event records. |

## Accounts and journey history

Accounts use salted PBKDF2 password hashes and random 30-day sessions. New sessions are delivered in an `HttpOnly`, `SameSite=Lax` cookie, marked `Secure` on HTTPS; the browser JavaScript cannot read the session cookie. The API accepts the previous bearer token during migration and exchanges a valid token for the cookie on `GET /api/auth/session`. The frontend clears its legacy local-storage token after session restoration. Profile, account-scoped trusted contacts, and journeys require a valid session; the existing Safety Center location-sharing workspace remains a separate browser-key capability. Keep the application frontend and API on the same origin unless CORS and cookie policy are deliberately configured.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/register` | Create an account and session. |
| `POST` | `/api/auth/login` | Start a session. |
| `GET` | `/api/auth/session` | Restore and validate the current signed-in session. |
| `POST` | `/api/auth/logout` | Revoke the current session. |
| `GET`, `PUT` | `/api/profile` | Read or update the signed-in profile. |
| `GET`, `POST` | `/api/contacts` | List or save account-scoped trusted contacts. |
| `PUT`, `DELETE` | `/api/contacts/{contact_id}` | Update or remove a contact owned by the signed-in account. |
| `POST` | `/api/journeys/plan` | Save the selected route for Journey Companion. |
| `GET` | `/api/journeys/active` | Read the current planned or in-progress journey. |
| `POST` | `/api/journeys/{journey_id}/start` | Record the start time. |
| `POST` | `/api/journeys/{journey_id}/complete` | Complete a started journey and record its end time. |
| `GET` | `/api/journeys/history` | List completed journeys for the signed-in account. |

The Render free blueprint uses an ephemeral filesystem, so SQLite account and journey records can be lost after an instance restart or redeploy. Use persistent storage or a managed database before relying on saved user data.
