import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- Database ---
DATABASE_URL = os.environ["DATABASE_URL"]

# --- YouTube Data API v3 ---
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# --- Gemini API ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# --- DataImpulse Proxy ---
PROXY_URL = os.environ.get("PROXY_URL", "")

# --- Reddit RSS ---
REDDIT_RSS_TOKEN = os.environ.get("REDDIT_RSS_TOKEN", "")
REDDIT_RSS_USER = os.environ.get("REDDIT_RSS_USER", "")

# --- Subreddit tiers (91 subs across 6 categories) ---
# Tier 1: General viral catch-all (polled via r/popular + individually)
TIER1_SUBS = [
    "popular",  # catch-all — polled as r/popular/rising/.rss
]

# Tier 2: High-traffic viral/meme subs
TIER2_SUBS = [
    "funny", "memes", "dankmemes", "me_irl", "shitposting",
    "interestingasfuck", "nextfuckinglevel", "Damnthatsinteresting",
    "MadeMeSmile", "wholesome", "pics", "videos", "TikTokCringe",
    "PublicFreakout", "facepalm", "therewasanattempt",
    "oddlysatisfying", "BeAmazed", "toptalent",
]

# Tier 3: Animal-specific subs
ANIMAL_SUBS = [
    "aww", "Eyebleach", "AnimalsBeingDerps", "AnimalsBeingBros",
    "NatureIsFuckingLit", "natureismetal", "AbsoluteUnits",
    "cats", "dogs", "AnimalsBeingJerks", "WhatsWrongWithYourDog",
    "rarepuppers", "Zoomies", "IllegallySmolCats",
]

# Tier 4: Entertainment & culture
ENTERTAINMENT_SUBS = [
    "movies", "television", "gaming", "Music", "anime",
    "entertainment", "popculture", "Unexpected",
    "CrazyFuckingVideos", "LivestreamFail",
]

# Tier 5: News & world events
NEWS_SUBS = [
    "news", "worldnews", "nottheonion", "UpliftingNews",
    "technology", "science", "space", "environment",
]

# Tier 6: Sports, AI/tech, international
MISC_SUBS = [
    "sports", "nba", "soccer", "nfl",
    "artificial", "singularity", "ChatGPT", "LocalLLaMA",
    "australia", "unitedkingdom", "europe", "canada", "japan",
    "india", "brasil",
]

# All subs that get individual RSS feeds (not r/popular)
ALL_NICHE_SUBS = TIER2_SUBS + ANIMAL_SUBS + ENTERTAINMENT_SUBS + NEWS_SUBS + MISC_SUBS

# --- Polling intervals (seconds) ---
POPULAR_INTERVAL = 120       # r/popular/rising every 2 min
NICHE_BATCH_INTERVAL = 180   # niche subs every 3 min (round-robin)
HN_INTERVAL = 300            # HN top stories every 5 min
GEMINI_CLUSTER_INTERVAL = 300  # Gemini clustering every 5 min
YOUTUBE_VALIDATION_INTERVAL = 600  # YouTube validation every 10 min
SCORING_INTERVAL = 120       # Momentum scoring every 2 min

# Reddit RSS rate limit: ~2 seconds between requests
RSS_REQUEST_DELAY = 2.5

# --- Momentum scoring ---
# Alert thresholds (mention-based)
ALERT_LEVEL_1 = 3    # 3+ mentions across 2+ subs in 4hrs -> digest
ALERT_LEVEL_2 = 5    # 5+ mentions across 3+ subs in 2hrs -> immediate
ALERT_LEVEL_3 = 10   # 10+ mentions across 5+ subs + YouTube -> VIRAL

ALERT_L1_MIN_SUBS = 2
ALERT_L1_WINDOW_HOURS = 4
ALERT_L2_MIN_SUBS = 3
ALERT_L2_WINDOW_HOURS = 2
ALERT_L3_MIN_SUBS = 5
ALERT_L3_WINDOW_HOURS = 6

ALERT_COOLDOWN_HOURS = 2
ALERT_DAILY_CAP = 20
DIGEST_INTERVAL_HOURS = 4

# YouTube validation thresholds
YT_VALIDATION_MIN_MENTIONS = 3  # Only search YT after 3+ mentions
YT_MAX_SEARCHES_PER_DAY = 90    # Leave buffer from 100 limit
YT_VIRAL_VIEW_THRESHOLD = 100000  # 100K views = strong signal

# Gemini budget
GEMINI_MAX_REQUESTS_PER_DAY = 1400  # Leave buffer from 1500

# --- Entity matching ---
JACCARD_THRESHOLD = 0.35
ENTITY_CREATION_MIN_MENTIONS = 2  # Need 2+ items to create entity

# --- Cleanup ---
ITEM_RETENTION_DAYS = 7
MOMENTUM_RETENTION_DAYS = 14

# --- Source sub -> location mapping ---
SUB_LOCATIONS = {
    "australia": "Australia",
    "unitedkingdom": "United Kingdom",
    "europe": "Europe",
    "canada": "Canada",
    "japan": "Japan",
    "india": "India",
    "brasil": "Brazil",
}
