import { afterEach, describe, expect, it, vi } from "vitest";
import { backendApi, newsApi, routesApi } from "./api.js";

afterEach(() => vi.unstubAllGlobals());

describe("route planner API integration", () => {
  it("loads source candidates and their explicit coverage separately", async () => {
    const payload={items:[],target:{from_year:2016,to_year:2025}};
    const fetchMock=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>payload});
    vi.stubGlobal("fetch",fetchMock);
    await expect(newsApi.candidates({locality:"CR Park",year:2022})).resolves.toEqual(payload);
    await expect(newsApi.coverage()).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/news/candidates?locality=CR+Park&year=2022");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/news/coverage");
  });

  it("posts selected locality search terms to the recent news discovery API", async () => {
    const payload={groups:[{status:"available",locality_search_term:"CR Park",items:[]}]};
    const fetchMock=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>payload});
    vi.stubGlobal("fetch",fetchMock);
    await expect(newsApi.discover(["CR Park","Welcome"])).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/news/discover");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({localities:["CR Park","Welcome"]});
  });

  it("searches for place suggestions only when requested", async () => {
    const payload = { items: [{ display_name: "Delhi, India", latitude: 28.6, longitude: 77.2 }] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);
    await expect(routesApi.suggest("Delhi")).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/geocoding/search?q=Delhi", expect.any(Object));
  });

  it("posts selected places to route comparison", async () => {
    const payload = { alternatives: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);
    await expect(routesApi.compare("Delhi, India", "AIIMS Delhi")).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/routes/compare");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ origin: "Delhi, India", destination: "AIIMS Delhi" });
  });

  it("requests a pilot walking path explicitly", async () => {
    const payload={provider_status:"unavailable",alternatives:[],error:"outside pilot map coverage"};
    const fetchMock=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>payload});
    vi.stubGlobal("fetch",fetchMock);
    await expect(routesApi.walking("CR Park, India","AIIMS, India")).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/routes/walking");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({origin:"CR Park, India",destination:"AIIMS, India"});
  });

  it("passes selected walking-place coordinates to the backend", async () => {
    const payload={provider_status:"unavailable",alternatives:[],error:"provider unavailable"};
    const fetchMock=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>payload});
    vi.stubGlobal("fetch",fetchMock);
    const origin={query:"Origin",display_name:"Origin Place",latitude:28.55,longitude:77.25,provider:"Nominatim"};
    const destination={query:"Destination",display_name:"Destination Place",latitude:28.56,longitude:77.26,provider:"Nominatim"};
    await routesApi.walking(origin.display_name,destination.display_name,origin,destination);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({origin:"Origin Place",destination:"Destination Place",origin_location:origin,destination_location:destination});
  });

  it("loads source-reported context for explicit selected endpoint names", async () => {
    const payload={status:"candidate_context",items:[],notice:"Text match only"};
    const fetchMock=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>payload});
    vi.stubGlobal("fetch",fetchMock);
    await expect(routesApi.localityReports("CR Park, Delhi","AIIMS, Delhi")).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/routes/locality-reports");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({origin:"CR Park, Delhi",destination:"AIIMS, Delhi"});
  });

  it("posts route geometry for traffic and preserves unavailable status", async () => {
    const payload = { status: "unavailable", provider: null, reason: "No traffic provider configured." };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);
    await expect(routesApi.traffic([[77.2, 28.6], [77.3, 28.7]], 1200, 5000)).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/routes/traffic");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ coordinates: [[77.2, 28.6], [77.3, 28.7]], duration_s: 1200, distance_m: 5000 });
  });

  it("requests mapped infrastructure using the selected route and corridor width", async () => {
    const payload = { status: "available", streetlights_mapped: 8, footpaths_mapped: 3 };
    const coordinates = [[77.2, 28.6], [77.3, 28.7]];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);
    await expect(routesApi.infrastructure(coordinates, 250)).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/routes/infrastructure");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ coordinates, corridor_m: 250 });
  });

  it("loads imported pedestrian map context only for the route bounds", async () => {
    const payload={type:"FeatureCollection",features:[],returned:0};
    const fetchMock=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>payload});
    vi.stubGlobal("fetch",fetchMock);
    await expect(routesApi.pedestrianNetwork([77.2,28.5,77.3,28.6])).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/map/pedestrian-network?bbox=77.2%2C28.5%2C77.3%2C28.6&limit=2000");
  });

  it("loads OSM infrastructure only for the visible map bounds and forwards cancellation", async () => {
    const payload = { type: "FeatureCollection", features: [], status: "available" };
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);
    await expect(routesApi.mapInfrastructure([77.2, 28.6, 77.22, 28.62], { signal: controller.signal })).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/map/infrastructure?bbox=77.2%2C28.6%2C77.22%2C28.62");
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });
});


describe("crime and news API integration", () => {
  it("loads locality route-safety coverage separately from aggregate counts", async () => {
    const payload = { status: "insufficient_data", route_matched_verified_incidents: 0, risk_estimate: "not_supported" };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", fetchMock);
    await expect(backendApi.routeSafetyDataStatus()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/routes/safety-data-status", expect.any(Object));
  });

});
