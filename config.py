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
BET_MIN_EDGE = 5.0  # percentage — raised from 3.0; smaller edges are market noise
LEAN_MIN_CONFIDENCE = 45
LEAN_MIN_EDGE = 1.0

# K prop thresholds — narrower data footprint than game preds, lower bar
K_BET_MIN_CONFIDENCE = 55
K_BET_MIN_EDGE = 1.0  # strikeouts
K_LEAN_MIN_CONFIDENCE = 40
K_LEAN_MIN_EDGE = 0.5

# NRFI thresholds
NRFI_BET_MIN_CONFIDENCE = 55  # was 60 — model signals are good but ceiling sits below 60
NRFI_BET_MIN_EDGE = 4.0  # percentage points
NRFI_LEAN_MIN_CONFIDENCE = 42
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

# League average baselines used by predictors
# Update these each season — MLB averages shift year to year
LEAGUE_AVG_K_RATE = 22.0      # % of PA ending in strikeout (league-wide batter K%)
LEAGUE_AVG_FIP = 4.20         # Pitching FIP used as xFIP/NRFI baseline
LEAGUE_AVG_NRFI_RATE = 0.52   # ~52% of half-innings are scoreless in the 1st

# K prop model weights for market blending
K_MARKET_WEIGHT = 0.40   # Weight on market-implied K line when blending
K_MODEL_WEIGHT = 0.60    # Weight on our model projection when blending

# Umpire K impact: points per K+ unit applied to projected strikeout total
# Research range: 0.8-1.4 Ks per start for extreme umpires.
# K+ is normalised around 0; typical range roughly -2 to +2.
UMP_K_IMPACT_PER_POINT = 0.35  # was 0.1 — raised to match empirical research

# Early season — weight prior year data more heavily
EARLY_SEASON_IP_THRESHOLD = 50   # Below this IP, lean on prior year
EARLY_SEASON_PRIOR_WEIGHT = 0.75  # 75% prior year, 25% current
NORMAL_SEASON_PRIOR_WEIGHT = 0.30  # 30% prior year after threshold

# TTOP adjustment for high K lines
# K rates drop in innings 5-6; high lines require sustained production through
# multiple trips through the order.
TTOP_75_ADJUSTMENT = 0.92  # 8% haircut for 7.5+ lines
TTOP_85_ADJUSTMENT = 0.88  # 12% haircut for 8.5+ lines

# NRFI first-inning ERA weighting
NRFI_FIRST_INNING_WEIGHT = 0.60  # weight on first-inning ERA when available
NRFI_SEASON_WEIGHT = 0.40        # weight on season FIP/xFIP when first-inning ERA present
