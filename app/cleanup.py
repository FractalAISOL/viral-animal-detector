"""Cleanup jobs, digest sender, health monitoring."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_, func, text

from app.db import (
    SessionLocal, Item, EntityCluster, MomentumHistory, YouTubeResult,
    HealthCheck, Alert,
)
from app.config import (
    ALERT_LEVEL_1, ALERT_LEVEL_2, ITEM_RETENTION_DAYS, MOMENTUM_RETENTION_DAYS,
)
from app import telegram

logger = logging.getLogger(__name__)


async def run_daily_cleanup():
    """Run daily cleanup at 03:00 UTC."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # 1. Delete old items (older than retention period)
        cutoff_items = now - timedelta(days=ITEM_RETENTION_DAYS)
        deleted_items = db.query(Item).filter(
            Item.first_seen_at < cutoff_items
        ).delete()
        logger.info(f"Cleanup: deleted {deleted_items} old items")

        # 2. Delete old momentum history
        cutoff_momentum = now - timedelta(days=MOMENTUM_RETENTION_DAYS)
        deleted_momentum = db.query(MomentumHistory).filter(
            MomentumHistory.recorded_at < cutoff_momentum
        ).delete()
        logger.info(f"Cleanup: deleted {deleted_momentum} old momentum records")

        # 3. Delete old health checks
        cutoff_7d = now - timedelta(days=7)
        deleted_health = db.query(HealthCheck).filter(
            HealthCheck.created_at < cutoff_7d
        ).delete()
        logger.info(f"Cleanup: deleted {deleted_health} old health checks")

        # 4. Delete old YouTube results
        cutoff_yt = now - timedelta(days=14)
        deleted_yt = db.query(YouTubeResult).filter(
            YouTubeResult.searched_at < cutoff_yt
        ).delete()
        logger.info(f"Cleanup: deleted {deleted_yt} old YouTube results")

        # 5. Transition entity statuses
        cutoff_24h = now - timedelta(hours=24)
        db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "active",
                EntityCluster.last_item_at < cutoff_24h,
            )
        ).update({"status": "cooling"})

        cutoff_7d_cluster = now - timedelta(days=7)
        db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "cooling",
                EntityCluster.last_item_at < cutoff_7d_cluster,
            )
        ).update({"status": "dormant"})

        cutoff_30d = now - timedelta(days=30)
        db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "dormant",
                EntityCluster.last_item_at < cutoff_30d,
            )
        ).update({"status": "dead"})

        # 6. Reconcile cluster aggregates
        db.execute(text("""
            UPDATE entity_clusters ec SET
                mention_count = COALESCE(sub.cnt, 0)
            FROM (
                SELECT cluster_id, COUNT(*) as cnt
                FROM items WHERE cluster_id IS NOT NULL
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
        # Find entities at L1 that haven't been digested
        digest_clusters = db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "active",
                EntityCluster.mention_count >= ALERT_LEVEL_1,
                EntityCluster.momentum_score < ALERT_LEVEL_2,
                EntityCluster.alert_level < 1,
            )
        ).order_by(EntityCluster.momentum_score.desc()).limit(10).all()

        if not digest_clusters:
            return

        cluster_dicts = []
        for c in digest_clusters:
            # Get most recent item for URL
            lead_item = db.query(Item).filter(
                Item.cluster_id == c.id
            ).order_by(Item.first_seen_at.desc()).first()

            cluster_dicts.append({
                "entity_name": c.entity_name,
                "entity_type": c.entity_type,
                "mention_count": c.mention_count,
                "sub_count": c.sub_count,
                "momentum_score": c.momentum_score,
                "lead_url": lead_item.url if lead_item else None,
            })

        msg = telegram.format_level1_digest(cluster_dicts)
        msg_id = await telegram.send_message(msg)

        if msg_id:
            alert = Alert(
                alert_type="digest",
                alert_level=1,
                message_text=msg,
                telegram_msg_id=msg_id,
            )
            db.add(alert)

            for c in digest_clusters:
                if c.alert_level < 1:
                    c.alert_level = 1

            db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Digest error: {e}")
    finally:
        db.close()


async def record_heartbeat(discovery_stats: dict | None = None):
    """Record a health check heartbeat."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)

        items_24h = db.query(Item).filter(Item.first_seen_at >= cutoff_24h).count()
        active_clusters = db.query(EntityCluster).filter(
            EntityCluster.status == "active"
        ).count()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        alerts_today = db.query(Alert).filter(Alert.sent_at >= today_start).count()

        hc = HealthCheck(
            check_type="heartbeat",
            items_discovered=items_24h,
            items_tracked=discovery_stats.get("total_ingested", 0) if discovery_stats else 0,
            clusters_active=active_clusters,
            alerts_sent=alerts_today,
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

        items_24h = db.query(Item).filter(Item.first_seen_at >= yesterday).count()
        active_clusters = db.query(EntityCluster).filter(
            EntityCluster.status == "active"
        ).count()
        alerts_24h = db.query(Alert).filter(Alert.sent_at >= yesterday).count()

        # Top entities by momentum
        top_clusters = db.query(EntityCluster).filter(
            and_(
                EntityCluster.status == "active",
                EntityCluster.peak_momentum > 0,
            )
        ).order_by(EntityCluster.peak_momentum.desc()).limit(5).all()

        # YouTube/Gemini budget
        from app.youtube import get_daily_usage as yt_usage
        from app.gemini_client import get_daily_usage as gemini_usage
        yt_used, yt_max = yt_usage()
        gem_used, gem_max = gemini_usage()

        lines = [
            f"Items discovered (24h): {items_24h}",
            f"Active entities: {active_clusters}",
            f"Alerts sent (24h): {alerts_24h}",
            f"YouTube budget: {yt_used}/{yt_max}",
            f"Gemini budget: {gem_used}/{gem_max}",
        ]

        if top_clusters:
            lines.append("\nTop entities:")
            for c in top_clusters:
                name = c.entity_name or "Unknown"
                lines.append(
                    f"  - {name}: momentum={c.peak_momentum:.1f}, "
                    f"{c.mention_count} mentions, {c.sub_count} subs"
                )
                if c.youtube_views > 0:
                    lines.append(f"    YT: {c.youtube_views:,} views")

        msg = telegram.format_system_message(
            f"Daily Summary ({now.strftime('%Y-%m-%d')})\n\n" + "\n".join(lines)
        )
        await telegram.send_message(msg)

        hc = HealthCheck(
            check_type="daily_summary",
            items_tracked=items_24h,
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
