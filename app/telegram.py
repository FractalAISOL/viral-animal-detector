import logging
import httpx
from datetime import datetime, timezone

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def send_message(text: str, parse_mode: str = "HTML") -> int | None:
    """Send a Telegram message. Returns message_id or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{API_BASE}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            data = resp.json()
            if data.get("ok"):
                return data["result"]["message_id"]
            logger.error(f"Telegram API error: {data}")
            return None
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return None


def format_level1_digest(posts: list[dict]) -> str:
    """Format Level 1 digest alert (batched every 4hrs)."""
    lines = ["<b>ANIMAL RADAR - 4h Digest</b>\n"]
    lines.append(f"{len(posts)} posts above baseline:\n")
    for i, p in enumerate(posts[:10], 1):
        lines.append(
            f"{i}. r/{p['subreddit']} - \"{p['title'][:60]}\"\n"
            f"   Score: {p['score']:,} (AS: {p['anomaly_score']:.1f}) | "
            f"{p['num_comments']} comments\n"
            f"   Velocity: +{p.get('velocity', 0):.0f}/hr | "
            f"Ratio: {p.get('upvote_ratio', 0):.2f}\n"
            f"   https://redd.it/{p['reddit_id']}\n"
        )
    return "\n".join(lines)


def format_level2(post: dict, cluster: dict | None = None) -> str:
    """Format Level 2 immediate alert."""
    lines = [
        f"<b>TRENDING - r/{post['subreddit']}</b>\n",
        f"\"{post['title'][:80]}\"\n"
        f"Score: {post['score']:,} (AS: {post['anomaly_score']:.1f}) | "
        f"{post['num_comments']} comments\n"
        f"Velocity: +{post.get('velocity', 0):.0f}/hr | "
        f"Ratio: {post.get('upvote_ratio', 0):.2f}\n",
    ]
    if cluster:
        cross = cluster.get("sub_count", 0)
        if cross > 1:
            lines.append(f"Cross-posts: {cross} subs\n")
        entity_parts = []
        if cluster.get("species"):
            entity_parts.append(cluster["species"])
        if cluster.get("location"):
            entity_parts.append(cluster["location"])
        if entity_parts:
            total = cluster.get("total_score", 0)
            lines.append(
                f"Entity: {' / '.join(entity_parts)} "
                f"({cluster.get('post_count', 0)} posts, {total:,} total)\n"
            )
    lines.append(f"\nhttps://redd.it/{post['reddit_id']}")
    return "\n".join(lines)


def format_level3(cluster: dict, lead_post: dict) -> str:
    """Format Level 3 viral breakout alert."""
    lines = [
        "<b>*** VIRAL BREAKOUT ***</b>\n",
    ]
    name = cluster.get("animal_name") or cluster.get("species") or "Unknown"
    lines.append(
        f"\"{name}\" - {cluster['post_count']} posts / "
        f"{cluster.get('sub_count', 0)} subs\n"
    )
    lines.append(
        f"Lead: r/{lead_post['subreddit']} - {lead_post['score']:,} score "
        f"(AS: {lead_post['anomaly_score']:.1f})\n"
        f"Total: {cluster['total_score']:,} across "
        f"{cluster.get('sub_count', 0)} subs | "
        f"+{lead_post.get('velocity', 0):.0f}/hr\n"
    )
    if cluster.get("top_archetype"):
        lines.append(f"Archetype: {cluster['top_archetype']}\n")
    entity_parts = []
    if cluster.get("species"):
        entity_parts.append(cluster["species"])
    if cluster.get("location"):
        entity_parts.append(cluster["location"])
    if cluster.get("animal_name"):
        entity_parts.append(f'"{cluster["animal_name"]}"')
    if entity_parts:
        lines.append(f"Entity: {' / '.join(entity_parts)}\n")
    lines.append(f"\nhttps://redd.it/{lead_post['reddit_id']}")
    return "\n".join(lines)


def format_system_message(text: str) -> str:
    return f"<b>SYSTEM</b>\n\n{text}"
