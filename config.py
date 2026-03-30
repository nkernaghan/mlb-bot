import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Season
SEASON_YEAR = int(os.getenv("SEASON_YEAR", "2026"))

# Paths
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "mlb.db")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

# The Odds API
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT_KEY = "baseball_mlb"
ODDS_REGIONS = "us"
ODDS_FORMAT = "american"

# MLB Stats API
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# OpenWeatherMap
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"

# Prediction Thresholds
HOME_ADVANTAGE_RUNS = 0.25  # MLB home advantage ~0.25 runs

# Game predictor weights
MARKET_WEIGHT = 0.60
MODEL_WEIGHT = 0.40

# Confidence thresholds
BET_MIN_CONFIDENCE = 65
BET_MIN_EDGE = 3.0  # percentage
LEAN_MIN_CONFIDENCE = 45
LEAN_MIN_EDGE = 1.0

# K prop thresholds
K_BET_MIN_EDGE = 1.0  # strikeouts
K_LEAN_MIN_EDGE = 0.5

# NRFI thresholds
NRFI_BET_MIN_EDGE = 4.0  # percentage points
NRFI_LEAN_MIN_EDGE = 2.0

# Cache TTLs (seconds)
CACHE_TTL_LEADERBOARDS = 86400  # 24 hours
CACHE_TTL_SCHEDULE = 900  # 15 minutes
CACHE_TTL_PLAYER_STATS = 14400  # 4 hours
CACHE_TTL_ODDS = 1800  # 30 minutes
CACHE_TTL_WEATHER = 7200  # 2 hours
CACHE_TTL_UMPIRE = 86400  # 24 hours

# Sharp / Casual books for line movement
SHARP_BOOKS = {"draftkings", "fanduel", "betonlineag"}
CASUAL_BOOKS = {"caesars", "pointsbetus", "williamhill_us"}
