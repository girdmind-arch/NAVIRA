# Synthetic demo data

The fictional fixture is stored at `backend/data/fixtures/navira_synthetic_route_demo.json` and served by the backend's separate read-only `/api/v1/demo/synthetic-data` endpoint. It is not a data import, and it does not contain observations from NCRB, Delhi Police, Safetipin, OpenStreetMap, traffic or weather providers, or NAVIRA users.

Keep this fixture separate from real ingestion, verified safety evidence, safety scoring, and model training/evaluation. Its place names have no coordinates, its routes and conditions are not real, its safety score fields are null, and its crime-rate examples use invented values and fictional population denominators. If shown in the UI, display a persistent `SYNTHETIC DEMO — NOT REAL SAFETY DATA` banner.

The source catalog links to candidate real providers for future integration. Listing a provider does not mean its data was accessed, licensed, or used here. The local walkthrough remains gated by the development-only flag `VITE_NAVIRA_SYNTHETIC_DEMO=true`; the Route Planner's standalone synthetic example card does not match the examples to real locations or use them for recommendations.
