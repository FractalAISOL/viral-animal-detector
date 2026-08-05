import praw
import logging
from datetime import datetime, timezone

from app.config import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME,
    REDDIT_PASSWORD, REDDIT_USER_AGENT, INTERNATIONAL_KEYWORDS,
)

logger = logging.getLogger(__name__)


def create_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT,
    )


def fetch_rising(reddit: praw.Reddit, subreddit_name: str, limit: int = 25):
    """Fetch /rising posts from a subreddit. Returns list of submission dicts."""
    try:
        sub = reddit.subreddit(subreddit_name)
        posts = []
        for submission in sub.rising(limit=limit):
            posts.append(_submission_to_dict(submission, subreddit_name))
        return posts
    except Exception as e:
        logger.error(f"Error fetching /rising from r/{subreddit_name}: {e}")
        return []


def fetch_new_filtered(reddit: praw.Reddit, subreddit_name: str, keywords: list[str], limit: int = 25):
    """Fetch /new posts from a subreddit, filtered by keywords."""
    try:
        sub = reddit.subreddit(subreddit_name)
        posts = []
        kw_lower = [k.lower() for k in keywords]
        for submission in sub.new(limit=limit):
            title_lower = submission.title.lower()
            if any(kw in title_lower for kw in kw_lower):
                posts.append(_submission_to_dict(submission, subreddit_name))
        return posts
    except Exception as e:
        logger.error(f"Error fetching /new from r/{subreddit_name}: {e}")
        return []


def search_news(reddit: praw.Reddit, subreddit_name: str, query: str, limit: int = 10):
    """Search a subreddit for a query."""
    try:
        sub = reddit.subreddit(subreddit_name)
        posts = []
        for submission in sub.search(query, sort="new", time_filter="day", limit=limit):
            posts.append(_submission_to_dict(submission, subreddit_name))
        return posts
    except Exception as e:
        logger.error(f"Error searching r/{subreddit_name} for '{query}': {e}")
        return []


def fetch_post_update(reddit: praw.Reddit, reddit_id: str):
    """Fetch current score/comments/ratio for a tracked post."""
    try:
        submission = reddit.submission(id=reddit_id)
        return {
            "score": submission.score,
            "num_comments": submission.num_comments,
            "upvote_ratio": submission.upvote_ratio,
        }
    except Exception as e:
        logger.error(f"Error fetching post {reddit_id}: {e}")
        return None


def _submission_to_dict(submission, subreddit_name: str) -> dict:
    """Convert a PRAW submission to a flat dict."""
    crosspost_parent = None
    is_crosspost = False
    if hasattr(submission, "crosspost_parent_list") and submission.crosspost_parent_list:
        is_crosspost = True
        crosspost_parent = submission.crosspost_parent_list[0].get("id")

    thumbnail_url = None
    if hasattr(submission, "preview") and submission.preview:
        try:
            thumbnail_url = submission.preview["images"][0]["source"]["url"]
        except (KeyError, IndexError):
            pass
    if not thumbnail_url and hasattr(submission, "thumbnail") and submission.thumbnail.startswith("http"):
        thumbnail_url = submission.thumbnail

    return {
        "reddit_id": submission.id,
        "subreddit": subreddit_name,
        "title": submission.title,
        "author": str(submission.author) if submission.author else None,
        "url": submission.url,
        "permalink": submission.permalink,
        "post_hint": getattr(submission, "post_hint", None),
        "flair": submission.link_flair_text,
        "created_utc": datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
        "is_crosspost": is_crosspost,
        "crosspost_parent": crosspost_parent,
        "score": submission.score,
        "num_comments": submission.num_comments,
        "upvote_ratio": submission.upvote_ratio,
        "thumbnail_url": thumbnail_url,
    }
