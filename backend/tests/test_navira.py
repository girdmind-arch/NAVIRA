import os, tempfile, uuid
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from http.cookies import SimpleCookie
from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient
from backend.app import core
from backend.app import main
from backend.app.main import NewsIn, OfficialIn, HazardIn, RouteIn, add_hazard, app, ingest_news, ingest_official, routes as route_endpoint, trends_endpoint
from backend.app.services.agents import quality, resolve, dup_score, redact, compare, validate_official, match_route_incidents, MockRouter, OSRMRouter, GeoapifyMotorcycleRouter, OpenRouteServiceWalkingRouter, OpenMeteoAdapter, distinct_route_alternatives, assess_route_safety
from backend.app.services.facilities import FacilitiesUnavailable, OverpassPlaces, nearby_facilities
from backend.app.services.ml import train

def setup_db(monkeypatch,tmp_path):
 monkeypatch.setattr(core,"DB_PATH",tmp_path/"test.sqlite3"); core.init_db()

def test_empty_coverage_has_gaps(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 with core.connect() as db:
  result=quality(db)
 assert len(result["missing_years"])==5 and len(result["official_missing_years"])==5 and result["official_statistics"]==0

def test_route_safety_status_keeps_city_aggregates_separate_from_pilot_evidence(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 with core.connect() as db:
  db.execute("insert into sources(source_type,name,permission_basis,retrieved_at,geographic_precision) values('official','aggregate','public','2026-10-29','city')")
  db.execute("insert into official_stats(source_id,year,geography_id,geography_type,category,count) values(1,2024,'Delhi City','metropolitan','women',12)")
 status=main.route_safety_data_status()
 assert status["status"]=="insufficient_data" and status["aggregate_statistics"]==1
 assert status["risk_estimate"]=="not_supported" and status["route_matched_verified_incidents"]==0

def test_locality_report_context_matches_endpoint_names_only(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 result=main.route_locality_reports(main.RouteLocalityReportsIn(origin="CR Park, Delhi",destination="AIIMS Delhi"))
 assert result["status"]=="insufficient_data" and not result["items"]
 assert "not spatially matched" in result["notice"]

def test_news_candidate_api_returns_source_provenance_without_claiming_rates(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 result=main.news_candidates(locality=None,year=None,limit=100)
 assert result["returned"] == 0 and not result["items"]
 assert "not crime rates" in result["notice"]

def test_news_coverage_reports_actual_sample_and_no_data_semantics(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 result=main.news_coverage()
 assert result["target"]["from_year"] == datetime.now(timezone.utc).year-10
 assert result["target"]["to_year"] == datetime.now(timezone.utc).year-1
 assert result["coverage_assessment"] == "incomplete_sample"
 assert result["years_with_candidates"] == []
 assert all("not evidence of zero incidents" in item["meaning"] for item in result["year_by_year"])
 assert result["sources"] == []


def test_pedestrian_network_bbox_returns_geojson_and_limits_extent(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 import json
 with core.connect() as db:
  db.execute("insert into sources(source_type,name,reference,permission_basis,retrieved_at,geographic_precision) values('map','OSM','test','ODbL','2026-10-29','pilot')")
  db.execute("insert into pedestrian_networks(source_id,version_date,license,attribution,source_url) values(1,'2026-10-29','ODbL','OpenStreetMap contributors','test')")
  feature={"type":"Feature","properties":{"osm_way_id":"123"},"geometry":{"type":"LineString","coordinates":[[77.25,28.55],[77.251,28.551]]}}
  db.execute("insert into pedestrian_segments(id,network_id,osm_way_id,geometry_geojson,walkable_status) values(?,?,?,?,?)",("osm-way-123",1,"123",json.dumps(feature),"unverified"))
 result=main.pedestrian_network("77.24,28.54,77.26,28.56")
 assert result["returned"]==1 and result["features"][0]["properties"]["osm_way_id"]=="123"
 try: main.pedestrian_network("77.0,28.0,77.2,28.2")
 except Exception as exc: assert "0.1 degree" in str(exc)
 else: raise AssertionError("large map bbox should be rejected")

def test_walking_route_uses_openrouteservice_and_has_no_car_fallback(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setenv("OPENROUTESERVICE_API_KEY","test-key")
 monkeypatch.setattr(main,"geocode_location",lambda query:{"query":query,"display_name":query,"latitude":28.55 if query=="Origin" else 28.551,"longitude":77.25 if query=="Origin" else 77.251,"provider":"test"})
 route={"id":"ors-foot-walking-1","distance_m":160,"duration_s":135,"geometry":{"type":"LineString","coordinates":[[77.25,28.55],[77.251,28.551]]}}
 monkeypatch.setattr(OpenRouteServiceWalkingRouter,"routes",lambda self,origin,destination:[route])
 result=main.walking_route(RouteIn(origin="Origin",destination="Destination"))
 assert result["provider_status"]=="provider_configured" and result["mode"]=="walking"
 assert result["provider"]=="openrouteservice · foot-walking"
 assert result["alternatives"][0]["duration_s"]==135
 def no_walk_route(self,origin,destination): raise RuntimeError("OpenRouteService returned no usable foot-walking route")
 monkeypatch.setattr(OpenRouteServiceWalkingRouter,"routes",no_walk_route)
 unavailable=main.walking_route(RouteIn(origin="Origin",destination="Destination"))
 assert unavailable["provider_status"]=="unavailable" and not unavailable["alternatives"]
 assert "OpenRouteService" in unavailable["error"]

def test_walking_route_uses_selected_coordinates_without_regeocoding(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 def should_not_geocode(query): raise AssertionError("selected places should be routed using their coordinates")
 monkeypatch.setattr(main,"geocode_location",should_not_geocode)
 seen={}
 def routes(self,origin,destination):
  seen["coordinates"]=(origin,destination)
  return [{"id":"ors-foot-walking-1","distance_m":160,"duration_s":135,"geometry":{"type":"LineString","coordinates":[[77.25,28.55],[77.251,28.551]]}}]
 monkeypatch.setattr(OpenRouteServiceWalkingRouter,"routes",routes)
 result=main.walking_route(RouteIn(
  origin="Origin Place",destination="Destination Place",
  origin_location={"query":"Origin","display_name":"Origin Place","latitude":28.55,"longitude":77.25,"provider":"Nominatim"},
  destination_location={"query":"Destination","display_name":"Destination Place","latitude":28.551,"longitude":77.251,"provider":"Nominatim"},
 ))
 assert seen["coordinates"]==("77.25,28.55","77.251,28.551")
 assert result["provider_status"]=="provider_configured" and result["alternatives"]

def test_openrouteservice_walking_request_is_backend_only_and_parses_geojson(monkeypatch):
 import json
 from urllib.request import Request
 seen={}
 payload={"type":"FeatureCollection","features":[{"type":"Feature","properties":{"summary":{"distance":1200,"duration":900}},"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}}]}
 class Response:
  def __enter__(self): return self
  def __exit__(self,*args): return False
  def read(self): return json.dumps(payload).encode()
 def fake_urlopen(request,timeout):
  seen["request"]=request; seen["timeout"]=timeout
  return Response()
 monkeypatch.setattr("urllib.request.urlopen",fake_urlopen)
 routes=OpenRouteServiceWalkingRouter("server-secret").routes("77.2,28.6","77.21,28.61")
 assert routes[0]["distance_m"]==1200 and routes[0]["duration_s"]==900
 request=seen["request"]
 assert isinstance(request,Request) and request.full_url==OpenRouteServiceWalkingRouter.endpoint
 assert request.get_header("Authorization")=="server-secret"
 assert json.loads(request.data)["coordinates"]==[[77.2,28.6],[77.21,28.61]]

def test_openrouteservice_quota_error_is_actionable(monkeypatch):
 from urllib.error import HTTPError
 def rate_limited(*args,**kwargs): raise HTTPError("https://api.heigit.org/ors/v2/directions/foot-walking/geojson",429,"Too Many Requests",{},None)
 monkeypatch.setattr("urllib.request.urlopen",rate_limited)
 try: OpenRouteServiceWalkingRouter("server-secret").routes("77.2,28.6","77.21,28.61")
 except RuntimeError as exc: assert "rate limit" in str(exc).lower()
 else: raise AssertionError("a 429 response should be surfaced as a rate-limit error")

def test_geoapify_motorcycle_request_uses_documented_profile_and_parses_geojson(monkeypatch):
 import json
 from urllib.request import Request
 seen={}
 payload={"type":"FeatureCollection","features":[{"type":"Feature","properties":{"distance":1234,"time":321},"geometry":{"type":"MultiLineString","coordinates":[[[77.2,28.6],[77.201,28.601]],[[77.201,28.601],[77.21,28.61]]]}}]}
 class Response:
  def __enter__(self): return self
  def __exit__(self,*args): return False
  def read(self): return json.dumps(payload).encode()
 def fake_urlopen(request,timeout):
  seen["request"]=request; seen["timeout"]=timeout
  return Response()
 monkeypatch.setattr("urllib.request.urlopen",fake_urlopen)
 routes=GeoapifyMotorcycleRouter("server-secret").routes("77.2,28.6","77.21,28.61")
 request=seen["request"]
 url=request.full_url if isinstance(request,Request) else request
 assert url.startswith(GeoapifyMotorcycleRouter.endpoint+"?")
 from urllib.parse import parse_qs,urlparse
 params=parse_qs(urlparse(url).query)
 assert params["mode"]==["motorcycle"] and params["apiKey"]==["server-secret"]
 assert params["waypoints"]==["28.6,77.2|28.61,77.21"]
 assert routes[0]["distance_m"]==1234 and routes[0]["duration_s"]==321
 assert routes[0]["geometry"]["type"]=="LineString" and len(routes[0]["geometry"]["coordinates"])==3

def test_geoapify_motorcycle_provider_errors_are_actionable(monkeypatch):
 from urllib.error import HTTPError
 for status,message in ((401,"GEOAPIFY_API_KEY"),(403,"quota"),(429,"rate limit")):
  def fail(*args,_status=status,**kwargs): raise HTTPError(GeoapifyMotorcycleRouter.endpoint,_status,"provider error",{},None)
  monkeypatch.setattr("urllib.request.urlopen",fail)
  try: GeoapifyMotorcycleRouter("server-secret").routes("77.2,28.6","77.21,28.61")
  except RuntimeError as exc: assert message.lower() in str(exc).lower()
  else: raise AssertionError(f"HTTP {status} should be surfaced")

def test_motorcycle_without_geoapify_key_uses_labeled_osrm_fallback(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.delenv("GEOAPIFY_API_KEY",raising=False)
 seen={}
 route={"id":"osrm-1","distance_m":1500,"duration_s":240,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}}
 def fake_compare(origin,destination,router=None):
  seen["router"]=router
  return {"alternatives":[route.copy()],"provider_status":"provider_configured","provider":"OSRM","limitations":[]}
 monkeypatch.setattr(main,"compare",fake_compare)
 origin={"display_name":"Origin","latitude":28.6,"longitude":77.2,"provider":"test"}
 destination={"display_name":"Destination","latitude":28.61,"longitude":77.21,"provider":"test"}
 result=main.routes(RouteIn(origin="Origin",destination="Destination",mode="motorcycle",origin_location=origin,destination_location=destination))
 assert isinstance(seen["router"],OSRMRouter)
 assert result["provider_status"]=="provider_fallback"
 assert "not motorcycle-optimized" in result["limitations"][0]
 assert "OSRM car-profile estimate only" in result["alternatives"][0]["rank_reason"]

def test_configured_geoapify_motorcycle_provider_failure_does_not_substitute_car_route(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setenv("GEOAPIFY_API_KEY","configured-secret")
 monkeypatch.setattr(main,"geocode_location",lambda query:{"query":query,"display_name":query,"latitude":28.55 if query=="Origin" else 28.551,"longitude":77.25 if query=="Origin" else 77.251,"provider":"test"})
 monkeypatch.setattr(GeoapifyMotorcycleRouter,"routes",lambda self,origin,destination:(_ for _ in ()).throw(RuntimeError("Geoapify rate limit reached")))
 result=main.routes(RouteIn(origin="Origin",destination="Destination",mode="motorcycle"))
 assert result["provider_status"]=="unavailable" and not result["alternatives"]
 assert "rate limit" in result["error"]

def test_osm_pilot_seed_imports_network_and_is_idempotent(monkeypatch,tmp_path):
 from backend.scripts.import_osm_pilot_network import seed_pilot_network
 monkeypatch.setattr(core,"DB_PATH",tmp_path/"pilot.sqlite3")
 core.init_db()
 first=seed_pilot_network()
 second=seed_pilot_network()
 assert first["features_seen"]==1362 and first["features_imported"]==1362
 assert second["features_imported"]==0 and second["features_skipped"]==1362

def test_locality_resolution_states(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 with core.connect() as db:
  db.execute("insert into localities(id,name,aliases) values('a','Alpha','[\"Shared\"]')")
  db.execute("insert into localities(id,name,aliases) values('b','Beta','[\"Shared\"]')")
  assert resolve(db,"Shared")["status"]=="ambiguous"
  assert resolve(db,"Noida")["status"]=="outside_scope"
  assert resolve(db,"Nowhere")["status"]=="unresolved"

def test_duplicate_is_candidate_score_not_merge():
 score,features=dup_score({"excerpt":"same story","incident_date":"2024-01-01","category":"assault","locality_id":"loc-1"},{"excerpt":"same story","incident_date":"2024-01-01","category":"assault","locality_id":"loc-1"})
 assert score==1 and features["same_date"]

def test_redaction(): assert "9876543210" not in redact("call 9876543210")

def test_api_separates_source_types(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 src={"name":"Example","reference":"dataset-id:test","permission_basis":"user authorized","geographic_precision":"district"}
 official=ingest_official(OfficialIn(source=src,records=[{"year":2024,"geography_id":"Delhi","geography_type":"district","geography_scope":"delhi_nct","category":"x","count":4}]))
 assert official["accepted"]==1
 news=ingest_news(NewsIn(source={**src,"geographic_precision":"unknown"},records=[{"article_reference":"user-provided reference","permission_basis":"licensed excerpt","incident_date":"2024-01-01","excerpt":"report"}]))
 assert news["accepted"]==1
 trends=trends_endpoint(years=None,category=None)
 assert len(trends["official_statistics"])==1 and len(trends["news_reported_incidents"])==1
 assert trends["comparability_warning"]

def test_verified_precise_news_locations_are_geocoded_before_storage(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setenv("NAVIRA_EVIDENCE_REVIEW_TOKEN","private-review-secret")
 monkeypatch.setattr(main,"geocode_incident_location",lambda location:{"latitude":28.61,"longitude":77.22,"display_name":location,"provider":"Nominatim"})
 source={"name":"Newspaper","reference":"https://paper.example","permission_basis":"licensed public report","geographic_precision":"street"}
 result=ingest_news(NewsIn(source=source,records=[{"article_reference":"https://paper.example/story","publication_date":"2025-01-03","incident_date":"2025-01-02","category":"assault","locality_text":"Example Road, Delhi","location_precision":"street","review_status":"verified","excerpt":"Verified report"}]),"private-review-secret")
 assert result["geocoded_incidents"]==1
 with core.connect() as db:
  stored=db.execute("select latitude,longitude from news_incidents").fetchone()
 assert (stored["latitude"],stored["longitude"])==(28.61,77.22)

def test_untrusted_news_ingestion_cannot_claim_verification(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setenv("NAVIRA_EVIDENCE_REVIEW_TOKEN","private-review-secret")
 source={"name":"Newspaper","reference":"https://paper.example","permission_basis":"licensed public report","geographic_precision":"street"}
 body=NewsIn(source=source,records=[{"article_reference":"https://paper.example/story","incident_date":"2025-01-02","locality_text":"Example Road, Delhi","location_precision":"street","review_status":"verified"}])
 try:
  ingest_news(body,None)
 except main.HTTPException as error:
  assert error.status_code==403
 else:
  raise AssertionError("untrusted news ingestion must not assert verification")
 with core.connect() as db:
  assert db.execute("select count(*) from news_incidents").fetchone()[0]==0

def test_route_provider_failure():
 class Broken:
  def routes(self,o,d): raise RuntimeError("provider down")
 assert compare("a","b",Broken())["provider_status"]=="unavailable"

def test_route_recommendation_does_not_invent_safety_evidence():
 result=compare("77.2,28.6","77.3,28.7",MockRouter())
 assert result["recommendation"]["route_id"]=="synthetic-fast"
 assert result["alternatives"][0]["safety_evidence"]["risk_score"] is None
 assert result["alternatives"][0]["safety_evidence"]["status"]=="unavailable"
 assert "Fastest and shortest" in result["alternatives"][0]["rank_reason"]

def test_route_provider_defaults_to_real_osrm_instead_of_synthetic(monkeypatch):
 monkeypatch.delenv("NAVIRA_OSRM_BASE_URL",raising=False)
 monkeypatch.setattr(OSRMRouter,"routes",lambda self,origin,destination:[{"id":"road-1","distance_m":1200,"duration_s":240,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}}])
 result=compare("77.2,28.6","77.21,28.61")
 assert result["provider"]=="OSRM"
 assert result["provider_status"]=="provider_configured"
 assert result["alternatives"][0]["geometry"]["coordinates"][0]==[77.2,28.6]

def test_verified_geocoded_news_matches_only_nearby_route_and_never_mints_risk_score(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 with core.connect() as db:
  source=db.execute("insert into sources(source_type,name,reference,permission_basis,retrieved_at,geographic_precision) values('news','Verified paper','https://news.example','licensed','2026-01-01','street')").lastrowid
  db.execute("insert into news_incidents(source_id,article_reference,publication_date,incident_date,category,location_precision,review_status,fingerprint,latitude,longitude) values(?,?,?,?,?,?,?,?,?,?)",(source,"https://news.example/story","2025-01-03","2025-01-02","assault","street","verified","same-incident",28.6,77.205))
  db.execute("insert into news_incidents(source_id,article_reference,publication_date,incident_date,category,location_precision,review_status,fingerprint,latitude,longitude) values(?,?,?,?,?,?,?,?,?,?)",(source,"https://news.example/duplicate","2025-01-03","2025-01-02","assault","street","verified","same-incident",28.6,77.205))
  db.execute("insert into news_incidents(source_id,article_reference,publication_date,incident_date,category,location_precision,review_status,latitude,longitude) values(?,?,?,?,?,?,?,?,?)",(source,"https://news.example/unverified","2025-01-03","2025-01-02","assault","street","needs_review",28.6,77.205))
  routes=[{"id":"near","geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.6]]}},{"id":"far","geometry":{"type":"LineString","coordinates":[[77.3,28.7],[77.31,28.7]]}}]
  evidence=match_route_incidents(routes,db,now=__import__("datetime").date(2026,1,1))
 assert evidence["near"]["status"]=="matched_reports"
 assert evidence["near"]["matched_incidents"]==1
 assert evidence["near"]["reports"][0]["source_url"]=="https://news.example/story"
 assert evidence["near"]["risk_score"] is None
 assert evidence["far"]["status"]=="no_route_matches"
 assert evidence["far"]["matched_incidents"]==0
 assert evidence["far"]["eligible_records_in_window"]==1

def test_osrm_substantial_overlap_filter_keeps_only_distinct_road_geometries():
 first={"id":"osrm-1","geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61],[77.22,28.6]]}}
 overlapping={"id":"osrm-2","geometry":{"type":"LineString","coordinates":[[77.2,28.60005],[77.21,28.61005],[77.22,28.60005]]}}
 distinct={"id":"osrm-3","geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.62],[77.22,28.6]]}}
 result=distinct_route_alternatives([first,overlapping,distinct],2)
 assert [route["id"] for route in result]==["osrm-1","osrm-3"]
 assert result[1]["geometry"]==distinct["geometry"]

def test_route_comparison_preserves_a_single_genuine_route_and_explains_it():
 class SingleRoute:
  def routes(self,origin,destination):
   return [{"id":"only-road","distance_m":1000,"duration_s":240,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}}]
 result=compare("77.2,28.6","77.21,28.61",SingleRoute())
 assert [route["id"] for route in result["alternatives"]]==["only-road"]
 assert any("only one distinct road route" in note for note in result["limitations"])
 assert result["recommendation"]["route_id"]=="only-road"

def test_route_comparison_respects_one_route_configuration(monkeypatch):
 monkeypatch.setenv("NAVIRA_MAX_ROUTE_ALTERNATIVES","1")
 result=compare("77.2,28.6","77.21,28.61",MockRouter())
 assert result["maximum_alternatives"]==1
 assert len(result["alternatives"])==1
 assert any("maximum of one route" in note for note in result["limitations"])

def test_missing_geocoded_news_is_not_reported_as_zero(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 with core.connect() as db:
  result=match_route_incidents([{"id":"route","geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.3,28.7]]}}],db)
 assert result["route"]["matched_incidents"] is None
 assert "Missing" not in result["route"]["reason"]
 assert "No review-verified" in result["route"]["reason"]

def test_route_endpoint_includes_historical_source_and_missing_route_evidence(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setattr(main,"geocode_location",lambda query:{"query":query,"display_name":query,"latitude":28.6,"longitude":77.2,"provider":"test"})
 monkeypatch.setattr(main,"compare",lambda origin,destination,**_:{"alternatives":[],"recommendation":None,"provider_status":"unavailable","limitations":[]})
 result=route_endpoint(RouteIn(origin="Origin",destination="Destination"))
 historical=result["evidence_context"]["historical_official_statistics"]
 assert historical["years"]==[2020,2021,2022,2023,2024]
 assert historical["records"][0]=={"year":2020,"count":9782,"category":"crime_against_women_total","geography":"Delhi City"}
 assert historical["source"] and historical["retrieved_at"]
 assert result["evidence_context"]["route_specific_news"]["status"]=="insufficient_route_level_evidence"

def test_route_endpoint_attaches_independent_evidence_and_withholds_safety_percentages(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setattr(main,"geocode_location",lambda query:{"query":query,"display_name":query,"latitude":28.6,"longitude":77.2,"provider":"test"})
 routes=[
  {"id":"near-news","distance_m":1200,"duration_s":300,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.6]]}},
  {"id":"no-match","distance_m":1500,"duration_s":400,"geometry":{"type":"LineString","coordinates":[[77.3,28.7],[77.31,28.7]]}},
 ]
 monkeypatch.setattr(main,"compare",lambda origin,destination,**_:{"alternatives":routes,"recommendation":{"route_id":"near-news"},"provider":"OSRM","provider_status":"provider_configured","limitations":[]})
 with core.connect() as db:
  source=db.execute("insert into sources(source_type,name,reference,permission_basis,retrieved_at,geographic_precision) values('news','Verified paper','https://news.example','licensed','2026-10-01','street')").lastrowid
  db.execute("insert into news_incidents(source_id,article_reference,publication_date,incident_date,category,location_precision,review_status,fingerprint,latitude,longitude) values(?,?,?,?,?,?,?,?,?,?)",(source,"https://news.example/story","2026-10-02","2026-10-01","assault","street","verified","unique-story",28.6,77.205))
 result=route_endpoint(RouteIn(origin="Origin",destination="Destination"))
 near,far=result["alternatives"]
 assert near["id"]=="near-news" and near["geometry"]==routes[0]["geometry"]
 assert near["safety_evidence"]["matched_incidents"]==1
 assert far["safety_evidence"]["status"]=="no_route_matches"
 assert far["safety_evidence"]["matched_incidents"]==0
 assert near["safety_assessment"] is not far["safety_assessment"]
 assert near["safety_assessment"]["estimated_safety_percentage"] is None
 assert far["safety_assessment"]["label"]=="Insufficient evidence"
 assert near["infrastructure_evidence"]["status"]=="unavailable"
 assert far["safety_assessment"]["coverage"]["historical_official_statistics"]["status"]=="aggregate_only"

def test_route_safety_assessment_does_not_assign_weights_or_normalize_incomplete_data():
 assessment=assess_route_safety({"status":"no_route_matches","matched_incidents":0,"eligible_records_in_window":2})
 assert assessment["estimated_safety_percentage"] is None
 assert assessment["method"]["weights"] is None
 assert assessment["method"]["normalization"].startswith("Not applied")
 assert "not evidence that it is safe" in assessment["summary"]

def test_account_session_cookie_and_private_persistent_records(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 monkeypatch.setattr(main,"seed_delhi_city_dataset",lambda:0)
 monkeypatch.setattr(main,"seed_pilot_network",lambda:{})
 with TestClient(app) as client:
  registered=client.post("/api/auth/register",json={"email":"owner@example.com","password":"strong-password","name":"Account Owner"})
  assert registered.status_code==201
  assert "access_token" not in registered.json()
  assert "HttpOnly" in registered.headers["set-cookie"]
  assert "SameSite=lax" in registered.headers["set-cookie"]
  session_cookie=client.cookies.get("navira_session")
  assert session_cookie
  with core.connect() as db:
   password_hash=db.execute("select password_hash from users where email=?",
                            ("owner@example.com",)).fetchone()["password_hash"]
  assert password_hash!="strong-password" and "strong-password" not in password_hash
  assert client.get("/api/auth/session").json()["name"]=="Account Owner"
  contact=client.post("/api/contacts",json={"name":"Trusted Person","phone":"+91 98765 43210"})
  assert contact.status_code==201
  assert client.post("/api/contacts",json={"name":"Duplicate Person","phone":"+919876543210"}).status_code==409
  second_contact=client.post("/api/contacts",json={"name":"Another Person","phone":"+919876543211"})
  assert second_contact.status_code==201
  assert client.put(f"/api/contacts/{second_contact.json()['id']}",json={"name":"Another Person","phone":"+919876543210"}).status_code==409
  assert client.delete(f"/api/contacts/{second_contact.json()['id']}").status_code==204
  assert client.post("/api/contacts",json={"name":"Bad Number","phone":"not a phone"}).status_code==422
  route={"id":"osrm-test","distance_m":4200,"duration_s":900,"geometry":{"coordinates":[[77.2,28.6],[77.3,28.7]]}}
  planned=client.post("/api/journeys/plan",json={"origin":"Origin","destination":"Destination","route_id":"osrm-test","route":route})
  assert planned.status_code==201
  journey_id=planned.json()["id"]
  assert client.post(f"/api/journeys/{journey_id}/start").status_code==200
  replacement=client.post("/api/journeys/plan",json={"origin":"New origin","destination":"New destination","route_id":"another-route","route":route})
  assert replacement.status_code==409
  assert client.get("/api/journeys/active").json()["id"]==journey_id
  completed=client.post(f"/api/journeys/{journey_id}/complete")
  assert completed.status_code==200 and completed.json()["completed_at"]
  assert len(client.get("/api/journeys/history").json())==1
  assert client.post("/api/auth/logout").status_code==204
  assert client.get("/api/profile").status_code==401

  signed_in=client.post("/api/auth/login",json={"email":"owner@example.com","password":"strong-password"})
  assert signed_in.status_code==200
  assert len(client.get("/api/contacts").json())==1
  assert len(client.get("/api/journeys/history").json())==1
  owner_cookie=client.cookies.get("navira_session")
  with core.connect() as db:
   db.execute("update auth_sessions set expires_at='2000-01-01T00:00:00+00:00' where token_hash=?",
              (hashlib.sha256(owner_cookie.encode()).hexdigest(),))
  assert client.get("/api/auth/session").status_code==401

  other=client.post("/api/auth/register",json={"email":"other@example.com","password":"another-password","name":"Other User"})
  assert other.status_code==201
  assert client.get("/api/contacts").json()==[]
  assert client.get("/api/journeys/history").json()==[]

def test_account_duplicate_email_prompts_sign_in_and_session_survives_client_restart(monkeypatch,tmp_path):
 test_data=Path.cwd()/"work-temp"
 test_data.mkdir(exist_ok=True)
 database=test_data/("auth-"+uuid.uuid4().hex+".sqlite3")
 monkeypatch.setattr(core,"DB_PATH",database)
 core.init_db()
 request=Request({"type":"http","method":"POST","scheme":"https","path":"/api/auth/register","headers":[],"client":("127.0.0.1",1234),"server":("navira.test",443)})
 body=main.AccountIn(email="Owner@Example.com",password="strong-password",name="Account Owner")
 response=Response()
 registered=main.register(body,response,request)
 assert registered=={"user":{"id":1,"email":"owner@example.com","name":"Account Owner"}}
 cookie_header=dict(response.raw_headers)[b"set-cookie"].decode()
 cookie=SimpleCookie(cookie_header)["navira_session"].value
 with core.connect() as db:
  password_hash=db.execute("select password_hash from users where email=?",("owner@example.com",)).fetchone()["password_hash"]
 assert password_hash!="strong-password" and "strong-password" not in password_hash

 try:
  main.register(main.AccountIn(email=" owner@example.com ",password="another-password",name="Duplicate"),Response(),request)
  assert False,"duplicate email registration should fail"
 except HTTPException as error:
  assert error.status_code==409 and "Please sign in instead" in error.detail

 # A fresh database lookup with the browser's still-valid cookie models
 # reopening NAVIRA: the persistent session hash resolves the same profile.
 user=main._current_user(None,cookie)
 assert main.get_profile(user)=={"id":1,"email":"owner@example.com","name":"Account Owner"}
 signed_in=main.login(main.AccountIn(email="owner@example.com",password="strong-password"),Response(),request)
 assert signed_in==registered

def test_community_redacts_phone(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 response=add_hazard(HazardIn(category="lighting",description="Call 9876543210",approximate_geography="unspecified"))
 assert "9876543210" not in response["description"]
 assert response["status"]=="unverified"


def test_official_scope_is_explicit():
 row={"year":2024,"geography_id":"Delhi","geography_type":"district","category":"x","count":1}
 assert any("geography_scope" in e for e in validate_official(row))
 row["geography_scope"]="delhi_nct"
 assert validate_official(row)==[]

def test_classifier_skips_without_human_labels():
 assert train([],persist=False)["status"]=="skipped"

def test_osrm_refuses_vague_places():
 try:
  OSRMRouter("https://example.invalid").routes("Delhi","Noida")
 except ValueError as error:
  assert "longitude,latitude" in str(error)
 else:
  raise AssertionError("vague place names must not be geocoded by guess")

def test_osrm_router_returns_actual_provider_geometry(monkeypatch):
 import json
 from contextlib import contextmanager
 import urllib.request
 requested=[]
 @contextmanager
 def response(_url,timeout):
  requested.append((_url,timeout))
  class Payload:
   def read(self):
    return json.dumps({"code":"Ok","routes":[{"distance":1250,"duration":260,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}}]}).encode()
  yield Payload()
 monkeypatch.setattr(urllib.request,"urlopen",response)
 routes=OSRMRouter("https://routing.example").routes("77.2,28.6","77.21,28.61")
 assert len(routes)==1
 assert routes[0]["distance_m"]==1250 and routes[0]["duration_s"]==260
 assert routes[0]["geometry"]["coordinates"]==[[77.2,28.6],[77.21,28.61]]
 assert "/route/v1/driving/77.2,28.6;77.21,28.61" in requested[0][0]
 assert "alternatives=2" in requested[0][0]

def test_osrm_router_keeps_distinct_provider_alternatives_and_discards_invalid_or_duplicate_routes(monkeypatch):
 import json
 from contextlib import contextmanager
 import urllib.request
 requested=[]
 coordinates=lambda offset:[[77.2,28.6],[77.2+offset,28.61]]
 payload={"code":"Ok","routes":[
  {"distance":1000,"duration":300,"geometry":{"type":"LineString","coordinates":coordinates(.01)}},
  {"distance":1200,"duration":360,"geometry":{"type":"LineString","coordinates":coordinates(.02)}},
  {"distance":1300,"duration":390,"geometry":{"type":"LineString","coordinates":coordinates(.03)}},
  {"distance":1100,"duration":330,"geometry":{"type":"LineString","coordinates":coordinates(.01)}},
  {"distance":900,"duration":240,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[999,28.61]]}},
 ]}
 @contextmanager
 def response(url,timeout):
  requested.append((url,timeout))
  class Payload:
   def read(self): return json.dumps(payload).encode()
  yield Payload()
 monkeypatch.setattr(urllib.request,"urlopen",response)
 routes=OSRMRouter("https://routing.example").routes("77.2,28.6","77.3,28.7")
 assert len(routes)==3
 assert [route["id"] for route in routes]==["osrm-1","osrm-2","osrm-3"]
 assert [route["distance_m"] for route in routes]==[1000,1200,1300]
 assert "alternatives=2" in requested[0][0]

def test_osrm_router_uses_configured_alternative_limit(monkeypatch):
 import json
 from contextlib import contextmanager
 import urllib.request
 monkeypatch.setenv("NAVIRA_MAX_ROUTE_ALTERNATIVES","2")
 requested=[]
 payload={"code":"Ok","routes":[
  {"distance":1000,"duration":300,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}},
  {"distance":1200,"duration":360,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.22,28.62]]}},
  {"distance":1300,"duration":390,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.23,28.63]]}},
 ]}
 @contextmanager
 def response(url,timeout):
  requested.append((url,timeout))
  class Payload:
   def read(self): return json.dumps(payload).encode()
  yield Payload()
 monkeypatch.setattr(urllib.request,"urlopen",response)
 routes=OSRMRouter("https://routing.example").routes("77.2,28.6","77.3,28.7")
 assert len(routes)==2
 assert "alternatives=1" in requested[0][0]

def test_osrm_router_disables_alternative_search_when_limit_is_one(monkeypatch):
 import json
 from contextlib import contextmanager
 import urllib.request
 monkeypatch.setenv("NAVIRA_MAX_ROUTE_ALTERNATIVES","1")
 requested=[]
 @contextmanager
 def response(url,timeout):
  requested.append((url,timeout))
  class Payload:
   def read(self): return json.dumps({"code":"Ok","routes":[{"distance":1000,"duration":300,"geometry":{"type":"LineString","coordinates":[[77.2,28.6],[77.21,28.61]]}}]}).encode()
  yield Payload()
 monkeypatch.setattr(urllib.request,"urlopen",response)
 routes=OSRMRouter("https://routing.example").routes("77.2,28.6","77.3,28.7")
 assert len(routes)==1
 assert "alternatives=false" in requested[0][0]

def test_overpass_nearby_facilities_use_real_tags_addresses_and_area_centers():
 requests=[]
 payload={"elements":[
  {"type":"node","id":11,"lat":28.61,"lon":77.21,"tags":{"amenity":"police","name":"Central Police Station","addr:street":"Main Road","addr:city":"Delhi"}},
  {"type":"way","id":12,"center":{"lat":28.62,"lon":77.22},"tags":{"amenity":"hospital","name":"District Hospital"}},
  {"type":"node","id":13,"lat":28.63,"lon":77.23,"tags":{"healthcare":"hospital"}},
 ]}
 provider=OverpassPlaces(fetcher=lambda url,data:requests.append((url,data)) or payload)
 places=provider.search(28.6,77.2,"all",5000,30)
 assert len(places)==3
 assert places[0]["name"]=="Central Police Station"
 assert places[0]["address"]=="Main Road, Delhi"
 assert places[1]["location_source"]=="OSM mapped area center"
 assert places[2]["name"]==""
 assert places[0]["operating_status"]=="unverified"
 assert b'around%3A5000%2C28.6%2C77.2' in requests[0][1]

def test_osrm_table_uses_selected_origin_and_destination_coordinates(monkeypatch):
 import urllib.request
 requested=[]
 class Response:
  def __enter__(self): return self
  def __exit__(self,*args): return False
  def read(self): return b'{"code":"Ok","distances":[[1200]],"durations":[[240]]}'
 monkeypatch.setattr(urllib.request,"urlopen",lambda url,timeout:requested.append((url,timeout)) or Response())
 result=OSRMRouter("https://routing.example").table("77.2,28.6",["77.21,28.61"])
 assert result["distances"]==[[1200]]
 assert "/table/v1/driving/77.2,28.6;77.21,28.61" in requested[0][0]
 assert "destinations=1&annotations=distance,duration" in requested[0][0]

def test_nearby_facilities_use_osrm_road_distance_and_report_unavailable_routes():
 class Places:
  def search(self,*args):
   return [
    {"id":"near","name":"Near","kind":"hospital","latitude":28.61,"longitude":77.2,"address":None,"location_source":"OSM mapped node","operating_status":"unverified","source_url":"https://www.openstreetmap.org/node/1","tags":{}},
    {"id":"far","name":"Far","kind":"police","latitude":28.63,"longitude":77.2,"address":None,"location_source":"OSM mapped node","operating_status":"unverified","source_url":"https://www.openstreetmap.org/node/2","tags":{}},
   ]
 class Router:
  def table(self,origin,destinations):
   assert origin=="77.2,28.6"
   return {"distances":[[2400,None]],"durations":[[480,None]]}
 result=nearby_facilities(28.6,77.2,"all",5000,30,places=Places(),router=Router())
 assert result["routing_status"]=="available"
 assert [item["id"] for item in result["items"]]==["near","far"]
 assert result["items"][0]["road_distance_m"]==2400
 assert result["items"][0]["road_duration_s"]==480
 assert result["items"][1]["road_distance_m"] is None
 assert result["items"][1]["route_status"]=="unavailable"
 assert "straight-line" in result["routing_note"]

def test_nearby_facilities_endpoint_uses_given_location_and_returns_provider_result(monkeypatch,tmp_path):
 setup_db(monkeypatch,tmp_path)
 expected={"items":[],"provider":"OpenStreetMap Overpass","routing_provider":"OSRM","routing_status":"unavailable"}
 monkeypatch.setattr(main,"nearby_facilities",lambda *args:expected)
 with TestClient(app) as client:
  response=client.get("/api/v1/facilities/nearby?latitude=28.6&longitude=77.2&category=hospitals")
 assert response.status_code==200
 assert response.json()==expected

def test_overpass_provider_errors_are_explicit():
 def fail(_url,_data):
  raise FacilitiesUnavailable("Overpass service down")
 try:
  OverpassPlaces(fetcher=fail).search(28.6,77.2,"police",5000,30)
 except FacilitiesUnavailable as error:
  assert "Overpass" in str(error)
 else:
  raise AssertionError("Overpass provider errors must not be hidden")


def test_weather_adapter_parses_and_timestamps():
 payload={"current":{"time":"2026-10-27T00:00","temperature_2m":20}}
 adapter=OpenMeteoAdapter(fetcher=lambda url:payload)
 result=adapter.current(28.6,77.2)
 assert result["status"] in {"available","stale"}
 assert result["provider"]=="Open-Meteo"
