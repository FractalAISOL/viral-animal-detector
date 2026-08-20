"""Reddit RSS fetcher — polls subreddit feeds via Atom XML through proxy."""

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.config import PROXY_URL, REDDIT_RSS_TOKEN, REDDIT_RSS_USER, RSS_REQUEST_DELAY

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
BASE_URL = "https://www.reddit.com"


def _build_feed_url(subreddit: str, sort: str = "rising") -> str:
    """Build RSS feed URL for a subreddit."""
    url = f"{BASE_URL}/r/{subreddit}/{sort}/.rss"
    if REDDIT_RSS_TOKEN and REDDIT_RSS_USER:
        url += f"?feed={REDDIT_RSS_TOKEN}&user={REDDIT_RSS_USER}"
    return url


def _get_proxy_client() -> httpx.AsyncClient:
    """Create an httpx client with proxy if configured."""
    kwargs = {
        "timeout": 15,
        "headers": {"User-Agent": USER_AGENT},
        "follow_redirects": True,
    }
    if PROXY_URL:
        kwargs["proxy"] = PROXY_URL
    return httpx.AsyncClient(**kwargs)


async def fetch_rss_feed(subreddit: str, sort: str = "rising") -> list[dict]:
    """
    Fetch and parse a subreddit RSS feed.
    Returns list of item dicts with: id, subreddit, title, url, author, created_at, permalink, image_url.
    """
    url = _build_feed_url(subreddit, sort)
    try:
        async with _get_proxy_client() as client:
            resp = await client.get(url)
            if resp.status_code == 403:
                logger.warning(f"RSS 403 for r/{subreddit} — IP blocked or sub private")
                return []
            if resp.status_code != 200:
                logger.warning(f"RSS {resp.status_code} for r/{subreddit}")
                return []
            content = resp.text
    except Exception as e:
        logger.error(f"RSS fetch error for r/{subreddit}: {e}")
        return []

    return _parse_feed(content, subreddit)


def _parse_feed(xml_content: str, subreddit: str) -> list[dict]:
    """Parse Atom XML feed into item dicts."""
    feed = feedparser.parse(xml_content)
    items = []

    for entry in feed.entries:
        # Extract reddit post ID from the entry link
        # Link format: https://www.reddit.com/r/sub/comments/abc123/title/
        reddit_id = _extract_reddit_id(entry.get("link", ""))
        if not reddit_id:
            continue

        # Parse timestamp
        created_at = _parse_timestamp(entry)

        # Extract thumbnail/image from content HTML
        image_url = _extract_image(entry)

        # Extract author (format: "/u/username")
        author = entry.get("author", "")
        if author.startswith("/u/"):
            author = author[3:]

        # Detect actual subreddit from entry (r/popular returns mixed subs)
        actual_sub = _extract_subreddit(entry) or subreddit

        items.append({
            "id": f"reddit:{reddit_id}",
            "reddit_id": reddit_id,
            "subreddit": actual_sub,
            "title": entry.get("title", "").strip(),
            "url": entry.get("link", ""),
            "author": author or None,
            "created_at": created_at,
            "permalink": entry.get("link", ""),
            "image_url": image_url,
        })

    return items


def _extract_reddit_id(url: str) -> str | None:
    """Extract post ID from Reddit URL."""
    # https://www.reddit.com/r/sub/comments/abc123/title/
    parts = url.split("/")
    try:
        comments_idx = parts.index("comments")
        return parts[comments_idx + 1]
    except (ValueError, IndexError):
        return None


def _extract_subreddit(entry) -> str | None:
    """Extract subreddit name from entry category or link."""
    # Category tag often has the subreddit
    for tag in entry.get("tags", []):
        term = tag.get("term", "")
        if term.startswith("r/"):
            return term[2:]
    # Try from link
    link = entry.get("link", "")
    parts = link.split("/")
    try:
        r_idx = parts.index("r")
        return parts[r_idx + 1]
    except (ValueError, IndexError):
        return None


def _parse_timestamp(entry) -> datetime:
    """Parse entry timestamp to UTC datetime."""
    for field in ["updated_parsed", "published_parsed"]:
        parsed = entry.get(field)
        if parsed:
            try:
                from calendar import timegm
                return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
            except Exception:
                pass
    # Fallback: try string parsing
    for field in ["updated", "published"]:
        ts = entry.get(field, "")
        if ts:
            try:
                return parsedate_to_datetime(ts).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def _extract_image(entry) -> str | None:
    """Extract image URL from entry content HTML."""
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        content = entry.summary or ""

    # Look for <img src="..."> in the content
    if '<img src="' in content:
        start = content.index('<img src="') + 10
        end = content.index('"', start)
        url = content[start:end]
        if url.startswith("http"):
            return url
    # Look for thumbnail in media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    return None
