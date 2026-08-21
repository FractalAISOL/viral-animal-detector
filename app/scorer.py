"""Momentum scoring engine — scores entities by mention velocity and cross-source spread."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_, text, func

from app.db import (
    SessionLocal, Item, EntityCluster, MomentumHistory, YouTubeResult, Alert, Source,
)
from app.config import (
    ALERT_LEVEL_1, ALERT_LEVEL_2, ALERT_LEVEL_3,
    ALERT_L1_MIN_SUBS, ALERT_L1_WINDOW_HOURS,
    ALERT_L2_MIN_SUBS, ALERT_L2_WINDOW_HOURS,
    ALERT_L3_MIN_SUBS, ALERT_L3_WINDOW_HOURS,
    ALERT_COOLDOWN_HOURS, ALERT_DAILY_CAP,
    YT_VALIDATION_MIN_MENTIONS, YT_VIRAL_VIEW_THRESHOLD,
)
from app import youtube
from app import telegram

logger = logging.getLogger(__name__)


class Scorer:
    def __init__(self):
        self.cold_start_active = True

    async def run_scoring_pass(self):
        """Score all active entity clusters."""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)

            active_clusters = db.query(EntityCluster).filter(
                EntityCluster.status == "active"
            ).all()

            for cluster in active_clusters:
                try:
                    await self._score_cluster(db, cluster, now)
                except Exception as e:
                    logger.error(f"Error scoring cluster {cluster.id}: {e}")

            db.commit()

        except Exception as e:
            db.rollback()
            logger.error(f"Scoring pass error: {e}")
        finally:
            db.close()

    async def _score_cluster(self, db, cluster: EntityCluster, now: datetime):
        """Score a single entity cluster based on mention momentum."""
        # Count mentions in different time windows
        windows = {
            "1h": now - timedelta(hours=1),
            "2h": now - timedelta(hours=2),
            "4h": now - timedelta(hours=4),
            "6h": now - timedelta(hours=6),
            "24h": now - timedelta(hours=24),
        }

        mention_counts = {}
        for label, cutoff in windows.items():
            count = db.query(Item).filter(
                and_(
                    Item.cluster_id == cluster.id,
                    Item.first_seen_at >= cutoff,
                )
            ).count()
            mention_counts[label] = count

        # Count distinct subreddits in 6h window
        sub_count = db.query(
            func.count(func.distinct(Item.extra["subreddit"].astext))
        ).filter(
            and_(
                Item.cluster_id == cluster.id,
                Item.first_seen_at >= windows["6h"],
                Item.extra["subreddit"].astext.isnot(None),
            )
        ).scalar() or 0

        # Count distinct source types
        source_count = db.query(
            func.count(func.distinct(Item.source_type))
        ).filter(
            and_(
                Item.cluster_id == cluster.id,
                Item.first_seen_at >= windows["24h"],
            )
        ).scalar() or 0

        # Compute mention velocity (mentions/hour over last 2 hours)
        mentions_2h = mention_counts["2h"]
        velocity = mentions_2h / 2.0 if mentions_2h > 0 else 0

        # Compute momentum score
        # Formula: velocity * source_diversity * youtube_boost
        source_mult = 1.0 + (sub_count * 0.3) + (source_count * 0.5)
        yt_boost = 1.0
        if cluster.youtube_views > 0:
            if cluster.youtube_views >= YT_VIRAL_VIEW_THRESHOLD:
                yt_boost = 2.0
            elif cluster.youtube_views >= 10000:
                yt_boost = 1.5
            elif cluster.youtube_views >= 1000:
                yt_boost = 1.2

        momentum = velocity * source_mult * yt_boost

        # Update cluster
        cluster.mention_count = mention_counts["24h"]
        cluster.source_count = source_count
        cluster.sub_count = sub_count
        cluster.momentum_score = momentum
        if momentum > cluster.peak_momentum:
            cluster.peak_momentum = momentum

        # Record momentum history
        history = MomentumHistory(
            cluster_id=cluster.id,
            mention_count=mention_counts["24h"],
            mention_velocity=velocity,
            source_count=source_count,
            sub_count=sub_count,
            momentum_score=momentum,
        )
        db.add(history)

        # YouTube validation for entities with enough mentions (only once per entity)
        if (mention_counts["4h"] >= YT_VALIDATION_MIN_MENTIONS
                and cluster.entity_name):
            already_searched = db.query(YouTubeResult).filter(
                YouTubeResult.cluster_id == cluster.id
            ).first()
            if not already_searched:
                await self._youtube_validate(db, cluster)

        # Check alert thresholds
        if not self.cold_start_active:
            await self._check_alerts(
                db, cluster, mention_counts, sub_count, source_count, momentum, now
            )

        db.flush()

    async def _youtube_validate(self, db, cluster: EntityCluster):
        """Search YouTube for entity validation."""
        query = cluster.entity_name
        if not query:
            return

        result = await youtube.search_videos(query)
        if not result:
            return

        # Store result
        yt_result = YouTubeResult(
            cluster_id=cluster.id,
            query=query,
            video_count=result["video_count"],
            total_views=result["total_views"],
            top_video_id=result.get("top_video_id"),
            top_video_views=result.get("top_video_views"),
            top_video_title=result.get("top_video_title"),
        )
        db.add(yt_result)

        # Update cluster
        cluster.youtube_views = result["total_views"]
        cluster.youtube_videos = result["video_count"]

        logger.info(
            f"YouTube validation for '{query}': "
            f"{result['video_count']} videos, {result['total_views']:,} views"
        )

    async def _check_alerts(self, db, cluster: EntityCluster,
                            mention_counts: dict, sub_count: int,
                            source_count: int, momentum: float,
                            now: datetime):
        """Check alert thresholds and send notifications."""
        # Determine alert level
        new_level = 0

        # Level 3: 10+ mentions, 5+ subs, YouTube validated
        mentions_6h = mention_counts.get("6h", 0)
        if (mentions_6h >= ALERT_LEVEL_3
                and sub_count >= ALERT_L3_MIN_SUBS
                and cluster.youtube_views > 0):
            new_level = 3

        # Level 2: 5+ mentions, 3+ subs in 2hrs
        elif (mention_counts.get("2h", 0) >= ALERT_LEVEL_2
              and sub_count >= ALERT_L2_MIN_SUBS):
            new_level = 2

        # Level 1: 3+ mentions, 2+ subs in 4hrs
        elif (mention_counts.get("4h", 0) >= ALERT_LEVEL_1
              and sub_count >= ALERT_L1_MIN_SUBS):
            new_level = 1

        if new_level == 0:
            return

        # Don't re-alert same level
        if new_level <= cluster.alert_level:
            return

        # Cooldown check
        if cluster.last_alert_at:
            hours_since = (now - cluster.last_alert_at).total_seconds() / 3600
            if hours_since < ALERT_COOLDOWN_HOURS:
                return

        # Daily cap (L3 bypasses)
        if new_level < 3:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            alerts_today = db.query(Alert).filter(Alert.sent_at >= today_start).count()
            if alerts_today >= ALERT_DAILY_CAP:
                return

        # Build alert message
        cluster_dict = {
            "entity_name": cluster.entity_name,
            "entity_type": cluster.entity_type,
            "mention_count": cluster.mention_count,
            "sub_count": sub_count,
            "source_count": source_count,
            "momentum_score": momentum,
            "youtube_views": cluster.youtube_views,
            "youtube_videos": cluster.youtube_videos,
        }

        # Get lead item (most recent)
        lead_item = db.query(Item).filter(
            Item.cluster_id == cluster.id
        ).order_by(Item.first_seen_at.desc()).first()

        item_dict = None
        if lead_item:
            item_dict = {
                "id": lead_item.id,
                "title": lead_item.title,
                "url": lead_item.url or lead_item.permalink,
                "source_type": lead_item.source_type,
                "subreddit": (lead_item.extra or {}).get("subreddit", ""),
            }

        # Format and send
        if new_level == 1:
            # Level 1 — will be batched in digest
            cluster.alert_level = new_level
            return

        if new_level == 2:
            msg = telegram.format_level2(cluster_dict, item_dict)
        else:
            msg = telegram.format_level3(cluster_dict, item_dict)

        msg_id = await telegram.send_message(msg)

        # Record alert
        alert = Alert(
            alert_type="cluster",
            alert_level=new_level,
            cluster_id=cluster.id,
            item_id=lead_item.id if lead_item else None,
            message_text=msg,
            telegram_msg_id=msg_id,
        )
        db.add(alert)
        cluster.alert_level = new_level
        cluster.last_alert_at = now

        db.flush()
        logger.info(
            f"Alert L{new_level}: {cluster.entity_name} "
            f"({cluster.mention_count} mentions, {sub_count} subs, momentum={momentum:.1f})"
        )
