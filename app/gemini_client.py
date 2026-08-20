"""Gemini API client — semantic entity clustering using free tier."""

import json
import logging
from datetime import datetime, timezone

import google.generativeai as genai

from app.config import GEMINI_API_KEY, GEMINI_MAX_REQUESTS_PER_DAY

logger = logging.getLogger(__name__)

# Track daily usage
_daily_requests = 0
_last_reset_date = None

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

MODEL_NAME = "gemini-2.0-flash-lite"


def _check_and_reset_daily():
    global _daily_requests, _last_reset_date
    today = datetime.now(timezone.utc).date()
    if _last_reset_date != today:
        _daily_requests = 0
        _last_reset_date = today


def _can_request() -> bool:
    _check_and_reset_daily()
    return _daily_requests < GEMINI_MAX_REQUESTS_PER_DAY


async def cluster_titles(titles: list[dict], existing_clusters: list[dict]) -> list[dict]:
    """
    Ask Gemini to cluster new titles with existing entity clusters.

    Args:
        titles: List of {id, title, source} dicts for unclustered items
        existing_clusters: List of {id, entity_name, entity_type, aliases} dicts

    Returns:
        List of {item_id, cluster_id, new_entity_name, new_entity_type} assignments.
        cluster_id=None means create new cluster with new_entity_name/type.
    """
    global _daily_requests

    if not GEMINI_API_KEY:
        logger.warning("Gemini API key not configured — falling back to n-gram matching")
        return []

    if not _can_request():
        logger.info("Gemini daily budget exhausted")
        return []

    if not titles:
        return []

    # Build prompt
    cluster_desc = "None yet" if not existing_clusters else "\n".join(
        f"  ID={c['id']}: \"{c['entity_name']}\" (type: {c['entity_type']}, aliases: {', '.join(c.get('aliases', []))})"
        for c in existing_clusters[:50]  # Cap at 50 to stay within context
    )

    title_list = "\n".join(
        f"  [{t['id']}] \"{t['title']}\" (from: {t['source']})"
        for t in titles[:30]  # Cap at 30 per batch
    )

    prompt = f"""You are a viral content clustering engine. Your job is to identify what entity, topic, or event each title is about, and group titles about the same thing together.

EXISTING CLUSTERS:
{cluster_desc}

NEW TITLES TO CLUSTER:
{title_list}

For each title, determine:
1. If it matches an existing cluster, assign it (use the cluster ID)
2. If it's about a NEW entity/topic not in any cluster, create a new one
3. If it's generic content (not about a specific viral entity), mark as null

Rules:
- An "entity" is a specific thing going viral: a named animal, a specific meme, a movie, an event, a person, etc.
- Generic posts like "look at this cute dog" are NOT entities — mark as null
- "Niu Lai ugly animation" and "Chinese cartoon controversy" are the SAME entity
- Be aggressive about matching — same topic = same cluster even if worded differently

Respond ONLY with a JSON array, no other text:
[
  {{"item_id": "...", "cluster_id": 5, "new_entity_name": null, "new_entity_type": null}},
  {{"item_id": "...", "cluster_id": null, "new_entity_name": "Pesto the Penguin", "new_entity_type": "animal"}},
  {{"item_id": "...", "cluster_id": null, "new_entity_name": null, "new_entity_type": null}}
]

Valid entity_types: animal, meme, movie, tv_show, game, event, person, tech, science, sports, music, other"""

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2048,
            ),
        )
        _daily_requests += 1

        # Parse response
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        assignments = json.loads(text)
        if not isinstance(assignments, list):
            logger.warning("Gemini returned non-list response")
            return []

        return assignments

    except json.JSONDecodeError as e:
        logger.error(f"Gemini JSON parse error: {e}")
        return []
    except Exception as e:
        logger.error(f"Gemini clustering error: {e}")
        _daily_requests += 1  # Count failed request too
        return []


async def extract_entity(title: str) -> dict | None:
    """
    Quick single-title entity extraction.
    Returns {entity_name, entity_type} or None.
    Used sparingly for high-priority items.
    """
    global _daily_requests

    if not GEMINI_API_KEY or not _can_request():
        return None

    prompt = f"""What specific viral entity/topic is this title about? If it's about a specific named thing (animal, meme, person, event, movie, etc.), extract it. If it's generic content, say null.

Title: "{title}"

Respond ONLY with JSON, no other text:
{{"entity_name": "Pesto the Penguin", "entity_type": "animal"}}
or
{{"entity_name": null, "entity_type": null}}"""

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.0,
                max_output_tokens=256,
            ),
        )
        _daily_requests += 1

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        if result.get("entity_name"):
            return result
        return None

    except Exception as e:
        logger.error(f"Gemini extract error: {e}")
        _daily_requests += 1
        return None


def get_daily_usage() -> tuple[int, int]:
    _check_and_reset_daily()
    return _daily_requests, GEMINI_MAX_REQUESTS_PER_DAY
