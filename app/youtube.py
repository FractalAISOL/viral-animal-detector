"""YouTube Data API v3 client — validates viral entities with video search."""

import logging
from datetime import datetime, timezone

import httpx

from app.config import YOUTUBE_API_KEY, YT_MAX_SEARCHES_PER_DAY

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"

# Track daily usage to stay within budget
_daily_searches = 0
_last_reset_date = None


def _check_and_reset_daily():
    """Reset daily counter if date has changed."""
    global _daily_searches, _last_reset_date
    today = datetime.now(timezone.utc).date()
    if _last_reset_date != today:
        _daily_searches = 0
        _last_reset_date = today


def _can_search() -> bool:
    """Check if we have budget for another search."""
    _check_and_reset_daily()
    return _daily_searches < YT_MAX_SEARCHES_PER_DAY


async def search_videos(query: str, max_results: int = 5) -> dict | None:
    """
    Search YouTube for videos matching query.
    Returns: {video_count, total_views, top_video_id, top_video_views, top_video_title}
    or None if budget exhausted or error.

    Costs: search.list = 100 units, videos.list = 1 unit per call.
    Budget: 10,000 units/day = ~100 searches.
    """
    global _daily_searches

    if not YOUTUBE_API_KEY:
        logger.warning("YouTube API key not configured")
        return None

    if not _can_search():
        logger.info("YouTube daily search budget exhausted")
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: Search (100 units)
            search_resp = await client.get(
                f"{API_BASE}/search",
                params={
                    "key": YOUTUBE_API_KEY,
                    "q": query,
                    "part": "snippet",
                    "type": "video",
                    "order": "relevance",
                    "publishedAfter": _recent_cutoff(),
                    "maxResults": max_results,
                },
            )
            _daily_searches += 1

            if search_resp.status_code == 403:
                logger.error("YouTube API quota exceeded")
                _daily_searches = YT_MAX_SEARCHES_PER_DAY  # Stop trying
                return None
            if search_resp.status_code != 200:
                logger.warning(f"YouTube search returned {search_resp.status_code}")
                return None

            search_data = search_resp.json()
            video_items = search_data.get("items", [])
            if not video_items:
                return {"video_count": 0, "total_views": 0,
                        "top_video_id": None, "top_video_views": 0, "top_video_title": None}

            # Step 2: Get video details for view counts (1 unit)
            video_ids = [v["id"]["videoId"] for v in video_items if v.get("id", {}).get("videoId")]
            if not video_ids:
                return {"video_count": 0, "total_views": 0,
                        "top_video_id": None, "top_video_views": 0, "top_video_title": None}

            details_resp = await client.get(
                f"{API_BASE}/videos",
                params={
                    "key": YOUTUBE_API_KEY,
                    "id": ",".join(video_ids),
                    "part": "statistics,snippet",
                },
            )

            if details_resp.status_code != 200:
                # Still return search results without view counts
                return {
                    "video_count": len(video_ids),
                    "total_views": 0,
                    "top_video_id": video_ids[0],
                    "top_video_views": 0,
                    "top_video_title": video_items[0]["snippet"]["title"],
                }

            details_data = details_resp.json()
            details_items = details_data.get("items", [])

            total_views = 0
            top_video = None
            top_views = 0

            for item in details_items:
                views = int(item.get("statistics", {}).get("viewCount", 0))
                total_views += views
                if views > top_views:
                    top_views = views
                    top_video = item

            result = {
                "video_count": len(details_items),
                "total_views": total_views,
                "top_video_id": top_video["id"] if top_video else None,
                "top_video_views": top_views,
                "top_video_title": top_video["snippet"]["title"] if top_video else None,
            }
            return result

    except Exception as e:
        logger.error(f"YouTube search error: {e}")
        return None


def _recent_cutoff() -> str:
    """Return ISO timestamp for 7 days ago (filter recent videos)."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_daily_usage() -> tuple[int, int]:
    """Return (used, max) for daily search budget."""
    _check_and_reset_daily()
    return _daily_searches, YT_MAX_SEARCHES_PER_DAY
