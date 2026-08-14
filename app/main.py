"""Main pipeline orchestrator — single-writer architecture."""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta

from app.config import DIGEST_INTERVAL_HOURS
from app.reddit import create_reddit_client
from app.poller import Poller
from app.scorer import Scorer
from app.baselines import recompute_baselines, check_cold_start_complete
from app.entity import check_cross_sub_alerts
from app.cleanup import (
    run_daily_cleanup, send_digest, record_heartbeat, send_daily_summary,
)
from app.db import SessionLocal
from app import telegram

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point — runs the single-writer pipeline."""
    logger.info("Viral Animal Momentum Detector starting...")

    # Initialize Reddit client
    try:
        reddit = create_reddit_client()
        # Verify connection
        me = reddit.user.me()
        logger.info(f"Reddit connected as u/{me}")
    except Exception as e:
        logger.error(f"Reddit connection failed: {e}")
        await telegram.send_message(
            telegram.format_system_message(f"STARTUP FAILED: Reddit connection error: {e}")
        )
        return

    # Send startup notification
    await telegram.send_message(
        telegram.format_system_message(
            "Viral Animal Detector started.\n"
            "Cold start mode: collecting baselines for 48 hours.\n"
            "No alerts will be sent during this period."
        )
    )

    # Initialize components
    poller = Poller(reddit)
    scorer = Scorer(reddit, cold_start_active=True)

    # Run all tasks concurrently
    results = await asyncio.gather(
        poller.start(),
        _scoring_loop(scorer),
        _cross_sub_loop(scorer),
        _baseline_loop(),
        _digest_loop(),
        _heartbeat_loop(poller),
        _daily_cleanup_loop(),
        _daily_summary_loop(),
        _cold_start_monitor(scorer),
        return_exceptions=True,
    )
    # Log any task failures
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Task {i} failed: {result}")


async def _scoring_loop(scorer: Scorer):
    """Run scoring every 60 seconds."""
    while True:
        try:
            await scorer.run_scoring_pass()
        except Exception as e:
            logger.error(f"Scoring loop error: {e}")
        await asyncio.sleep(60)


async def _cross_sub_loop(scorer: Scorer):
    """Check cross-sub signals every 5 minutes."""
    while True:
        try:
            db = SessionLocal()
            try:
                await check_cross_sub_alerts(db, scorer.cold_start_active)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Cross-sub check error: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Cross-sub loop error: {e}")
        await asyncio.sleep(300)


async def _baseline_loop():
    """Recompute baselines every hour."""
    while True:
        try:
            db = SessionLocal()
            try:
                recompute_baselines(db)
            except Exception as e:
                db.rollback()
                logger.error(f"Baseline recompute error: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Baseline loop error: {e}")
        await asyncio.sleep(3600)


async def _digest_loop():
    """Send Level 1 digest every 4 hours."""
    while True:
        await asyncio.sleep(DIGEST_INTERVAL_HOURS * 3600)
        try:
            await send_digest()
        except Exception as e:
            logger.error(f"Digest error: {e}")


async def _heartbeat_loop(poller: Poller):
    """Record heartbeat every 10 minutes."""
    while True:
        try:
            await record_heartbeat(poller.get_stats())
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        await asyncio.sleep(600)


async def _daily_cleanup_loop():
    """Run cleanup daily at 03:00 UTC."""
    while True:
        now = datetime.now(timezone.utc)
        # Calculate seconds until next 03:00 UTC
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        try:
            await run_daily_cleanup()
        except Exception as e:
            logger.error(f"Daily cleanup error: {e}")


async def _daily_summary_loop():
    """Send daily summary at 09:00 UTC."""
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        try:
            await send_daily_summary()
        except Exception as e:
            logger.error(f"Daily summary error: {e}")


async def _cold_start_monitor(scorer: Scorer):
    """Monitor cold start status and activate alerts when ready."""
    while scorer.cold_start_active:
        await asyncio.sleep(600)  # Check every 10 minutes
        try:
            db = SessionLocal()
            try:
                ready = await check_cold_start_complete(db)
                if ready:
                    scorer.cold_start_active = False
                    logger.info("Cold start complete — alerts activated")
                    await telegram.send_message(
                        telegram.format_system_message(
                            "Baselines established. Monitoring active.\n"
                            "Alerts are now enabled."
                        )
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Cold start monitor error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
