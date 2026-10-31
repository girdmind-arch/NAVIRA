"""FastAPI application for NAVIRA."""
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
import os
import base64,hashlib,hmac,json,logging,secrets
import math
from fastapi import Cookie,Depends,FastAPI,HTTPException,Query,Header,Request,Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from urllib.parse import urlparse
from pydantic import BaseModel,Field,field_validator
from typing import Literal
from backend.app.core import connect,init_db
from backend.app.services.ncrb_dataset import get_delhi_city_dataset,load_dataset,seed_delhi_city_dataset
from backend.app.services.agents import quality,validate_official,validate_news,redact,compare,emergency,trends,sanitize,match_route_incidents,assess_route_safety,GeoapifyMotorcycleRouter,OpenRouteServiceWalkingRouter,OSRMRouter
from backend.app.services.geocoding import GeocodingUnavailable,LocationNotFound,geocode_location,search_locations,geocode_incident_location
from backend.app.services.route_localities import resolve_route_localities
from backend.scripts.import_osm_pilot_network import seed_pilot_network
from backend.app.services.facilities import FacilitiesUnavailable,nearby_facilities
from backend.app.services.traffic import get_route_traffic
from backend.app.services.weather import get_route_weather
from backend.app.services.infrastructure import InfrastructureUnavailable,get_route_infrastructure
from backend.app.services.map_infrastructure import MapInfrastructureUnavailable,get_viewport_infrastructure
from backend.app.services.news_discovery import discover_locality_news
from backend.app.services.press_release_archive import discover_press_release_candidates
from backend.app.services.police_station_boundaries import match_route_police_stations
from backend.app.services.synthetic_demo import load_synthetic_route_demo
from backend.app.routers.ml import router as ml_router
from backend.app.routers.safety import router as safety_router
from backend.app.routers.journey_sos import router as journey_sos_router
logging.basicConfig(level=logging.INFO)
app=FastAPI(title="NAVIRA",version="0.1.0",description="Evidence-first Delhi NCT route comparison prototype. No route is guaranteed safe.")
app.include_router(ml_router)
app.include_router(safety_router)
app.include_router(journey_sos_router)
@app.on_event("startup")
def startup():
 init_db()
 seed_delhi_city_dataset()
 seed_pilot_network()
@app.get("/health")
def health(): return {"status":"ok","service":"navira"}

# Account-backed profiles, trusted contacts, and journey history.
class AccountIn(BaseModel):
 email:str=Field(min_length=3,max_length=254)
 password:str=Field(min_length=8,max_length=200)
 name:str=Field(default="NAVIRA user",min_length=1,max_length=100)
 @field_validator("email")
 @classmethod
 def normalize_email(cls,value):
  value=value.strip().lower()
  if "@" not in value or "." not in value.rsplit("@",1)[-1]: raise ValueError("Enter a valid email address")
  return value
 @field_validator("name")
 @classmethod
 def normalize_name(cls,value):
  name=" ".join(value.split())
  if not name: raise ValueError("Enter your name")
  return name
class ProfileIn(BaseModel): name:str=Field(min_length=1,max_length=100)
class ContactIn(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 phone:str=Field(min_length=3,max_length=32)
 relationship_label:str=Field(default="Trusted contact",max_length=60)
 @field_validator("name")
 @classmethod
 def valid_name(cls,value):
  name=" ".join(value.split())
  if not name: raise ValueError("Enter a contact name")
  return name
 @field_validator("phone")
 @classmethod
 def valid_phone(cls,value):
  import re
  phone=value.strip()
  if not re.fullmatch(r"\+?[0-9\s().-]{3,32}",phone) or sum(character.isdigit() for character in phone)<3:
   raise ValueError("Enter a valid phone number")
  return phone
class JourneyPlanIn(BaseModel):
 origin:str=Field(min_length=1,max_length=200)
 destination:str=Field(min_length=1,max_length=200)
 route_id:str=Field(min_length=1,max_length=200)
 route:dict

def _password_hash(password:str,salt:bytes|None=None)->str:
 salt=salt or secrets.token_bytes(16)
 digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,310000)
 return base64.urlsafe_b64encode(salt).decode()+"$"+base64.urlsafe_b64encode(digest).decode()

def _verify_password(password:str,stored:str)->bool:
 try:
  salt_text,digest_text=stored.split("$",1)
  salt=base64.urlsafe_b64decode(salt_text)
  expected=base64.urlsafe_b64decode(digest_text)
  actual=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,310000)
  return hmac.compare_digest(actual,expected)
 except (ValueError,TypeError): return False

def _session_token(authorization:str|None,cookie_token:str|None)->str|None:
 if cookie_token:
  return cookie_token
 if authorization and authorization.lower().startswith("bearer "):
  return authorization.split(None,1)[1].strip()
 return None

def _current_user(authorization:str|None,cookie_token:str|None=None):
 token=_session_token(authorization,cookie_token)
 if not token:
  raise HTTPException(401,"Please sign in to continue")
 token_hash=hashlib.sha256(token.encode()).hexdigest()
 with connect() as db:
  row=db.execute("select u.id,u.email from auth_sessions s join users u on u.id=s.user_id where s.token_hash=? and s.expires_at>?",(token_hash,datetime.now(timezone.utc).isoformat())).fetchone()
 if not row: raise HTTPException(401,"Your session has expired. Please sign in again")
 return row

def _current_account(
 authorization:str|None=Header(None),
 navira_session:str|None=Cookie(None),
):
 return _current_user(authorization,navira_session)

def _set_session_cookie(response:Response,token:str,request:Request):
 secure=request.url.scheme=="https" or request.headers.get("x-forwarded-proto","").split(",",1)[0].strip().lower()=="https"
 response.set_cookie(
  "navira_session",
  token,
  max_age=30*24*60*60,
  httponly=True,
  secure=secure,
  samesite="lax",
  path="/api",
 )

def _issue_session(user_id:int,email:str,name:str,response:Response,request:Request):
 now=datetime.now(timezone.utc)
 token=secrets.token_urlsafe(32)
 with connect() as db:
  db.execute("insert into auth_sessions(token_hash,user_id,expires_at) values(?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user_id,(now+timedelta(days=30)).isoformat()))
 _set_session_cookie(response,token,request)
 return {"user":{"id":user_id,"email":email,"name":name}}

@app.post("/api/auth/register",status_code=201)
def register(body:AccountIn,response:Response,request:Request):
 now=datetime.now(timezone.utc)
 try:
  with connect() as db:
   cur=db.execute("insert into users(email,name,password_hash,created_at) values(?,?,?,?)",(body.email,body.name.strip(),_password_hash(body.password),now.isoformat()))
   user_id=cur.lastrowid
 except Exception as exc:
  if "UNIQUE constraint failed" in str(exc): raise HTTPException(409,"An account with this email already exists. Please sign in instead.") from exc
  raise
 return _issue_session(user_id,body.email,body.name.strip(),response,request)

@app.post("/api/auth/login")
def login(body:AccountIn,response:Response,request:Request):
 with connect() as db: row=db.execute("select id,email,name,password_hash from users where email=?",(body.email,)).fetchone()
 if not row or not _verify_password(body.password,row["password_hash"]): raise HTTPException(401,"Email or password is incorrect")
 return _issue_session(row["id"],row["email"],row["name"],response,request)

@app.get("/api/auth/session")
def restore_session(
 request:Request,
 response:Response,
 authorization:str|None=Header(None),
 navira_session:str|None=Cookie(None),
):
 user=_current_user(authorization,navira_session)
 if not navira_session:
  token=_session_token(authorization,None)
  _set_session_cookie(response,token,request)
 with connect() as db: row=db.execute("select id,email,name from users where id=?",(user["id"],)).fetchone()
 return dict(row)

@app.post("/api/auth/logout",status_code=204)
def logout(
 response:Response,
 authorization:str|None=Header(None),
 navira_session:str|None=Cookie(None),
):
 token=_session_token(authorization,navira_session)
 if token:
  with connect() as db: db.execute("delete from auth_sessions where token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))
 response.delete_cookie("navira_session",path="/api",httponly=True,samesite="lax")

@app.get("/api/profile")
def get_profile(user=Depends(_current_account)):
 with connect() as db: row=db.execute("select id,email,name from users where id=?",(user["id"],)).fetchone()
 return dict(row)

@app.put("/api/profile")
def update_profile(body:ProfileIn,user=Depends(_current_account)):
 name=" ".join(body.name.split())
 if not name: raise HTTPException(422,"Enter your name")
 with connect() as db: db.execute("update users set name=? where id=?",(name,user["id"]))
 return {"id":user["id"],"email":user["email"],"name":name}

@app.get("/api/contacts")
def list_contacts(user=Depends(_current_account)):
 with connect() as db: return [dict(row) for row in db.execute("select id,name,phone,relationship_label from trusted_contacts where user_id=? order by id",(user["id"],))]

def _contact_phone_digits(phone):
 return "".join(character for character in phone if character in "0123456789")

def _contact_phone_exists(db,user_id,phone,exclude_contact_id=None):
 digits=_contact_phone_digits(phone)
 contacts=db.execute("select id,phone from trusted_contacts where user_id=?",(user_id,))
 return any(
  row["id"]!=exclude_contact_id and _contact_phone_digits(row["phone"])==digits
  for row in contacts
 )

@app.post("/api/contacts",status_code=201)
def create_contact(body:ContactIn,user=Depends(_current_account)):
 name=" ".join(body.name.split()); phone=body.phone.strip(); relation=" ".join(body.relationship_label.split()) or "Trusted contact"
 with connect() as db:
  if _contact_phone_exists(db,user["id"],phone):
   raise HTTPException(409,"This phone number is already saved as a trusted contact")
  cur=db.execute("insert into trusted_contacts(user_id,name,phone,relationship_label) values(?,?,?,?)",(user["id"],name,phone,relation))
 return {"id":cur.lastrowid,"name":name,"phone":phone,"relationship_label":relation}

@app.put("/api/contacts/{contact_id}")
def update_contact(contact_id:int,body:ContactIn,user=Depends(_current_account)):
 name=" ".join(body.name.split()); phone=body.phone.strip(); relation=" ".join(body.relationship_label.split()) or "Trusted contact"
 with connect() as db:
  if not db.execute("select 1 from trusted_contacts where user_id=? and id=?",(user["id"],contact_id)).fetchone():
   raise HTTPException(404,"Trusted contact not found")
  if _contact_phone_exists(db,user["id"],phone,contact_id):
   raise HTTPException(409,"This phone number is already saved as a trusted contact")
  cur=db.execute("update trusted_contacts set name=?,phone=?,relationship_label=? where id=? and user_id=?",(name,phone,relation,contact_id,user["id"]))
  if not cur.rowcount: raise HTTPException(404,"Trusted contact not found")
 return {"id":contact_id,"name":name,"phone":phone,"relationship_label":relation}

@app.delete("/api/contacts/{contact_id}",status_code=204)
def delete_contact(contact_id:int,user=Depends(_current_account)):
 with connect() as db:
  cur=db.execute("delete from trusted_contacts where id=? and user_id=?",(contact_id,user["id"]))
  if not cur.rowcount: raise HTTPException(404,"Trusted contact not found")

@app.post("/api/journeys/plan",status_code=201)
def plan_journey(body:JourneyPlanIn,user=Depends(_current_account)):
 now=datetime.now(timezone.utc).isoformat()
 with connect() as db:
  in_progress=db.execute("select id from journeys where user_id=? and status='in_progress' limit 1",(user["id"],)).fetchone()
  if in_progress: raise HTTPException(409,"Finish the in-progress journey before saving a different route.")
  db.execute("update journeys set status='superseded' where user_id=? and status='planned'",(user["id"],))
  cur=db.execute("insert into journeys(user_id,origin,destination,route_id,route_json,status,planned_at) values(?,?,?,?,?,'planned',?)",(user["id"],body.origin.strip(),body.destination.strip(),body.route_id,json.dumps(body.route),now))
  row=db.execute("select * from journeys where id=?",(cur.lastrowid,)).fetchone()
 return _journey_dict(row)

def _journey_dict(row):
 result=dict(row); result["route"]=json.loads(result.pop("route_json")); return result

@app.get("/api/journeys/active")
def active_journey(user=Depends(_current_account)):
 with connect() as db: row=db.execute("select * from journeys where user_id=? and status in ('planned','in_progress') order by id desc limit 1",(user["id"],)).fetchone()
 return {"active":False} if not row else {"active":True,**_journey_dict(row)}

@app.post("/api/journeys/{journey_id}/start")
def start_journey(journey_id:int,user=Depends(_current_account)):
 now=datetime.now(timezone.utc).isoformat()
 with connect() as db:
  existing=db.execute("select * from journeys where id=? and user_id=?",(journey_id,user["id"])).fetchone()
  if existing and existing["status"]=="in_progress": return _journey_dict(existing)
  cur=db.execute("update journeys set status='in_progress',started_at=? where id=? and user_id=? and status='planned'",(now,journey_id,user["id"]))
  if not cur.rowcount: raise HTTPException(404,"Planned journey not found")
  row=db.execute("select * from journeys where id=?",(journey_id,)).fetchone()
 return _journey_dict(row)

@app.post("/api/journeys/{journey_id}/complete")
def complete_journey(journey_id:int,user=Depends(_current_account)):
 now=datetime.now(timezone.utc).isoformat()
 with connect() as db:
  existing=db.execute("select * from journeys where id=? and user_id=?",(journey_id,user["id"])).fetchone()
  if existing and existing["status"]=="completed": return _journey_dict(existing)
  cur=db.execute("update journeys set status='completed',completed_at=? where id=? and user_id=? and status='in_progress'",(now,journey_id,user["id"]))
  if not cur.rowcount: raise HTTPException(404,"In-progress journey not found")
  row=db.execute("select * from journeys where id=?",(journey_id,)).fetchone()
 return _journey_dict(row)

@app.get("/api/journeys/history")
def journey_history(user=Depends(_current_account)):
 with connect() as db: rows=db.execute("select * from journeys where user_id=? and status='completed' order by completed_at desc limit 100",(user["id"],)).fetchall()
 return [_journey_dict(row) for row in rows]
@app.get("/api/v1/data-status")
def data_status():
 with connect() as db: return quality(db)
@app.get("/api/v1/datasets/ncrb/delhi-city/crimes-against-women")
def ncrb_delhi_city_women_crimes(start_year:int|None=Query(None,ge=1900),end_year:int|None=Query(None,ge=1900)):
 if start_year is not None and end_year is not None and start_year>end_year:
  raise HTTPException(422,detail="start_year must be less than or equal to end_year")
 return get_delhi_city_dataset(start_year,end_year)
@app.get("/api/v1/data-quality/report")
def quality_endpoint():
 with connect() as db:
  return {"coverage":quality(db),"issues":[dict(x) for x in db.execute("select * from quality_issues where resolved=0 limit 200")]}
class OfficialIn(BaseModel):
 source:dict
 records:list[dict]
 dry_run:bool=False
class NewsIn(BaseModel):
 source:dict
 records:list[dict]
 dry_run:bool=False
class GazetteerIn(BaseModel):
 source:dict
 records:list[dict]
 dry_run:bool=False
class RouteIn(BaseModel):
 origin:str=Field(min_length=1,max_length=200)
 destination:str=Field(min_length=1,max_length=200)
 mode:Literal["car","motorcycle"]="car"
 origin_location:dict|None=None
 destination_location:dict|None=None
 @field_validator("origin","destination")
 @classmethod
 def clean_location(cls,value):
  value=value.strip()
  if not value: raise ValueError("Enter a location name or address")
  return value
class RouteTrafficIn(BaseModel):
 coordinates:list[list[float]]=Field(min_length=2,max_length=20000)
 duration_s:float=Field(gt=0,le=172800)
 distance_m:float=Field(gt=0,le=10000000)
 @field_validator("coordinates")
 @classmethod
 def validate_route_coordinates(cls,value):
  for point in value:
   if len(point)!=2 or not all(math.isfinite(value) for value in point):
    raise ValueError("Route coordinates must contain finite longitude,latitude pairs")
   longitude,latitude=point
   if not -180<=longitude<=180 or not -90<=latitude<=90:
    raise ValueError("Route coordinates are outside valid geographic ranges")
  return value
class RouteWeatherIn(BaseModel):
 coordinates:list[list[float]]=Field(min_length=2,max_length=20000)
 @field_validator("coordinates")
 @classmethod
 def validate_route_coordinates(cls,value):
  for point in value:
   if len(point)!=2 or not all(math.isfinite(number) for number in point):
    raise ValueError("Route coordinates must contain finite longitude,latitude pairs")
   longitude,latitude=point
   if not -180<=longitude<=180 or not -90<=latitude<=90:
    raise ValueError("Route coordinates are outside valid geographic ranges")
  return value
class RouteInfrastructureIn(BaseModel):
 coordinates:list[list[float]]=Field(min_length=2,max_length=20000)
 corridor_m:int|None=Field(default=None,ge=25,le=500)
 @field_validator("coordinates")
 @classmethod
 def validate_route_coordinates(cls,value):
  for point in value:
   if len(point)!=2 or not all(math.isfinite(number) for number in point):
    raise ValueError("Route coordinates must contain finite longitude,latitude pairs")
   longitude,latitude=point
   if not -180<=longitude<=180 or not -90<=latitude<=90:
    raise ValueError("Route coordinates are outside valid geographic ranges")
  return value
class HazardIn(BaseModel):
 category:str=Field(min_length=1,max_length=80)
 description:str=Field(min_length=1,max_length=500)
 approximate_geography:str|None=Field(default=None,max_length=100)
 expires_days:int=Field(default=7,ge=1,le=30)
 @field_validator("approximate_geography")
 @classmethod
 def coarse_location_only(cls,value):
  import re
  if value and (re.search(r"-?\d{1,3}\.\d{3,}",value) or re.search(r"\b(?:street|road|lane|house|flat|plot|marg)\b",value,re.I)):
   raise ValueError("Use a coarse locality name, not coordinates or an exact address")
  return value
def source_id(db,source,typ):
 required=("name","reference","permission_basis","geographic_precision")
 missing=[x for x in required if not source.get(x)]
 if missing: raise HTTPException(422,detail={"missing_source_provenance":missing})
 cur=db.execute("insert into sources(source_type,name,reference,permission_basis,retrieved_at,version,geographic_precision,notes) values(?,?,?,?,?,?,?,?)",(typ,source["name"],source.get("reference"),source["permission_basis"],source.get("retrieved_at",datetime.now(timezone.utc).isoformat()),source.get("version"),source["geographic_precision"],source.get("notes")))
 return cur.lastrowid
@app.post("/api/v1/ingest/official")
def ingest_official(body:OfficialIn):
 errors=[]
 for i,r in enumerate(body.records):
  e=validate_official(r)
  geo=str(r.get("geography_id","")).casefold()
  outside={"noida","gurugram","gurgaon","faridabad","ghaziabad","sonipat","rohtak","rewari","alwar","bhiwadi"}
  if geo in outside: e.append("outside Delhi NCT")
  if r.get("geography_type")=="state" and geo not in {"delhi","delhi nct","national capital territory of delhi"}: e.append("outside Delhi NCT")
  if e: errors.append({"index":i,"errors":e})
 if errors: raise HTTPException(422,detail={"invalid_records":errors})
 if body.dry_run:return {"accepted":len(body.records),"dry_run":True}
 with connect() as db:
  sid=source_id(db,body.source,"official")
  for r in body.records: db.execute("insert into official_stats(source_id,year,geography_id,geography_type,category,count,notes) values(?,?,?,?,?,?,?)",(sid,r["year"],r["geography_id"],r["geography_type"],r["category"],r["count"],r.get("notes")))
 return {"accepted":len(body.records),"source_id":sid}
@app.post("/api/v1/ingest/news")
def ingest_news(body:NewsIn,x_navira_evidence_review_token:str|None=Header(None,alias="X-NAVIRA-EVIDENCE-REVIEW-TOKEN")):
 errors=[]
 for i,r in enumerate(body.records):
  e=validate_news(r)
  if e: errors.append({"index":i,"errors":e})
 if errors: raise HTTPException(422,detail={"invalid_records":errors})
 configured_review_token=os.getenv("NAVIRA_EVIDENCE_REVIEW_TOKEN","")
 requests_verified=any(r.get("review_status")=="verified" for r in body.records)
 can_verify=bool(configured_review_token and x_navira_evidence_review_token and hmac.compare_digest(configured_review_token,x_navira_evidence_review_token))
 if requests_verified and not can_verify:
  raise HTTPException(403,detail="Verified news ingestion requires the server-side evidence review credential.")
 if body.dry_run:return {"accepted":len(body.records),"dry_run":True}
 geocoded=0
 for r in body.records:
  if r.get("latitude") is None and r.get("longitude") is None and r.get("review_status")=="verified" and r.get("locality_text") and r.get("location_precision") in {"address","building","landmark","premise","street"}:
   try:
    place=geocode_incident_location(r["locality_text"])
    r["latitude"]=place["latitude"]; r["longitude"]=place["longitude"]; geocoded+=1
   except LocationNotFound:
    pass
   except GeocodingUnavailable as exc:
    raise HTTPException(503,detail="Verified incident locations could not be geocoded right now; retry the news ingestion.") from exc
 with connect() as db:
  sid=source_id(db,body.source,"news")
  for r in body.records:
   excerpt=redact(r.get("excerpt","")); fp=hashlib.sha256(excerpt.encode()).hexdigest()
   db.execute("insert into news_incidents(source_id,article_reference,publication_date,incident_date,category,locality_text,locality_id,location_precision,confidence,review_status,excerpt,fingerprint,latitude,longitude) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(sid,r["article_reference"],r.get("publication_date"),r.get("incident_date"),r.get("category"),r.get("locality_text"),r.get("locality_id"),r.get("location_precision","unknown"),r.get("confidence"),r.get("review_status","needs_review"),excerpt,fp,r.get("latitude"),r.get("longitude")))
 return {"accepted":len(body.records),"source_id":sid,"geocoded_incidents":geocoded,"notice":"Permitted user-provided references only; geocoding does not verify the report or imply crime incidence."}
@app.post("/api/v1/ingest/localities")
def ingest_localities(body:GazetteerIn):
 errors=[]
 for i,r in enumerate(body.records):
  if not r.get("id") or not r.get("name"): errors.append({"index":i,"error":"id and name required"})
  if r.get("scope_status","delhi_nct")!="delhi_nct": errors.append({"index":i,"error":"outside-scope locality rejected"})
 if errors: raise HTTPException(422,detail={"invalid_records":errors})
 if body.dry_run: return {"accepted":len(body.records),"dry_run":True}
 with connect() as db:
  sid=source_id(db,body.source,"gazetteer")
  for r in body.records: db.execute("insert or replace into localities(id,name,aliases,scope_status,source_id,boundary_ref) values(?,?,?,?,?,?)",(r["id"],r["name"],json.dumps(r.get("aliases",[])),"delhi_nct",sid,r.get("boundary_ref")))
 return {"accepted":len(body.records),"source_id":sid}
@app.get("/api/v1/localities")
def localities(limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0)):
 with connect() as db: return {"items":[dict(x) for x in db.execute("select id,name,aliases,scope_status,boundary_ref from localities where scope_status='delhi_nct' limit ? offset ?",(limit,offset))],"limit":limit,"offset":offset}
@app.get("/api/v1/localities/{locality_id}/summary")
def locality_summary(locality_id:str):
 with connect() as db:
  loc=db.execute("select id,name from localities where id=? and scope_status='delhi_nct'",(locality_id,)).fetchone()
  if not loc: raise HTTPException(404,"Locality not found")
  official=[dict(x) for x in db.execute("select year,geography_id,geography_type,category,count from official_stats where geography_id=?",(locality_id,))]
  news=[dict(x) for x in db.execute("select incident_date,publication_date,category,location_precision,review_status from news_incidents where locality_id=?",(locality_id,))]
  return {"locality":dict(loc),"official_statistics":official,"news_reported_records":news,"note":"District-level statistics are not mapped to a locality; article records are not incidence."}
@app.get("/api/v1/routes/safety-data-status")
def route_safety_data_status():
 with connect() as db:
  aggregates=db.execute("select count(*) as n from official_stats").fetchone()["n"]
  reviewed=db.execute("select count(*) as n from incident_events where event_status in ('verified','FIR','charge_sheet','court_outcome')").fetchone()["n"]
  geolocated=db.execute("select count(*) as n from place_observations where latitude is not null and longitude is not null and review_status='verified'").fetchone()["n"]
  matches=db.execute("select count(*) as n from incident_segment_matches where review_decision='accepted'").fetchone()["n"]
  networks=db.execute("select count(*) as n from pedestrian_networks").fetchone()["n"]
  audited=db.execute("select count(*) as n from street_context_observations").fetchone()["n"]
 return {"status":"available" if matches else "insufficient_data","route_matched_verified_incidents":matches,"verified_incidents":reviewed,"verified_geolocated_places":geolocated,"pedestrian_networks":networks,"street_audit_observations":audited,"aggregate_statistics":aggregates,"risk_estimate":"not_supported","message":"No verified incident-to-pedestrian-segment matches are available. City-level NCRB aggregates and unresolved/locality-only reports are not assigned to route segments." if not matches else "Evidence counts are incomplete indicators, not safety guarantees."}

@app.get("/api/v1/demo/synthetic-data")
def synthetic_route_demo_data():
 """Serve the isolated synthetic demo fixture; never import it into evidence tables."""
 try:
  return load_synthetic_route_demo()
 except (OSError,ValueError,json.JSONDecodeError) as exc:
  logging.exception("Synthetic route demo fixture could not be loaded")
  raise HTTPException(503,detail="Synthetic demo data is temporarily unavailable.") from exc

@app.get("/api/v1/news/candidates")
def news_candidates(locality:str|None=Query(None,max_length=120),year:int|None=Query(None,ge=1900,le=2100),limit:int=Query(100,ge=1,le=250)):
 """Source-linked reported candidates; this endpoint is not a crime-rate feed."""
 with connect() as db:
  rows=db.execute("""select e.id,e.event_date_start,e.event_date_end,e.date_precision,e.incident_type_raw,
   e.incident_type_normalized,e.event_status,e.summary_neutral,s.canonical_url,s.headline,s.published_at,
   src.name as publisher,p.locality,p.landmark,p.location_confidence,p.review_status
   from incident_events e join incident_sources s on s.incident_id=e.id
   join sources src on src.id=s.source_id left join place_observations p on p.incident_id=e.id
   order by coalesce(e.event_date_start,s.published_at) desc limit ?""",(limit*4,)).fetchall()
 items=[]
 for row in rows:
  item=dict(row)
  item["publisher"]=urlparse(item.get("canonical_url") or "").hostname or item.get("publisher")
  if year is not None and str(item.get("event_date_start") or "")[:4]!=str(year): continue
  if locality and locality.casefold() not in " ".join((item.get("locality") or "",item.get("landmark") or "")).casefold(): continue
  item["location_precision"]="locality" if item.get("locality") else "unknown"
  item["review_status"]=item.get("review_status") or "needs_review"
  items.append(item)
  if len(items)>=limit: break
 return {"items":items,"returned":len(items),"status":"candidates_available" if items else "no_candidates","notice":"News-reported incident candidates only. Sources are selective; a place-name match is not a route or incident-point match. Counts are not crime rates, and an empty result does not mean zero crime."}

@app.get("/api/v1/news/coverage")
def news_coverage():
 """Expose the ten-year target and the coverage actually present in this database."""
 current_year=datetime.now(timezone.utc).year
 start_year=current_year-10; end_year=current_year-1
 requested=list(range(start_year,end_year+1))
 with connect() as db:
  counts={row["year"]:row["n"] for row in db.execute("select cast(substr(event_date_start,1,4) as integer) year,count(distinct id) n from incident_events where event_date_start is not null group by year")}
  sources=[dict(row) for row in db.execute("""select s.id,s.name,s.reference,s.geographic_precision,c.requested_years,c.processed_years,c.missing_years,c.gap_reasons,c.checkpoint,c.last_checked_at,c.record_count,c.coverage_note,
    (select min(e.event_date_start) from incident_events e join incident_sources x on x.incident_id=e.id where x.source_id=s.id) as earliest_incident_date,
    (select max(e.event_date_start) from incident_events e join incident_sources x on x.incident_id=e.id where x.source_id=s.id) as latest_incident_date,
    (select min(x.published_at) from incident_sources x where x.source_id=s.id) as earliest_publication_date,
    (select max(x.published_at) from incident_sources x where x.source_id=s.id) as latest_publication_date,
    (select count(distinct x.incident_id) from incident_sources x where x.source_id=s.id) as observed_candidate_count
    from sources s left join news_source_coverage c on c.source_id=s.id where s.source_type='news' order by s.id""")]
  for source in sources:
   source["coverage_completeness_status"]="declared" if json.loads(source.get("requested_years") or "[]") else "not_assessed"
   source["requested_years"]=json.loads(source["requested_years"] or "[]")
   source["processed_years"]=json.loads(source["processed_years"] or "[]")
   source["missing_years"]=json.loads(source["missing_years"] or "[]")
   source["gap_reasons"]=json.loads(source["gap_reasons"] or "{}")
   with connect() as source_db:
    source["incident_years_with_candidates"]=[r[0] for r in source_db.execute("select distinct cast(substr(e.event_date_start,1,4) as integer) from incident_events e join incident_sources x on x.incident_id=e.id where x.source_id=? and e.event_date_start is not null order by 1",(source["id"],))]
 years=[{"year":year,"candidate_count":counts.get(year,0),"status":"records_present" if counts.get(year,0) else "no_candidates_in_loaded_data","meaning":"No candidates in the loaded sources is not evidence of zero incidents."} for year in requested]
 present=[year for year in requested if counts.get(year,0)]
 return {"target":{"from_year":start_year,"to_year":end_year,"years":requested},"coverage_assessment":"incomplete_sample","observed_incident_date_range":{"earliest":min((s["earliest_incident_date"] for s in sources if s.get("earliest_incident_date")),default=None),"latest":max((s["latest_incident_date"] for s in sources if s.get("latest_incident_date")),default=None)},"years_with_candidates":present,"year_by_year":years,"sources":sources,"limitations":["No ten-year historical news archive has been verified or imported.","Delhi Police press releases and news reports are selective, not a complete FIR or crime register.","The bundled locality news pilot was removed; any remaining candidate records were imported separately and do not establish crime rates."],"last_checked_at":max((s["last_checked_at"] for s in sources if s.get("last_checked_at")),default=None)}

class NewsDiscoveryIn(BaseModel):
 localities:list[str]=Field(min_length=1,max_length=2)
 @field_validator("localities")
 @classmethod
 def clean_localities(cls,values):
  cleaned=[" ".join(value.split()) for value in values]
  if any(len(value)<2 or len(value)>120 for value in cleaned): raise ValueError("Each locality must be between 2 and 120 characters")
  return list(dict.fromkeys(cleaned))

@app.post("/api/v1/news/discover")
def discover_news(body:NewsDiscoveryIn):
 """Search a recent article index for place mentions; results are review candidates."""
 try:
  groups=[discover_locality_news(locality) for locality in body.localities]
 except ValueError as exc:
  raise HTTPException(422,detail=str(exc)) from exc
 return {"provider":"GDELT DOC 2.0","search_window":"recent 3 months","groups":groups,"notice":"Recent indexed articles are grouped by the locality search term. A match does not prove an incident occurred there; missing results do not mean zero crime."}

class RouteLocalityNewsIn(BaseModel):
 geometry:dict

@app.post("/api/v1/routes/locality-news")
def route_locality_news(body:RouteLocalityNewsIn):
 """Search recent article candidates for sampled Delhi localities on a road route."""
 if body.geometry.get("type")!="LineString" or not isinstance(body.geometry.get("coordinates"),list) or len(body.geometry["coordinates"])<2 or len(body.geometry["coordinates"])>10000:
  raise HTTPException(422,detail="A valid road-route LineString is required.")
 locality_context=resolve_route_localities(body.geometry)
 localities=[item["name"] for item in locality_context["route_localities"] if 2<=len(item["name"])<=120][:6]
 police_station_context=match_route_police_stations(body.geometry)
 with ThreadPoolExecutor(max_workers=3) as executor:
  groups=list(executor.map(discover_locality_news,localities))
 press_release_evidence=discover_press_release_candidates(police_stations=police_station_context.get("stations",[]))
 dataset=load_dataset()
 return {
  "status":"available" if localities else locality_context["status"],
  "route_locality_context":locality_context,
  "groups":groups,
  "route_police_station_context":police_station_context,
  "official_press_release_evidence":press_release_evidence,
  "official_locality_counts":{
   "status":"unavailable",
   "available_city_aggregate_years":sorted({record["year"] for record in dataset["records"]}),
   "geographic_precision":dataset["source"].get("geographic_precision"),
   "reason":"The loaded NCRB series is Delhi City-wide. No verified police-station or neighbourhood annual crime counts are loaded, so city totals are not allocated to sampled route localities.",
  },
  "notice":"Route places are approximated from a maximum of six reverse-geocoded sample points. News and press-release matches are source-linked review candidates, not verified route incident locations or complete crime counts. Missing results do not mean zero crime.",
 }

class RouteLocalityReportsIn(BaseModel):
 origin:str=Field(min_length=1,max_length=200)
 destination:str=Field(min_length=1,max_length=200)
@app.post("/api/v1/routes/locality-reports")
def route_locality_reports(body:RouteLocalityReportsIn):
 import re
 def tokens(value):
  return {re.sub(r"[^a-z0-9]+"," ",part.casefold()).strip() for part in value.split(",") if len(part.strip())>2}
 labels=tokens(body.origin)|tokens(body.destination)
 if not labels:return {"status":"insufficient_data","items":[],"notice":"No named locality matched. This is not a route-segment search."}
 with connect() as db:
  rows=db.execute("select e.id,e.event_date_start,e.date_precision,e.incident_type_normalized,e.event_status,e.summary_neutral,p.place_role,p.locality,p.landmark,p.location_confidence,p.review_status,s.canonical_url,s.headline,s.published_at from incident_events e join place_observations p on p.incident_id=e.id join incident_sources s on s.incident_id=e.id order by e.event_date_start desc").fetchall()
 items=[]
 for row in rows:
  place_labels={str(row[7] or "").casefold().strip(),str(row[8] or "").casefold().strip()}
  if labels & place_labels:
   items.append({"id":row[0],"event_date":row[1],"date_precision":row[2],"category":row[3],"status":row[4],"summary":row[5],"place_role":row[6],"locality":row[7],"landmark":row[8],"location_confidence":row[9],"review_status":row[10],"source_url":row[11],"source_title":row[12],"published_at":row[13]})
 return {"status":"candidate_context" if items else "insufficient_data","items":items,"notice":"These are source-reported candidates matched by place-name text only. They are not spatially matched to the route and do not estimate risk."}
@app.get("/api/v1/map/pedestrian-network")
def pedestrian_network(bbox:str=Query(...,description="west,south,east,north in WGS84"),limit:int=2000):
 try: west,south,east,north=map(float,bbox.split(","))
 except (ValueError,TypeError): raise HTTPException(422,"bbox must be west,south,east,north") from None
 if not 1<=limit<=3000: raise HTTPException(422,"limit must be between 1 and 3000")
 if not all(math.isfinite(x) for x in (west,south,east,north)) or not (-180<=west<east<=180 and -90<=south<north<=90) or east-west>.1 or north-south>.1:
  raise HTTPException(422,"bbox bounds are invalid or exceed the 0.1 degree pilot query limit")
 with connect() as db:
  nets=[dict(row) for row in db.execute("select id,version_date,license,attribution,source_url,notes from pedestrian_networks order by id")]
  rows=db.execute("select id,network_id,geometry_geojson from pedestrian_segments order by id").fetchall()
 features=[]
 for row in rows:
  feature=json.loads(row["geometry_geojson"]); coords=feature.get("geometry",{}).get("coordinates",[])
  if any(west<=point[0]<=east and south<=point[1]<=north for point in coords):
   feature["properties"]["network_id"]=row["network_id"]; features.append(feature)
   if len(features)>=limit: break
 return {"type":"FeatureCollection","features":features,"networks":nets,"returned":len(features),"truncated":len(features)>=limit,"notice":"OSM highway tags indicate candidate walkable ways only; this pilot extract is incomplete and ground accessibility is unverified. It is not a safety rating."}
@app.get("/api/v1/map/infrastructure")
def map_infrastructure(bbox:str=Query(...,description="west,south,east,north in WGS84")):
 try: west,south,east,north=map(float,bbox.split(","))
 except (ValueError,TypeError): raise HTTPException(422,"bbox must be west,south,east,north") from None
 bounds=(west,south,east,north)
 if not all(math.isfinite(value) for value in bounds) or not (-180<=west<east<=180 and -90<=south<north<=90) or east-west>.08 or north-south>.08:
  raise HTTPException(422,"Map area is too large or invalid. Zoom in to a smaller area.")
 try:
  return get_viewport_infrastructure(bounds)
 except MapInfrastructureUnavailable as exc:
  return {"type":"FeatureCollection","features":[],"counts":{"roads":None,"pedestrian":None,"lighting":None,"surface":None},"status":"unavailable","coverage_status":"unavailable","retrieved_at":datetime.now(timezone.utc).isoformat(),"bbox":list(bounds),"provider":"OpenStreetMap Overpass","source_url":"https://www.openstreetmap.org/","attribution":"© OpenStreetMap contributors","note":"Live OSM data could not be retrieved. This does not mean matching infrastructure is absent.","reason":str(exc)}
@app.get("/api/v1/trends")
def trends_endpoint(years:list[int]|None=Query(None),category:str|None=None):
 with connect() as db:return trends(db,years,category)
@app.get("/api/v1/geocoding/search")
def geocoding_search(q:str=Query(min_length=2,max_length=200),limit:int=Query(5,ge=1,le=10)):
 try:
  items=search_locations(q,limit)
 except LocationNotFound:
  return {"items":[]}
 except GeocodingUnavailable as exc:
  raise HTTPException(503,detail="Location suggestions are temporarily unavailable. Try again shortly.") from exc
 return {"items":items,"provider":"OpenStreetMap Nominatim"}
@app.get("/api/v1/facilities/nearby")
def facilities_nearby(
 latitude:float=Query(ge=-90,le=90),
 longitude:float=Query(ge=-180,le=180),
 category:str=Query("all",pattern="^(police|hospitals|all)$"),
 radius_m:int=Query(5000,ge=250,le=10000),
 limit:int=Query(30,ge=1,le=30),
):
 try:
  return nearby_facilities(latitude,longitude,category,radius_m,limit)
 except FacilitiesUnavailable as exc:
  raise HTTPException(503,detail=str(exc)) from exc
 except ValueError as exc:
  raise HTTPException(422,detail=str(exc)) from exc
@app.post("/api/v1/routes/compare")
def routes(body:RouteIn):
 resolved={}
 for field,label in (("origin","starting location"),("destination","destination")):
  query=getattr(body,field)
  selected=getattr(body,f"{field}_location")
  if selected is not None:
   try:
    latitude=float(selected["latitude"]); longitude=float(selected["longitude"])
    if not (-90<=latitude<=90 and -180<=longitude<=180): raise ValueError
    resolved[field]={"query":str(selected.get("query") or query),"display_name":str(selected["display_name"]),"latitude":latitude,"longitude":longitude,"provider":str(selected.get("provider") or "Nominatim"),"place_type":str(selected.get("place_type") or "place")}
   except (KeyError,TypeError,ValueError) as exc:
    raise HTTPException(422,detail=f"Select a valid {label} from the location suggestions.") from exc
  else:
   try:
    resolved[field]=geocode_location(query)
   except LocationNotFound as exc:
    raise HTTPException(422,detail=f"We couldn't find the {label}. Try a more specific locality, landmark, street, or full address.") from exc
   except GeocodingUnavailable as exc:
    raise HTTPException(503,detail="Location lookup is temporarily unavailable. Please try again shortly.") from exc
 origin=resolved["origin"]
 destination=resolved["destination"]
 motorcycle_fallback=body.mode=="motorcycle" and not os.getenv("GEOAPIFY_API_KEY","").strip()
 route_result=compare(
  f"{origin['longitude']},{origin['latitude']}",
  f"{destination['longitude']},{destination['latitude']}",
  router=OSRMRouter() if motorcycle_fallback else GeoapifyMotorcycleRouter() if body.mode=="motorcycle" else None,
 )
 if motorcycle_fallback:
  route_result["provider"]="OSRM driving profile · motorcycle fallback"
  route_result["provider_status"]="provider_fallback" if route_result.get("alternatives") else route_result.get("provider_status","unavailable")
  route_result["limitations"]=["This is an OSRM car-profile route shown as a motorcycle fallback; it is not motorcycle-optimized and motorcycle access or restrictions are not verified.",*route_result.get("limitations",[])]
  for route in route_result.get("alternatives",[]): route["rank_reason"]="OSRM car-profile estimate only; not motorcycle-optimized and not a safety score. Verify vehicle access and restrictions before travel."
 route_result["mode"]=body.mode
 route_result["resolved_locations"]={
  key:{name:location[name] for name in ("query","display_name","latitude","longitude","provider") if name in location}
  for key,location in resolved.items()
 }
 with connect() as db:
  route_evidence=match_route_incidents(route_result.get("alternatives",[]),db)
 for route in route_result.get("alternatives",[]):
  news_evidence=route_evidence.get(str(route.get("id")),{
   "status":"insufficient_route_level_evidence","risk_score":None,"matched_incidents":None,"reports":[],
   "reason":"Route geometry is unavailable, so newspaper reports cannot be matched to this option.",
  })
  route["safety_evidence"]=news_evidence
  route["infrastructure_evidence"]={
   "status":"unavailable",
   "reason":"No geocoded, route-covering lighting or pedestrian-activity audits are configured.",
  }
  route["safety_assessment"]=assess_route_safety(news_evidence)
 dataset=load_dataset()
 route_result["evidence_context"]={
  "route_specific_news":{
   "status":"available" if any(item["status"]=="matched_reports" for item in route_evidence.values()) else "insufficient_route_level_evidence",
   "proximity_radius_m":max(50,min(int(os.getenv("NAVIRA_ROUTE_INCIDENT_RADIUS_M","500")),5000)),
   "incident_window_days":max(1,min(int(os.getenv("NAVIRA_ROUTE_INCIDENT_MAX_AGE_DAYS","1095")),3650)),
   "reason":"Only review-verified news reports with precise coordinates, source links, and dates are matched. Newspaper reporting is not a complete crime dataset and does not justify a route-risk score." if any(item["status"]=="matched_reports" for item in route_evidence.values()) else "No eligible verified, geocoded news reports were matched to these road routes. Missing reports do not mean zero crime.",
  },
  "historical_official_statistics":{
   "status":"aggregate_only",
   "dataset":dataset["source"]["name"],
   "years":[record["year"] for record in dataset["records"]],
   "source":dataset["source"]["reference"],
   "retrieved_at":dataset["source"]["retrieved_at"],
   "version":dataset["source"]["version"],
   "geographic_precision":dataset["source"]["geographic_precision"],
   "geography":f"{dataset['records'][0]['geography_id']} {dataset['records'][0]['geography_type']}" if dataset["records"] else dataset["source"]["geographic_precision"],
   "records":[{"year":record["year"],"count":record["count"],"category":record["category"],"geography":record["geography_id"]} for record in dataset["records"]],
   "limitations":[
    "Delhi City metropolitan totals cannot be assigned to an individual road, route, or locality.",
    "Registered cases are historical counts, not a measure of route-level risk.",
   ],
  },
 }
 return route_result
@app.post("/api/v1/routes/walking")
def walking_route(body:RouteIn):
 resolved={}
 for field,label in (("origin","starting location"),("destination","destination")):
  query=getattr(body,field)
  selected=getattr(body,f"{field}_location")
  if selected is not None:
   try:
    latitude=float(selected["latitude"]); longitude=float(selected["longitude"])
    if not (-90<=latitude<=90 and -180<=longitude<=180): raise ValueError
    resolved[field]={"query":str(selected.get("query") or query),"display_name":str(selected["display_name"]),"latitude":latitude,"longitude":longitude,"provider":str(selected.get("provider") or "Nominatim")}
   except (KeyError,TypeError,ValueError) as exc:
    raise HTTPException(422,detail=f"Select a valid {label} from the location suggestions.") from exc
  else:
   try: resolved[field]=geocode_location(query)
   except LocationNotFound as exc: raise HTTPException(422,detail=f"We couldn't find the {label}. Try a more specific locality, landmark, street, or full address.") from exc
   except GeocodingUnavailable as exc: raise HTTPException(503,detail="Location lookup is temporarily unavailable. Please try again shortly.") from exc
 locations={key:{name:value[name] for name in ("query","display_name","latitude","longitude","provider")} for key,value in resolved.items()}
 result=compare(
  f"{resolved['origin']['longitude']},{resolved['origin']['latitude']}",
  f"{resolved['destination']['longitude']},{resolved['destination']['latitude']}",
  router=OpenRouteServiceWalkingRouter(),
 )
 result.update({"mode":"walking","provider":"openrouteservice · foot-walking","resolved_locations":locations})
 result["limitations"]=["Walking directions use the openrouteservice foot-walking profile. OSM tagging, sidewalks, crossings, accessibility, and current path access may be incomplete; verify local conditions.",*result.get("limitations",[])]
 return result
@app.post("/api/v1/routes/traffic")
def route_traffic(body:RouteTrafficIn):
 return get_route_traffic(body.coordinates,body.duration_s,body.distance_m)
@app.post("/api/v1/routes/weather")
def route_weather(body:RouteWeatherIn):
 return get_route_weather(body.coordinates)
@app.post("/api/v1/routes/infrastructure")
def route_infrastructure(body:RouteInfrastructureIn):
 corridor=body.corridor_m
 if corridor is None:
  try: corridor=max(25,min(int(os.getenv("NAVIRA_INFRASTRUCTURE_CORRIDOR_M","100")),500))
  except ValueError: corridor=100
 try:
  return get_route_infrastructure(body.coordinates,corridor)
 except InfrastructureUnavailable as exc:
  return {
    "status":"unavailable","provider":"OpenStreetMap Overpass","retrieved_at":datetime.now(timezone.utc).isoformat(),
   "streetlights_mapped":None,"footpaths_mapped":None,"mapped_feature_count":None,
   "working_status":"unavailable","working_status_label":"Unavailable — map data could not be retrieved.",
   "night_visibility":"not_assessed","night_visibility_label":"Not assessed — no lighting audit or night-visibility measurement is available.",
   "corridor_m":corridor,
   "coverage":{"status":"unavailable","note":"The infrastructure data provider could not be reached. This does not mean no features exist."},
   "official_sources":[
    {"name":"Delhi PWD","status":"unavailable","source_url":"https://pwd.delhi.gov.in/"},
    {"name":"MCD","status":"unavailable","source_url":"https://mcdonline.nic.in/portal/downloadFile/circular_reg._complaints_lodged_on_mcd_311_app_230824113534834.pdf","complaint_url":"https://mcdonline.nic.in/portal/feedback"},
    {"name":"NDMC","status":"unavailable","source_url":"https://www.ndmc.gov.in/ndmc/achievements_it.aspx","complaint_url":"https://onlineservices.ndmc.gov.in/auth/"},
   ],"reason":str(exc),
  }
@app.post("/api/v1/community/hazards")
def add_hazard(body:HazardIn):
 now=datetime.now(timezone.utc); exp=(now+timedelta(days=body.expires_days)).isoformat(); desc=sanitize(body.description)
 with connect() as db:
  cur=db.execute("insert into hazards(created_at,geography,category,description,status,expires_at) values(?,?,?,?,?,?)",(now.isoformat(),body.approximate_geography,body.category,desc,"unverified",exp))
  return {"id":cur.lastrowid,"created_at":now.isoformat(),"category":body.category,"description":desc,"status":"unverified","expires_at":exp}
@app.get("/api/v1/community/hazards")
def list_hazards(limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0)):
 with connect() as db: return {"items":[dict(x) for x in db.execute("select id,created_at,geography,category,description,status,expires_at from hazards where expires_at>? order by created_at desc limit ? offset ?",(datetime.now(timezone.utc).isoformat(),limit,offset))],"limit":limit,"offset":offset,"note":"Community submissions are unverified, time-limited reports."}
@app.get("/api/v1/emergency/resources")
def emergency_resources():return emergency()

# Render serves the built single-page frontend and API from one origin. During
# local development Vite serves the frontend separately, so this is optional.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
 app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
