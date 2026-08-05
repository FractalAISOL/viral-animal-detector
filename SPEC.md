# Viral Animal Momentum Detector — Complete Technical Specification (v5 FINAL)

All 40+ audit issues from v3/v4 have been addressed. This is the build-from document.

---

## 1. SUBREDDIT STRATEGY (25 subreddits, down from 58)

### Tier 1 — Poll /rising every 4min (11 subs)
High-volume animal + crossover subs. /rising only, no /new (rising catches everything within 15min).

| Subreddit | ~Subs | Why |
|-----------|-------|-----|
| r/aww | 38M | #1 animal content launchpad |
| r/funny | 67M | Largest sub, 20-30% animal |
| r/Eyebleach | 4.6M | High quality animal content |
| r/AnimalsBeingDerps | 3.5M | High viral-per-post ratio |
| r/NatureIsFuckingLit | 7M | Primary wildlife source |
| r/interestingasfuck | 12M | Crossover signal — animal posts here = breakout |
| r/nextfuckinglevel | 9.1M | Animal skill/intelligence clips |
| r/MadeMeSmile | 5.3M | Rescue stories, emotional viral |
| r/pics | 30M | General photos |
| r/videos | 27M | Video-format animal content |
| r/TikTokCringe | 2.2M | Reddit window into TikTok virality — PROMOTED from Tier 3 |

### Tier 2 — Poll /rising every 8min (9 subs)
Species-specific and secondary signal subs.

| Subreddit | Why |
|-----------|-----|
| r/cats | Largest species sub |
| r/dogs | Dog-specific virality |
| r/AbsoluteUnits | Size-based virality (Pesto) |
| r/AnimalsBeingBros | Interspecies friendship |
| r/natureismetal | Shock/awe wildlife |
| r/UpliftingNews | Animal rescue news |
| r/AnimalsBeingJerks | Chaos content |
| r/WhatsWrongWithYourDog | Weird behavior |
| r/memes | Meme-template detection |

### International (5 subs) — Keyword-filtered /new every 15min
Replaces US city subs. Catches Moo Deng, Pesto, Punch patterns.

| Subreddit | Why |
|-----------|-----|
| r/australia | Pesto, Melbourne Zoo content |
| r/unitedkingdom | London Zoo, UK wildlife |
| r/europe | European zoo content |
| r/canada | Toronto/Calgary Zoo content |
| r/japan | Punch-type content |

Keyword filter for international subs: `animal OR dog OR cat OR bear OR wildlife OR zoo OR escaped OR rescued OR viral`

### Dropped from plan
- All 14 Tier 3 niche subs (r/corgi, r/goldenretrievers, etc.) — cross-post to Tier 1
- All 20 US city subs — animal content too rare, international gap more important
- /new polling for Tier 1 and 2 — /rising catches content within 15min

### News detection (lightweight)
- 4 broad searches once per hour across r/news + r/worldnews:
  - `"animal zoo wildlife"`, `"pet euthanized seized"`, `"endangered species"`, `"viral animal"`
- 4 searches × 2 subs × 1/hr = 8 req/hr (down from 112)

---

## 2. API REQUEST BUDGET

```
Tier 1:  11 subs × /rising every 4min    = 11 × 15/hr = 165 req/hr
Tier 2:   9 subs × /rising every 8min    =  9 × 7.5/hr = 68 req/hr
Intl:     5 subs × /new every 15min      =  5 × 4/hr   = 20 req/hr
News:     4 searches × 2 subs × 1/hr     =              =  8 req/hr
Tracking: ~200 posts × every 15min       = 200 × 4/hr   = 800 req/hr
                                                    TOTAL: 1,061 req/hr
                                                         = 17.7 req/min

Scaling to 500 tracked posts:                            = 22.0 req/min
Scaling to 1000 tracked posts:                           = 30.7 req/min

Rate limit: 100 req/min. Headroom: 70-83%.
```

### Tracked post ceiling
- Maximum 500 actively tracked posts at any time
- When limit reached: stop tracking posts with lowest anomaly scores
- Posts older than 24hrs auto-deactivate regardless

---

## 3. SCORING ENGINE (all audit issues fixed)

### 3.1 Baseline Calculation

**Time buckets**: 6 × 4hr UTC windows, separate weekday/weekend = 12 baselines per sub
**Window**: Rolling 14 days
**Statistic**: Median + MAD on LOG-TRANSFORMED values (fixes power-law inflation)
**Minimum samples**: 5 per bucket before baseline is reliable

**Cold start strategy** (NO hardcoded baselines):
- First 48 hours: silent data collection mode. No alerts.
- System collects raw samples and builds baselines.
- After 48hrs with ≥5 samples per bucket: alerts activate.
- Telegram notification: "Baselines established. Monitoring active."

### 3.2 Anomaly Score Formula

**All metrics log-transformed before z-scoring:**
```
log_score_z    = (log(score) - median_log_score) / MAD_log_score
log_comment_z  = (log(comments+1) - median_log_comments) / MAD_log_comments
velocity_z     = (log(velocity+1) - median_log_velocity_for_age_bracket) / MAD_log_velocity_for_age_bracket
```

**All z-scores clamped to [0, 30]** (was [0, 50] for score only — now consistent)

**Ratio is a MULTIPLIER, not additive:**
```
ratio_mult:
  ≥ 0.97 → 1.15
  ≥ 0.95 → 1.10
  ≥ 0.92 → 1.00
  ≥ 0.88 → 0.90
  < 0.88 → 0.75  (controversial content penalized)
```

**Final formula:**
```
raw_AS = (0.35 × log_score_z) + (0.35 × log_comment_z) + (0.30 × velocity_z)
AS = ratio_mult × raw_AS
```

**Theoretical range**: 0 to 1.15 × (0.35×30 + 0.35×30 + 0.30×30) = 1.15 × 30 = 34.5

**Weights rationale (changed from v3):**
- Score and comments equally weighted at 0.35 (comments = engagement depth)
- Velocity at 0.30 (earliest signal of breakout)
- Ratio removed from additive, now multiplicative gate

### 3.3 Velocity Baselines

**Per-age-bracket baselines** (fixes apples-to-oranges comparison):

| Bracket | Post age |
|---------|----------|
| V1 | 0-30min |
| V2 | 30min-1.5hr |
| V3 | 1.5hr-3hr |
| V4 | 3hr-6hr |
| V5 | 6hr-12hr |
| V6 | 12hr-24hr |

Each bracket has its own median and MAD for velocity. Early velocity compared to early velocity. Late compared to late.

### 3.4 Scoring Schedule

First score at **30 minutes** (was 20min — extra 10min reduces noise from vote fuzzing).
Then: 1hr, 2hr, 4hr, 8hr, 16hr, 24hr.

7 scoring passes per post. Logarithmic intervals match Reddit's growth curve.

### 3.5 Alert Thresholds

| Level | Trigger | Delivery |
|-------|---------|----------|
| Level 1 | AS ≥ 5.0 | Batched digest every 4hrs |
| Level 2 | AS ≥ 8.0 | Immediate Telegram |
| Level 3 | AS ≥ 12.0 OR cross-sub trigger | Immediate, no rate limit |

**Threshold calibration (validated with realistic numbers):**
- Normal r/aww post (200 score, 15 comments): AS ≈ 2.5 → No alert ✓
- Moderately viral (5K score, 400 comments): AS ≈ 8.5 → Level 2 ✓
- Mega viral / Peanut-level (80K score, 5K comments): AS ≈ 13.3 → Level 3 ✓
- Controversial low-ratio (300 score, 200 comments, 0.82 ratio): AS ≈ 3.5 → No alert ✓

**Cross-sub Level 3 trigger (fixed):**
```
3+ posts about same entity across different subs within 24hrs
WHERE each post AS ≥ 2.0
AND at least one post AS ≥ 5.0
```

### 3.6 Alert Deduplication

- **Level transitions only**: re-alert only when post crosses to a higher level (L1→L2, L2→L3)
- **No re-alerts within same level** (was 50% growth — removed to prevent alert fatigue)
- **Cooldown**: minimum 2 hours between any alerts for the same entity
- **Daily cap**: 20 messages max. Level 3 bypasses cap.

### 3.7 Alert Formats

**Level 1 digest (every 4hrs, if any):**
```
ANIMAL RADAR - 4h Digest

3 posts above baseline:

1. r/aww - "Baby fox found in shed"
   Score: 4,200 (AS: 7.2) | 189 comments
   Velocity: +320/hr | Ratio: 0.97
   https://redd.it/abc123

2. ...
```

**Level 2 (immediate):**
```
TRENDING - r/aww

"Baby fox found in shed"
Score: 18,400 (AS: 11.3) | 1,290 comments
Velocity: +2,100/hr | Ratio: 0.98

Cross-posts: 2 subs (r/Eyebleach, r/foxes)
Entity: fox / Portland (3 posts, 22,400 total)

https://redd.it/abc123
```

**Level 3 (immediate):**
```
*** VIRAL BREAKOUT ***

"Peanut the Squirrel" - 6 posts / 4 subs

Lead: r/aww - 67,200 score (AS: 24.1)
Total: 121,600 across 4 subs | +8,400/hr

Archetype: OUTRAGE + NAMED (1.5x combo)
Entity: squirrel / New York / "Peanut"

https://redd.it/abc123
```

### 3.8 False Positive Filtering

**Repost bots**: Account age < 30 days + >10K karma → 0.3x score multiplier
**Karma farmers**: >20 posts in monitored subs in 7 days → 0.5x (computed live, not cached)
**Media accounts**: Maintained blocklist (TheDodo, etc.) → excluded
**Scheduled content**: Flair contains "megathread"/"weekly"/"daily" → excluded

### 3.9 Minimum Score Gate

**Ignore posts with raw score < 50** before scoring.
Fixes: vote fuzzing noise on low-score posts, reduces processing load.

---

## 4. ENTITY MATCHING (all audit issues fixed)

### 4.1 Species Detection

~580 terms → ~200 canonical species. Same word list as v3 spec, with these fixes:

**Fix: Subreddit-context disambiguation**

```python
# Subreddits where ambiguous terms should be ACCEPTED as animals
ANIMAL_SUBREDDITS = {
    "aww", "eyebleach", "animalsbeingderps", "animalsbeingbros",
    "natureisfuckinglit", "absoluteunits", "cats", "dogs",
    "animalsbeingjerks", "whatswrongwithyourdog", "natureismetal",
    "zoomies", "rarepuppers", "snakes", "reptiles", "birding",
    "aquariums", "fishing", ...
}

# Subreddits where ambiguous terms should be REJECTED
NON_ANIMAL_SUBREDDITS = {
    "programming", "boxing", "nfl", "nba", "music", "cars",
    "hardware", "baseball", "cricket", ...
}

def should_accept_ambiguous(term, subreddit):
    sub = subreddit.lower()
    if sub in ANIMAL_SUBREDDITS:
        return True
    if sub in NON_ANIMAL_SUBREDDITS:
        return False
    # General subs (r/funny, r/pics): require second animal signal
    # (another species term, or animal keyword like "pet", "rescue", "zoo")
    return False  # conservative default
```

**Fix: "chonk" maps to generic "animal" not "cat"**
```python
"chonk": ("animal", "generic"),
"chonker": ("animal", "generic"),
"void": REMOVED  # too ambiguous, not useful
```

**Fix: Multi-word matching includes stemmed variants**
Before matching, normalize: "chonky" → "chonk", "rescuing" → "rescue" (simple suffix stripping, not full NLP).

### 4.2 Name Extraction (8 patterns, up from 6)

```python
NAME_PATTERNS = [
    # 1. "Meet X, the [species]" / "Meet X the [species]"
    r'meet\s+(.+?)\s*[,.]?\s*(?:the|a|an)\s',

    # 2. "X the [species]" at start
    r'^(.+?)\s+the\s+(?:' + SPECIES_PATTERN + r')',

    # 3. "This is X" / "Say hello to X" / "Introducing X"
    r'(?:this is|say (?:hello|hi) to|introducing|everyone meet)\s+(.+?)(?:\s*[,!.]|\s+the\s|\s+who|\s+and)',

    # 4. "[species] named/called/nicknamed X"
    r'(?:named|called|dubbed|nicknamed|known as)\s+(.+?)(?:\s*[,!.]|\s+(?:who|and|is|was|has|after)|\s*$)',

    # 5. "RIP X" / "Rest in peace X"
    r'(?:rip|rest in peace|farewell|goodbye|rip to)\s+(.+?)(?:\s*[,!.]|\s+the\s|\s*$)',

    # 6. "X update" / "X news" / "X is..."
    r'^(.+?)\s+(?:update|news|watch|alert|is\s)',

    # 7. NEW: "My/Our [species] X" — MOST COMMON REDDIT FORMAT
    r'(?:my|our|his|her|their)\s+(?:' + SPECIES_PATTERN + r')\s+(.+?)(?:\s+(?:just|is|was|did|has|had|does|got|went|loves|hates|found|ate|broke|met|turned)|\s*[,!.])',

    # 8. NEW: "X, the/a [species] from/at/in [location]"
    r'^(.+?),?\s+(?:the|a|an)\s+(?:' + SPECIES_PATTERN + r')\s+(?:from|at|in|of)\s',
]
```

**Key fixes:**
- All capture groups use `(.+?)` not `(\w+)` — captures multi-word names like "Moo Deng"
- Pattern 7 added: "My dog Max just did..." → extracts "Max"
- Pattern 8 added: "Jimothy, the raccoon from Seattle" → extracts "Jimothy"
- Patterns terminate at verb words / punctuation to avoid over-capturing

**Name blacklist expanded:**
```python
NAME_BLACKLIST = {
    "the", "this", "that", "what", "why", "how", "when", "where", "who",
    "just", "look", "see", "watch", "can", "does", "did", "has", "have",
    "breaking", "update", "news", "alert", "warning", "help", "please",
    "urgent", "psa", "til", "tifu", "oc", "rant", "reminder", "official",
    "confirmed", "megathread",
    "my", "our", "your", "his", "her", "its", "their",
    "new", "old", "big", "little", "baby", "cute", "rare",
    "today", "yesterday", "finally", "apparently", "literally",
    "ever", "never", "always", "still", "now", "here", "there",
    "everyone", "someone", "anyone", "nobody", "nothing",
    "omg", "wow", "holy", "oh", "damn", "lol", "lmao",
}
```

### 4.3 Entity Memory (NEW — fixes "Moo Deng update!" problem)

```python
# Persistent lookup: known viral animal names → species + location
# Grows over time as entities are created
# NOT a separate table — derived from entity_clusters WHERE animal_name IS NOT NULL

known_entities = {
    # Populated from entity_clusters where animal_name IS NOT NULL
    # Format: lowercase_name → (species, location)
    "moo deng": ("pygmy hippo", "Chonburi"),
    "peanut": ("squirrel", "New York"),
    "jimothy": ("raccoon", "Seattle"),
    "punch": ("monkey", "Ichikawa"),
    ...
}
```

**On every new post:**
1. Check title against known_entities FIRST (before species/location extraction)
2. If known name found → inherit species + location from entity memory
3. Skip species/name extraction for known matches (already resolved)

### 4.4 Cluster Key Strategy

**Keys stored in separate `cluster_keys` table (not a column):**

Priority order for matching:
1. `name:{normalized_name}` — e.g., `name:moo_deng` (highest confidence)
2. `species_location:{species}:{location}` — e.g., `species_location:raccoon:seattle`
3. `species_sub:{species}:{subreddit}` — NEW: same species + same subreddit within 24hrs

**REMOVED: `species_only:{species}`** — too contamination-prone. Posts with species but no location/name get stored but don't create entities. They can be retroactively matched when a name or location emerges.

### 4.5 Cross-Sub Detection

**Method 1: Reddit crosspost_parent** (~10-15% of reposts)
Check first, cheapest.

**Method 2: Title similarity**
- Jaccard threshold lowered to **0.35** (was 0.45)
- **Proper noun boost**: words starting with uppercase get 2x weight in Jaccard
- Proper nouns that match both titles → auto-match regardless of Jaccard score

**Method 3: Perceptual image hash**
- Hamming distance threshold raised to **≤ 12** (was ≤ 8)
- Only for posts where `thumbnail.startswith('http')`
- Use `submission.preview` source images when available
- **Combined signal**: if Hamming 8-16 AND (same species + Jaccard > 0.25) → match

### 4.6 Viral Narrative Keywords

**Key fix: require 2+ keywords from same archetype** before scoring it.
Single keyword matches ("died", "rescued") alone don't count — too noisy.

**Combination bonuses: take MAX, don't stack multiplicatively:**
```python
combo_bonus = max(applicable_bonuses)  # NOT multiplicative
# Outrage + Named → 1.5x
# Underdog + Cute → 1.2x
# Genetic + Size → 1.15x
```

**Entity creation threshold lowered to 1.0** (was 2.0).
Fixes: cute-only and named-only posts can now create entities.
Paired with the 2+ keyword minimum, this doesn't increase noise.

**Archetype weights adjusted:**
```
outrage_controversy: 1.3  (was 1.4 — slightly reduced)
celebrity_named:     1.2  (unchanged)
genetic_oddity:      1.1  (unchanged)
underdog_survivor:   1.0  (unchanged)
unusual_behavior:    1.0  (unchanged)
size_anomaly:        0.9  (unchanged)
cuteness_overload:   0.8  (was 0.6 — raised so cute content can create entities)
```

### 4.7 Location Extraction

**Fixes:**
- "Portland" → check for "South Portland", "Portland, Maine" vs "Portland, Oregon" — use state co-occurrence
- r/Georgia → check title for US state context vs country context
- Zoo names require lowercase match (not case-sensitive — "Night Safari" in any context could false-match)
  - Fix: zoo names only match if preceded/followed by zoo-context words ("zoo", "visit", "born at", "at the")

### 4.8 Entity Lifecycle

```
NEW POST → extract species/location/name → generate cluster keys
    │
    ├─ Match against known_entities (name lookup) → FOUND → link to existing cluster
    │
    ├─ Match against cluster_keys table → FOUND → link to existing cluster
    │                                              update cluster aggregates atomically
    │
    ├─ Cross-sub detection (crosspost/Jaccard/pHash) → FOUND → link + merge if needed
    │
    └─ NO MATCH + virality ≥ 1.0 + has species or name → CREATE new entity
       Posts with no species AND no name → store but don't create entity
       Posts with virality < 1.0 → store for baseline data only
```

**Race condition fix**: Use `SELECT ... FOR UPDATE SKIP LOCKED` when creating clusters.
If two posts for same entity arrive simultaneously, one gets the lock, creates the cluster.
The other waits, finds the existing cluster, and links to it.

---

## 5. DATABASE SCHEMA (all audit issues fixed)

```sql
-- =============================================
-- Create tables in dependency order
-- (entity_clusters BEFORE posts — fixes circular FK)
-- =============================================

-- 1. Subreddit config
CREATE TABLE subreddits (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    tier            TEXT NOT NULL DEFAULT 'tier2'
                    CHECK (tier IN ('tier1', 'tier2', 'international')),
    enabled         BOOLEAN NOT NULL DEFAULT true,
    poll_interval_s INTEGER NOT NULL DEFAULT 480,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Subreddit baselines
CREATE TABLE subreddit_baselines (
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
CREATE TABLE velocity_baselines (
    id              SERIAL PRIMARY KEY,
    subreddit_id    INTEGER NOT NULL REFERENCES subreddits(id) ON UPDATE CASCADE ON DELETE CASCADE,
    day_type        TEXT NOT NULL CHECK (day_type IN ('weekday', 'weekend')),
    age_bracket     SMALLINT NOT NULL CHECK (age_bracket BETWEEN 0 AND 5),
    -- 0=0-30min, 1=30min-1.5hr, 2=1.5hr-3hr, 3=3hr-6hr, 4=6hr-12hr, 5=12hr-24hr
    log_velocity_median REAL NOT NULL DEFAULT 0,
    log_velocity_mad    REAL NOT NULL DEFAULT 1,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subreddit_id, day_type, age_bracket)
);

-- 4. Baseline raw samples (for computing medians)
CREATE TABLE baseline_samples (
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

CREATE INDEX idx_baseline_samples_lookup
    ON baseline_samples(subreddit_id, day_type, time_bucket, sampled_at DESC);

-- Retention: delete samples older than 14 days (run daily)

-- 5. Entity clusters (BEFORE posts — fixes circular FK)
CREATE TABLE entity_clusters (
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

CREATE INDEX idx_clusters_status ON entity_clusters(status) WHERE status = 'active';
CREATE INDEX idx_clusters_species ON entity_clusters(species) WHERE species IS NOT NULL;
CREATE INDEX idx_clusters_name ON entity_clusters(animal_name) WHERE animal_name IS NOT NULL;

-- 6. Cluster lookup keys (multiple keys per cluster)
CREATE TABLE cluster_keys (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    key_type    TEXT NOT NULL CHECK (key_type IN ('name', 'species_location', 'species_sub')),
    key_value   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (key_type, key_value)
);

CREATE INDEX idx_cluster_keys_lookup ON cluster_keys(key_type, key_value);
CREATE INDEX idx_cluster_keys_cluster ON cluster_keys(cluster_id);

-- 7. Cluster aliases (animal name variants)
CREATE TABLE cluster_aliases (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER NOT NULL REFERENCES entity_clusters(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    source      TEXT,  -- 'title_extraction', 'crosspost', 'manual'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, alias)
);

CREATE INDEX idx_cluster_aliases_alias ON cluster_aliases(alias);
CREATE INDEX idx_cluster_aliases_cluster ON cluster_aliases(cluster_id);

-- 8. Posts (core tracking)
CREATE TABLE posts (
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
    next_score_at   TIMESTAMPTZ  -- when the next scoring pass is due
);

CREATE INDEX idx_posts_tracking ON posts(tracking_active) WHERE tracking_active = true;
CREATE INDEX idx_posts_scoring_due ON posts(next_score_at)
    WHERE tracking_active = true AND next_score_at IS NOT NULL;
CREATE INDEX idx_posts_cluster ON posts(cluster_id) WHERE cluster_id IS NOT NULL;
CREATE INDEX idx_posts_image_hash_recent ON posts(image_hash, created_utc DESC)
    WHERE image_hash IS NOT NULL AND tracking_active = true;
CREATE INDEX idx_posts_author ON posts(author) WHERE author IS NOT NULL;
CREATE INDEX idx_posts_subreddit_created ON posts(subreddit_id, created_utc DESC);

-- 9. Score history (time series)
CREATE TABLE score_history (
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

CREATE INDEX idx_score_history_post ON score_history(post_id, recorded_at DESC);
CREATE INDEX idx_score_history_recorded ON score_history(recorded_at);

-- 10. Author tracking (for false positive filtering)
CREATE TABLE author_activity (
    username        TEXT PRIMARY KEY,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_posts     INTEGER NOT NULL DEFAULT 0
    -- post_count_7d REMOVED — compute live from posts table
);

CREATE TABLE flagged_authors (
    username        TEXT PRIMARY KEY,
    reason          TEXT NOT NULL CHECK (reason IN ('repost_bot', 'celebrity_pet', 'karma_farmer', 'media_account')),
    score_multiplier REAL NOT NULL DEFAULT 0.3 CHECK (score_multiplier BETWEEN 0 AND 1),
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT
);

-- 11. Alerts log
CREATE TABLE alerts (
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

CREATE INDEX idx_alerts_sent ON alerts(sent_at DESC);
CREATE INDEX idx_alerts_post ON alerts(post_id) WHERE post_id IS NOT NULL;
CREATE INDEX idx_alerts_cluster ON alerts(cluster_id) WHERE cluster_id IS NOT NULL;

-- 12. Health checks
CREATE TABLE health_checks (
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

CREATE INDEX idx_health_created ON health_checks(created_at DESC);
-- Retention: keep 7 days, run cleanup daily

-- =============================================
-- TRIGGERS
-- =============================================

CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_clusters_updated
    BEFORE UPDATE ON entity_clusters
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_baselines_updated
    BEFORE UPDATE ON subreddit_baselines
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_velocity_baselines_updated
    BEFORE UPDATE ON velocity_baselines
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
```

### Schema fixes addressed:
- [x] Circular FK: entity_clusters created before posts
- [x] Missing baseline_samples table: added
- [x] Missing cluster_keys table: added
- [x] Missing cluster_aliases table: added
- [x] Missing cluster_key storage: cluster_keys table
- [x] post_count_7d staleness: column removed, compute live
- [x] Race conditions: use atomic SET col = col + delta (enforced in app layer)
- [x] Score history cleanup: snapshot finals into posts row before cleanup
- [x] Health checks retention: 7-day cleanup
- [x] CHECK constraints: added on all enum columns
- [x] ON DELETE/ON UPDATE cascades: added
- [x] updated_at triggers: added
- [x] Missing indexes: scoring_due, score_history_recorded, image_hash_recent
- [x] Alert target constraint: CHECK added
- [x] Subreddit PK: changed to SERIAL id with UNIQUE name
- [x] Velocity baselines table: added (per-age-bracket)
- [x] next_score_at column: added for efficient scoring scheduling
- [x] v6 fix: posts.subreddit_id ON DELETE CASCADE added
- [x] v6 fix: flagged_authors.score_multiplier CHECK (0-1) added
- [x] v6 fix: alerts FK indexes added (post_id, cluster_id)
- [x] v6 fix: cluster_aliases FK index added (cluster_id)
- [x] v6 fix: known_entities clarified as derived from entity_clusters (not a separate table)
- [x] v6 fix: alert thresholds recalibrated (L1: 5.0, L2: 8.0, L3: 12.0) — validated with realistic numbers
- [x] v6 fix: post deactivation at 25hrs (1hr buffer past final 24hr scoring pass)

---

## 6. ARCHITECTURE: SINGLE-WRITER PIPELINE

**Fixes scorer/alerter race condition. One process does everything:**

```
MAIN LOOP (single Python process)
│
├── POLLER (async, runs continuously)
│   ├── Fetch /rising for Tier 1 subs every 4min
│   ├── Fetch /rising for Tier 2 subs every 8min
│   ├── Fetch /new for International subs every 15min
│   ├── Run news searches every 1hr
│   ├── For each new post:
│   │   ├── Extract species/location/name
│   │   ├── Match to entity (or create new)
│   │   ├── Download thumbnail + compute pHash (if applicable)
│   │   ├── Store in DB
│   │   └── Schedule first scoring at created_utc + 30min
│   └── Deduplicate: skip posts already in DB (in-memory seen-set)
│
├── SCORER (async, runs continuously)
│   ├── Query: posts WHERE next_score_at <= now() AND tracking_active = true
│   ├── For each due post:
│   │   ├── Fetch current score/comments/ratio from Reddit API
│   │   ├── Compute log z-scores against baselines
│   │   ├── Compute velocity against age-bracket baseline
│   │   ├── Compute final AS with ratio multiplier
│   │   ├── Apply author multiplier (bot/farmer check)
│   │   ├── Update post record (atomic)
│   │   ├── Insert score_history row
│   │   ├── Update entity cluster aggregates (atomic: SET col = col + delta)
│   │   ├── Update baseline_samples with this data point
│   │   ├── Check alert thresholds → send Telegram if crossed
│   │   └── Schedule next_score_at (logarithmic intervals)
│   └── Deactivate posts older than 25hrs (1hr buffer past final scoring at 24hr)
│
├── CROSS-SUB DETECTOR (runs every 5min)
│   ├── For active entities with 2+ posts:
│   │   ├── Check if 3+ subs involved
│   │   ├── Check minimum AS thresholds
│   │   └── Trigger Level 3 alert if criteria met
│   └── Merge duplicate clusters if new evidence found
│
├── BASELINE UPDATER (runs every 1hr)
│   ├── Recompute medians/MADs from baseline_samples (last 14 days)
│   └── Update subreddit_baselines and velocity_baselines
│
├── CLEANUP (runs daily at 03:00 UTC)
│   ├── Delete baseline_samples older than 14 days
│   ├── Delete score_history older than 30 days for inactive posts
│   ├── Delete health_checks older than 7 days
│   ├── Transition entity statuses: active→cooling (24hr), cooling→dormant (7d), dormant→dead (30d)
│   ├── Reconcile cluster aggregates (safety net):
│   │   UPDATE entity_clusters SET post_count = (SELECT COUNT FROM posts...), ...
│   └── Enforce 500 tracked-post ceiling
│
└── HEALTH (runs every 10min)
    ├── Insert heartbeat row
    └── Daily summary at 09:00 UTC via Telegram
```

**No separate alerter process.** Scorer triggers alerts directly after writing scores. Eliminates race conditions.

---

## 7. ERROR HANDLING

### Reddit API down
- Exponential backoff: 30s, 60s, 2min, 5min, 10min max
- After 5 consecutive failures (~18min): Telegram alert
- Continue retrying every 10min
- On recovery: Telegram notification with gap duration
- During downtime: freeze all post timers (don't expire)

### Subreddit gone private (HTTP 403)
- Set subreddit.enabled = false
- One-time Telegram notification
- Daily HEAD request to check if reopened

### Rate limit exceeded (HTTP 429)
- PRAW handles this automatically via X-Ratelimit headers
- If sustained >80% utilization: increase poll intervals by 30%
- Track utilization in health_checks

### Container restart
1. Resume all tracking_active posts
2. Resume all active entity clusters
3. Detect gap via health_checks
4. If gap > 30min: Telegram notification
5. Mark posts that aged past 24hrs during gap as inactive
6. Do NOT retroactively score (stale velocity data)

### Connection pooling
- Use SQLAlchemy connection pool: min=2, max=8
- Never exceed Railway's default max_connections (100)

---

## 8. TECH STACK

| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Reddit API | PRAW (or AsyncPRAW for async) |
| Database | PostgreSQL (Railway managed) |
| ORM | SQLAlchemy 2.0 |
| Image hashing | imagehash + Pillow |
| HTTP | httpx (async, for thumbnail downloads) |
| Alerts | python-telegram-bot |
| Scheduling | asyncio tasks (no external scheduler) |
| Hosting | Railway (~$5/month) |

---

## 9. KNOWN LIMITATIONS (accepted)

1. **TikTok-origin animals**: 1-4 day delay (caught on Reddit cross-post)
2. **Non-English origin** (Punch from Japan): 3-7 day delay
3. **Not fast enough for memecoin trading** — beats mainstream media by days, not hours
4. **Common-word animal names** ("Punch", "Baby") — partial regex solution, not perfect
5. **Reddit OAuth approval** may take days/weeks — apply immediately, build while waiting
6. **First 48 hours**: no alerts (baseline building)
7. **Image hash** misses heavily cropped/modified reposts (Hamming > 12)

---

## 10. ESTIMATED DATA VOLUMES

| Table | 30 days | 90 days | 1 year |
|-------|---------|---------|--------|
| posts | 6,000 | 18,000 | 73,000 |
| score_history | 42,000 | 126,000 | 500,000 |
| baseline_samples | capped at 14d | capped | capped |
| entity_clusters | 200 | 600 | 2,400 |
| cluster_keys | 400 | 1,200 | 4,800 |
| alerts | 300 | 900 | 3,600 |
| health_checks | capped at 7d | capped | capped |

**Total DB size after 1 year: ~80-100MB**
