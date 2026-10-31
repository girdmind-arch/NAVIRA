"""SQLAlchemy 2.x domain schema. Text JSON fields keep the SQLite demo portable."""
from sqlalchemy import Integer,String,Text,Float,ForeignKey,Index
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column

class Base(DeclarativeBase): pass
class SourceRecord(Base):
 __tablename__="sources"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); source_type:Mapped[str]=mapped_column(String(40),nullable=False); name:Mapped[str]=mapped_column(String(240),nullable=False); reference:Mapped[str|None]=mapped_column(Text); permission_basis:Mapped[str]=mapped_column(Text,nullable=False); retrieved_at:Mapped[str]=mapped_column(String(40),nullable=False); version:Mapped[str|None]=mapped_column(String(100)); geographic_precision:Mapped[str]=mapped_column(String(80),nullable=False); notes:Mapped[str|None]=mapped_column(Text)
class OfficialCrimeStat(Base):
 __tablename__="official_stats"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); source_id:Mapped[int]=mapped_column(ForeignKey("sources.id"),nullable=False); year:Mapped[int]=mapped_column(Integer,nullable=False); geography_id:Mapped[str]=mapped_column(String(200),nullable=False); geography_type:Mapped[str]=mapped_column(String(40),nullable=False); category:Mapped[str]=mapped_column(String(120),nullable=False); count:Mapped[int]=mapped_column(Integer,nullable=False); notes:Mapped[str|None]=mapped_column(Text)
 __table_args__=(Index("ix_official_year_geo_cat","year","geography_id","category"),)
class NewsIncident(Base):
 __tablename__="news_incidents"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); source_id:Mapped[int]=mapped_column(ForeignKey("sources.id"),nullable=False); article_reference:Mapped[str]=mapped_column(Text,nullable=False); publication_date:Mapped[str|None]=mapped_column(String(40)); incident_date:Mapped[str|None]=mapped_column(String(40)); category:Mapped[str|None]=mapped_column(String(120)); locality_text:Mapped[str|None]=mapped_column(Text); locality_id:Mapped[str|None]=mapped_column(String(160)); location_precision:Mapped[str]=mapped_column(String(80),nullable=False); confidence:Mapped[float|None]=mapped_column(Float); review_status:Mapped[str]=mapped_column(String(40),nullable=False); excerpt:Mapped[str|None]=mapped_column(Text); fingerprint:Mapped[str|None]=mapped_column(String(64)); latitude:Mapped[float|None]=mapped_column(Float); longitude:Mapped[float|None]=mapped_column(Float)
 __table_args__=(Index("ix_news_incident_date_locality","incident_date","locality_id"),)
class Locality(Base):
 __tablename__="localities"
 id:Mapped[str]=mapped_column(String(160),primary_key=True); name:Mapped[str]=mapped_column(String(240),nullable=False); aliases:Mapped[str]=mapped_column(Text,nullable=False,default="[]"); scope_status:Mapped[str]=mapped_column(String(40),nullable=False,default="delhi_nct"); source_id:Mapped[int|None]=mapped_column(ForeignKey("sources.id")); boundary_ref:Mapped[str|None]=mapped_column(Text)
class SafetyAudit(Base):
 __tablename__="safety_audits"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); source_id:Mapped[int]=mapped_column(ForeignKey("sources.id"),nullable=False); locality_id:Mapped[str|None]=mapped_column(ForeignKey("localities.id")); audit_date:Mapped[str]=mapped_column(String(40),nullable=False); fields_json:Mapped[str]=mapped_column(Text,nullable=False); geometry_ref:Mapped[str|None]=mapped_column(Text)
class CommunityHazard(Base):
 __tablename__="hazards"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); created_at:Mapped[str]=mapped_column(String(40),nullable=False); geography:Mapped[str|None]=mapped_column(String(160)); category:Mapped[str]=mapped_column(String(80),nullable=False); description:Mapped[str]=mapped_column(String(500),nullable=False); status:Mapped[str]=mapped_column(String(40),nullable=False,default="unverified"); expires_at:Mapped[str]=mapped_column(String(40),nullable=False)
class DuplicateCandidate(Base):
 __tablename__="duplicate_candidates"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); record_a:Mapped[int]=mapped_column(ForeignKey("news_incidents.id"),nullable=False); record_b:Mapped[int]=mapped_column(ForeignKey("news_incidents.id"),nullable=False); features:Mapped[str]=mapped_column(Text,nullable=False); score:Mapped[float]=mapped_column(Float,nullable=False); status:Mapped[str]=mapped_column(String(40),nullable=False,default="needs_review"); reviewer_decision:Mapped[str|None]=mapped_column(String(80))
class DataQualityIssue(Base):
 __tablename__="quality_issues"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); source_id:Mapped[int|None]=mapped_column(ForeignKey("sources.id")); record_ref:Mapped[str|None]=mapped_column(String(200)); severity:Mapped[str]=mapped_column(String(20),nullable=False); issue_type:Mapped[str]=mapped_column(String(80),nullable=False); explanation:Mapped[str]=mapped_column(Text,nullable=False); resolved:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
class ModelRun(Base):
 __tablename__="model_runs"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); model_name:Mapped[str]=mapped_column(String(120),nullable=False); version:Mapped[str|None]=mapped_column(String(40)); dataset_fingerprint:Mapped[str|None]=mapped_column(String(64)); metrics:Mapped[str]=mapped_column(Text,nullable=False); created_at:Mapped[str]=mapped_column(String(40),nullable=False); config:Mapped[str|None]=mapped_column(Text)
class RouteEvidence(Base):
 __tablename__="route_evidence"
 id:Mapped[int]=mapped_column(Integer,primary_key=True); provider:Mapped[str]=mapped_column(String(120),nullable=False); created_at:Mapped[str]=mapped_column(String(40),nullable=False); origin_label:Mapped[str|None]=mapped_column(String(200)); destination_label:Mapped[str|None]=mapped_column(String(200)); alternatives_json:Mapped[str]=mapped_column(Text,nullable=False); limitations:Mapped[str]=mapped_column(Text,nullable=False)
