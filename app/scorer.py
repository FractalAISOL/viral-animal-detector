"""Scoring engine — computes anomaly scores and triggers alerts."""

import asyncio
import math
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_, text

from app.db import (
    SessionLocal, Post, ScoreHistory, SubredditBaseline, VelocityBaseline,
    EntityCluster, Alert, FlaggedAuthor, Subreddit,
)
from app.baselines import (
    get_time_bucket, get_day_type, get_velocity_bracket, add_baseline_sample,
)
from app.config import (
    SCORE_WEIGHTS, Z_SCORE_CLAMP, RATIO_MULTIPLIERS, SCORING_SCHEDULE_MINUTES,
    ALERT_LEVEL_1, ALERT_LEVEL_2, ALERT_LEVEL_3,
    ALERT_COOLDOWN_HOURS, ALERT_DAILY_CAP, POST_DEACTIVATE_HOURS,
    FARMER_MAX_POSTS_7D, FARMER_SCORE_MULT, MEDIA_BLOCKLIST,
)
from app.reddit import fetch_post_update
from app import telegram

logger = logging.getLogger(__name__)


def _clamp_z(z: float) -> float:
    return max(Z_SCORE_CLAMP[0], min(Z_SCORE_CLAMP[1], z))


def _get_ratio_mult(ratio: float | None) -> float:
    if ratio is None:
        return 1.0
    for threshold, mult in RATIO_MULTIPLIERS:
        if ratio >= threshold:
            return mult
    return 0.75


def _compute_z(value: float, median_val: float, mad: float) -> float:
    """Compute z-score with MAD. MAD is floored at 0.1 in baseline computation."""
    if mad <= 0:
        return 0.0
    return (value - median_val) / mad


class Scorer:
    def __init__(self, reddit, cold_start_active: bool = True):
        self.reddit = reddit
        self.cold_start_active = cold_start_active

    async def run_scoring_pass(self):
        """Find all posts due for scoring and score them."""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)

            # Find posts due for scoring
            due_posts = db.query(Post).filter(
                and_(
                    Post.tracking_active == True,
                    Post.next_score_at <= now,
                    Post.next_score_at.isnot(None),
                )
            ).all()

            for post in due_posts:
                try:
                    with db.begin_nested():
                        await self._score_post(db, post, now)
                except Exception as e:
                    logger.error(f"Error scoring post {post.reddit_id}: {e}")

            # Deactivate old posts (25hr buffer past final 24hr scoring)
            cutoff = now - timedelta(hours=POST_DEACTIVATE_HOURS)
            db.query(Post).filter(
                and_(
                    Post.tracking_active == True,
                    Post.created_utc <= cutoff,
                )
            ).update({"tracking_active": False, "next_score_at": None})

            db.commit()

        except Exception as e:
            db.rollback()
            logger.error(f"Scoring pass error: {e}")
        finally:
            db.close()

    async def _score_post(self, db, post: Post, now: datetime):
        """Score a single post."""
        # Fetch current stats from Reddit
        update = await asyncio.to_thread(
            fetch_post_update, self.reddit, post.reddit_id
        )
        if not update:
            # Reddit API failed — retry next pass, don't reschedule
            return

        score = update["score"]
        comments = update["num_comments"]
        ratio = update["upvote_ratio"]

        # Compute velocity (score/hr since last check)
        age_minutes = (now - post.created_utc).total_seconds() / 60
        velocity = 0.0
        if post.last_scored_at:
            elapsed_hours = (now - post.last_scored_at).total_seconds() / 3600
            if elapsed_hours > 0:
                score_delta = score - post.current_score
                velocity = score_delta / elapsed_hours
        else:
            # First scoring — velocity since creation
            elapsed_hours = age_minutes / 60
            if elapsed_hours > 0:
                velocity = score / elapsed_hours

        # Get baselines
        dt = post.created_utc
        bucket = get_time_bucket(dt)
        day_type = get_day_type(dt)

        baseline = db.query(SubredditBaseline).filter(
            and_(
                SubredditBaseline.subreddit_id == post.subreddit_id,
                SubredditBaseline.day_type == day_type,
                SubredditBaseline.time_bucket == bucket,
            )
        ).first()

        v_bracket = get_velocity_bracket(age_minutes)
        v_baseline = None
        if v_bracket is not None:
            v_baseline = db.query(VelocityBaseline).filter(
                and_(
                    VelocityBaseline.subreddit_id == post.subreddit_id,
                    VelocityBaseline.day_type == day_type,
                    VelocityBaseline.age_bracket == v_bracket,
                )
            ).first()

        # Compute log z-scores
        log_score = math.log(max(score, 1))
        log_comments = math.log(max(comments + 1, 1))
        log_velocity = math.log(max(velocity + 1, 1))

        if baseline and baseline.sample_count >= 5:
            log_score_z = _clamp_z(_compute_z(
                log_score, baseline.log_score_median, baseline.log_score_mad
            ))
            log_comment_z = _clamp_z(_compute_z(
                log_comments, baseline.log_comment_median, baseline.log_comment_mad
            ))
        else:
            log_score_z = 0.0
            log_comment_z = 0.0

        if v_baseline and v_baseline.sample_count >= 5:
            velocity_z = _clamp_z(_compute_z(
                log_velocity, v_baseline.log_velocity_median, v_baseline.log_velocity_mad
            ))
        else:
            velocity_z = 0.0

        # Compute raw anomaly score
        raw_as = (
            SCORE_WEIGHTS["score"] * log_score_z +
            SCORE_WEIGHTS["comments"] * log_comment_z +
            SCORE_WEIGHTS["velocity"] * velocity_z
        )

        # Apply ratio multiplier
        ratio_mult = _get_ratio_mult(ratio)
        anomaly_score = ratio_mult * raw_as

        # Apply author multiplier (false positive filter)
        author_mult = await self._get_author_multiplier(db, post.author)
        anomaly_score *= author_mult

        # Record score history
        history = ScoreHistory(
            post_id=post.reddit_id,
            score=score,
            num_comments=comments,
            upvote_ratio=ratio,
            score_velocity=velocity,
            log_score_z=log_score_z,
            log_comment_z=log_comment_z,
            velocity_z=velocity_z,
            anomaly_score=anomaly_score,
        )
        db.add(history)

        # Capture old values BEFORE updating post (needed for cluster delta)
        old_score = post.current_score or 0
        old_comments = post.current_comments or 0

        # Update post
        post.current_score = score
        post.current_comments = comments
        post.upvote_ratio = ratio
        post.anomaly_score = anomaly_score
        post.last_scored_at = now

        # Schedule next scoring
        post.next_score_at = self._next_score_time(post.created_utc, now)

        # Add to baseline samples
        add_baseline_sample(
            db, post.subreddit_id, score, comments,
            velocity=velocity, age_minutes=age_minutes, dt=dt,
        )

        # Update entity cluster (atomic)
        if post.cluster_id:
            db.execute(text("""
                UPDATE entity_clusters SET
                    total_score = total_score + :score_delta,
                    total_comments = total_comments + :comment_delta,
                    peak_anomaly = GREATEST(peak_anomaly, :anomaly),
                    last_post_at = GREATEST(last_post_at, :now)
                WHERE id = :cid
            """), {
                "score_delta": score - old_score,
                "comment_delta": comments - old_comments,
                "anomaly": anomaly_score,
                "now": now,
                "cid": post.cluster_id,
            })

        db.flush()

        # Check alert thresholds (skip during cold start)
        if not self.cold_start_active:
            await self._check_alerts(db, post, anomaly_score, velocity, now)

    def _next_score_time(self, created: datetime, now: datetime) -> datetime | None:
        """Compute next scoring time based on logarithmic schedule."""
        age_minutes = (now - created).total_seconds() / 60
        for schedule_min in SCORING_SCHEDULE_MINUTES:
            target = created + timedelta(minutes=schedule_min)
            if target > now:
                return target
        # Past all scheduled scores — deactivate
        return None

    async def _get_author_multiplier(self, db, author: str | None) -> float:
        """Check if author is flagged and return score multiplier."""
        if not author:
            return 1.0

        # Check blocklist
        if author in MEDIA_BLOCKLIST:
            return 0.0

        # Check flagged authors table
        flagged = db.query(FlaggedAuthor).filter(
            FlaggedAuthor.username == author
        ).first()
        if flagged:
            return flagged.score_multiplier

        # Check karma farmer (>20 posts in 7 days in monitored subs)
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        post_count = db.query(Post).filter(
            and_(
                Post.author == author,
                Post.first_seen_at >= seven_days_ago,
            )
        ).count()
        if post_count > FARMER_MAX_POSTS_7D:
            return FARMER_SCORE_MULT

        return 1.0

    async def _check_alerts(self, db, post: Post, anomaly_score: float,
                            velocity: float, now: datetime):
        """Check if post crosses alert thresholds and send alerts."""
        new_level = 0
        if anomaly_score >= ALERT_LEVEL_3:
            new_level = 3
        elif anomaly_score >= ALERT_LEVEL_2:
            new_level = 2
        elif anomaly_score >= ALERT_LEVEL_1:
            new_level = 1

        if new_level == 0:
            return

        # Level transitions only — don't re-alert same level
        if new_level <= post.alert_level:
            return

        # Cooldown check
        if post.last_alert_at:
            hours_since = (now - post.last_alert_at).total_seconds() / 3600
            if hours_since < ALERT_COOLDOWN_HOURS:
                return

        # Daily cap check (Level 3 bypasses)
        if new_level < 3:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            alerts_today = db.query(Alert).filter(
                Alert.sent_at >= today_start
            ).count()
            if alerts_today >= ALERT_DAILY_CAP:
                return

        # Get subreddit name for formatting
        sub = db.query(Subreddit).filter(Subreddit.id == post.subreddit_id).first()
        sub_name = sub.name if sub else "unknown"

        # Build post dict for formatting
        post_dict = {
            "reddit_id": post.reddit_id,
            "subreddit": sub_name,
            "title": post.title,
            "score": post.current_score,
            "num_comments": post.current_comments,
            "anomaly_score": anomaly_score,
            "velocity": velocity,
            "upvote_ratio": post.upvote_ratio,
        }

        # Build cluster dict if available
        cluster_dict = None
        if post.cluster_id:
            cluster = db.query(EntityCluster).filter(
                EntityCluster.id == post.cluster_id
            ).first()
            if cluster:
                # Count distinct subreddits
                sub_count = db.query(Post.subreddit_id).filter(
                    Post.cluster_id == cluster.id
                ).distinct().count()
                cluster_dict = {
                    "animal_name": cluster.animal_name,
                    "species": cluster.species,
                    "location": cluster.location,
                    "post_count": cluster.post_count,
                    "total_score": cluster.total_score,
                    "sub_count": sub_count,
                    "top_archetype": cluster.top_archetype,
                }

        # Format and send
        if new_level == 2:
            msg = telegram.format_level2(post_dict, cluster_dict)
        elif new_level == 3:
            if cluster_dict:
                msg = telegram.format_level3(cluster_dict, post_dict)
            else:
                msg = telegram.format_level2(post_dict, cluster_dict)
        else:
            # Level 1 — will be batched in digest, just log it
            post.alert_level = new_level
            return

        # Send immediate alert (Level 2 and 3)
        msg_id = await telegram.send_message(msg)

        # Record alert
        alert = Alert(
            alert_type="upgrade" if post.alert_level > 0 else "post",
            alert_level=new_level,
            post_id=post.reddit_id,
            cluster_id=post.cluster_id,
            message_text=msg,
            telegram_msg_id=msg_id,
        )
        db.add(alert)
        post.alert_level = new_level
        post.last_alert_at = now

        # Update cluster alert level
        if post.cluster_id:
            db.execute(text("""
                UPDATE entity_clusters SET
                    alert_level = GREATEST(alert_level, :level)
                WHERE id = :cid
            """), {"level": new_level, "cid": post.cluster_id})

        db.flush()
        logger.info(f"Alert L{new_level}: {post.title[:60]} (AS={anomaly_score:.1f})")

