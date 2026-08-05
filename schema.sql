-- Viral Animal Momentum Detector — Database Schema
-- Run this against Railway PostgreSQL to initialize

-- 1. Subreddit config
CREATE TABLE IF NOT EXISTS subreddits (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    tier            TEXT NOT NULL DEFAULT 'tier2'
                    CHECK (tier IN ('tier1', 'tier2', 'international')),
    enabled         BOOLEAN NOT NULL DEFAULT true,
    poll_interval_s INTEGER NOT NULL DEFAULT 480,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Subreddit baselines
CREATE TABLE IF NOT EXISTS subreddit_baselines (
    id              SERIAL PRIMARY KEY,
    subreddit_id    INTEGER NOT NULL REFERENCES subreddits(id) ON UPDATE CASCADE ON DELETE CASCADE,
    day_type        TEXT NOT NULL CHECK (day_type IN ('weekday', 'weekend')),
    time_bucket     SMALLINT NOT NULL CHECK (time_bucket BETWEEN 0 AND 5),
    log_score_median    REAL NOT NULL DEFAULT 0,
    log_score_mad       REAL NOT NULL DEFAULT 1,
    log_comment_median  REAL NOT NULL DEFAULT 0,
    log_comment_mad     REAL NOT NULL DEFAULT 1,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subreddit_id, day_type, time_bucket)
);

-- 3. Velocity baselines (per age bracket)
CREATE TABLE IF NOT EXISTS velocity_baselines (
    id              SERIAL PRIMARY KEY,
    subreddit_id    INTEGER NOT NULL REFERENCES subreddits(id) ON UPDATE CASCADE ON DELETE CASCADE,
    day_type        TEXT NOT NULL CHECK (day_type IN ('weekday', 'weekend')),
    age_bracket     SMALLINT NOT NULL CHECK (age_bracket BETWEEN 0 AND 5),
    log_velocity_median REAL NOT NULL DEFAULT 0,
    log_velocity_mad    REAL NOT NULL DEFAULT 1,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subreddit_id, day_type, age_bracket)
);

-- 4. Baseline raw samples
CREATE TABLE IF NOT EXISTS baseline_samples (
    id              BIGSERIAL PRIMARY KEY,
    subreddit_id    INTEGER NOT NULL REFERENCES subreddits(id) ON DELETE CASCADE,
    day_type        TEXT NOT NULL CHECK (day_type IN ('weekday', 'weekend')),
    time_bucket     SMALLINT NOT NULL CHECK (time_bucket BETWEEN 0 AND 5),
    log_score       REAL NOT NULL,
    log_comments    REAL NOT NULL,
    age_bracket     SMALLINT CHECK (age_bracket BETWEEN 0 AND 5),
    log_velocity    REAL,
    sampled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_baseline_samples_lookup
    ON baseline_samples(subreddit_id, day_type, time_bucket, sampled_at DESC);

-- 5. Entity clusters (before posts — no circular FK)
CREATE TABLE IF NOT EXISTS entity_clusters (
    id              SERIAL PRIMARY KEY,
    animal_name     TEXT,
    species         TEXT,
    location        TEXT,
    zoo_or_facility TEXT,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'cooling', 'dormant', 'dead')),
    post_count      INTEGER NOT NULL DEFAULT 0,
    total_score     BIGINT NOT NULL DEFAULT 0,
    total_comments  INTEGER NOT NULL DEFAULT 0,
    peak_anomaly    REAL NOT NULL DEFAULT 0,
    alert_level     SMALLINT NOT NULL DEFAULT 0,
    last_alert_at   TIMESTAMPTZ,
    top_archetype   TEXT,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_post_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clusters_status ON entity_clusters(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_clusters_species ON entity_clusters(species) WHERE species IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clusters_name ON entity_clusters(animal_name) WHERE animal_name IS NOT NULL;

-- 6. Cluster lookup keys
CREATE TABLE IF NOT EXISTS cluster_keys (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    key_type    TEXT NOT NULL CHECK (key_type IN ('name', 'species_location', 'species_sub')),
    key_value   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (key_type, key_value)
);

CREATE INDEX IF NOT EXISTS idx_cluster_keys_lookup ON cluster_keys(key_type, key_value);
CREATE INDEX IF NOT EXISTS idx_cluster_keys_cluster ON cluster_keys(cluster_id);

-- 7. Cluster aliases
CREATE TABLE IF NOT EXISTS cluster_aliases (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    source      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_cluster_aliases_alias ON cluster_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_cluster_aliases_cluster ON cluster_aliases(cluster_id);

-- 8. Posts
CREATE TABLE IF NOT EXISTS posts (
    reddit_id       TEXT PRIMARY KEY,
    subreddit_id    INTEGER NOT NULL REFERENCES subreddits(id) ON UPDATE CASCADE ON DELETE CASCADE,
    title           TEXT NOT NULL,
    author          TEXT,
    url             TEXT,
    permalink       TEXT NOT NULL,
    post_hint       TEXT,
    flair           TEXT,
    created_utc     TIMESTAMPTZ NOT NULL,
    is_crosspost    BOOLEAN NOT NULL DEFAULT false,
    crosspost_parent TEXT,
    image_hash      BIGINT,
    current_score   INTEGER NOT NULL DEFAULT 0,
    current_comments INTEGER NOT NULL DEFAULT 0,
    upvote_ratio    REAL,
    anomaly_score   REAL NOT NULL DEFAULT 0,
    alert_level     SMALLINT NOT NULL DEFAULT 0,
    last_alert_at   TIMESTAMPTZ,
    tracking_active BOOLEAN NOT NULL DEFAULT true,
    cluster_id      INTEGER REFERENCES entity_clusters(id) ON DELETE SET NULL,
    extracted_species TEXT,
    extracted_location TEXT,
    extracted_name  TEXT,
    top_archetype   TEXT,
    narrative_score REAL NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scored_at  TIMESTAMPTZ,
    next_score_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_posts_tracking ON posts(tracking_active) WHERE tracking_active = true;
CREATE INDEX IF NOT EXISTS idx_posts_scoring_due ON posts(next_score_at)
    WHERE tracking_active = true AND next_score_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_posts_cluster ON posts(cluster_id) WHERE cluster_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_posts_image_hash_recent ON posts(image_hash, created_utc DESC)
    WHERE image_hash IS NOT NULL AND tracking_active = true;
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author) WHERE author IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_posts_subreddit_created ON posts(subreddit_id, created_utc DESC);

-- 9. Score history
CREATE TABLE IF NOT EXISTS score_history (
    id              BIGSERIAL PRIMARY KEY,
    post_id         TEXT NOT NULL REFERENCES posts(reddit_id) ON DELETE CASCADE,
    score           INTEGER NOT NULL,
    num_comments    INTEGER NOT NULL,
    upvote_ratio    REAL,
    score_velocity  REAL,
    log_score_z     REAL,
    log_comment_z   REAL,
    velocity_z      REAL,
    anomaly_score   REAL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_score_history_post ON score_history(post_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_score_history_recorded ON score_history(recorded_at);

-- 10. Author tracking
CREATE TABLE IF NOT EXISTS author_activity (
    username        TEXT PRIMARY KEY,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_posts     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS flagged_authors (
    username        TEXT PRIMARY KEY,
    reason          TEXT NOT NULL CHECK (reason IN ('repost_bot', 'celebrity_pet', 'karma_farmer', 'media_account')),
    score_multiplier REAL NOT NULL DEFAULT 0.3 CHECK (score_multiplier BETWEEN 0 AND 1),
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT
);

-- 11. Alerts log
CREATE TABLE IF NOT EXISTS alerts (
    id              SERIAL PRIMARY KEY,
    alert_type      TEXT NOT NULL CHECK (alert_type IN ('post', 'cluster', 'upgrade', 'digest', 'system')),
    alert_level     SMALLINT NOT NULL,
    post_id         TEXT REFERENCES posts(reddit_id) ON DELETE SET NULL,
    cluster_id      INTEGER REFERENCES entity_clusters(id) ON DELETE SET NULL,
    message_text    TEXT NOT NULL,
    telegram_msg_id BIGINT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alert_has_target CHECK (
        post_id IS NOT NULL OR cluster_id IS NOT NULL OR alert_type IN ('digest', 'system')
    )
);

CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_post ON alerts(post_id) WHERE post_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_alerts_cluster ON alerts(cluster_id) WHERE cluster_id IS NOT NULL;

-- 12. Health checks
CREATE TABLE IF NOT EXISTS health_checks (
    id              SERIAL PRIMARY KEY,
    check_type      TEXT NOT NULL CHECK (check_type IN ('heartbeat', 'daily_summary', 'error')),
    posts_scanned   INTEGER DEFAULT 0,
    posts_tracked   INTEGER DEFAULT 0,
    clusters_active INTEGER DEFAULT 0,
    alerts_sent     INTEGER DEFAULT 0,
    api_calls_hour  INTEGER DEFAULT 0,
    errors          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_health_created ON health_checks(created_at DESC);

-- Triggers
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clusters_updated ON entity_clusters;
CREATE TRIGGER trg_clusters_updated
    BEFORE UPDATE ON entity_clusters
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

DROP TRIGGER IF EXISTS trg_baselines_updated ON subreddit_baselines;
CREATE TRIGGER trg_baselines_updated
    BEFORE UPDATE ON subreddit_baselines
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

DROP TRIGGER IF EXISTS trg_velocity_baselines_updated ON velocity_baselines;
CREATE TRIGGER trg_velocity_baselines_updated
    BEFORE UPDATE ON velocity_baselines
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- Seed subreddits
INSERT INTO subreddits (name, tier, poll_interval_s) VALUES
    ('aww', 'tier1', 240), ('funny', 'tier1', 240), ('Eyebleach', 'tier1', 240),
    ('AnimalsBeingDerps', 'tier1', 240), ('NatureIsFuckingLit', 'tier1', 240),
    ('interestingasfuck', 'tier1', 240), ('nextfuckinglevel', 'tier1', 240),
    ('MadeMeSmile', 'tier1', 240), ('pics', 'tier1', 240), ('videos', 'tier1', 240),
    ('TikTokCringe', 'tier1', 240),
    ('cats', 'tier2', 480), ('dogs', 'tier2', 480), ('AbsoluteUnits', 'tier2', 480),
    ('AnimalsBeingBros', 'tier2', 480), ('natureismetal', 'tier2', 480),
    ('UpliftingNews', 'tier2', 480), ('AnimalsBeingJerks', 'tier2', 480),
    ('WhatsWrongWithYourDog', 'tier2', 480), ('memes', 'tier2', 480),
    ('australia', 'international', 900), ('unitedkingdom', 'international', 900),
    ('europe', 'international', 900), ('canada', 'international', 900),
    ('japan', 'international', 900)
ON CONFLICT (name) DO NOTHING;
