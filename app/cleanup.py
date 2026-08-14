"""Cleanup jobs and health monitoring."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_, text, func

from app.db import (
    SessionLocal, Post, EntityCluster, BaselineSample, ScoreHistory,
    HealthCheck, Alert, Subreddit,
)
from app.config import ALERT_LEVEL_1, ALERT_LEVEL_2
from app import telegram

logger = logging.getLogger(__name__)


async def run_daily_cleanup():
    """Run daily cleanup at 03:00 UTC."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # 1. Delete baseline_samples older than 14 days
        cutoff_14d = now - timedelta(days=14)
        deleted_samples = db.query(BaselineSample).filter(
            BaselineSample.sampled_at < cutoff_14d
        ).delete()
        logger.info(f"Cleanup: deleted {deleted_samples} old baseline samples")

        # 2. Delete score_history older than 30 days for inactive posts
        cutoff_30d = now - timedelta(days=30)
        inactive_ids = db.query(Post.reddit_id).filter(
            Post.tracking_active == False
        ).subquery()
        deleted_history = db.query(ScoreHistory).filter(
            and_(
                ScoreHistory.post_id.in_(inactive_ids),
                ScoreHistory.recorded_at < cutoff_30d,
            )
        ).delete(synchronize_session=False)
        logger.info(f"Cleanup: deleted {deleted_history} old score history rows")

        # 3. Delete health_checks older than 7 days
        cutoff_7d = now - timedelta(days=7)
        deleted_health = db.query(HealthCheck).filter(
            HealthCheck.created_at < cutoff_7d
        ).delete()
        logger.info(f"Cleanup: deleted {deleted_health} old health checks")

        # 4. Transition entity statuses
        # active → cooling (no posts in 24hrs)
        cutoff_24h = now - timedelta(hours=24)
        db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "active",
                EntityCluster.last_post_at < cutoff_24h,
            )
        ).update({"status": "cooling"})

        # cooling → dormant (no posts in 7 days)
        cutoff_7d_cluster = now - timedelta(days=7)
        db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "cooling",
                EntityCluster.last_post_at < cutoff_7d_cluster,
            )
        ).update({"status": "dormant"})

        # dormant → dead (no posts in 30 days)
        cutoff_30d_cluster = now - timedelta(days=30)
        db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "dormant",
                EntityCluster.last_post_at < cutoff_30d_cluster,
            )
        ).update({"status": "dead"})

        # 5. Reconcile cluster aggregates (safety net)
        db.execute(text("""
            UPDATE entity_clusters ec SET
                post_count = sub.cnt,
                total_score = sub.total_s,
                total_comments = sub.total_c
            FROM (
                SELECT cluster_id,
                       COUNT(*) as cnt,
                       COALESCE(SUM(current_score), 0) as total_s,
                       COALESCE(SUM(current_comments), 0) as total_c
                FROM posts
                WHERE cluster_id IS NOT NULL
                GROUP BY cluster_id
            ) sub
            WHERE ec.id = sub.cluster_id
        """))

        db.commit()
        logger.info("Daily cleanup complete")

    except Exception as e:
        db.rollback()
        logger.error(f"Cleanup error: {e}")
    finally:
        db.close()


async def send_digest():
    """Send Level 1 digest every 4 hours."""
    db = SessionLocal()
    try:
        # Find posts at L1 that haven't been included in a digest yet
        cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
        digest_posts = db.query(Post).filter(
            and_(
                Post.anomaly_score >= ALERT_LEVEL_1,
                Post.anomaly_score < ALERT_LEVEL_2,
                Post.alert_level < 1,
                Post.last_scored_at >= cutoff,
                Post.tracking_active == True,
            )
        ).order_by(Post.anomaly_score.desc()).limit(10).all()

        if not digest_posts:
            return

        # Build post dicts
        post_dicts = []
        for p in digest_posts:
            sub = db.query(Subreddit).filter(Subreddit.id == p.subreddit_id).first()
            # Fetch latest velocity from score history
            latest_sh = db.query(ScoreHistory).filter(
                ScoreHistory.post_id == p.reddit_id
            ).order_by(ScoreHistory.recorded_at.desc()).first()
            velocity = latest_sh.score_velocity if latest_sh and latest_sh.score_velocity else 0
            post_dicts.append({
                "reddit_id": p.reddit_id,
                "subreddit": sub.name if sub else "unknown",
                "title": p.title,
                "score": p.current_score,
                "num_comments": p.current_comments,
                "anomaly_score": p.anomaly_score,
                "velocity": velocity,
                "upvote_ratio": p.upvote_ratio,
            })

        msg = telegram.format_level1_digest(post_dicts)
        msg_id = await telegram.send_message(msg)

        if msg_id:
            alert = Alert(
                alert_type="digest",
                alert_level=1,
                message_text=msg,
                telegram_msg_id=msg_id,
            )
            db.add(alert)

            # Mark posts as alerted
            for p in digest_posts:
                if p.alert_level < 1:
                    p.alert_level = 1

            db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Digest error: {e}")
    finally:
        db.close()


async def record_heartbeat(poller_stats: dict | None = None):
    """Record a health check heartbeat."""
    db = SessionLocal()
    try:
        tracked = db.query(Post).filter(Post.tracking_active == True).count()
        active_clusters = db.query(EntityCluster).filter(
            EntityCluster.status == "active"
        ).count()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        alerts_today = db.query(Alert).filter(Alert.sent_at >= today_start).count()

        hc = HealthCheck(
            check_type="heartbeat",
            posts_tracked=tracked,
            clusters_active=active_clusters,
            alerts_sent=alerts_today,
            api_calls_hour=poller_stats.get("api_calls", 0) if poller_stats else 0,
        )
        db.add(hc)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Heartbeat error: {e}")
    finally:
        db.close()


async def send_daily_summary():
    """Send daily summary at 09:00 UTC."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)

        tracked = db.query(Post).filter(Post.tracking_active == True).count()
        new_posts_24h = db.query(Post).filter(
            Post.first_seen_at >= yesterday
        ).count()
        active_clusters = db.query(EntityCluster).filter(
            EntityCluster.status == "active"
        ).count()
        alerts_24h = db.query(Alert).filter(Alert.sent_at >= yesterday).count()

        # Top entities
        top_clusters = db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "active",
                EntityCluster.peak_anomaly > 0,
            )
        ).order_by(EntityCluster.peak_anomaly.desc()).limit(5).all()

        lines = [
            f"Posts tracked: {tracked}",
            f"New posts (24h): {new_posts_24h}",
            f"Active entities: {active_clusters}",
            f"Alerts sent (24h): {alerts_24h}",
        ]

        if top_clusters:
            lines.append("\nTop entities:")
            for c in top_clusters:
                name = c.animal_name or c.species or "Unknown"
                lines.append(f"  - {name}: AS={c.peak_anomaly:.1f}, {c.post_count} posts")

        msg = telegram.format_system_message(
            f"Daily Summary ({now.strftime('%Y-%m-%d')})\n\n" + "\n".join(lines)
        )
        await telegram.send_message(msg)

        # Record as health check
        hc = HealthCheck(
            check_type="daily_summary",
            posts_tracked=tracked,
            clusters_active=active_clusters,
            alerts_sent=alerts_24h,
        )
        db.add(hc)
        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Daily summary error: {e}")
    finally:
        db.close()
