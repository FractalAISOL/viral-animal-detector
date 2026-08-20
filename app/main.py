"""Main pipeline orchestrator — multi-source viral moment detector."""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta

from app.config import (
    SCORING_INTERVAL, GEMINI_CLUSTER_INTERVAL, DIGEST_INTERVAL_HOURS,
)
from app.discovery import Discovery
from app.scorer import Scorer
from app.entity import run_gemini_clustering
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
    """Main entry point — runs the multi-source pipeline."""
    logger.info("Viral Moment Detector starting...")

    # Send startup notification
    await telegram.send_message(
        telegram.format_system_message(
            "Viral Moment Detector started.\n"
            "Sources: Reddit RSS + Hacker News + YouTube + Gemini\n"
            "Cold start: collecting data for 1 hour before enabling alerts."
        )
    )

    # Initialize components
    discovery = Discovery()
    scorer = Scorer()

    # Run all tasks concurrently
    results = await asyncio.gather(
        discovery.start(),
        _scoring_loop(scorer),
        _gemini_cluster_loop(),
        _digest_loop(),
        _heartbeat_loop(discovery),
        _daily_cleanup_loop(),
        _daily_summary_loop(),
        _cold_start_monitor(scorer),
        return_exceptions=True,
    )
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Task {i} failed: {result}")


async def _scoring_loop(scorer: Scorer):
    """Run momentum scoring every 2 minutes."""
    while True:
        try:
            await scorer.run_scoring_pass()
        except Exception as e:
            logger.error(f"Scoring loop error: {e}")
        await asyncio.sleep(SCORING_INTERVAL)


async def _gemini_cluster_loop():
    """Run Gemini semantic clustering every 5 minutes."""
    # Initial delay to accumulate some items first
    await asyncio.sleep(120)
    while True:
        try:
            db = SessionLocal()
            try:
                await run_gemini_clustering(db)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Gemini clustering error: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Gemini loop error: {e}")
        await asyncio.sleep(GEMINI_CLUSTER_INTERVAL)


async def _digest_loop():
    """Send Level 1 digest every 4 hours."""
    while True:
        await asyncio.sleep(DIGEST_INTERVAL_HOURS * 3600)
        try:
            await send_digest()
        except Exception as e:
            logger.error(f"Digest error: {e}")


async def _heartbeat_loop(discovery: Discovery):
    """Record heartbeat every 10 minutes."""
    while True:
        try:
            await record_heartbeat(discovery.get_stats())
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        await asyncio.sleep(600)


async def _daily_cleanup_loop():
    """Run cleanup daily at 03:00 UTC."""
    while True:
        now = datetime.now(timezone.utc)
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
    """Disable cold start after 1 hour of data collection."""
    await asyncio.sleep(3600)  # 1 hour
    scorer.cold_start_active = False
    logger.info("Cold start complete — alerts enabled")
    await telegram.send_message(
        telegram.format_system_message(
            "Cold start complete. Monitoring active.\nAlerts are now enabled."
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
