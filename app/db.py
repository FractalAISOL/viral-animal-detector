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
    max_overflow=6,  # max 8 total connections
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

class Subreddit(Base):
    __tablename__ = "subreddits"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    tier = Column(Text, nullable=False, default="tier2")
    enabled = Column(Boolean, nullable=False, default=True)
    poll_interval_s = Column(Integer, nullable=False, default=480)
    added_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class SubredditBaseline(Base):
    __tablename__ = "subreddit_baselines"

    id = Column(Integer, primary_key=True)
    subreddit_id = Column(Integer, ForeignKey("subreddits.id", ondelete="CASCADE"), nullable=False)
    day_type = Column(Text, nullable=False)
    time_bucket = Column(SmallInteger, nullable=False)
    log_score_median = Column(Real, nullable=False, default=0)
    log_score_mad = Column(Real, nullable=False, default=1)
    log_comment_median = Column(Real, nullable=False, default=0)
    log_comment_mad = Column(Real, nullable=False, default=1)
    sample_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    __table_args__ = (
        UniqueConstraint("subreddit_id", "day_type", "time_bucket"),
    )


class VelocityBaseline(Base):
    __tablename__ = "velocity_baselines"

    id = Column(Integer, primary_key=True)
    subreddit_id = Column(Integer, ForeignKey("subreddits.id", ondelete="CASCADE"), nullable=False)
    day_type = Column(Text, nullable=False)
    age_bracket = Column(SmallInteger, nullable=False)
    log_velocity_median = Column(Real, nullable=False, default=0)
    log_velocity_mad = Column(Real, nullable=False, default=1)
    sample_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    __table_args__ = (
        UniqueConstraint("subreddit_id", "day_type", "age_bracket"),
    )


class BaselineSample(Base):
    __tablename__ = "baseline_samples"

    id = Column(BigInteger, primary_key=True)
    subreddit_id = Column(Integer, ForeignKey("subreddits.id", ondelete="CASCADE"), nullable=False)
    day_type = Column(Text, nullable=False)
    time_bucket = Column(SmallInteger, nullable=False)
    log_score = Column(Real, nullable=False)
    log_comments = Column(Real, nullable=False)
    age_bracket = Column(SmallInteger)
    log_velocity = Column(Real)
    sampled_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class EntityCluster(Base):
    __tablename__ = "entity_clusters"

    id = Column(Integer, primary_key=True)
    animal_name = Column(Text)
    species = Column(Text)
    location = Column(Text)
    zoo_or_facility = Column(Text)
    description = Column(Text)
    status = Column(Text, nullable=False, default="active")
    post_count = Column(Integer, nullable=False, default=0)
    total_score = Column(BigInteger, nullable=False, default=0)
    total_comments = Column(Integer, nullable=False, default=0)
    peak_anomaly = Column(Real, nullable=False, default=0)
    alert_level = Column(SmallInteger, nullable=False, default=0)
    last_alert_at = Column(DateTime(timezone=True))
    top_archetype = Column(Text)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_post_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    keys = relationship("ClusterKey", back_populates="cluster", cascade="all, delete-orphan")
    aliases = relationship("ClusterAlias", back_populates="cluster", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="cluster")


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


class Post(Base):
    __tablename__ = "posts"

    reddit_id = Column(Text, primary_key=True)
    subreddit_id = Column(Integer, ForeignKey("subreddits.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    author = Column(Text)
    url = Column(Text)
    permalink = Column(Text, nullable=False)
    post_hint = Column(Text)
    flair = Column(Text)
    created_utc = Column(DateTime(timezone=True), nullable=False)
    is_crosspost = Column(Boolean, nullable=False, default=False)
    crosspost_parent = Column(Text)
    image_hash = Column(BigInteger)
    current_score = Column(Integer, nullable=False, default=0)
    current_comments = Column(Integer, nullable=False, default=0)
    upvote_ratio = Column(Real)
    anomaly_score = Column(Real, nullable=False, default=0)
    alert_level = Column(SmallInteger, nullable=False, default=0)
    last_alert_at = Column(DateTime(timezone=True))
    tracking_active = Column(Boolean, nullable=False, default=True)
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="SET NULL"))
    extracted_species = Column(Text)
    extracted_location = Column(Text)
    extracted_name = Column(Text)
    top_archetype = Column(Text)
    narrative_score = Column(Real, nullable=False, default=0)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_scored_at = Column(DateTime(timezone=True))
    next_score_at = Column(DateTime(timezone=True))

    cluster = relationship("EntityCluster", back_populates="posts")
    score_history = relationship("ScoreHistory", back_populates="post", cascade="all, delete-orphan")


class ScoreHistory(Base):
    __tablename__ = "score_history"

    id = Column(BigInteger, primary_key=True)
    post_id = Column(Text, ForeignKey("posts.reddit_id", ondelete="CASCADE"), nullable=False)
    score = Column(Integer, nullable=False)
    num_comments = Column(Integer, nullable=False)
    upvote_ratio = Column(Real)
    score_velocity = Column(Real)
    log_score_z = Column(Real)
    log_comment_z = Column(Real)
    velocity_z = Column(Real)
    anomaly_score = Column(Real)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    post = relationship("Post", back_populates="score_history")


class AuthorActivity(Base):
    __tablename__ = "author_activity"

    username = Column(Text, primary_key=True)
    first_seen = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    total_posts = Column(Integer, nullable=False, default=0)


class FlaggedAuthor(Base):
    __tablename__ = "flagged_authors"

    username = Column(Text, primary_key=True)
    reason = Column(Text, nullable=False)
    score_multiplier = Column(Real, nullable=False, default=0.3)
    flagged_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    notes = Column(Text)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    alert_type = Column(Text, nullable=False)
    alert_level = Column(SmallInteger, nullable=False)
    post_id = Column(Text, ForeignKey("posts.reddit_id", ondelete="SET NULL"))
    cluster_id = Column(Integer, ForeignKey("entity_clusters.id", ondelete="SET NULL"))
    message_text = Column(Text, nullable=False)
    telegram_msg_id = Column(BigInteger)
    sent_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id = Column(Integer, primary_key=True)
    check_type = Column(Text, nullable=False)
    posts_scanned = Column(Integer, default=0)
    posts_tracked = Column(Integer, default=0)
    clusters_active = Column(Integer, default=0)
    alerts_sent = Column(Integer, default=0)
    api_calls_hour = Column(Integer, default=0)
    errors = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now_utc)
