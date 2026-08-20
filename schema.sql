-- Viral Moment Detector — Database Schema v2
-- Multi-source architecture: Reddit RSS + HN + YouTube + Gemini

-- Drop old tables if migrating from v1
DROP TABLE IF EXISTS health_checks CASCADE;
DROP TABLE IF EXISTS alerts CASCADE;
DROP TABLE IF EXISTS score_history CASCADE;
DROP TABLE IF EXISTS baseline_samples CASCADE;
DROP TABLE IF EXISTS velocity_baselines CASCADE;
DROP TABLE IF EXISTS subreddit_baselines CASCADE;
DROP TABLE IF EXISTS author_activity CASCADE;
DROP TABLE IF EXISTS flagged_authors CASCADE;
DROP TABLE IF EXISTS cluster_aliases CASCADE;
DROP TABLE IF EXISTS cluster_keys CASCADE;
DROP TABLE IF EXISTS posts CASCADE;
DROP TABLE IF EXISTS items CASCADE;
DROP TABLE IF EXISTS youtube_results CASCADE;
DROP TABLE IF EXISTS momentum_history CASCADE;
DROP TABLE IF EXISTS entity_clusters CASCADE;
DROP TABLE IF EXISTS subreddits CASCADE;
DROP TABLE IF EXISTS sources CASCADE;

-- 1. Sources (RSS feeds, HN, etc.)
CREATE TABLE sources (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    source_type     TEXT NOT NULL DEFAULT 'reddit'
                    CHECK (source_type IN ('reddit', 'hackernews', 'youtube', 'system')),
    tier            TEXT NOT NULL DEFAULT 'niche',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    poll_interval_s INTEGER NOT NULL DEFAULT 180,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Entity clusters
CREATE TABLE entity_clusters (
    id              SERIAL PRIMARY KEY,
    entity_name     TEXT,
    entity_type     TEXT,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'cooling', 'dormant', 'dead')),
    mention_count   INTEGER NOT NULL DEFAULT 0,
    source_count    INTEGER NOT NULL DEFAULT 0,
    sub_count       INTEGER NOT NULL DEFAULT 0,
    youtube_views   BIGINT NOT NULL DEFAULT 0,
    youtube_videos  INTEGER NOT NULL DEFAULT 0,
    momentum_score  REAL NOT NULL DEFAULT 0,
    peak_momentum   REAL NOT NULL DEFAULT 0,
    alert_level     SMALLINT NOT NULL DEFAULT 0,
    last_alert_at   TIMESTAMPTZ,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_item_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clusters_status ON entity_clusters(status) WHERE status = 'active';
CREATE INDEX idx_clusters_name ON entity_clusters(entity_name) WHERE entity_name IS NOT NULL;
CREATE INDEX idx_clusters_momentum ON entity_clusters(momentum_score DESC) WHERE status = 'active';

-- 3. Items (discovered from all sources)
CREATE TABLE items (
    id              TEXT PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT,
    author          TEXT,
    permalink       TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    image_url       TEXT,
    image_hash      BIGINT,
    cluster_id      INTEGER REFERENCES entity_clusters(id) ON DELETE SET NULL,
    extracted_entity TEXT,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    extra           JSONB
);

CREATE INDEX idx_items_cluster ON items(cluster_id) WHERE cluster_id IS NOT NULL;
CREATE INDEX idx_items_source ON items(source_id, created_at DESC);
CREATE INDEX idx_items_first_seen ON items(first_seen_at DESC);
CREATE INDEX idx_items_image_hash ON items(image_hash) WHERE image_hash IS NOT NULL;

-- 4. Cluster lookup keys
CREATE TABLE cluster_keys (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    key_type    TEXT NOT NULL,
    key_value   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (key_type, key_value)
);

CREATE INDEX idx_cluster_keys_lookup ON cluster_keys(key_type, key_value);

-- 5. Cluster aliases
CREATE TABLE cluster_aliases (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    source      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, alias)
);

CREATE INDEX idx_cluster_aliases_alias ON cluster_aliases(alias);

-- 6. Momentum history (time-series)
CREATE TABLE momentum_history (
    id              BIGSERIAL PRIMARY KEY,
    cluster_id      INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    mention_count   INTEGER NOT NULL,
    mention_velocity REAL,
    source_count    INTEGER,
    sub_count       INTEGER,
    momentum_score  REAL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_momentum_cluster ON momentum_history(cluster_id, recorded_at DESC);

-- 7. YouTube validation results
CREATE TABLE youtube_results (
    id              SERIAL PRIMARY KEY,
    cluster_id      INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    query           TEXT NOT NULL,
    video_count     INTEGER NOT NULL DEFAULT 0,
    total_views     BIGINT NOT NULL DEFAULT 0,
    top_video_id    TEXT,
    top_video_views BIGINT,
    top_video_title TEXT,
    searched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_yt_results_cluster ON youtube_results(cluster_id, searched_at DESC);

-- 8. Alerts
CREATE TABLE alerts (
    id              SERIAL PRIMARY KEY,
    alert_type      TEXT NOT NULL CHECK (alert_type IN ('mention', 'cluster', 'digest', 'system')),
    alert_level     SMALLINT NOT NULL,
    item_id         TEXT REFERENCES items(id) ON DELETE SET NULL,
    cluster_id      INTEGER REFERENCES entity_clusters(id) ON DELETE SET NULL,
    message_text    TEXT NOT NULL,
    telegram_msg_id BIGINT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_alerts_sent ON alerts(sent_at DESC);

-- 9. Health checks
CREATE TABLE health_checks (
    id              SERIAL PRIMARY KEY,
    check_type      TEXT NOT NULL CHECK (check_type IN ('heartbeat', 'daily_summary', 'error')),
    items_discovered INTEGER DEFAULT 0,
    items_tracked   INTEGER DEFAULT 0,
    clusters_active INTEGER DEFAULT 0,
    alerts_sent     INTEGER DEFAULT 0,
    errors          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_health_created ON health_checks(created_at DESC);

-- Auto-update timestamp trigger
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clusters_updated ON entity_clusters;
CREATE TRIGGER trg_clusters_updated
    BEFORE UPDATE ON entity_clusters
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- Seed sources: Reddit subreddits
INSERT INTO sources (name, source_type, tier, poll_interval_s) VALUES
    -- Tier 1: r/popular catch-all
    ('popular', 'reddit', 'popular', 120),
    -- Tier 2: High-traffic viral/meme
    ('funny', 'reddit', 'tier2', 180),
    ('memes', 'reddit', 'tier2', 180),
    ('dankmemes', 'reddit', 'tier2', 180),
    ('me_irl', 'reddit', 'tier2', 180),
    ('shitposting', 'reddit', 'tier2', 180),
    ('interestingasfuck', 'reddit', 'tier2', 180),
    ('nextfuckinglevel', 'reddit', 'tier2', 180),
    ('Damnthatsinteresting', 'reddit', 'tier2', 180),
    ('MadeMeSmile', 'reddit', 'tier2', 180),
    ('wholesome', 'reddit', 'tier2', 180),
    ('pics', 'reddit', 'tier2', 180),
    ('videos', 'reddit', 'tier2', 180),
    ('TikTokCringe', 'reddit', 'tier2', 180),
    ('PublicFreakout', 'reddit', 'tier2', 180),
    ('facepalm', 'reddit', 'tier2', 180),
    ('therewasanattempt', 'reddit', 'tier2', 180),
    ('oddlysatisfying', 'reddit', 'tier2', 180),
    ('BeAmazed', 'reddit', 'tier2', 180),
    ('toptalent', 'reddit', 'tier2', 180),
    -- Tier 3: Animal subs
    ('aww', 'reddit', 'animal', 180),
    ('Eyebleach', 'reddit', 'animal', 180),
    ('AnimalsBeingDerps', 'reddit', 'animal', 180),
    ('AnimalsBeingBros', 'reddit', 'animal', 180),
    ('NatureIsFuckingLit', 'reddit', 'animal', 180),
    ('natureismetal', 'reddit', 'animal', 180),
    ('AbsoluteUnits', 'reddit', 'animal', 180),
    ('cats', 'reddit', 'animal', 180),
    ('dogs', 'reddit', 'animal', 180),
    ('AnimalsBeingJerks', 'reddit', 'animal', 180),
    ('WhatsWrongWithYourDog', 'reddit', 'animal', 180),
    ('rarepuppers', 'reddit', 'animal', 180),
    ('Zoomies', 'reddit', 'animal', 180),
    ('IllegallySmolCats', 'reddit', 'animal', 180),
    -- Tier 4: Entertainment
    ('movies', 'reddit', 'entertainment', 300),
    ('television', 'reddit', 'entertainment', 300),
    ('gaming', 'reddit', 'entertainment', 300),
    ('Music', 'reddit', 'entertainment', 300),
    ('anime', 'reddit', 'entertainment', 300),
    ('entertainment', 'reddit', 'entertainment', 300),
    ('popculture', 'reddit', 'entertainment', 300),
    ('Unexpected', 'reddit', 'entertainment', 300),
    ('CrazyFuckingVideos', 'reddit', 'entertainment', 300),
    ('LivestreamFail', 'reddit', 'entertainment', 300),
    -- Tier 5: News
    ('news', 'reddit', 'news', 300),
    ('worldnews', 'reddit', 'news', 300),
    ('nottheonion', 'reddit', 'news', 300),
    ('UpliftingNews', 'reddit', 'news', 300),
    ('technology', 'reddit', 'news', 300),
    ('science', 'reddit', 'news', 300),
    ('space', 'reddit', 'news', 300),
    ('environment', 'reddit', 'news', 300),
    -- Tier 6: Misc
    ('sports', 'reddit', 'misc', 300),
    ('nba', 'reddit', 'misc', 300),
    ('soccer', 'reddit', 'misc', 300),
    ('nfl', 'reddit', 'misc', 300),
    ('artificial', 'reddit', 'misc', 300),
    ('singularity', 'reddit', 'misc', 300),
    ('ChatGPT', 'reddit', 'misc', 300),
    ('LocalLLaMA', 'reddit', 'misc', 300),
    ('australia', 'reddit', 'misc', 300),
    ('unitedkingdom', 'reddit', 'misc', 300),
    ('europe', 'reddit', 'misc', 300),
    ('canada', 'reddit', 'misc', 300),
    ('japan', 'reddit', 'misc', 300),
    ('india', 'reddit', 'misc', 300),
    ('brasil', 'reddit', 'misc', 300),
    -- HN source
    ('hackernews', 'hackernews', 'system', 300)
ON CONFLICT (name) DO NOTHING;
