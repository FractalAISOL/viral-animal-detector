"""Multi-source discovery engine — replaces the old Reddit PRAW poller."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_

from app.config import (
    POPULAR_INTERVAL, NICHE_BATCH_INTERVAL, HN_INTERVAL,
    RSS_REQUEST_DELAY, ALL_NICHE_SUBS,
)
from app.db import SessionLocal, Source, Item, EntityCluster, ClusterAlias
from app.reddit_rss import fetch_rss_feed
from app.hackernews import fetch_top_story_ids, fetch_items_batch
from app.entity import match_or_create_entity_fast

logger = logging.getLogger(__name__)


class Discovery:
    def __init__(self):
        self.seen_ids: set[str] = set()
        self._source_id_cache: dict[str, int] = {}
        self._hn_seen_ids: set[int] = set()
        self.stats = {
            "reddit_items": 0,
            "hn_items": 0,
            "total_ingested": 0,
            "rss_errors": 0,
        }

    def _load_seen_ids(self):
        """Load recently seen item IDs from DB."""
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            ids = db.query(Item.id).filter(Item.first_seen_at >= cutoff).all()
            self.seen_ids = {row[0] for row in ids}
            logger.info(f"Loaded {len(self.seen_ids)} seen item IDs")
        finally:
            db.close()

    def _load_source_ids(self):
        """Cache source name -> id mapping."""
        db = SessionLocal()
        try:
            sources = db.query(Source).all()
            self._source_id_cache = {s.name.lower(): s.id for s in sources}
        finally:
            db.close()

    def _get_source_id(self, name: str) -> int | None:
        return self._source_id_cache.get(name.lower())

    async def start(self):
        """Start all discovery loops."""
        self._load_seen_ids()
        self._load_source_ids()
        logger.info(f"Discovery started — {len(self._source_id_cache)} sources loaded")

        await asyncio.gather(
            self._poll_popular(),
            self._poll_niche_subs(),
            self._poll_hackernews(),
            return_exceptions=True,
        )

    async def _poll_popular(self):
        """Poll r/popular/rising every 2 minutes."""
        while True:
            try:
                items = await fetch_rss_feed("popular", "rising")
                if items:
                    await self._ingest_reddit_items(items)
                    logger.debug(f"r/popular: {len(items)} items fetched")
            except Exception as e:
                logger.error(f"r/popular poll error: {e}")
                self.stats["rss_errors"] += 1
            await asyncio.sleep(POPULAR_INTERVAL)

    async def _poll_niche_subs(self):
        """Round-robin poll niche subreddit RSS feeds."""
        sub_index = 0
        while True:
            sub_name = ALL_NICHE_SUBS[sub_index % len(ALL_NICHE_SUBS)]
            try:
                items = await fetch_rss_feed(sub_name, "rising")
                if items:
                    await self._ingest_reddit_items(items)
                    logger.debug(f"r/{sub_name}: {len(items)} items fetched")
            except Exception as e:
                logger.error(f"r/{sub_name} poll error: {e}")
                self.stats["rss_errors"] += 1

            sub_index += 1
            # Respect rate limit between requests
            await asyncio.sleep(RSS_REQUEST_DELAY)

            # After a full cycle, sleep until next batch interval
            if sub_index % len(ALL_NICHE_SUBS) == 0:
                remaining = NICHE_BATCH_INTERVAL - (len(ALL_NICHE_SUBS) * RSS_REQUEST_DELAY)
                if remaining > 0:
                    await asyncio.sleep(remaining)

    async def _poll_hackernews(self):
        """Poll HN top stories every 5 minutes, diff-based."""
        while True:
            try:
                story_ids = await fetch_top_story_ids(limit=100)
                # Only fetch new stories we haven't seen
                new_ids = [sid for sid in story_ids if sid not in self._hn_seen_ids]
                if new_ids:
                    stories = await fetch_items_batch(new_ids[:30])  # Cap per batch
                    self._hn_seen_ids.update(new_ids)
                    if stories:
                        await self._ingest_hn_items(stories)
                        logger.debug(f"HN: {len(stories)} new stories")

                # Cap seen IDs
                if len(self._hn_seen_ids) > 10000:
                    self._hn_seen_ids = set(list(self._hn_seen_ids)[-5000:])

            except Exception as e:
                logger.error(f"HN poll error: {e}")
            await asyncio.sleep(HN_INTERVAL)

    async def _ingest_reddit_items(self, items: list[dict]):
        """Ingest Reddit RSS items into the database."""
        for item_data in items:
            item_id = item_data["id"]
            if item_id in self.seen_ids:
                continue
            self.seen_ids.add(item_id)

            # Cap seen_ids
            if len(self.seen_ids) > 50000:
                self.seen_ids = set(list(self.seen_ids)[:25000])

            subreddit = item_data.get("subreddit", "unknown")
            source_id = self._get_source_id(subreddit)
            if not source_id:
                # Try to find or skip — might be a sub from r/popular not in our list
                source_id = self._get_source_id("popular")
                if not source_id:
                    continue

            db = SessionLocal()
            try:
                item = Item(
                    id=item_id,
                    source_id=source_id,
                    source_type="reddit",
                    title=item_data["title"],
                    url=item_data["url"],
                    author=item_data.get("author"),
                    permalink=item_data.get("permalink"),
                    created_at=item_data["created_at"],
                    image_url=item_data.get("image_url"),
                    extra={"subreddit": subreddit},
                )
                db.add(item)

                # Fast entity matching (n-gram + Jaccard, no Gemini here)
                match_or_create_entity_fast(db, item)

                db.commit()
                self.stats["reddit_items"] += 1
                self.stats["total_ingested"] += 1

            except Exception as e:
                db.rollback()
                # Likely duplicate key — skip silently
                if "duplicate key" not in str(e).lower():
                    logger.error(f"Ingest error {item_id}: {e}")
            finally:
                db.close()

    async def _ingest_hn_items(self, items: list[dict]):
        """Ingest HN stories into the database."""
        hn_source_id = self._get_source_id("hackernews")
        if not hn_source_id:
            return

        for item_data in items:
            item_id = item_data["id"]
            if item_id in self.seen_ids:
                continue
            self.seen_ids.add(item_id)

            db = SessionLocal()
            try:
                item = Item(
                    id=item_id,
                    source_id=hn_source_id,
                    source_type="hackernews",
                    title=item_data["title"],
                    url=item_data["url"],
                    author=item_data.get("author"),
                    permalink=item_data.get("permalink"),
                    created_at=item_data["created_at"],
                    extra=item_data.get("extra"),
                )
                db.add(item)

                match_or_create_entity_fast(db, item)

                db.commit()
                self.stats["hn_items"] += 1
                self.stats["total_ingested"] += 1

            except Exception as e:
                db.rollback()
                if "duplicate key" not in str(e).lower():
                    logger.error(f"HN ingest error {item_id}: {e}")
            finally:
                db.close()

    def get_stats(self) -> dict:
        return self.stats.copy()
