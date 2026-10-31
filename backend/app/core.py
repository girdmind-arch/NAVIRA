"""SQLite configuration and schema."""
import os, sqlite3
from pathlib import Path
BACKEND_ROOT=Path(__file__).resolve().parents[2]
DB_PATH=Path(os.getenv("NAVIRA_DB_PATH",str(BACKEND_ROOT/"navira.sqlite3")))
SCHEMA="""
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,source_type TEXT NOT NULL,name TEXT NOT NULL,reference TEXT,permission_basis TEXT NOT NULL,retrieved_at TEXT NOT NULL,version TEXT,geographic_precision TEXT NOT NULL,notes TEXT);
CREATE TABLE IF NOT EXISTS official_stats(id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL,year INTEGER NOT NULL,geography_id TEXT NOT NULL,geography_type TEXT NOT NULL,category TEXT NOT NULL,count INTEGER NOT NULL,notes TEXT,FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS news_incidents(id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL,article_reference TEXT NOT NULL,publication_date TEXT,incident_date TEXT,category TEXT,locality_text TEXT,locality_id TEXT,location_precision TEXT NOT NULL,confidence REAL,review_status TEXT NOT NULL,excerpt TEXT,fingerprint TEXT,latitude REAL,longitude REAL,FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS localities(id TEXT PRIMARY KEY,name TEXT NOT NULL,aliases TEXT NOT NULL DEFAULT '[]',scope_status TEXT NOT NULL DEFAULT 'delhi_nct',source_id INTEGER,boundary_ref TEXT,FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS hazards(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,geography TEXT,category TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'unverified',expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quality_issues(id INTEGER PRIMARY KEY,source_id INTEGER,record_ref TEXT,severity TEXT NOT NULL,issue_type TEXT NOT NULL,explanation TEXT NOT NULL,resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS duplicate_candidates(id INTEGER PRIMARY KEY,record_a INTEGER NOT NULL,record_b INTEGER NOT NULL,features TEXT NOT NULL,score REAL NOT NULL,status TEXT NOT NULL DEFAULT 'needs_review',reviewer_decision TEXT);
-- Route-safety evidence is deliberately separate from the existing aggregate
-- statistics and article triage tables. Empty evidence must remain unknown.
CREATE TABLE IF NOT EXISTS incident_events(
 id TEXT PRIMARY KEY,event_date_start TEXT,event_date_end TEXT,date_precision TEXT NOT NULL DEFAULT 'unknown',
 incident_type_raw TEXT,incident_type_normalized TEXT,event_status TEXT NOT NULL DEFAULT 'reported',
 status_as_of TEXT,summary_neutral TEXT,public_space_relevance TEXT NOT NULL DEFAULT 'unknown',
 sensitivity_flag INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,record_version TEXT NOT NULL DEFAULT '1');
CREATE TABLE IF NOT EXISTS incident_sources(
 id INTEGER PRIMARY KEY,incident_id TEXT NOT NULL,source_id INTEGER NOT NULL,canonical_url TEXT NOT NULL,
 headline TEXT,published_at TEXT,updated_at TEXT,accessed_at TEXT NOT NULL,source_kind TEXT NOT NULL,
 primary_or_secondary TEXT,quoted_location_text TEXT,quoted_date_text TEXT,evidence_location TEXT,
 corroboration_group_id TEXT,source_quality_notes TEXT,
 UNIQUE(incident_id,canonical_url),FOREIGN KEY(incident_id) REFERENCES incident_events(id),FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS place_observations(
 id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,place_role TEXT NOT NULL,place_text_verbatim TEXT,
 normalized_place TEXT,locality TEXT,landmark TEXT,latitude REAL,longitude REAL,coordinate_crs TEXT,
 uncertainty_radius_m REAL,geocode_method TEXT,geocoder_and_version TEXT,location_confidence TEXT NOT NULL DEFAULT 'unresolved',
 privacy_generalization_level TEXT NOT NULL DEFAULT 'coarse',review_status TEXT NOT NULL DEFAULT 'needs_review',
 FOREIGN KEY(incident_id) REFERENCES incident_events(id));
CREATE TABLE IF NOT EXISTS pedestrian_networks(
 id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL,version_date TEXT NOT NULL,license TEXT NOT NULL,
 attribution TEXT NOT NULL,source_url TEXT NOT NULL,notes TEXT,FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS pedestrian_segments(
 id TEXT PRIMARY KEY,network_id INTEGER NOT NULL,osm_way_id TEXT,parent_segment_id TEXT,geometry_geojson TEXT NOT NULL,
 walkable_status TEXT NOT NULL DEFAULT 'unverified',segment_length_m REAL,
 FOREIGN KEY(network_id) REFERENCES pedestrian_networks(id));
CREATE TABLE IF NOT EXISTS street_context_observations(
 id TEXT PRIMARY KEY,segment_id TEXT NOT NULL,source_id INTEGER NOT NULL,observed_at TEXT NOT NULL,
 lighting TEXT,sidewalk_presence TEXT,crossing TEXT,visibility TEXT,active_frontage TEXT,transit_access TEXT,
 crowd_or_activity TEXT,observed_security TEXT,audit_method TEXT NOT NULL,missingness TEXT,license TEXT NOT NULL,
 FOREIGN KEY(segment_id) REFERENCES pedestrian_segments(id),FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS incident_segment_matches(
 id INTEGER PRIMARY KEY,incident_id TEXT NOT NULL,place_id TEXT NOT NULL,segment_id TEXT NOT NULL,
 network_version_date TEXT NOT NULL,distance_to_segment_m REAL,candidate_rank INTEGER,match_method TEXT NOT NULL,
 match_confidence REAL NOT NULL,review_decision TEXT NOT NULL DEFAULT 'needs_review',review_reason TEXT,
 FOREIGN KEY(incident_id) REFERENCES incident_events(id),FOREIGN KEY(place_id) REFERENCES place_observations(id),
 FOREIGN KEY(segment_id) REFERENCES pedestrian_segments(id));
CREATE TABLE IF NOT EXISTS route_safety_import_runs(
 id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL,source_version TEXT,started_at TEXT NOT NULL,finished_at TEXT,
 status TEXT NOT NULL,records_seen INTEGER NOT NULL DEFAULT 0,records_imported INTEGER NOT NULL DEFAULT 0,
 records_skipped INTEGER NOT NULL DEFAULT 0,notes TEXT,FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS news_source_coverage(
 source_id INTEGER PRIMARY KEY,requested_years TEXT NOT NULL DEFAULT '[]',processed_years TEXT NOT NULL DEFAULT '[]',
 missing_years TEXT NOT NULL DEFAULT '[]',gap_reasons TEXT NOT NULL DEFAULT '{}',checkpoint TEXT,last_checked_at TEXT,
 record_count INTEGER NOT NULL DEFAULT 0,coverage_note TEXT,FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS model_runs(id INTEGER PRIMARY KEY,model_name TEXT NOT NULL,version TEXT,dataset_fingerprint TEXT,metrics TEXT NOT NULL,created_at TEXT NOT NULL,config TEXT);
CREATE TABLE IF NOT EXISTS safety_contacts(id TEXT PRIMARY KEY,owner_hash TEXT NOT NULL,name TEXT NOT NULL,phone TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_safety_contacts_owner ON safety_contacts(owner_hash);
CREATE TABLE IF NOT EXISTS safety_location_shares(id TEXT PRIMARY KEY,owner_hash TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,latitude REAL NOT NULL,longitude REAL NOT NULL,accuracy REAL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,revoked_at TEXT);
CREATE INDEX IF NOT EXISTS ix_safety_shares_owner ON safety_location_shares(owner_hash,expires_at);
CREATE TABLE IF NOT EXISTS safety_sos_events(id TEXT PRIMARY KEY,owner_hash TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_safety_sos_owner ON safety_sos_events(owner_hash,created_at);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS trusted_contacts(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,phone TEXT NOT NULL,relationship_label TEXT NOT NULL DEFAULT 'Trusted contact',FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS journeys(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,origin TEXT NOT NULL,destination TEXT NOT NULL,route_id TEXT NOT NULL,route_json TEXT NOT NULL,status TEXT NOT NULL,planned_at TEXT NOT NULL,started_at TEXT,completed_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
"""
def connect():
 DB_PATH.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(DB_PATH); db.row_factory=sqlite3.Row; db.execute("PRAGMA foreign_keys=ON"); return db
def init_db():
 with connect() as db:
  db.executescript(SCHEMA)
  columns={row["name"] for row in db.execute("pragma table_info(news_incidents)")}
  if "latitude" not in columns: db.execute("alter table news_incidents add column latitude REAL")
  if "longitude" not in columns: db.execute("alter table news_incidents add column longitude REAL")
 from sqlalchemy import create_engine
 from sqlalchemy.engine import URL
 from backend.app.models import Base
 engine=create_engine(URL.create("sqlite",database=str(DB_PATH.resolve())))
 Base.metadata.create_all(engine)
 engine.dispose()
