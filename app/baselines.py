"""Baseline collector and calculator — computes median + MAD for z-scoring."""

import math
import logging
from datetime import datetime, timezone, timedelta
from statistics import median

from sqlalchemy import and_

from app.db import (
    SessionLocal, SubredditBaseline, VelocityBaseline, BaselineSample,
    Subreddit, HealthCheck,
)
from app.config import (
    COLD_START_HOURS, MIN_BASELINE_SAMPLES, TIME_BUCKETS, VELOCITY_BRACKETS,
)
from app import telegram

logger = logging.getLogger(__name__)


def get_time_bucket(dt: datetime) -> int:
    """Return time bucket index (0-5) for a UTC datetime."""
    hour = dt.hour
    for i, (start, end) in enumerate(TIME_BUCKETS):
        if start <= hour < end:
            return i
    return 0


def get_day_type(dt: datetime) -> str:
    """Return 'weekday' or 'weekend'."""
    return "weekend" if dt.weekday() >= 5 else "weekday"


def get_velocity_bracket(age_minutes: float) -> int | None:
    """Return velocity bracket index (0-5) for post age in minutes."""
    for i, (start, end) in enumerate(VELOCITY_BRACKETS):
        if start <= age_minutes < end:
            return i
    return None


def add_baseline_sample(
    db, subreddit_id: int, score: int, comments: int,
    velocity: float | None = None, age_minutes: float | None = None,
    dt: datetime | None = None,
):
    """Add a raw sample to baseline_samples table."""
    if dt is None:
        dt = datetime.now(timezone.utc)

    log_score = math.log(max(score, 1))
    log_comments = math.log(max(comments + 1, 1))

    age_bracket = None
    log_velocity = None
    if velocity is not None and age_minutes is not None:
        age_bracket = get_velocity_bracket(age_minutes)
        log_velocity = math.log(max(velocity + 1, 1))

    sample = BaselineSample(
        subreddit_id=subreddit_id,
        day_type=get_day_type(dt),
        time_bucket=get_time_bucket(dt),
        log_score=log_score,
        log_comments=log_comments,
        age_bracket=age_bracket,
        log_velocity=log_velocity,
    )
    db.add(sample)


def _compute_mad(values: list[float]) -> float:
    """Compute Median Absolute Deviation. Returns 1.0 if insufficient data."""
    if len(values) < 3:
        return 1.0
    med = median(values)
    deviations = [abs(v - med) for v in values]
    mad = median(deviations)
    # MAD can be 0 if data is very uniform — floor at 0.1
    return max(mad, 0.1)


def recompute_baselines(db):
    """
    Recompute all subreddit baselines and velocity baselines
    from the last 14 days of samples. Runs hourly.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    subs = db.query(Subreddit).filter(Subreddit.enabled == True).all()

    for sub in subs:
        for day_type in ["weekday", "weekend"]:
            for bucket in range(6):
                samples = db.query(BaselineSample).filter(
                    and_(
                        BaselineSample.subreddit_id == sub.id,
                        BaselineSample.day_type == day_type,
                        BaselineSample.time_bucket == bucket,
                        BaselineSample.sampled_at >= cutoff,
                    )
                ).all()

                if len(samples) < MIN_BASELINE_SAMPLES:
                    continue

                log_scores = [s.log_score for s in samples]
                log_comments = [s.log_comments for s in samples]

                baseline = db.query(SubredditBaseline).filter(
                    and_(
                        SubredditBaseline.subreddit_id == sub.id,
                        SubredditBaseline.day_type == day_type,
                        SubredditBaseline.time_bucket == bucket,
                    )
                ).first()

                vals = {
                    "log_score_median": median(log_scores),
                    "log_score_mad": _compute_mad(log_scores),
                    "log_comment_median": median(log_comments),
                    "log_comment_mad": _compute_mad(log_comments),
                    "sample_count": len(samples),
                }

                if baseline:
                    for k, v in vals.items():
                        setattr(baseline, k, v)
                else:
                    baseline = SubredditBaseline(
                        subreddit_id=sub.id,
                        day_type=day_type,
                        time_bucket=bucket,
                        **vals,
                    )
                    db.add(baseline)

            # Velocity baselines per age bracket
            for bracket in range(6):
                v_samples = db.query(BaselineSample).filter(
                    and_(
                        BaselineSample.subreddit_id == sub.id,
                        BaselineSample.day_type == day_type,
                        BaselineSample.age_bracket == bracket,
                        BaselineSample.log_velocity.isnot(None),
                        BaselineSample.sampled_at >= cutoff,
                    )
                ).all()

                if len(v_samples) < MIN_BASELINE_SAMPLES:
                    continue

                log_velocities = [s.log_velocity for s in v_samples]

                v_baseline = db.query(VelocityBaseline).filter(
                    and_(
                        VelocityBaseline.subreddit_id == sub.id,
                        VelocityBaseline.day_type == day_type,
                        VelocityBaseline.age_bracket == bracket,
                    )
                ).first()

                vals = {
                    "log_velocity_median": median(log_velocities),
                    "log_velocity_mad": _compute_mad(log_velocities),
                    "sample_count": len(v_samples),
                }

                if v_baseline:
                    for k, v in vals.items():
                        setattr(v_baseline, k, v)
                else:
                    v_baseline = VelocityBaseline(
                        subreddit_id=sub.id,
                        day_type=day_type,
                        age_bracket=bracket,
                        **vals,
                    )
                    db.add(v_baseline)

    db.commit()
    logger.info("Baselines recomputed")


async def check_cold_start_complete(db) -> bool:
    """
    Check if we have enough baseline data to start alerting.
    Returns True if cold start period is over and baselines are ready.
    """
    # Check if we've been running long enough
    first_sample = db.query(BaselineSample).order_by(
        BaselineSample.sampled_at.asc()
    ).first()

    if not first_sample:
        return False

    hours_running = (
        datetime.now(timezone.utc) - first_sample.sampled_at
    ).total_seconds() / 3600

    if hours_running < COLD_START_HOURS:
        return False

    # Check if enough baselines exist
    baseline_count = db.query(SubredditBaseline).filter(
        SubredditBaseline.sample_count >= MIN_BASELINE_SAMPLES
    ).count()

    # Need at least some baselines for Tier 1 subs
    if baseline_count < 10:
        return False

    return True
