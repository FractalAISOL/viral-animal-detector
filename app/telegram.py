"""Telegram alert formatting and sending."""

import logging
import httpx

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


def format_level1_digest(clusters: list[dict]) -> str:
    """Format Level 1 digest alert (batched every 4hrs)."""
    lines = ["<b>VIRAL RADAR - 4h Digest</b>\n"]
    lines.append(f"{len(clusters)} entities gaining momentum:\n")
    for i, c in enumerate(clusters[:10], 1):
        name = c.get("entity_name") or "Unknown"
        etype = c.get("entity_type") or ""
        mentions = c.get("mention_count", 0)
        subs = c.get("sub_count", 0)
        momentum = c.get("momentum_score", 0)
        lines.append(
            f"{i}. <b>{name}</b>"
            f"{f' ({etype})' if etype else ''}\n"
            f"   {mentions} mentions / {subs} subs | "
            f"Momentum: {momentum:.1f}\n"
        )
        if c.get("lead_url"):
            lines.append(f"   {c['lead_url']}\n")
    return "\n".join(lines)


def format_level2(cluster: dict, item: dict | None = None) -> str:
    """Format Level 2 immediate alert — entity trending."""
    name = cluster.get("entity_name") or "Unknown"
    etype = cluster.get("entity_type") or ""
    mentions = cluster.get("mention_count", 0)
    subs = cluster.get("sub_count", 0)
    sources = cluster.get("source_count", 0)
    momentum = cluster.get("momentum_score", 0)

    lines = [
        f"<b>TRENDING{f' ({etype})' if etype else ''}</b>\n",
        f"<b>{name}</b>\n"
        f"{mentions} mentions / {subs} subs / {sources} sources\n"
        f"Momentum: {momentum:.1f}\n",
    ]

    yt_views = cluster.get("youtube_views", 0)
    if yt_views > 0:
        lines.append(f"YouTube: {yt_views:,} views ({cluster.get('youtube_videos', 0)} videos)\n")

    if item:
        sub = item.get("subreddit", "")
        source = item.get("source_type", "")
        title = item.get("title", "")[:80]
        lines.append(f"\nLead: \"{title}\"\n")
        if sub:
            lines.append(f"r/{sub}")
        elif source:
            lines.append(f"Source: {source}")
        url = item.get("url", "")
        if url:
            lines.append(f"\n{url}")

    return "\n".join(lines)


def format_level3(cluster: dict, item: dict | None = None) -> str:
    """Format Level 3 viral breakout alert."""
    name = cluster.get("entity_name") or "Unknown"
    etype = cluster.get("entity_type") or ""
    mentions = cluster.get("mention_count", 0)
    subs = cluster.get("sub_count", 0)
    sources = cluster.get("source_count", 0)
    momentum = cluster.get("momentum_score", 0)

    lines = [
        "<b>*** VIRAL BREAKOUT ***</b>\n",
        f"<b>{name}</b>"
        f"{f' ({etype})' if etype else ''}\n",
        f"{mentions} mentions / {subs} subs / {sources} sources\n"
        f"Momentum: {momentum:.1f}\n",
    ]

    yt_views = cluster.get("youtube_views", 0)
    if yt_views > 0:
        lines.append(f"YouTube: {yt_views:,} views ({cluster.get('youtube_videos', 0)} videos)\n")

    if item:
        title = item.get("title", "")[:80]
        lines.append(f"\nLead: \"{title}\"")
        url = item.get("url", "")
        if url:
            lines.append(f"\n{url}")

    return "\n".join(lines)


def format_system_message(text: str) -> str:
    return f"<b>SYSTEM</b>\n\n{text}"
