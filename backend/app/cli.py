"""NAVIRA data and model command line."""
import argparse,csv,json,sys,hashlib
from datetime import datetime,timezone
from pathlib import Path
from backend.app.core import connect,init_db
from backend.app.services.agents import quality,validate_official,validate_news,resolve,find_duplicate_candidates,trends,compare,classify_rules,extract_candidate,redact

def load(path):
 p=Path(path); text=p.read_text(encoding="utf-8")
 if p.suffix.lower()==".csv": return list(csv.DictReader(text.splitlines()))
 if p.suffix.lower()==".jsonl": return [json.loads(x) for x in text.splitlines() if x.strip()]
 value=json.loads(text); return value if isinstance(value,list) else value

def source_and_records(path,args):
 value=load(path)
 if isinstance(value,dict): return value.get("source",{}),value.get("records",[])
 source={"name":getattr(args,"source_name",None),"reference":getattr(args,"reference",None),"permission_basis":getattr(args,"permission_basis",None),"geographic_precision":getattr(args,"geographic_precision",None),"version":getattr(args,"version",None)}
 return source,value

def insert_source(db,source,source_type):
 required=("name","reference","permission_basis","geographic_precision")
 missing=[k for k in required if not source.get(k)]
 if missing: raise ValueError("Missing source provenance: "+", ".join(missing))
 cursor=db.execute("insert into sources(source_type,name,reference,permission_basis,retrieved_at,version,geographic_precision,notes) values(?,?,?,?,?,?,?,?)",(source_type,source["name"],source["reference"],source["permission_basis"],source.get("retrieved_at",datetime.now(timezone.utc).isoformat()),source.get("version"),source["geographic_precision"],source.get("notes")))
 return cursor.lastrowid

def main():
 p=argparse.ArgumentParser(prog="navira",description="NAVIRA provenance, analytics, and ML CLI"); sub=p.add_subparsers(dest="command",required=True)
 for name in ("init-db","quality-report","build-trends","find-duplicate-candidates"): sub.add_parser(name)
 for name in ("validate-data","ingest-official","ingest-news","ingest-localities","train-classifier","evaluate-classifier","extract-incidents","resolve-localities","build-route-evidence"):
  q=sub.add_parser(name); q.add_argument("path",nargs="?"); q.add_argument("--dry-run",action="store_true")
  if name=="validate-data": q.add_argument("--kind",choices=("official","news"),required=True)
  if name.startswith("ingest-"):
   q.add_argument("--source-name"); q.add_argument("--reference"); q.add_argument("--permission-basis"); q.add_argument("--geographic-precision"); q.add_argument("--version")
 a=p.parse_args()
 if a.command=="init-db": init_db(); print("Database initialized"); return 0
 init_db()
 if a.command in ("quality-report","build-trends"):
  with connect() as db: result=quality(db) if a.command=="quality-report" else trends(db)
  print(json.dumps(result,indent=2)); return 0
 if a.command in ("validate-data","ingest-official","ingest-news"):
  if not a.path: p.error(a.command+" requires a CSV, JSON, or JSONL path")
  source,rs=source_and_records(a.path,a)
  typ=(a.kind if a.command=="validate-data" else ("official" if a.command.endswith("official") else "news"))
  validator=validate_official if typ=="official" else validate_news
  errors=[]
  for i,r in enumerate(rs):
   e=validator(r)
   if typ=="official" and str(r.get("geography_id","")).casefold() in {"noida","gurugram","gurgaon","faridabad","ghaziabad","alwar"}: e.append("outside Delhi NCT")
   if e: errors.append({"index":i,"errors":e})
  if a.command.startswith("ingest-"):
   missing=[k for k in ("name","reference","permission_basis","geographic_precision") if not source.get(k)]
   if missing: errors.append({"source_errors":["missing "+k for k in missing]})
  if errors: print(json.dumps({"records":len(rs),"invalid":errors},indent=2)); return 1
  if a.command=="validate-data" or a.dry_run:
   print(json.dumps({"records":len(rs),"valid":True,"dry_run":a.dry_run},indent=2)); return 0
  with connect() as db:
   sid=insert_source(db,source,typ)
   for r in rs:
    if typ=="official":
     db.execute("insert into official_stats(source_id,year,geography_id,geography_type,category,count,notes) values(?,?,?,?,?,?,?)",(sid,int(r["year"]),r["geography_id"],r["geography_type"],r["category"],int(r["count"]),r.get("notes")))
    else:
     excerpt=redact(r.get("excerpt","")); fp=hashlib.sha256(excerpt.encode()).hexdigest()
     db.execute("insert into news_incidents(source_id,article_reference,publication_date,incident_date,category,locality_text,locality_id,location_precision,confidence,review_status,excerpt,fingerprint) values(?,?,?,?,?,?,?,?,?,?,?,?)",(sid,r["article_reference"],r.get("publication_date"),r.get("incident_date"),r.get("category"),r.get("locality_text"),r.get("locality_id"),r.get("location_precision","unknown"),r.get("confidence"),r.get("review_status","needs_review"),excerpt,fp))
  print(json.dumps({"records_ingested":len(rs),"source_id":sid,"source_type":typ},indent=2)); return 0
 if a.command=="ingest-localities":
  if not a.path:p.error("ingest-localities requires a JSON gazetteer with source and records")
  val=load(a.path); source=val.get("source",{}); rs=val.get("records",[]); issues=[]
  for i,r in enumerate(rs):
   if not r.get("id") or not r.get("name"): issues.append({"index":i,"error":"id and name are required"})
   if r.get("scope_status","delhi_nct")!="delhi_nct": issues.append({"index":i,"error":"out-of-scope localities are rejected"})
  missing=[k for k in ("name","reference","permission_basis","geographic_precision") if not source.get(k)]
  if missing: issues.append({"source_errors":["missing "+k for k in missing]})
  if issues: print(json.dumps({"invalid":issues},indent=2)); return 1
  if a.dry_run: print(json.dumps({"records":len(rs),"dry_run":True})); return 0
  with connect() as db:
   sid=insert_source(db,source,"gazetteer")
   for r in rs: db.execute("insert or replace into localities(id,name,aliases,scope_status,source_id,boundary_ref) values(?,?,?,?,?,?)",(r["id"],r["name"],json.dumps(r.get("aliases",[])),"delhi_nct",sid,r.get("boundary_ref")))
  print(json.dumps({"localities_ingested":len(rs),"source_id":sid})); return 0
 if a.command in ("train-classifier","evaluate-classifier"):
  if not a.path:p.error(a.command+" needs human-labelled JSON/JSONL rows")
  rs=load(a.path); from backend.app.services.ml import train,evaluate
  result=train(rs,persist=True) if a.command=="train-classifier" else evaluate(rs)
  print(json.dumps(result,indent=2)); return 0 if result.get("status") in ("trained","skipped") else 1
 if a.command=="extract-incidents":
  if not a.path:p.error("extract-incidents requires user-provided JSON/JSONL records")
  result=[]
  for r in load(a.path):
   text=redact(r.get("text",r.get("excerpt","")))
   with connect() as db: candidate=extract_candidate(text,db)
   result.append({"article_reference":r.get("article_reference"),"publication_date":r.get("publication_date"),**candidate,"source_incident_date":r.get("incident_date")})
  print(json.dumps({"mode":"rules_only","records":result},indent=2)); return 0
 if a.command=="resolve-localities":
  if not a.path:p.error("resolve-localities requires a locality mention")
  with connect() as db: result=resolve(db,a.path)
  print(json.dumps(result,indent=2)); return 0
 if a.command=="find-duplicate-candidates":
  with connect() as db: ids=find_duplicate_candidates(db)
  print(json.dumps({"created_candidates":ids,"status":"needs_review"},indent=2)); return 0
 if a.command=="build-route-evidence":
  if not a.path:p.error("build-route-evidence requires JSON with origin and destination")
  request=load(a.path); print(json.dumps(compare(request["origin"],request["destination"]),indent=2)); return 0
 return 0
if __name__=="__main__": sys.exit(main())
