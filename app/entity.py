"""Entity clustering — matches posts to entity clusters and detects cross-sub signals."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import and_, text

from app.db import (
    SessionLocal, Post, EntityCluster, ClusterKey, ClusterAlias, Subreddit, Alert,
)
from app.config import (
    JACCARD_THRESHOLD, PHASH_THRESHOLD, ENTITY_CREATION_THRESHOLD,
    CROSS_SUB_MIN_POSTS, CROSS_SUB_MIN_AS, CROSS_SUB_LEAD_AS,
)
from app import telegram

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalize a name for cluster key matching."""
    return name.lower().strip().replace(" ", "_")


def _jaccard_similarity(title1: str, title2: str) -> float:
    """Jaccard similarity with proper noun 2x weight boost."""
    words1 = set(title1.split())
    words2 = set(title2.split())

    # Weight proper nouns 2x
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


def _hamming_distance(hash1: int, hash2: int) -> int:
    """Compute Hamming distance between two perceptual hashes."""
    return bin(hash1 ^ hash2).count("1")


def _build_known_entities(db) -> dict[str, tuple[int, str, str]]:
    """
    Build known_entities lookup from entity_clusters.
    Returns: {lowercase_name: (cluster_id, species, location)}
    """
    clusters = db.query(EntityCluster).filter(
        and_(
            EntityCluster.animal_name.isnot(None),
            EntityCluster.status.in_(["active", "cooling"]),
        )
    ).all()

    known = {}
    for c in clusters:
        known[c.animal_name.lower()] = (c.id, c.species, c.location)
        # Also add aliases
        for alias in c.aliases:
            known[alias.alias.lower()] = (c.id, c.species, c.location)

    return known


def match_or_create_entity(db, post: Post, extraction: dict):
    """
    Match a post to an existing entity cluster or create a new one.
    Called during post ingestion.
    """
    species = extraction.get("species")
    name = extraction.get("name")
    location = extraction.get("location")
    narrative_score = extraction.get("narrative_score", 0)

    # 1. Check known entities by name first
    if name:
        known = _build_known_entities(db)
        name_lower = name.lower()
        if name_lower in known:
            cluster_id, k_species, k_location = known[name_lower]
            post.cluster_id = cluster_id
            # Inherit species/location if not extracted
            if not species and k_species:
                post.extracted_species = k_species
            if not location and k_location:
                post.extracted_location = k_location
            _update_cluster_on_link(db, cluster_id, post)
            return

    # 2. Check cluster_keys table
    cluster_id = _match_by_cluster_keys(db, name, species, location, post)
    if cluster_id:
        post.cluster_id = cluster_id
        _update_cluster_on_link(db, cluster_id, post)
        return

    # 3. Cross-sub detection: crosspost_parent
    if post.crosspost_parent:
        parent = db.query(Post).filter(
            Post.reddit_id == post.crosspost_parent
        ).first()
        if parent and parent.cluster_id:
            post.cluster_id = parent.cluster_id
            _update_cluster_on_link(db, parent.cluster_id, post)
            return

    # 4. Cross-sub detection: title Jaccard similarity
    cluster_id = _match_by_title_similarity(db, post)
    if cluster_id:
        post.cluster_id = cluster_id
        _update_cluster_on_link(db, cluster_id, post)
        return

    # 5. Cross-sub detection: pHash
    if post.image_hash:
        cluster_id = _match_by_phash(db, post)
        if cluster_id:
            post.cluster_id = cluster_id
            _update_cluster_on_link(db, cluster_id, post)
            return

    # 6. No match — create new entity if criteria met
    if narrative_score >= ENTITY_CREATION_THRESHOLD and (species or name):
        cluster = EntityCluster(
            animal_name=name,
            species=species,
            location=location,
            post_count=1,
            total_score=post.current_score,
            total_comments=post.current_comments,
            top_archetype=extraction.get("top_archetype"),
        )
        db.add(cluster)
        db.flush()  # Get cluster.id

        post.cluster_id = cluster.id

        # Add cluster keys
        if name:
            _add_cluster_key(db, cluster.id, "name", f"name:{_normalize_name(name)}")
            # Add alias
            db.add(ClusterAlias(
                cluster_id=cluster.id, alias=name.lower(), source="title_extraction"
            ))

        if species and location:
            _add_cluster_key(
                db, cluster.id, "species_location",
                f"species_location:{species.lower()}:{location.lower()}"
            )

        sub = db.query(Subreddit).filter(Subreddit.id == post.subreddit_id).first()
        if species and sub:
            _add_cluster_key(
                db, cluster.id, "species_sub",
                f"species_sub:{species.lower()}:{sub.name.lower()}"
            )

        logger.info(f"New entity: {name or species} / {location or 'unknown'}")


def _match_by_cluster_keys(db, name, species, location, post) -> int | None:
    """Try to match by cluster key lookup."""
    # Try name key
    if name:
        key = db.query(ClusterKey).filter(
            and_(
                ClusterKey.key_type == "name",
                ClusterKey.key_value == f"name:{_normalize_name(name)}",
            )
        ).first()
        if key:
            return key.cluster_id

    # Try species+location key
    if species and location:
        key = db.query(ClusterKey).filter(
            and_(
                ClusterKey.key_type == "species_location",
                ClusterKey.key_value == f"species_location:{species.lower()}:{location.lower()}",
            )
        ).first()
        if key:
            return key.cluster_id

    # Try species+sub key (only within 24hrs)
    sub = db.query(Subreddit).filter(Subreddit.id == post.subreddit_id).first()
    if species and sub:
        key = db.query(ClusterKey).filter(
            and_(
                ClusterKey.key_type == "species_sub",
                ClusterKey.key_value == f"species_sub:{species.lower()}:{sub.name.lower()}",
            )
        ).first()
        if key:
            # Verify cluster was active in last 24hrs
            cluster = db.query(EntityCluster).filter(
                and_(
                    EntityCluster.id == key.cluster_id,
                    EntityCluster.last_post_at >= datetime.now(timezone.utc) - timedelta(hours=24),
                )
            ).first()
            if cluster:
                return key.cluster_id

    return None


def _match_by_title_similarity(db, post: Post) -> int | None:
    """Find matching posts by Jaccard title similarity."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_posts = db.query(Post).filter(
        and_(
            Post.reddit_id != post.reddit_id,
            Post.cluster_id.isnot(None),
            Post.subreddit_id != post.subreddit_id,  # Different sub only
            Post.first_seen_at >= cutoff,
        )
    ).limit(200).all()

    best_score = 0.0
    best_cluster_id = None

    for rp in recent_posts:
        sim = _jaccard_similarity(post.title, rp.title)
        if sim > best_score:
            best_score = sim
            best_cluster_id = rp.cluster_id

        # Auto-match on proper noun overlap
        post_proper = {w for w in post.title.split() if w and w[0].isupper() and len(w) > 1}
        rp_proper = {w for w in rp.title.split() if w and w[0].isupper() and len(w) > 1}
        common_proper = post_proper & rp_proper
        # Skip common words
        common_proper -= {"The", "This", "That", "My", "Our", "His", "Her",
                          "It", "In", "At", "On", "Of", "An", "To", "So",
                          "No", "Or", "If", "Up", "As", "By", "We", "He",
                          "She", "Its", "All", "But", "For", "Not", "Are",
                          "Was", "One", "Two", "Has", "Had", "Can", "Did",
                          "Got", "New", "Old", "Big", "How", "Why", "Who",
                          "Just", "Now", "Here", "Very", "Much", "Even",
                          "More", "Most", "Some", "Any", "Each", "Every"}
        if len(common_proper) >= 2:
            return rp.cluster_id

    if best_score >= JACCARD_THRESHOLD:
        return best_cluster_id

    return None


def _match_by_phash(db, post: Post) -> int | None:
    """Find matching posts by perceptual image hash."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    candidates = db.query(Post).filter(
        and_(
            Post.reddit_id != post.reddit_id,
            Post.image_hash.isnot(None),
            Post.cluster_id.isnot(None),
            Post.first_seen_at >= cutoff,
        )
    ).limit(500).all()

    for cand in candidates:
        dist = _hamming_distance(post.image_hash, cand.image_hash)
        if dist <= PHASH_THRESHOLD:
            return cand.cluster_id
        # Combined signal: loose hash + same species + some title similarity
        if dist <= 16 and post.extracted_species and post.extracted_species == cand.extracted_species:
            sim = _jaccard_similarity(post.title, cand.title)
            if sim > 0.25:
                return cand.cluster_id

    return None


def _update_cluster_on_link(db, cluster_id: int, post: Post):
    """Atomically update cluster aggregates when linking a post."""
    db.execute(text("""
        UPDATE entity_clusters SET
            post_count = post_count + 1,
            total_score = total_score + :score,
            total_comments = total_comments + :comments,
            peak_anomaly = GREATEST(peak_anomaly, :anomaly),
            last_post_at = GREATEST(last_post_at, :now)
        WHERE id = :cid
    """), {
        "score": post.current_score,
        "comments": post.current_comments,
        "anomaly": post.anomaly_score or 0,
        "now": datetime.now(timezone.utc),
        "cid": cluster_id,
    })

    # Add name as alias if new
    if post.extracted_name:
        existing = db.query(ClusterAlias).filter(
            and_(
                ClusterAlias.cluster_id == cluster_id,
                ClusterAlias.alias == post.extracted_name.lower(),
            )
        ).first()
        if not existing:
            db.add(ClusterAlias(
                cluster_id=cluster_id,
                alias=post.extracted_name.lower(),
                source="crosspost",
            ))


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


async def check_cross_sub_alerts(db, cold_start_active: bool = False):
    """
    Check for cross-sub Level 3 triggers.
    3+ posts about same entity across 3+ different subs within 24hrs,
    each AS >= 2.0 and at least one AS >= 5.0.
    """
    if cold_start_active:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    active_clusters = db.query(EntityCluster).filter(
        and_(
            EntityCluster.status == "active",
            EntityCluster.post_count >= CROSS_SUB_MIN_POSTS,
            EntityCluster.alert_level < 3,  # Not already L3
        )
    ).all()

    for cluster in active_clusters:
        # Get recent posts for this cluster
        posts = db.query(Post).filter(
            and_(
                Post.cluster_id == cluster.id,
                Post.first_seen_at >= cutoff,
                Post.anomaly_score >= CROSS_SUB_MIN_AS,
            )
        ).all()

        if len(posts) < CROSS_SUB_MIN_POSTS:
            continue

        # Check distinct subreddits
        sub_ids = {p.subreddit_id for p in posts}
        if len(sub_ids) < 3:
            continue

        # Check at least one AS >= 5.0
        max_as = max(p.anomaly_score for p in posts)
        if max_as < CROSS_SUB_LEAD_AS:
            continue

        # Trigger Level 3!
        lead_post = max(posts, key=lambda p: p.anomaly_score)
        sub = db.query(Subreddit).filter(Subreddit.id == lead_post.subreddit_id).first()

        lead_dict = {
            "reddit_id": lead_post.reddit_id,
            "subreddit": sub.name if sub else "unknown",
            "title": lead_post.title,
            "score": lead_post.current_score,
            "anomaly_score": lead_post.anomaly_score,
            "velocity": 0,
        }
        cluster_dict = {
            "animal_name": cluster.animal_name,
            "species": cluster.species,
            "location": cluster.location,
            "post_count": cluster.post_count,
            "total_score": cluster.total_score,
            "sub_count": len(sub_ids),
            "top_archetype": cluster.top_archetype,
        }

        msg = telegram.format_level3(cluster_dict, lead_dict)
        msg_id = await telegram.send_message(msg)

        alert = Alert(
            alert_type="cluster",
            alert_level=3,
            cluster_id=cluster.id,
            post_id=lead_post.reddit_id,
            message_text=msg,
            telegram_msg_id=msg_id,
        )
        db.add(alert)
        cluster.alert_level = 3
        cluster.last_alert_at = datetime.now(timezone.utc)
        db.flush()

        logger.info(f"Cross-sub L3: {cluster.animal_name or cluster.species} "
                     f"({len(posts)} posts / {len(sub_ids)} subs)")
