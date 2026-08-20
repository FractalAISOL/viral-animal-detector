"""Entity clustering — matches items to entity clusters using fast heuristics + Gemini."""

import logging
from datetime import datetime, timezone, timedelta
from collections import Counter

from sqlalchemy import and_, text

from app.db import (
    SessionLocal, Item, EntityCluster, ClusterKey, ClusterAlias,
)
from app.config import JACCARD_THRESHOLD, ENTITY_CREATION_MIN_MENTIONS
from app import gemini_client

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    return name.lower().strip().replace(" ", "_")


def _jaccard_similarity(title1: str, title2: str) -> float:
    """Jaccard similarity with proper noun 2x weight boost."""
    words1 = set(title1.split())
    words2 = set(title2.split())

    weighted1 = set()
    for w in words1:
        if not w:
            continue
        weighted1.add(w.lower())
        if w[0].isupper() and len(w) > 1:
            weighted1.add(f"PROPER_{w.lower()}")
    weighted2 = set()
    for w in words2:
        if not w:
            continue
        weighted2.add(w.lower())
        if w[0].isupper() and len(w) > 1:
            weighted2.add(f"PROPER_{w.lower()}")

    intersection = weighted1 & weighted2
    union = weighted1 | weighted2
    if not union:
        return 0.0
    return len(intersection) / len(union)


# Common title words to skip in proper noun matching
_COMMON_WORDS = {
    "The", "This", "That", "My", "Our", "His", "Her", "It", "In", "At",
    "On", "Of", "An", "To", "So", "No", "Or", "If", "Up", "As", "By",
    "We", "He", "She", "Its", "All", "But", "For", "Not", "Are", "Was",
    "One", "Two", "Has", "Had", "Can", "Did", "Got", "New", "Old", "Big",
    "How", "Why", "Who", "Just", "Now", "Here", "Very", "Much", "Even",
    "More", "Most", "Some", "Any", "Each", "Every", "After", "Before",
    "About", "With", "From", "What", "When", "Where", "Which", "While",
    "First", "Last", "Next", "Only", "Just", "Over", "Into", "Back",
    "Down", "Well", "Also", "Than", "Then", "Like", "Will", "Been",
    "Would", "Could", "Should", "Said", "Made", "Found", "Know",
}


def match_or_create_entity_fast(db, item: Item):
    """
    Fast entity matching at ingestion time.
    Uses Jaccard similarity + proper noun overlap.
    Gemini clustering runs separately in batch.
    """
    # 1. Check cluster_keys by extracted entity name
    if item.extracted_entity:
        key = db.query(ClusterKey).filter(
            and_(
                ClusterKey.key_type == "name",
                ClusterKey.key_value == f"name:{_normalize_name(item.extracted_entity)}",
            )
        ).first()
        if key:
            item.cluster_id = key.cluster_id
            _update_cluster_on_link(db, key.cluster_id)
            return

        # Check aliases
        alias = db.query(ClusterAlias).filter(
            ClusterAlias.alias == item.extracted_entity.lower()
        ).first()
        if alias:
            item.cluster_id = alias.cluster_id
            _update_cluster_on_link(db, alias.cluster_id)
            return

    # 2. Jaccard title similarity against recent clustered items
    cluster_id = _match_by_title_similarity(db, item)
    if cluster_id:
        item.cluster_id = cluster_id
        _update_cluster_on_link(db, cluster_id)
        return

    # 3. No match — leave unclustered for Gemini batch pass


def _match_by_title_similarity(db, item: Item) -> int | None:
    """Find matching cluster by Jaccard title similarity."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_items = db.query(Item).filter(
        and_(
            Item.id != item.id,
            Item.cluster_id.isnot(None),
            Item.first_seen_at >= cutoff,
        )
    ).limit(200).all()

    best_score = 0.0
    best_cluster_id = None

    for ri in recent_items:
        sim = _jaccard_similarity(item.title, ri.title)
        if sim > best_score:
            best_score = sim
            best_cluster_id = ri.cluster_id

        # Auto-match on 2+ shared proper nouns (non-common words)
        item_proper = {w for w in item.title.split() if w and w[0].isupper() and len(w) > 1}
        ri_proper = {w for w in ri.title.split() if w and w[0].isupper() and len(w) > 1}
        common_proper = (item_proper & ri_proper) - _COMMON_WORDS
        if len(common_proper) >= 2:
            return ri.cluster_id

    if best_score >= JACCARD_THRESHOLD:
        return best_cluster_id

    return None


def _update_cluster_on_link(db, cluster_id: int):
    """Update cluster stats when linking an item."""
    db.execute(text("""
        UPDATE entity_clusters SET
            mention_count = (SELECT COUNT(*) FROM items WHERE cluster_id = :cid),
            source_count = (SELECT COUNT(DISTINCT source_type) FROM items WHERE cluster_id = :cid),
            sub_count = (SELECT COUNT(DISTINCT extra->>'subreddit')
                         FROM items WHERE cluster_id = :cid AND extra->>'subreddit' IS NOT NULL),
            last_item_at = now()
        WHERE id = :cid
    """), {"cid": cluster_id})


async def run_gemini_clustering(db):
    """
    Batch clustering pass — sends unclustered items to Gemini for semantic matching.
    Runs every 5 minutes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Get unclustered items from last 24hrs
    unclustered = db.query(Item).filter(
        and_(
            Item.cluster_id.is_(None),
            Item.first_seen_at >= cutoff,
        )
    ).order_by(Item.first_seen_at.desc()).limit(30).all()

    if not unclustered:
        return

    # Get existing active clusters
    active_clusters = db.query(EntityCluster).filter(
        EntityCluster.status == "active"
    ).order_by(EntityCluster.mention_count.desc()).limit(50).all()

    # Build inputs for Gemini
    titles = [{
        "id": item.id,
        "title": item.title,
        "source": item.source_type + (":" + (item.extra or {}).get("subreddit", "") if item.source_type == "reddit" else ""),
    } for item in unclustered]

    existing = [{
        "id": c.id,
        "entity_name": c.entity_name or "unnamed",
        "entity_type": c.entity_type or "unknown",
        "aliases": [a.alias for a in c.aliases],
    } for c in active_clusters]

    # Call Gemini
    assignments = await gemini_client.cluster_titles(titles, existing)

    if not assignments:
        return

    # Process assignments
    item_map = {item.id: item for item in unclustered}

    for assignment in assignments:
        item_id = assignment.get("item_id")
        cluster_id = assignment.get("cluster_id")
        new_name = assignment.get("new_entity_name")
        new_type = assignment.get("new_entity_type")

        item = item_map.get(item_id)
        if not item:
            continue

        if cluster_id:
            # Assign to existing cluster
            existing_cluster = db.query(EntityCluster).filter(
                EntityCluster.id == cluster_id
            ).first()
            if existing_cluster:
                item.cluster_id = cluster_id
                _update_cluster_on_link(db, cluster_id)

        elif new_name:
            # Check if we already have a cluster with this name (Gemini might not know)
            alias = db.query(ClusterAlias).filter(
                ClusterAlias.alias == new_name.lower()
            ).first()
            if alias:
                item.cluster_id = alias.cluster_id
                _update_cluster_on_link(db, alias.cluster_id)
                continue

            # Create new cluster
            cluster = EntityCluster(
                entity_name=new_name,
                entity_type=new_type,
                mention_count=1,
                source_count=1,
                sub_count=1 if item.source_type == "reddit" else 0,
            )
            db.add(cluster)
            db.flush()

            item.cluster_id = cluster.id

            # Add cluster key and alias
            _add_cluster_key(db, cluster.id, "name", f"name:{_normalize_name(new_name)}")
            db.add(ClusterAlias(
                cluster_id=cluster.id,
                alias=new_name.lower(),
                source="gemini",
            ))

            logger.info(f"New entity from Gemini: {new_name} ({new_type})")

    db.flush()
    logger.info(f"Gemini clustering: processed {len(assignments)} assignments")


def _add_cluster_key(db, cluster_id: int, key_type: str, key_value: str):
    """Add a cluster key, ignoring duplicates."""
    existing = db.query(ClusterKey).filter(
        and_(
            ClusterKey.key_type == key_type,
            ClusterKey.key_value == key_value,
        )
    ).first()
    if not existing:
        db.add(ClusterKey(
            cluster_id=cluster_id,
            key_type=key_type,
            key_value=key_value,
        ))


def extract_ngram_entities(titles: list[str]) -> list[tuple[str, int]]:
    """
    N-gram frequency analysis — find repeated proper noun phrases across titles.
    Returns list of (phrase, count) sorted by count desc.
    Supplementary to Gemini — catches ~40% of viral moments.
    """
    # Extract 1-3 word proper noun phrases
    phrase_counts: Counter = Counter()

    for title in titles:
        words = title.split()
        # Single proper nouns
        for w in words:
            if w and w[0].isupper() and len(w) > 2 and w not in _COMMON_WORDS:
                phrase_counts[w] += 1
        # Bigrams
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if (w1 and w1[0].isupper() and w2 and w2[0].isupper()
                    and w1 not in _COMMON_WORDS and w2 not in _COMMON_WORDS):
                phrase_counts[f"{w1} {w2}"] += 1
        # Trigrams
        for i in range(len(words) - 2):
            w1, w2, w3 = words[i], words[i + 1], words[i + 2]
            if (w1 and w1[0].isupper() and w3 and w3[0].isupper()
                    and w1 not in _COMMON_WORDS):
                phrase_counts[f"{w1} {w2} {w3}"] += 1

    # Filter to phrases appearing 2+ times
    return [(phrase, count) for phrase, count in phrase_counts.most_common(20) if count >= 2]
