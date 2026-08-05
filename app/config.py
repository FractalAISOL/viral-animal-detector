import os
from dotenv import load_dotenv

load_dotenv()


# Reddit API
REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USERNAME = os.environ["REDDIT_USERNAME"]
REDDIT_PASSWORD = os.environ["REDDIT_PASSWORD"]
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "viral-animal-detector/1.0")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Database
DATABASE_URL = os.environ["DATABASE_URL"]

# --- Subreddit tiers ---
TIER1_SUBS = [
    "aww", "funny", "Eyebleach", "AnimalsBeingDerps", "NatureIsFuckingLit",
    "interestingasfuck", "nextfuckinglevel", "MadeMeSmile", "pics", "videos",
    "TikTokCringe",
]
TIER2_SUBS = [
    "cats", "dogs", "AbsoluteUnits", "AnimalsBeingBros", "natureismetal",
    "UpliftingNews", "AnimalsBeingJerks", "WhatsWrongWithYourDog", "memes",
]
INTERNATIONAL_SUBS = ["australia", "unitedkingdom", "europe", "canada", "japan"]
INTERNATIONAL_KEYWORDS = [
    "animal", "dog", "cat", "bear", "wildlife", "zoo",
    "escaped", "rescued", "viral",
]

# --- Polling intervals (seconds) ---
TIER1_INTERVAL = 240     # 4 min
TIER2_INTERVAL = 480     # 8 min
INTL_INTERVAL = 900      # 15 min
NEWS_INTERVAL = 3600     # 1 hr

# --- Scoring ---
SCORE_WEIGHTS = {"score": 0.35, "comments": 0.35, "velocity": 0.30}
Z_SCORE_CLAMP = (0.0, 30.0)
MIN_SCORE_GATE = 50
COLD_START_HOURS = 48
MIN_BASELINE_SAMPLES = 5
MAX_TRACKED_POSTS = 500
POST_DEACTIVATE_HOURS = 25

# Ratio multipliers
RATIO_MULTIPLIERS = [
    (0.97, 1.15),
    (0.95, 1.10),
    (0.92, 1.00),
    (0.88, 0.90),
    (0.00, 0.75),
]

# Scoring schedule: minutes after post creation
SCORING_SCHEDULE_MINUTES = [30, 60, 120, 240, 480, 960, 1440]

# Velocity age brackets (minutes)
VELOCITY_BRACKETS = [
    (0, 30),        # V1
    (30, 90),       # V2
    (90, 180),      # V3
    (180, 360),     # V4
    (360, 720),     # V5
    (720, 1440),    # V6
]

# --- Alert thresholds ---
ALERT_LEVEL_1 = 5.0
ALERT_LEVEL_2 = 8.0
ALERT_LEVEL_3 = 12.0
ALERT_COOLDOWN_HOURS = 2
ALERT_DAILY_CAP = 20
DIGEST_INTERVAL_HOURS = 4

# Cross-sub Level 3 trigger
CROSS_SUB_MIN_POSTS = 3
CROSS_SUB_MIN_AS = 2.0
CROSS_SUB_LEAD_AS = 5.0

# --- Entity matching ---
JACCARD_THRESHOLD = 0.35
PHASH_THRESHOLD = 12
NARRATIVE_MIN_KEYWORDS = 2
ENTITY_CREATION_THRESHOLD = 1.0

# --- False positive filters ---
BOT_MAX_ACCOUNT_AGE_DAYS = 30
BOT_MIN_KARMA = 10000
BOT_SCORE_MULT = 0.3
FARMER_MAX_POSTS_7D = 20
FARMER_SCORE_MULT = 0.5
MEDIA_BLOCKLIST = [
    "thedaboratory", "TheDodo", "PeopleOfReddit", "GallowBoob",
]

# --- News searches ---
NEWS_SUBS = ["news", "worldnews"]
NEWS_QUERIES = [
    "animal zoo wildlife",
    "pet euthanized seized",
    "endangered species",
    "viral animal",
]

# --- Time buckets for baselines ---
TIME_BUCKETS = [
    (0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24),
]
