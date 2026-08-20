from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, SmallInteger, Text, Real,
    Boolean, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, Index,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import QueuePool
from datetime import datetime, timezone

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=2,
    max_overflow=6,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def now_utc():
    return datetime.now(timezone.utc)


# --- Models ---

class Source(Base):
    """A feed source — subreddit RSS, HN, etc."""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    source_type = Column(Text, nullable=False, default="reddit")
    tier = Column(Text, nullable=False, default="niche")
    enabled = Column(Boolean, nullable=False, default=True)
    poll_interval_s = Column(Integer, nullable=False, default=180)
    added_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class Item(Base):
    """A discovered item from any source (Reddit post, HN story, etc.)."""
    __tablename__ = "items"

    id = Column(Text, primary_key=True)  # source-prefixed: reddit:abc123, hn:12345
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(Text, nullable=False)  # reddit, hackernews, youtube
    title = Column(Text, nullable=False)
    url = Column(Text)
    author = Column(Text)
    permalink = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False)
    image_url = Column(Text)
    image_hash = Column(BigInteger)
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="SET NULL"))
    extracted_entity = Column(Text)  # quick extraction from title
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    extra = Column(JSONB)  # source-specific: {hn_score, yt_views, subreddit, etc.}

    cluster = relationship("EntityCluster", back_populates="items")


class EntityCluster(Base):
    """A viral entity/topic — can be animal, meme, movie, event, person, etc."""
    __tablename__ = "entity_clusters"

    id = Column(Integer, primary_key=True)
    entity_name = Column(Text)  # was animal_name
    entity_type = Column(Text)  # animal, meme, movie, event, person, tech, etc.
    description = Column(Text)
    status = Column(Text, nullable=False, default="active")
    mention_count = Column(Integer, nullable=False, default=0)
    source_count = Column(Integer, nullable=False, default=0)  # distinct sources
    sub_count = Column(Integer, nullable=False, default=0)  # distinct subreddits
    youtube_views = Column(BigInteger, nullable=False, default=0)
    youtube_videos = Column(Integer, nullable=False, default=0)
    momentum_score = Column(Real, nullable=False, default=0)
    peak_momentum = Column(Real, nullable=False, default=0)
    alert_level = Column(SmallInteger, nullable=False, default=0)
    last_alert_at = Column(DateTime(timezone=True))
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_item_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    items = relationship("Item", back_populates="cluster")
    aliases = relationship("ClusterAlias", back_populates="cluster", cascade="all, delete-orphan")
    keys = relationship("ClusterKey", back_populates="cluster", cascade="all, delete-orphan")


class ClusterKey(Base):
    __tablename__ = "cluster_keys"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="CASCADE"), nullable=False)
    key_type = Column(Text, nullable=False)
    key_value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    cluster = relationship("EntityCluster", back_populates="keys")

    __table_args__ = (
        UniqueConstraint("key_type", "key_value"),
    )


class ClusterAlias(Base):
    __tablename__ = "cluster_aliases"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="CASCADE"), nullable=False)
    alias = Column(Text, nullable=False)
    source = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    cluster = relationship("EntityCluster", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("cluster_id", "alias"),
    )


class MomentumHistory(Base):
    """Time-series snapshots of entity momentum."""
    __tablename__ = "momentum_history"

    id = Column(BigInteger, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="CASCADE"), nullable=False)
    mention_count = Column(Integer, nullable=False)
    mention_velocity = Column(Real)  # mentions/hour
    source_count = Column(Integer)
    sub_count = Column(Integer)
    momentum_score = Column(Real)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class YouTubeResult(Base):
    """YouTube validation results for entities."""
    __tablename__ = "youtube_results"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="CASCADE"), nullable=False)
    query = Column(Text, nullable=False)
    video_count = Column(Integer, nullable=False, default=0)
    total_views = Column(BigInteger, nullable=False, default=0)
    top_video_id = Column(Text)
    top_video_views = Column(BigInteger)
    top_video_title = Column(Text)
    searched_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    alert_type = Column(Text, nullable=False)
    alert_level = Column(SmallInteger, nullable=False)
    item_id = Column(Text, ForeignKey("items.id", ondelete="SET NULL"))
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="SET NULL"))
    message_text = Column(Text, nullable=False)
    telegram_msg_id = Column(BigInteger)
    sent_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id = Column(Integer, primary_key=True)
    check_type = Column(Text, nullable=False)
    items_discovered = Column(Integer, default=0)
    items_tracked = Column(Integer, default=0)
    clusters_active = Column(Integer, default=0)
    alerts_sent = Column(Integer, default=0)
    errors = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
