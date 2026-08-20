"""Hacker News API client — Firebase + Algolia for story discovery."""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

HN_FIREBASE = "https://hacker-news.firebaseio.com/v0"
HN_ALGOLIA = "https://hn.algolia.com/api/v1"


async def fetch_top_story_ids(limit: int = 200) -> list[int]:
    """Fetch top story IDs from HN Firebase API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{HN_FIREBASE}/topstories.json")
            if resp.status_code != 200:
                logger.warning(f"HN topstories returned {resp.status_code}")
                return []
            ids = resp.json()
            return ids[:limit] if ids else []
    except Exception as e:
        logger.error(f"HN topstories error: {e}")
        return []


async def fetch_item(item_id: int) -> dict | None:
    """Fetch a single HN item by ID."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{HN_FIREBASE}/item/{item_id}.json")
            if resp.status_code != 200 or not resp.content:
                return None
            data = resp.json()
            if not data or data.get("type") != "story":
                return None
            return _item_to_dict(data)
    except Exception as e:
        logger.error(f"HN item {item_id} error: {e}")
        return None


async def fetch_items_batch(item_ids: list[int]) -> list[dict]:
    """Fetch multiple HN items. Returns list of story dicts."""
    items = []
    async with httpx.AsyncClient(timeout=10) as client:
        for item_id in item_ids:
            try:
                resp = await client.get(f"{HN_FIREBASE}/item/{item_id}.json")
                if resp.status_code == 200 and resp.content:
                    data = resp.json()
                    if data and data.get("type") == "story" and data.get("title"):
                        items.append(_item_to_dict(data))
            except Exception as e:
                logger.debug(f"HN item {item_id} error: {e}")
    return items


async def search_algolia(query: str, hits_per_page: int = 20) -> list[dict]:
    """Search HN via Algolia API. Returns recent stories matching query."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{HN_ALGOLIA}/search_by_date",
                params={
                    "query": query,
                    "tags": "story",
                    "hitsPerPage": hits_per_page,
                },
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [_algolia_to_dict(hit) for hit in data.get("hits", [])]
    except Exception as e:
        logger.error(f"HN Algolia search error: {e}")
        return []


def _item_to_dict(data: dict) -> dict:
    """Convert Firebase HN item to our dict format."""
    created_at = datetime.fromtimestamp(data.get("time", 0), tz=timezone.utc)
    hn_id = str(data["id"])
    return {
        "id": f"hn:{hn_id}",
        "hn_id": hn_id,
        "title": data.get("title", ""),
        "url": data.get("url", f"https://news.ycombinator.com/item?id={hn_id}"),
        "author": data.get("by"),
        "created_at": created_at,
        "permalink": f"https://news.ycombinator.com/item?id={hn_id}",
        "extra": {
            "hn_score": data.get("score", 0),
            "hn_comments": data.get("descendants", 0),
        },
    }


def _algolia_to_dict(hit: dict) -> dict:
    """Convert Algolia hit to our dict format."""
    hn_id = hit.get("objectID", "")
    created_at = datetime.fromtimestamp(
        hit.get("created_at_i", 0), tz=timezone.utc
    )
    return {
        "id": f"hn:{hn_id}",
        "hn_id": hn_id,
        "title": hit.get("title", ""),
        "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hn_id}",
        "author": hit.get("author"),
        "created_at": created_at,
        "permalink": f"https://news.ycombinator.com/item?id={hn_id}",
        "extra": {
            "hn_score": hit.get("points", 0),
            "hn_comments": hit.get("num_comments", 0),
        },
    }
