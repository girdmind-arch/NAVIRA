"""Shared, transparent implementations for the seven NAVIRA service areas."""
from __future__ import annotations
import hashlib,json,math,os,re
from datetime import date,datetime,timezone
from difflib import SequenceMatcher
from typing import Any
PII=re.compile(r"\b(?:\+?91[- ]?)?[6-9]\d{9}\b|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",re.I)
def redact(text:str)->str: return PII.sub("[REDACTED]",text or "")
def validate_official(r:dict[str,Any])->list[str]:
 e=[f"missing {k}" for k in ("year","geography_id","geography_type","category","count") if r.get(k) is None]
 if str(r.get("geography_scope","")).casefold()!="delhi_nct": e.append("geography_scope must be explicitly marked delhi_nct")
 if r.get("geography_type") not in {"district","metropolitan","locality","state"}: e.append("invalid geography_type")
 try:
  if not 1900<=int(r.get("year",0))<=date.today().year: e.append("year outside supported range")
  if int(r.get("count",-1))<0: e.append("count must be non-negative")
 except (ValueError,TypeError): e.append("year/count must be integers")
 return e
def validate_news(r:dict[str,Any])->list[str]:
 e=[f"missing {k}" for k in ("article_reference",) if not r.get(k)]
 for k in ("publication_date","incident_date"):
  if r.get(k):
   try: date.fromisoformat(str(r[k])[:10])
   except ValueError: e.append(f"invalid {k}")
 if (r.get("latitude") is None)!=(r.get("longitude") is None): e.append("latitude and longitude must be provided together")
 if r.get("latitude") is not None and r.get("longitude") is not None:
  try:
   if not -90<=float(r["latitude"])<=90 or not -180<=float(r["longitude"])<=180: e.append("incident coordinates are outside valid ranges")
  except (ValueError,TypeError): e.append("incident coordinates must be numbers")
 return e
def classify_rules(text:str)->dict[str,Any]:
 low=(text or "").lower(); terms={"harassment":("harass","eve-teas"),"assault":("assault","attack"),"stalking":("stalk",)}
 found=[k for k,v in terms.items() if any(term in low for term in v)]
 return {"relevant":bool(found),"category":found[0] if found else None,"mode":"rules_only","confidence":None,"review_status":"needs_review"}
def extract_candidate(text:str,db=None)->dict[str,Any]:
 safe=sanitize(text)
 classification=classify_rules(safe)
 dates=re.findall(r"\b20\d{2}-\d{2}-\d{2}\b",safe)
 incident_date=None
 if dates:
  try: incident_date=date.fromisoformat(dates[0]).isoformat()
  except ValueError: pass
 mentions=[]
 if db is not None:
  for row in db.execute("select id,name,aliases,scope_status from localities"):
   for name in [row[1],*json.loads(row[2] or "[]")]:
    if re.search(r"(?<!\w)"+re.escape(name)+r"(?!\w)",safe,re.I):
     mentions.append({"text":name,"resolution":resolve(db,name)}); break
 return {"classification":classification,"incident_date_candidate":incident_date,"locality_candidates":mentions,"review_status":"needs_review","excerpt":safe}
def quality(db)->dict[str,Any]:
 end=date.today().year-1; win=list(range(end-4,end+1))
 official=sorted({int(x[0]) for x in db.execute("select distinct year from official_stats")})
 news=sorted({int(x[0][:4]) for x in db.execute("select distinct incident_date from news_incidents where incident_date is not null") if x[0][:4].isdigit()})
 observed=sorted(set(official)|set(news))
 stale_after=int(os.getenv("NAVIRA_STALE_AFTER_DAYS","365")); now=datetime.now(timezone.utc); stale=[]
 for row in db.execute("select id,name,source_type,retrieved_at from sources"):
  try:
   retrieved=datetime.fromisoformat(row[3].replace("Z","+00:00"))
   if retrieved.tzinfo is None: retrieved=retrieved.replace(tzinfo=timezone.utc)
   age=(now-retrieved).days
   if age>stale_after: stale.append({"source_id":row[0],"name":row[1],"source_type":row[2],"age_days":age})
  except (ValueError,TypeError): stale.append({"source_id":row[0],"name":row[1],"source_type":row[2],"age_days":None,"issue":"invalid retrieved_at"})
 return {"scope":"Delhi NCT only","target_years":win,"observed_years":observed,"missing_years":[y for y in win if y not in observed],"official_years":official,"official_missing_years":[y for y in win if y not in official],"news_report_years":news,"news_missing_years":[y for y in win if y not in news],"official_statistics":db.execute("select count(*) from official_stats").fetchone()[0],"news_reported_records":db.execute("select count(*) from news_incidents").fetchone()[0],"quality_issues":db.execute("select count(*) from quality_issues where resolved=0").fetchone()[0],"stale_after_days":stale_after,"stale_sources":stale,"note":"Coverage is reported per source type; missing years are not zero incidents."}
def resolve(db,mention:str)->dict[str,Any]:
 needle=mention.casefold().strip(); found=[]
 for row in db.execute("select id,name,aliases,scope_status from localities"):
  aliases=json.loads(row[2] or "[]")
  if any(needle==n.casefold() for n in [row[1],*aliases]): found.append(row)
 if len(found)==1 and found[0][3]=="delhi_nct": return {"status":"resolved","locality_id":found[0][0],"name":found[0][1],"method":"exact gazetteer match","confidence":1.0}
 if len(found)>1: return {"status":"ambiguous","locality_ids":[x[0] for x in found],"method":"exact alias collision","confidence":None}
 if any(x in needle for x in ("gurugram","gurgaon","noida","ghaziabad","faridabad","sonipat","rohtak","alwar")): return {"status":"outside_scope","method":"out-of-scope NCR name detected","confidence":None}
 return {"status":"unresolved","method":"no supported gazetteer match","confidence":None}
def route_locality_evidence(_geometry:Any)->dict[str,str]: return {"status":"unavailable","reason":"Approved locality boundaries are not configured."}
def dup_score(a:dict[str,Any],b:dict[str,Any])->tuple[float,dict[str,Any]]:
 sim=SequenceMatcher(None,(a.get("excerpt") or "").lower(),(b.get("excerpt") or "").lower()).ratio(); same_date=bool(a.get("incident_date") and a.get("incident_date")==b.get("incident_date")); same_loc=bool(a.get("locality_id") and a.get("locality_id")==b.get("locality_id")); same_cat=bool(a.get("category") and a.get("category")==b.get("category"))
 return .55*sim+.2*same_date+.15*same_loc+.1*same_cat,{"text_similarity":round(sim,3),"same_date":same_date,"same_locality":same_loc,"same_category":same_cat}
def find_duplicate_candidates(db,threshold:float=.8)->list[int]:
 rows=[dict(r) for r in db.execute("select id,incident_date,category,locality_id,excerpt from news_incidents")]; created=[]
 for i,a in enumerate(rows):
  for b in rows[i+1:]:
   score,features=dup_score(a,b)
   exists=db.execute("select 1 from duplicate_candidates where record_a=? and record_b=?",(a["id"],b["id"])).fetchone()
   if score>=threshold and not exists:
    cur=db.execute("insert into duplicate_candidates(record_a,record_b,features,score,status) values(?,?,?,?,?)",(a["id"],b["id"],json.dumps(features),score,"needs_review")); created.append(cur.lastrowid)
 return created
def trends(db,years:list[int]|None=None,category:str|None=None)->dict[str,Any]:
 f=""; args=[]
 if years: f+=" and year in ("+",".join("?" for _ in years)+")"; args.extend(years)
 if category: f+=" and category=?"; args.append(category)
 official=[dict(x) for x in db.execute("select year,geography_id,geography_type,category,sum(count) as count from official_stats where 1=1"+f+" group by year,geography_id,geography_type,category order by year",args)]
 nf=""; na=[]
 if years: nf+=" and substr(incident_date,1,4) in ("+",".join("?" for _ in years)+")"; na.extend(str(y) for y in years)
 if category: nf+=" and category=?"; na.append(category)
 news=[dict(x) for x in db.execute("select substr(incident_date,1,4) as year,locality_id,category,count(*) as article_records from news_incidents where incident_date is not null"+nf+" group by year,locality_id,category order by year",na)]
 return {"official_statistics":official,"news_reported_incidents":news,"comparability_warning":"Separate series; article record counts are not crime incidence.","quality":quality(db)}
class MockRouter:
 def routes(self,origin:str,destination:str)->list[dict[str,Any]]: return [{"id":"synthetic-fast","distance_m":4200,"duration_s":900,"geometry":None},{"id":"synthetic-alt","distance_m":5100,"duration_s":1200,"geometry":None}]

MAX_ROUTE_ALTERNATIVES = 5
ROUTE_OVERLAP_TOLERANCE_M = 80
ROUTE_OVERLAP_THRESHOLD = .85

def configured_route_alternatives()->int:
 raw=os.getenv("NAVIRA_MAX_ROUTE_ALTERNATIVES","3")
 try: maximum=int(raw)
 except ValueError as exc: raise ValueError("NAVIRA_MAX_ROUTE_ALTERNATIVES must be an integer from 1 to 5.") from exc
 if not 1<=maximum<=MAX_ROUTE_ALTERNATIVES:
  raise ValueError("NAVIRA_MAX_ROUTE_ALTERNATIVES must be an integer from 1 to 5.")
 return maximum

def _sample_route_geometry(geometry:Any,limit:int=120)->list[tuple[float,float]]:
 coordinates=(geometry or {}).get("coordinates") if isinstance(geometry,dict) else None
 if not isinstance(coordinates,list) or len(coordinates)<2: return []
 valid=[]
 for point in coordinates:
  if not isinstance(point,(list,tuple)) or len(point)<2: continue
  try: longitude,latitude=float(point[0]),float(point[1])
  except (TypeError,ValueError): continue
  if math.isfinite(longitude) and math.isfinite(latitude) and -180<=longitude<=180 and -90<=latitude<=90:
   valid.append((longitude,latitude))
 if len(valid)<2: return []
 segment_lengths=[]
 for first,second in zip(valid,valid[1:]):
  latitude=math.radians((first[1]+second[1])/2)
  segment_lengths.append(math.hypot((second[0]-first[0])*111320*math.cos(latitude),(second[1]-first[1])*110574))
 total_length=sum(segment_lengths)
 if total_length<=0: return [valid[0],valid[-1]]
 count=min(limit,max(2,len(valid)))
 samples=[]; segment_index=0; segment_start=0.0
 for index in range(count):
  target=total_length*index/(count-1)
  while segment_index<len(segment_lengths)-1 and segment_start+segment_lengths[segment_index]<target:
   segment_start+=segment_lengths[segment_index]; segment_index+=1
  segment_length=segment_lengths[segment_index]
  ratio=0.0 if segment_length==0 else max(0.0,min(1.0,(target-segment_start)/segment_length))
  first,second=valid[segment_index],valid[segment_index+1]
  samples.append((first[0]+(second[0]-first[0])*ratio,first[1]+(second[1]-first[1])*ratio))
 return samples

def _route_proximity_fraction(samples:list[tuple[float,float]],geometry:Any)->float:
 target=_sample_route_geometry(geometry)
 if not samples or len(target)<2: return 0.0
 near=0
 for longitude,latitude in samples:
  distance=min(
   _point_to_segment_distance_m(latitude,longitude,target[index],target[index+1])
   for index in range(len(target)-1)
  )
  if distance<=ROUTE_OVERLAP_TOLERANCE_M: near+=1
 return near/len(samples)

def routes_substantially_overlap(first:dict[str,Any],second:dict[str,Any])->bool:
 first_samples=_sample_route_geometry(first.get("geometry"))
 second_samples=_sample_route_geometry(second.get("geometry"))
 if len(first_samples)<2 or len(second_samples)<2: return False
 return min(
  _route_proximity_fraction(first_samples,second.get("geometry")),
  _route_proximity_fraction(second_samples,first.get("geometry")),
 )>=ROUTE_OVERLAP_THRESHOLD

def distinct_route_alternatives(routes:list[dict[str,Any]],maximum:int|None=None)->list[dict[str,Any]]:
 limit=maximum if maximum is not None else configured_route_alternatives()
 distinct=[]
 for route in routes:
  if any(routes_substantially_overlap(route,existing) for existing in distinct):
   continue
  distinct.append(route)
  if len(distinct)>=limit: break
 return distinct

class OSRMRouter:
 """OSRM road-routing adapter; endpoints must provide explicit longitude,latitude pairs."""
 def __init__(self,base_url:str|None=None): self.base_url=(base_url or os.getenv("NAVIRA_OSRM_BASE_URL") or "https://router.project-osrm.org").rstrip("/")
 def routes(self,origin:str,destination:str)->list[dict[str,Any]]:
  import urllib.request
  from urllib.error import HTTPError,URLError
  if not self.base_url: raise RuntimeError("NAVIRA_OSRM_BASE_URL is not configured")
  maximum=configured_route_alternatives()
  def coordinate(point):
   try:
    lon,lat=map(float,point.split(","))
   except (ValueError,TypeError): raise ValueError("OSRM needs explicit longitude,latitude coordinate pairs") from None
   if not -180<=lon<=180 or not -90<=lat<=90: raise ValueError("Coordinate out of range")
   return f"{lon},{lat}"
  osrm_alternatives="false" if maximum==1 else str(maximum-1)
  url=f"{self.base_url}/route/v1/driving/{coordinate(origin)};{coordinate(destination)}?alternatives={osrm_alternatives}&overview=full&geometries=geojson"
  try:
   with urllib.request.urlopen(url,timeout=8) as response: payload=json.loads(response.read().decode("utf-8"))
  except HTTPError as exc: raise RuntimeError(f"Road routing service returned HTTP {exc.code}.") from exc
  except (URLError,TimeoutError,OSError,json.JSONDecodeError) as exc: raise RuntimeError("Road routing service is temporarily unavailable or returned invalid data.") from exc
  if payload.get("code")!="Ok": raise RuntimeError("Routing provider returned no route")
  routes=[]
  seen_geometries=set()
  for provider_index,route in enumerate(payload.get("routes",[]),start=1):
   if not isinstance(route,dict): continue
   distance=route.get("distance"); duration=route.get("duration"); geometry=route.get("geometry")
   coordinates=geometry.get("coordinates") if isinstance(geometry,dict) and geometry.get("type")=="LineString" else None
   if not isinstance(distance,(int,float)) or not math.isfinite(distance) or distance<=0: continue
   if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0: continue
   if not isinstance(coordinates,list) or len(coordinates)<2: continue
   valid_coordinates=True
   for point in coordinates:
    if not isinstance(point,(list,tuple)) or len(point)<2:
     valid_coordinates=False
     break
    try: longitude,latitude=float(point[0]),float(point[1])
    except (TypeError,ValueError):
     valid_coordinates=False
     break
    if not math.isfinite(longitude) or not math.isfinite(latitude) or not -180<=longitude<=180 or not -90<=latitude<=90:
     valid_coordinates=False
     break
   if not valid_coordinates: continue
   signature=tuple((round(float(point[0]),6),round(float(point[1]),6)) for point in coordinates)
   if signature in seen_geometries: continue
   seen_geometries.add(signature)
   routes.append({"id":f"osrm-{provider_index}","distance_m":distance,"duration_s":duration,"geometry":geometry})
  if not routes: raise RuntimeError("Routing provider returned no valid road route geometry")
  return distinct_route_alternatives(routes,maximum)
 def table(self,origin:str,destinations:list[str])->dict[str,Any]:
  import urllib.request
  from urllib.error import HTTPError,URLError
  def coordinate(point):
   try: lon,lat=map(float,point.split(","))
   except (ValueError,TypeError): raise ValueError("OSRM needs explicit longitude,latitude coordinate pairs") from None
   if not -180<=lon<=180 or not -90<=lat<=90: raise ValueError("Coordinate out of range")
   return f"{lon},{lat}"
  coordinates=[coordinate(origin),*(coordinate(point) for point in destinations)]
  destination_indexes=";".join(str(index) for index in range(1,len(coordinates)))
  url=f"{self.base_url}/table/v1/driving/{';'.join(coordinates)}?sources=0&destinations={destination_indexes}&annotations=distance,duration"
  try:
   with urllib.request.urlopen(url,timeout=12) as response: payload=json.loads(response.read().decode("utf-8"))
  except HTTPError as exc: raise RuntimeError(f"Road routing service returned HTTP {exc.code}.") from exc
  except (URLError,TimeoutError,OSError,json.JSONDecodeError) as exc: raise RuntimeError("Road routing service is temporarily unavailable or returned invalid data.") from exc
  if payload.get("code")!="Ok": raise RuntimeError("Road routing provider returned no travel-time table")
  return payload

class GeoapifyMotorcycleRouter:
 """Geoapify Routing API adapter using its documented motorcycle profile."""
 provider="Geoapify Routing API · motorcycle profile"
 endpoint="https://api.geoapify.com/v1/routing"
 def __init__(self,api_key:str|None=None): self.api_key=api_key if api_key is not None else os.getenv("GEOAPIFY_API_KEY","")
 def routes(self,origin:str,destination:str)->list[dict[str,Any]]:
  import urllib.request
  from urllib.error import HTTPError,URLError
  from urllib.parse import urlencode
  if not self.api_key: raise RuntimeError("Motorcycle routing is not configured. Set GEOAPIFY_API_KEY on the backend to enable Geoapify motorcycle routes.")
  def coordinate(point):
   try: lon,lat=map(float,point.split(","))
   except (ValueError,TypeError): raise ValueError("Motorcycle routing needs explicit longitude,latitude coordinate pairs") from None
   if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90: raise ValueError("Coordinate out of range")
   return f"{lat},{lon}"
  waypoints=f"{coordinate(origin)}|{coordinate(destination)}"
  params=urlencode({"waypoints":waypoints,"mode":"motorcycle","format":"geojson","apiKey":self.api_key})
  url=f"{self.endpoint}?{params}"
  try:
   with urllib.request.urlopen(url,timeout=12) as response: payload=json.loads(response.read().decode("utf-8"))
  except HTTPError as exc:
   if exc.code==401: raise RuntimeError("Geoapify rejected the backend key. Check that GEOAPIFY_API_KEY is valid and Routing API access is enabled.") from exc
   if exc.code==403: raise RuntimeError("Geoapify denied the routing request. Check GEOAPIFY_API_KEY, project permissions, and daily quota.") from exc
   if exc.code==429: raise RuntimeError("Geoapify routing rate limit reached. Wait before trying again.") from exc
   if exc.code in (400,404): raise RuntimeError("Geoapify could not find a motorcycle route for these locations. Try different places.") from exc
   raise RuntimeError(f"Geoapify motorcycle routing returned HTTP {exc.code}; try again later.") from exc
  except (URLError,TimeoutError,OSError,json.JSONDecodeError) as exc: raise RuntimeError("Geoapify motorcycle routing is temporarily unavailable or returned invalid data.") from exc
  if not isinstance(payload,dict): raise RuntimeError("Geoapify returned an invalid motorcycle-routing response.")
  if payload.get("error") or payload.get("statusCode"):
   raise RuntimeError(str(payload.get("message") or payload.get("error") or "Geoapify could not calculate this motorcycle route."))
  if not isinstance(payload.get("features"),list): raise RuntimeError("Geoapify returned an invalid motorcycle-routing response.")
  routes=[]
  for provider_index,feature in enumerate(payload.get("features",[]),start=1):
   if not isinstance(feature,dict): continue
   properties=feature.get("properties") or {}; geometry=feature.get("geometry") or {}
   distance=properties.get("distance"); duration=properties.get("time"); raw=geometry.get("coordinates")
   if geometry.get("type")=="LineString": lines=[raw]
   elif geometry.get("type")=="MultiLineString" and isinstance(raw,list): lines=raw
   else: continue
   points=[]; valid=True
   for line in lines:
    if not isinstance(line,list): valid=False; break
    for point in line:
     if not isinstance(point,(list,tuple)) or len(point)<2: valid=False; break
     try: lon,lat=float(point[0]),float(point[1])
     except (TypeError,ValueError): valid=False; break
     if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90: valid=False; break
     pair=[lon,lat]
     if not points or points[-1]!=pair: points.append(pair)
    if not valid: break
   if not valid or not isinstance(distance,(int,float)) or not math.isfinite(distance) or distance<=0: continue
   if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0 or len(points)<2: continue
   routes.append({"id":f"geoapify-motorcycle-{provider_index}","distance_m":float(distance),"duration_s":float(duration),"geometry":{"type":"LineString","coordinates":points}})
  if not routes: raise RuntimeError("Geoapify returned no usable motorcycle route for these locations.")
  return distinct_route_alternatives(routes,configured_route_alternatives())

class OpenRouteServiceWalkingRouter:
 """OpenRouteService foot-walking adapter; the API key is backend-only."""
 provider="openrouteservice · foot-walking"
 # Use HeiGIT's current public API host; api.openrouteservice.org is deprecated.
 endpoint="https://api.heigit.org/openrouteservice/v2/directions/foot-walking/geojson"
 def __init__(self,api_key:str|None=None): self.api_key=api_key if api_key is not None else os.getenv("OPENROUTESERVICE_API_KEY","")
 def routes(self,origin:str,destination:str)->list[dict[str,Any]]:
  import urllib.request
  from urllib.error import HTTPError,URLError
  if not self.api_key: raise RuntimeError("Walking directions are not configured. Set OPENROUTESERVICE_API_KEY on the backend.")
  def coordinate(point:str)->list[float]:
   try: longitude,latitude=map(float,point.split(","))
   except (ValueError,TypeError): raise ValueError("OpenRouteService needs explicit longitude,latitude coordinate pairs") from None
   if not math.isfinite(longitude) or not math.isfinite(latitude) or not -180<=longitude<=180 or not -90<=latitude<=90:
    raise ValueError("Coordinate out of range")
   return [longitude,latitude]
  body={"coordinates":[coordinate(origin),coordinate(destination)],"instructions":False,"elevation":False}
  request=urllib.request.Request(self.endpoint,data=json.dumps(body).encode("utf-8"),headers={"Authorization":self.api_key,"Content-Type":"application/json","Accept":"application/geo+json"},method="POST")
  try:
   with urllib.request.urlopen(request,timeout=15) as response: payload=json.loads(response.read().decode("utf-8"))
  except HTTPError as exc:
   detail=""
   try:
    error_payload=json.loads(exc.read().decode("utf-8")); detail=str((error_payload.get("error") or {}).get("message") or error_payload.get("message") or "")
   except (ValueError,AttributeError): pass
   if exc.code==401: raise RuntimeError("OpenRouteService rejected the backend key. Check OPENROUTESERVICE_API_KEY.") from exc
   if exc.code==403: raise RuntimeError("OpenRouteService denied this walking request; verify key access or whether the daily quota was exhausted.") from exc
   if exc.code==429: raise RuntimeError("OpenRouteService walking rate limit reached. Wait before trying again.") from exc
   if exc.code in (400,404): raise RuntimeError(detail or "OpenRouteService could not find a walkable route for these places.") from exc
   raise RuntimeError(detail or f"OpenRouteService walking directions returned HTTP {exc.code}.") from exc
  except (URLError,TimeoutError,OSError,json.JSONDecodeError) as exc:
   raise RuntimeError("OpenRouteService walking directions are temporarily unavailable or returned invalid data.") from exc
  features=payload.get("features") if isinstance(payload,dict) else None
  routes=[]
  for index,feature in enumerate(features or [],start=1):
   if not isinstance(feature,dict): continue
   properties=feature.get("properties") or {}; summary=properties.get("summary") or {}; geometry=feature.get("geometry") or {}
   distance=summary.get("distance"); duration=summary.get("duration"); coordinates=geometry.get("coordinates")
   if not isinstance(distance,(int,float)) or not math.isfinite(distance) or distance<=0: continue
   if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0: continue
   if geometry.get("type")!="LineString" or not isinstance(coordinates,list) or len(coordinates)<2: continue
   valid=True
   for point in coordinates:
    if not isinstance(point,(list,tuple)) or len(point)<2:
     valid=False; break
    try: longitude,latitude=float(point[0]),float(point[1])
    except (TypeError,ValueError):
     valid=False; break
    if not math.isfinite(longitude) or not math.isfinite(latitude) or not -180<=longitude<=180 or not -90<=latitude<=90:
     valid=False; break
   if valid: routes.append({"id":f"ors-foot-walking-{index}","distance_m":float(distance),"duration_s":float(duration),"geometry":geometry})
  if not routes: raise RuntimeError("OpenRouteService returned no usable foot-walking route for these places.")
  return distinct_route_alternatives(routes,configured_route_alternatives())

class OpenMeteoAdapter:
 """Optional Open-Meteo current conditions adapter with a three-hour freshness bound."""
 def __init__(self,fetcher=None): self.fetcher=fetcher
 def current(self,latitude:float,longitude:float)->dict[str,Any]:
  from urllib.parse import urlencode
  import urllib.request
  if not -90<=latitude<=90 or not -180<=longitude<=180: raise ValueError("weather coordinates out of range")
  params=urlencode({"latitude":latitude,"longitude":longitude,"current":"temperature_2m,precipitation,rain,weather_code,wind_speed_10m","timezone":"UTC"})
  url="https://api.open-meteo.com/v1/forecast?"+params
  if self.fetcher: payload=self.fetcher(url)
  else:
   with urllib.request.urlopen(url,timeout=6) as response: payload=json.loads(response.read().decode("utf-8"))
  current=payload.get("current") or {}; stamp=current.get("time")
  if not stamp: return {"status":"unavailable","provider":"Open-Meteo","reason":"provider omitted current timestamp"}
  observed=datetime.fromisoformat(stamp.replace("Z","+00:00"))
  if observed.tzinfo is None: observed=observed.replace(tzinfo=timezone.utc)
  now=datetime.now(timezone.utc); age=(now-observed).total_seconds()
  fresh=0<=age<=10800
  return {"status":"available" if fresh else "stale","provider":"Open-Meteo","reference":"https://api.open-meteo.com/v1/forecast","observed_at":observed.isoformat(),"retrieved_at":now.isoformat(),"age_seconds":max(0,int(age)),"current":current if fresh else None}

def compare(origin:str,destination:str,router=None)->dict[str,Any]:
 chosen=router or OSRMRouter()
 try:
  maximum=configured_route_alternatives()
  alternatives=distinct_route_alternatives(chosen.routes(origin,destination),maximum)
 except Exception as exc:
  configured_missing=hasattr(chosen,"api_key") and not chosen.api_key
  return {"alternatives":[],"provider_status":"unconfigured" if configured_missing else "unavailable","provider":getattr(chosen,"provider","OSRM"),"error":str(exc),"compared_at":datetime.now(timezone.utc).isoformat(),"limitations":["No route evidence available; verify provider configuration and retry."]}
 alternatives.sort(key=lambda r:(r.get("duration_s",1e99),r.get("distance_m",1e99)))
 route_evidence={
  "status":"unavailable",
  "risk_score":None,
  "matched_incidents":None,
  "reason":"No verified incident records with route-level coordinates or approved locality boundaries are available for this comparison.",
 }
 weather={"status":"unavailable"}
 if os.getenv("NAVIRA_WEATHER_ENABLED","false").casefold()=="true":
  try:
   lon,lat=map(float,origin.split(",")); weather=OpenMeteoAdapter().current(lat,lon)
   weather["coverage_note"]="Current conditions for route origin only; not a route-wide forecast."
  except Exception as exc: weather={"status":"unavailable","provider":"Open-Meteo","reason":str(exc)}
 fastest_index=min(range(len(alternatives)),key=lambda index:(alternatives[index].get("duration_s",1e99),alternatives[index].get("distance_m",1e99))) if alternatives else None
 shortest_index=min(range(len(alternatives)),key=lambda index:(alternatives[index].get("distance_m",1e99),alternatives[index].get("duration_s",1e99))) if alternatives else None
 for index,route in enumerate(alternatives):
  if index==fastest_index and index==shortest_index: rank_reason="Fastest and shortest by provider-estimated travel time and road distance; not a safety score."
  elif index==fastest_index: rank_reason="Fastest by provider-estimated travel time; not a safety score."
  elif index==shortest_index: rank_reason="Shortest by provider-estimated road distance; not a safety score."
  else: rank_reason="Alternative real road route; compare provider-estimated travel time and distance. No safety ranking is justified."
  route.update({"rank_reason":rank_reason,"safety_evidence":route_evidence,"locality_evidence":{"status":"unavailable"},"weather":weather,"traffic":{"status":"unavailable"},"community_reports":{"status":"unavailable"}})
 configured=isinstance(chosen,(OSRMRouter,GeoapifyMotorcycleRouter,OpenRouteServiceWalkingRouter)) or chosen.__class__.__name__=="MapplsRouter"
 is_demo=isinstance(chosen,MockRouter)
 recommendation={
  "route_id":alternatives[0].get("id"),
  "basis":"Lowest provider-estimated travel time; distance is a tie-breaker. Route-specific safety evidence is unavailable.",
 } if alternatives else None
 limitations=["Synthetic demo metrics are not for navigation.","No route is guaranteed safe."] if is_demo else ["Route comparison is not a safety rating.","No route is guaranteed safe."]
 if len(alternatives)==1:
  if maximum==1:
   limitations.append("NAVIRA requested a maximum of one route; no additional route geometry was requested or fabricated.")
  else:
   limitations.append("The routing provider returned only one distinct road route for these locations; no alternative geometry was fabricated.")
 return {"alternatives":alternatives,"recommendation":recommendation,"safety_evidence":route_evidence,"provider_status":"demo_synthetic" if is_demo else "provider_configured" if configured else "provider_unavailable","provider":"Synthetic demo" if is_demo else getattr(chosen,"provider","OSRM"),"maximum_alternatives":maximum,"compared_at":datetime.now(timezone.utc).isoformat(),"limitations":limitations}

def _point_to_segment_distance_m(latitude:float,longitude:float,a:tuple[float,float],b:tuple[float,float])->float:
 import math
 scale_x=111320*math.cos(math.radians(latitude)); scale_y=110574
 px=0.0; py=0.0
 ax=(a[0]-longitude)*scale_x; ay=(a[1]-latitude)*scale_y
 bx=(b[0]-longitude)*scale_x; by=(b[1]-latitude)*scale_y
 dx=bx-ax; dy=by-ay
 denominator=dx*dx+dy*dy
 ratio=0.0 if denominator==0 else max(0.0,min(1.0,-(ax*dx+ay*dy)/denominator))
 return math.hypot(ax+ratio*dx,ay+ratio*dy)

def distance_to_route_m(latitude:float,longitude:float,geometry:Any)->float|None:
 coordinates=(geometry or {}).get("coordinates") if isinstance(geometry,dict) else None
 if not isinstance(coordinates,list) or len(coordinates)<2: return None
 points=[]
 for coordinate in coordinates:
  if not isinstance(coordinate,(list,tuple)) or len(coordinate)<2: continue
  try:
   lon,lat=float(coordinate[0]),float(coordinate[1])
   if -180<=lon<=180 and -90<=lat<=90: points.append((lon,lat))
  except (TypeError,ValueError): continue
 if len(points)<2: return None
 return min(_point_to_segment_distance_m(latitude,longitude,points[i],points[i+1]) for i in range(len(points)-1))

def match_route_incidents(routes:list[dict[str,Any]],db,now:date|None=None)->dict[str,dict[str,Any]]:
 """Match only review-verified, precisely geocoded newspaper records to route lines."""
 radius_m=max(50,min(int(os.getenv("NAVIRA_ROUTE_INCIDENT_RADIUS_M","500")),5000))
 age_days=max(1,min(int(os.getenv("NAVIRA_ROUTE_INCIDENT_MAX_AGE_DAYS","1095")),3650))
 today=now or date.today()
 cutoff=(today.fromordinal(today.toordinal()-age_days)).isoformat()
 records=[dict(row) for row in db.execute(
  "select n.id,n.article_reference,n.publication_date,n.incident_date,n.category,n.location_precision,n.latitude,n.longitude,n.fingerprint,n.confidence,n.excerpt,s.name as source_name,s.retrieved_at as source_retrieved_at "
  "from news_incidents n join sources s on s.id=n.source_id "
  "where s.source_type='news' and n.review_status='verified' and n.latitude is not null and n.longitude is not null "
  "and n.location_precision in ('address','building','coordinates','exact','landmark','premise','street') "
  "and n.incident_date>=? and n.article_reference like 'http%' order by n.incident_date desc",(cutoff,))]
 deduplicated=[]; seen=set()
 for record in records:
  fingerprint=record.get("fingerprint")
  if not fingerprint or fingerprint==hashlib.sha256(b"").hexdigest(): fingerprint=record["article_reference"]
  fingerprint=fingerprint or f"record:{record['id']}"
  if fingerprint in seen: continue
  seen.add(fingerprint); deduplicated.append(record)
 result={}
 for route in routes:
  geometry_available=len(_sample_route_geometry(route.get("geometry")))>=2
  matched=[]
  for record in deduplicated:
   distance=distance_to_route_m(float(record["latitude"]),float(record["longitude"]),route.get("geometry"))
   if distance is not None and distance<=radius_m:
    matched.append({
     "incident_date":record["incident_date"],"publication_date":record["publication_date"],
     "category":record["category"],"location_precision":record["location_precision"],
     "source_url":record["article_reference"],"source_name":record["source_name"],
     "source_retrieved_at":record["source_retrieved_at"],"distance_m":round(distance),
    })
  matched.sort(key=lambda item:(item["distance_m"],item["incident_date"] or ""))
  result[str(route.get("id"))]={
   "status":"geometry_unavailable" if not geometry_available else "matched_reports" if matched else "no_route_matches" if deduplicated else "insufficient_route_level_evidence",
   "risk_score":None,
   "matched_incidents":len(matched) if deduplicated and geometry_available else None,
   "eligible_records_in_window":len(deduplicated),
   "proximity_radius_m":radius_m,"incident_window_days":age_days,
   "reports":matched,
   "reason":"Verified, geocoded newspaper reports are observational and do not provide a complete incident denominator; no numeric risk score is justified." if deduplicated else "No review-verified, geocoded newspaper records in the configured time window are available for route matching.",
  }
 return result

def assess_route_safety(news_evidence:dict[str,Any])->dict[str,Any]:
 """Return an evidence-gated assessment without converting incomplete data into safety odds."""
 matched=news_evidence.get("matched_incidents")
 if news_evidence.get("status")=="geometry_unavailable":
  summary="Insufficient evidence: this route has no usable geometry for incident matching."
 elif matched:
  summary=f"{matched} verified newspaper report(s) matched this route, but the incomplete sample cannot establish route-level risk."
 elif matched==0:
  summary="No eligible newspaper reports matched this route; this is not evidence that it is safe."
 else:
  summary="Insufficient evidence: no eligible, verified, geolocated newspaper sample is available for this route."
 return {
  "status":"insufficient_evidence",
  "label":"Insufficient evidence",
  "estimated_safety_percentage":None,
  "summary":summary,
  "coverage":{
   "newspaper_incidents":{
    "status":news_evidence.get("status","unavailable"),
    "matched_reports":matched,
    "eligible_records_in_window":news_evidence.get("eligible_records_in_window",0),
    "quality":"Review-verified, dated, source-linked, precise coordinates; source coverage is incomplete.",
   },
   "historical_official_statistics":{
    "status":"aggregate_only",
    "quality":"Official historical aggregates are not spatially assignable to this route.",
   },
   "traffic":{
    "status":"separate_context",
    "quality":"Live traffic observations and provider-estimated delays are not personal-safety indicators.",
   },
   "infrastructure":{
    "status":"unavailable",
    "quality":"No geocoded, route-covering lighting or pedestrian-activity audit is configured.",
   },
  },
  "method":{
   "name":"Evidence-gated route safety assessment",
   "score_status":"withheld",
   "features":["verified geolocated newspaper reports","route-compatible official incident rates","fresh route-level traffic observations","geocoded infrastructure audits"],
   "weights":None,
   "normalization":"Not applied: the available records lack a route-level incident/exposure denominator and complete, comparable spatial coverage.",
   "reason":"No numeric score is computed because the available indicators cannot be normalized into a defensible route-safety estimate.",
  },
  "limitations":[
   "Newspaper reports reflect editorial and source coverage, not total incidents or route exposure.",
   "Delhi City historical totals cannot be assigned to an individual road, route, or locality.",
   "Traffic conditions are shown as separate travel context and are not treated as a safety signal.",
   "Lighting and pedestrian-activity audits are not available as geocoded route coverage.",
   "Missing data and no matched reports do not indicate zero incidents or prove safety.",
  ],
 }
def sanitize(text:str)->str:
 text=redact(text)
 text=re.sub(r"\b\d{1,5}\s+[\w ]{1,30}\s+(?:street|road|lane|marg)\b","[LOCATION REDACTED]",text,flags=re.I)
 return text[:500]
def emergency()->dict[str,str]:
 number=os.getenv("NAVIRA_EMERGENCY_NUMBER","112")
 return {"country":"India","number":number,"action":"available","dial_uri":"tel:"+number,"status_note":"A dial action is available; NAVIRA cannot confirm that a call was placed or answered."}
