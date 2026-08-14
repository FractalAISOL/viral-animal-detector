"""Reddit poller — fetches posts from subreddits on tier-based intervals."""

import logging
import asyncio
from datetime import datetime, timezone, timedelta

import praw
import httpx
import imagehash
from PIL import Image
from io import BytesIO

from app.config import (
    TIER1_SUBS, TIER2_SUBS, INTERNATIONAL_SUBS, INTERNATIONAL_KEYWORDS,
    TIER1_INTERVAL, TIER2_INTERVAL, INTL_INTERVAL, NEWS_INTERVAL,
    NEWS_SUBS, NEWS_QUERIES, MIN_SCORE_GATE, SCORING_SCHEDULE_MINUTES,
    MAX_TRACKED_POSTS,
)
from app.reddit import fetch_rising, fetch_new_filtered, search_news
from app.extraction import extract_all
from app.db import SessionLocal, Post, Subreddit, AuthorActivity
from app.entity import match_or_create_entity

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, reddit: praw.Reddit):
        self.reddit = reddit
        self.seen_ids: set[str] = set()
        self._sub_id_cache: dict[str, int] = {}
        self._stats = {"total_polled": 0, "new_posts": 0, "api_calls": 0}

    def _load_seen_ids(self):
        """Load already-tracked post IDs from DB to avoid reprocessing."""
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            post_ids = db.query(Post.reddit_id).filter(
                Post.first_seen_at >= cutoff
            ).all()
            self.seen_ids = {p[0] for p in post_ids}
            logger.info(f"Loaded {len(self.seen_ids)} seen post IDs from DB")
        finally:
            db.close()

    def _load_sub_ids(self):
        """Cache subreddit name -> id mapping."""
        db = SessionLocal()
        try:
            subs = db.query(Subreddit).all()
            self._sub_id_cache = {s.name.lower(): s.id for s in subs}
        finally:
            db.close()

    def _get_sub_id(self, name: str) -> int | None:
        return self._sub_id_cache.get(name.lower())

    async def start(self):
        """Start all polling loops."""
        self._load_seen_ids()
        self._load_sub_ids()
        logger.info("Poller started")

        await asyncio.gather(
            self._poll_tier("tier1", TIER1_SUBS, TIER1_INTERVAL),
            self._poll_tier("tier2", TIER2_SUBS, TIER2_INTERVAL),
            self._poll_international(),
            self._poll_news(),
        )

    async def _poll_tier(self, tier_name: str, subs: list[str], interval: int):
        """Poll /rising for a tier of subreddits."""
        while True:
            for sub_name in subs:
                try:
                    posts = await asyncio.to_thread(
                        fetch_rising, self.reddit, sub_name
                    )
                    self._stats["api_calls"] += 1
                    await self._process_posts(posts, sub_name)
                except Exception as e:
                    logger.error(f"Error polling r/{sub_name}: {e}")
            await asyncio.sleep(interval)

    async def _poll_international(self):
        """Poll /new for international subs with keyword filter."""
        while True:
            for sub_name in INTERNATIONAL_SUBS:
                try:
                    posts = await asyncio.to_thread(
                        fetch_new_filtered, self.reddit, sub_name, INTERNATIONAL_KEYWORDS
                    )
                    self._stats["api_calls"] += 1
                    await self._process_posts(posts, sub_name)
                except Exception as e:
                    logger.error(f"Error polling intl r/{sub_name}: {e}")
            await asyncio.sleep(INTL_INTERVAL)

    async def _poll_news(self):
        """Search news subreddits for animal-related content."""
        while True:
            for query in NEWS_QUERIES:
                for sub_name in NEWS_SUBS:
                    try:
                        posts = await asyncio.to_thread(
                            search_news, self.reddit, sub_name, query
                        )
                        self._stats["api_calls"] += 1
                        await self._process_posts(posts, sub_name)
                    except Exception as e:
                        logger.error(f"Error searching r/{sub_name} for '{query}': {e}")
            await asyncio.sleep(NEWS_INTERVAL)

    async def _process_posts(self, posts: list[dict], sub_name: str):
        """Process fetched posts: filter, extract, store."""
        for post_data in posts:
            reddit_id = post_data["reddit_id"]

            # Skip already seen
            if reddit_id in self.seen_ids:
                continue
            self.seen_ids.add(reddit_id)
            # Cap seen_ids to prevent unbounded memory growth
            if len(self.seen_ids) > 50000:
                # Evict arbitrary half (sets are unordered; dupes hit PK guard)
                self.seen_ids = set(list(self.seen_ids)[:25000])
            self._stats["total_polled"] += 1

            # Minimum score gate
            if post_data["score"] < MIN_SCORE_GATE:
                continue

            # Skip megathreads / scheduled content
            flair = (post_data.get("flair") or "").lower()
            if any(kw in flair for kw in ["megathread", "weekly", "daily"]):
                continue

            # Run extraction
            extraction = extract_all(post_data["title"], sub_name)

            # Compute image hash if thumbnail available
            image_hash_val = None
            if post_data.get("thumbnail_url"):
                image_hash_val = await self._compute_phash(post_data["thumbnail_url"])

            # Schedule first scoring at 30min after creation
            created = post_data["created_utc"]
            first_score_at = created + timedelta(minutes=SCORING_SCHEDULE_MINUTES[0])

            # Store in DB
            sub_id = self._get_sub_id(sub_name)
            if not sub_id:
                continue

            db = SessionLocal()
            try:
                # Check tracked post ceiling
                tracked_count = db.query(Post).filter(Post.tracking_active == True).count()
                if tracked_count >= MAX_TRACKED_POSTS:
                    # Drop lowest anomaly_score tracked post
                    lowest = db.query(Post).filter(
                        Post.tracking_active == True
                    ).order_by(Post.anomaly_score.asc()).first()
                    if lowest:
                        lowest.tracking_active = False
                        db.flush()

                post = Post(
                    reddit_id=reddit_id,
                    subreddit_id=sub_id,
                    title=post_data["title"],
                    author=post_data["author"],
                    url=post_data["url"],
                    permalink=post_data["permalink"],
                    post_hint=post_data.get("post_hint"),
                    flair=post_data.get("flair"),
                    created_utc=created,
                    is_crosspost=post_data["is_crosspost"],
                    crosspost_parent=post_data.get("crosspost_parent"),
                    image_hash=image_hash_val,
                    current_score=post_data["score"],
                    current_comments=post_data["num_comments"],
                    upvote_ratio=post_data["upvote_ratio"],
                    extracted_species=extraction["species"],
                    extracted_location=extraction["location"],
                    extracted_name=extraction["name"],
                    top_archetype=extraction["top_archetype"],
                    narrative_score=extraction["narrative_score"],
                    next_score_at=first_score_at,
                )
                db.add(post)

                # Update author activity
                if post_data["author"]:
                    self._update_author(db, post_data["author"])

                db.flush()

                # Entity matching
                match_or_create_entity(db, post, extraction)

                db.commit()
                self._stats["new_posts"] += 1
                logger.debug(f"New post: r/{sub_name} - {post_data['title'][:60]}")

            except Exception as e:
                db.rollback()
                logger.error(f"Error storing post {reddit_id}: {e}")
            finally:
                db.close()

    def _update_author(self, db, username: str):
        """Update or create author activity record."""
        author = db.query(AuthorActivity).filter(
            AuthorActivity.username == username
        ).first()
        if author:
            author.last_seen = datetime.now(timezone.utc)
            author.total_posts += 1
        else:
            db.add(AuthorActivity(username=username, total_posts=1))

    async def _compute_phash(self, url: str) -> int | None:
        """Download image and compute perceptual hash."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    img = Image.open(BytesIO(resp.content))
                    h = imagehash.phash(img)
                    return int(str(h), 16)
        except Exception as e:
            logger.debug(f"pHash failed for {url[:60]}: {e}")
        return None

    def get_stats(self) -> dict:
        return self._stats.copy()
