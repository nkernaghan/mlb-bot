# MLB Prediction Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MLB prediction bot with three models (game outcomes, pitcher K props, NRFI) using free data sources and the pybaseball ecosystem.

**Architecture:** Pipeline-based Python system — fetch schedule/odds/stats, run three independent prediction engines in parallel, generate graded daily report, store results in SQLite. Uses MLB Stats API as backbone, pybaseball for advanced metrics, The Odds API for market data.

**Tech Stack:** Python 3.11+, SQLite, MLB-StatsAPI, pybaseball, pandas, requests, beautifulsoup4, python-dotenv

**Spec:** `docs/superpowers/specs/2026-03-30-mlb-prediction-bot-design.md`
**API Research:** `docs/superpowers/specs/2026-03-30-api-research.md`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `main.py` (skeleton)
- Create: `modules/__init__.py`
- Create: `modules/data/__init__.py`
- Create: `modules/models/__init__.py`
- Create: `modules/output/__init__.py`
- Create: `modules/database.py`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/nickkernaghan/Desktop/mlb-bot
git init
```

- [ ] **Step 2: Create requirements.txt**

```
MLB-StatsAPI>=1.7.0
pybaseball>=2.3.0
pandas>=2.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
python-dotenv>=1.0.0
tabulate>=0.9.0
colorama>=0.4.6
anthropic>=0.40.0
```

- [ ] **Step 3: Create .env.example**

```
ODDS_API_KEY=your_key_here
OPENWEATHERMAP_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
SEASON_YEAR=2026
```

- [ ] **Step 4: Create .gitignore**

```
.env
__pycache__/
*.pyc
data/mlb.db
data/odds_history/
logs/
reports/
.DS_Store
venv/
```

- [ ] **Step 5: Create config.py**

```python
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
BET_MIN_CONFIDENCE = 60
BET_MIN_EDGE = 2.0  # percentage
LEAN_MIN_CONFIDENCE = 40
LEAN_MIN_EDGE = 0.5

# K prop thresholds
K_BET_MIN_EDGE = 0.5  # strikeouts
K_LEAN_MIN_EDGE = 0.2

# NRFI thresholds
NRFI_BET_MIN_EDGE = 5.0  # percentage points
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
```

- [ ] **Step 6: Create directory structure and __init__.py files**

```bash
mkdir -p modules/data modules/models modules/output data reports logs tests
touch modules/__init__.py modules/data/__init__.py modules/models/__init__.py modules/output/__init__.py
```

- [ ] **Step 7: Create database.py with full schema**

```python
import sqlite3
import os
from config import DB_PATH


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            game_pk INTEGER PRIMARY KEY,
            game_date TEXT NOT NULL,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_team_name TEXT,
            away_team_name TEXT,
            venue_id INTEGER,
            venue_name TEXT,
            game_time_utc TEXT,
            day_night TEXT,
            status TEXT DEFAULT 'Scheduled',
            home_score INTEGER,
            away_score INTEGER,
            home_pitcher_id INTEGER,
            away_pitcher_id INTEGER,
            home_pitcher_name TEXT,
            away_pitcher_name TEXT,
            umpire_id INTEGER,
            umpire_name TEXT
        );

        CREATE TABLE IF NOT EXISTS odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            home_ml INTEGER,
            away_ml INTEGER,
            run_line_spread REAL,
            run_line_home_price INTEGER,
            run_line_away_price INTEGER,
            total REAL,
            over_price INTEGER,
            under_price INTEGER,
            bookmaker TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS k_prop_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            pitcher_id INTEGER NOT NULL,
            pitcher_name TEXT,
            fetched_at TEXT NOT NULL,
            line REAL,
            over_price INTEGER,
            under_price INTEGER,
            bookmaker TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS nrfi_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            nrfi_price INTEGER,
            yrfi_price INTEGER,
            bookmaker TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS pitcher_stats_cache (
            player_id INTEGER NOT NULL,
            player_name TEXT,
            team TEXT,
            date_cached TEXT NOT NULL,
            era REAL,
            fip REAL,
            xfip REAL,
            siera REAL,
            xera REAL,
            k_rate REAL,
            bb_rate REAL,
            csw REAL,
            swstr REAL,
            barrel_rate_against REAL,
            first_inning_era REAL,
            f_strike_pct REAL,
            innings_pitched REAL,
            games_started INTEGER,
            k_per_9 REAL,
            whip REAL,
            nrfi_rate REAL,
            PRIMARY KEY (player_id, date_cached)
        );

        CREATE TABLE IF NOT EXISTS batter_stats_cache (
            player_id INTEGER NOT NULL,
            player_name TEXT,
            team TEXT,
            date_cached TEXT NOT NULL,
            ops REAL,
            k_rate REAL,
            bb_rate REAL,
            barrel_rate REAL,
            xba REAL,
            xslg REAL,
            xwoba REAL,
            wrc_plus REAL,
            vs_lhp_ops REAL,
            vs_rhp_ops REAL,
            vs_lhp_k_rate REAL,
            vs_rhp_k_rate REAL,
            PRIMARY KEY (player_id, date_cached)
        );

        CREATE TABLE IF NOT EXISTS park_factors (
            venue_id INTEGER NOT NULL,
            venue_name TEXT,
            season INTEGER NOT NULL,
            run_factor INTEGER DEFAULT 100,
            hr_factor INTEGER DEFAULT 100,
            k_factor INTEGER DEFAULT 100,
            bb_factor INTEGER DEFAULT 100,
            PRIMARY KEY (venue_id, season)
        );

        CREATE TABLE IF NOT EXISTS umpire_stats (
            umpire_id INTEGER NOT NULL,
            umpire_name TEXT,
            season INTEGER NOT NULL,
            accuracy_pct REAL,
            consistency_pct REAL,
            k_plus REAL,
            favor REAL,
            games_behind_plate INTEGER,
            PRIMARY KEY (umpire_id, season)
        );

        CREATE TABLE IF NOT EXISTS bullpen_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            pitcher_id INTEGER NOT NULL,
            pitcher_name TEXT,
            pitches_thrown INTEGER,
            innings_pitched REAL,
            days_rest INTEGER,
            era REAL,
            fip REAL
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            bet_type TEXT NOT NULL,
            pick TEXT NOT NULL,
            pick_detail TEXT,
            confidence INTEGER,
            edge REAL,
            model_value REAL,
            market_value REAL,
            grade TEXT,
            reasons TEXT,
            risks TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            bet_type TEXT NOT NULL,
            pick TEXT NOT NULL,
            result TEXT,
            actual_outcome TEXT,
            edge_at_pick REAL,
            confidence_at_pick INTEGER,
            graded_at TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
        CREATE INDEX IF NOT EXISTS idx_odds_game ON odds(game_pk);
        CREATE INDEX IF NOT EXISTS idx_predictions_game ON predictions(game_pk);
        CREATE INDEX IF NOT EXISTS idx_predictions_type ON predictions(bet_type);
        CREATE INDEX IF NOT EXISTS idx_results_type ON results(bet_type);
        CREATE INDEX IF NOT EXISTS idx_results_date ON results(graded_at);
        CREATE INDEX IF NOT EXISTS idx_pitcher_cache ON pitcher_stats_cache(player_id, date_cached);
        CREATE INDEX IF NOT EXISTS idx_batter_cache ON batter_stats_cache(player_id, date_cached);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
```

- [ ] **Step 8: Create main.py skeleton with CLI**

```python
import argparse
import sys
from datetime import datetime, timedelta

from config import SEASON_YEAR
from modules.database import init_db


def parse_args():
    parser = argparse.ArgumentParser(description="MLB Prediction Bot")
    parser.add_argument("--date", type=str, help="Analysis date (YYYY-MM-DD), default today")
    parser.add_argument("--game-only", action="store_true", help="Only run game predictions")
    parser.add_argument("--strikeouts", action="store_true", help="Only run K prop predictions")
    parser.add_argument("--nrfi", action="store_true", help="Only run NRFI predictions")
    parser.add_argument("--grade-results", action="store_true", help="Grade yesterday's picks")
    parser.add_argument("--record", action="store_true", help="Show season record")
    parser.add_argument("--days", type=int, default=0, help="Rolling N-day record (0=full season)")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch cached data")
    parser.add_argument("--notify", action="store_true", help="Send notifications")
    return parser.parse_args()


def main():
    args = parse_args()
    init_db()

    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    run_all = not (args.game_only or args.strikeouts or args.nrfi)

    if args.grade_results:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"Grading results for {yesterday}...")
        # TODO: implement grade_results(yesterday)
        return

    if args.record:
        print("Season record...")
        # TODO: implement show_record(args.days)
        return

    print(f"MLB Prediction Bot — {target_date}")
    print("=" * 60)

    # Step 1: Fetch schedule
    print("\n[1/6] Fetching schedule...")
    # TODO: games = schedule.fetch_games(target_date)

    # Step 2: Fetch odds
    print("[2/6] Fetching odds...")
    # TODO: odds.fetch_odds(games)

    # Step 3: Fetch stats (cached daily)
    print("[3/6] Fetching stats...")
    # TODO: cache.refresh_daily_caches(target_date, force=args.refresh)

    # Step 4: Run predictions
    print("[4/6] Running predictions...")
    # TODO: per-game analysis with game_predictor, strikeout_predictor, nrfi_predictor

    # Step 5: Generate report
    print("[5/6] Generating report...")
    # TODO: reporting.generate_report(predictions, target_date)

    # Step 6: Save to database
    print("[6/6] Saving predictions...")
    # TODO: database saves

    print("\nDone.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Install dependencies and verify**

```bash
cd /Users/nickkernaghan/Desktop/mlb-bot
pip install -r requirements.txt
python -c "import statsapi; import pybaseball; import pandas; print('All imports OK')"
```

- [ ] **Step 10: Initialize database and verify**

```bash
python modules/database.py
python -c "import sqlite3; conn = sqlite3.connect('data/mlb.db'); print([t[0] for t in conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()])"
```

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with config, database schema, CLI skeleton"
```

---

## Task 2: Schedule + Lineups Module

**Files:**
- Create: `modules/data/schedule.py`
- Create: `tests/test_schedule.py`

- [ ] **Step 1: Write test_schedule.py**

```python
import json
from unittest.mock import patch, MagicMock
from modules.data.schedule import fetch_games, parse_game


def make_mock_game(game_pk=748532, home="Boston Red Sox", away="New York Yankees",
                   home_id=111, away_id=147, venue="Fenway Park", venue_id=3,
                   home_pitcher_id=656302, home_pitcher="Brayan Bello",
                   away_pitcher_id=543037, away_pitcher="Gerrit Cole",
                   day_night="night", status="Preview"):
    return {
        "gamePk": game_pk,
        "gameDate": "2026-04-01T23:10:00Z",
        "officialDate": "2026-04-01",
        "dayNight": day_night,
        "status": {"abstractGameState": status},
        "teams": {
            "home": {
                "team": {"id": home_id, "name": home},
                "probablePitcher": {"id": home_pitcher_id, "fullName": home_pitcher},
            },
            "away": {
                "team": {"id": away_id, "name": away},
                "probablePitcher": {"id": away_pitcher_id, "fullName": away_pitcher},
            },
        },
        "venue": {"id": venue_id, "name": venue},
    }


def test_parse_game_extracts_fields():
    raw = make_mock_game()
    game = parse_game(raw)
    assert game["game_pk"] == 748532
    assert game["home_team_name"] == "Boston Red Sox"
    assert game["away_team_name"] == "New York Yankees"
    assert game["home_pitcher_id"] == 656302
    assert game["away_pitcher_id"] == 543037
    assert game["venue_name"] == "Fenway Park"
    assert game["day_night"] == "night"


def test_parse_game_missing_pitcher():
    raw = make_mock_game()
    del raw["teams"]["home"]["probablePitcher"]
    game = parse_game(raw)
    assert game["home_pitcher_id"] is None
    assert game["home_pitcher_name"] is None


@patch("modules.data.schedule.statsapi")
def test_fetch_games_returns_parsed_list(mock_api):
    mock_api.schedule.return_value = {
        "dates": [{"games": [make_mock_game(), make_mock_game(game_pk=748533)]}]
    }
    games = fetch_games("2026-04-01")
    assert len(games) == 2
    assert games[0]["game_pk"] == 748532
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/nickkernaghan/Desktop/mlb-bot
python -m pytest tests/test_schedule.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.data.schedule'`

- [ ] **Step 3: Implement schedule.py**

```python
import statsapi
from datetime import datetime
from modules.database import get_connection


def fetch_games(date_str):
    """Fetch today's MLB games from the Stats API with hydrated data."""
    raw = statsapi.schedule(
        date=date_str,
        sportId=1,
    )
    games = []
    for game_data in raw:
        game = parse_schedule_entry(game_data)
        if game:
            games.append(game)
    return games


def parse_schedule_entry(entry):
    """Parse a statsapi.schedule() entry into our game dict."""
    return {
        "game_pk": entry.get("game_id"),
        "game_date": entry.get("game_date"),
        "home_team_id": entry.get("home_id"),
        "away_team_id": entry.get("away_id"),
        "home_team_name": entry.get("home_name"),
        "away_team_name": entry.get("away_name"),
        "venue_id": entry.get("venue_id"),
        "venue_name": entry.get("venue_name"),
        "game_time_utc": entry.get("game_datetime"),
        "day_night": entry.get("day_night", "night"),
        "status": entry.get("status", "Scheduled"),
        "home_pitcher_id": entry.get("home_probable_pitcher_id"),
        "home_pitcher_name": entry.get("home_probable_pitcher"),
        "away_pitcher_id": entry.get("away_probable_pitcher_id"),
        "away_pitcher_name": entry.get("away_probable_pitcher"),
        "home_score": entry.get("home_score"),
        "away_score": entry.get("away_score"),
    }


def parse_game(raw_game):
    """Parse a raw MLB API game object (from direct API call) into our game dict."""
    home = raw_game["teams"]["home"]
    away = raw_game["teams"]["away"]
    home_pitcher = home.get("probablePitcher", {})
    away_pitcher = away.get("probablePitcher", {})

    return {
        "game_pk": raw_game["gamePk"],
        "game_date": raw_game.get("officialDate"),
        "home_team_id": home["team"]["id"],
        "away_team_id": away["team"]["id"],
        "home_team_name": home["team"]["name"],
        "away_team_name": away["team"]["name"],
        "venue_id": raw_game.get("venue", {}).get("id"),
        "venue_name": raw_game.get("venue", {}).get("name"),
        "game_time_utc": raw_game.get("gameDate"),
        "day_night": raw_game.get("dayNight", "night"),
        "status": raw_game.get("status", {}).get("abstractGameState", "Scheduled"),
        "home_pitcher_id": home_pitcher.get("id"),
        "home_pitcher_name": home_pitcher.get("fullName"),
        "away_pitcher_id": away_pitcher.get("id"),
        "away_pitcher_name": away_pitcher.get("fullName"),
        "home_score": home.get("score"),
        "away_score": away.get("score"),
    }


def fetch_lineups(game_pk):
    """Fetch confirmed lineups from the live feed. Returns None if not yet posted."""
    try:
        data = statsapi.get("game", {"gamePk": game_pk})
        live_data = data.get("liveData", {})
        boxscore = live_data.get("boxscore", {})
        teams = boxscore.get("teams", {})

        result = {"home": [], "away": []}
        for side in ["home", "away"]:
            batting_order = teams.get(side, {}).get("battingOrder", [])
            players = teams.get(side, {}).get("players", {})
            for player_id in batting_order:
                player_key = f"ID{player_id}"
                player_data = players.get(player_key, {})
                person = player_data.get("person", {})
                result[side].append({
                    "id": person.get("id", player_id),
                    "name": person.get("fullName", "Unknown"),
                    "position": player_data.get("position", {}).get("abbreviation", ""),
                })

        if not result["home"] and not result["away"]:
            return None
        return result
    except Exception:
        return None


def save_games(games):
    """Save games to the database."""
    conn = get_connection()
    for g in games:
        conn.execute("""
            INSERT OR REPLACE INTO games
            (game_pk, game_date, home_team_id, away_team_id, home_team_name,
             away_team_name, venue_id, venue_name, game_time_utc, day_night,
             status, home_score, away_score, home_pitcher_id, away_pitcher_id,
             home_pitcher_name, away_pitcher_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g["game_pk"], g["game_date"], g["home_team_id"], g["away_team_id"],
            g["home_team_name"], g["away_team_name"], g["venue_id"], g["venue_name"],
            g["game_time_utc"], g["day_night"], g["status"], g["home_score"],
            g["away_score"], g["home_pitcher_id"], g["away_pitcher_id"],
            g["home_pitcher_name"], g["away_pitcher_name"],
        ))
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_schedule.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/data/schedule.py tests/test_schedule.py
git commit -m "feat: schedule + lineups module with MLB Stats API"
```

---

## Task 3: Odds Module (The Odds API)

**Files:**
- Create: `modules/data/odds.py`
- Create: `tests/test_odds.py`

- [ ] **Step 1: Write test_odds.py**

```python
from modules.data.odds import parse_game_odds, parse_k_props, parse_nrfi_odds, american_to_implied


def test_american_to_implied_favorite():
    assert abs(american_to_implied(-150) - 0.6) < 0.01


def test_american_to_implied_underdog():
    assert abs(american_to_implied(150) - 0.4) < 0.01


def test_parse_game_odds():
    raw_bookmaker = {
        "key": "draftkings",
        "title": "DraftKings",
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "New York Yankees", "price": -128},
                    {"name": "Boston Red Sox", "price": 108},
                ],
            },
            {
                "key": "spreads",
                "outcomes": [
                    {"name": "New York Yankees", "price": 145, "point": -1.5},
                    {"name": "Boston Red Sox", "price": -165, "point": 1.5},
                ],
            },
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": -110, "point": 8.5},
                    {"name": "Under", "price": -110, "point": 8.5},
                ],
            },
        ],
    }
    odds = parse_game_odds(raw_bookmaker, "New York Yankees", "Boston Red Sox")
    assert odds["away_ml"] == -128
    assert odds["home_ml"] == 108
    assert odds["run_line_spread"] == -1.5
    assert odds["total"] == 8.5


def test_parse_k_props():
    raw_bookmaker = {
        "key": "draftkings",
        "markets": [
            {
                "key": "pitcher_strikeouts",
                "outcomes": [
                    {"name": "Over", "description": "Gerrit Cole", "price": -115, "point": 7.5},
                    {"name": "Under", "description": "Gerrit Cole", "price": -105, "point": 7.5},
                ],
            },
        ],
    }
    props = parse_k_props(raw_bookmaker)
    assert len(props) == 1
    assert props[0]["pitcher_name"] == "Gerrit Cole"
    assert props[0]["line"] == 7.5
    assert props[0]["over_price"] == -115


def test_parse_nrfi_odds():
    raw_bookmaker = {
        "key": "draftkings",
        "markets": [
            {
                "key": "1st_1_innings",
                "outcomes": [
                    {"name": "Under", "price": -130, "point": 0.5},
                    {"name": "Over", "price": 110, "point": 0.5},
                ],
            },
        ],
    }
    nrfi = parse_nrfi_odds(raw_bookmaker)
    assert nrfi["nrfi_price"] == -130
    assert nrfi["yrfi_price"] == 110
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_odds.py -v
```

- [ ] **Step 3: Implement odds.py**

```python
import requests
from datetime import datetime
from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY, ODDS_REGIONS, ODDS_FORMAT
from modules.database import get_connection


def american_to_implied(american_odds):
    """Convert American odds to implied probability (0-1)."""
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    else:
        return 100 / (american_odds + 100)


def fetch_game_odds():
    """Fetch moneylines, run lines, and totals for all MLB games."""
    if not ODDS_API_KEY:
        print("  WARNING: No ODDS_API_KEY set, skipping odds fetch")
        return []

    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": "h2h,spreads,totals",
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"  Odds API requests remaining: {remaining}")

    return resp.json()


def fetch_event_props(event_id, markets="pitcher_strikeouts,1st_1_innings"):
    """Fetch player props and NRFI odds for a specific event."""
    if not ODDS_API_KEY:
        return {}

    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": markets,
        "oddsFormat": ODDS_FORMAT,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_game_odds(bookmaker, away_team, home_team):
    """Parse a single bookmaker's odds for a game."""
    result = {
        "bookmaker": bookmaker["key"],
        "home_ml": None, "away_ml": None,
        "run_line_spread": None, "run_line_home_price": None, "run_line_away_price": None,
        "total": None, "over_price": None, "under_price": None,
    }

    for market in bookmaker.get("markets", []):
        if market["key"] == "h2h":
            for outcome in market["outcomes"]:
                if outcome["name"] == away_team:
                    result["away_ml"] = outcome["price"]
                elif outcome["name"] == home_team:
                    result["home_ml"] = outcome["price"]

        elif market["key"] == "spreads":
            for outcome in market["outcomes"]:
                if outcome["name"] == away_team:
                    result["run_line_spread"] = outcome.get("point")
                    result["run_line_away_price"] = outcome["price"]
                elif outcome["name"] == home_team:
                    result["run_line_home_price"] = outcome["price"]

        elif market["key"] == "totals":
            for outcome in market["outcomes"]:
                if outcome["name"] == "Over":
                    result["total"] = outcome.get("point")
                    result["over_price"] = outcome["price"]
                elif outcome["name"] == "Under":
                    result["under_price"] = outcome["price"]

    return result


def parse_k_props(bookmaker):
    """Parse pitcher strikeout props from a bookmaker."""
    props = []
    for market in bookmaker.get("markets", []):
        if market["key"] != "pitcher_strikeouts":
            continue
        pitchers = {}
        for outcome in market["outcomes"]:
            name = outcome.get("description", "")
            if name not in pitchers:
                pitchers[name] = {"pitcher_name": name, "line": outcome.get("point"),
                                   "over_price": None, "under_price": None, "bookmaker": bookmaker["key"]}
            if outcome["name"] == "Over":
                pitchers[name]["over_price"] = outcome["price"]
                pitchers[name]["line"] = outcome.get("point")
            elif outcome["name"] == "Under":
                pitchers[name]["under_price"] = outcome["price"]
        props.extend(pitchers.values())
    return props


def parse_nrfi_odds(bookmaker):
    """Parse NRFI/YRFI odds from a bookmaker."""
    for market in bookmaker.get("markets", []):
        if market["key"] == "1st_1_innings":
            result = {"nrfi_price": None, "yrfi_price": None, "bookmaker": bookmaker["key"]}
            for outcome in market["outcomes"]:
                if outcome["name"] == "Under":
                    result["nrfi_price"] = outcome["price"]
                elif outcome["name"] == "Over":
                    result["yrfi_price"] = outcome["price"]
            return result
    return None


def get_consensus_odds(all_bookmaker_odds):
    """Average odds across bookmakers for consensus line."""
    if not all_bookmaker_odds:
        return None

    fields = ["home_ml", "away_ml", "total"]
    consensus = {}
    for field in fields:
        values = [o[field] for o in all_bookmaker_odds if o.get(field) is not None]
        consensus[field] = round(sum(values) / len(values)) if values else None

    spread_values = [o["run_line_spread"] for o in all_bookmaker_odds if o.get("run_line_spread") is not None]
    consensus["run_line_spread"] = spread_values[0] if spread_values else None

    return consensus


def save_odds(game_pk, odds_list):
    """Save odds snapshots to database."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    for odds in odds_list:
        conn.execute("""
            INSERT INTO odds (game_pk, fetched_at, home_ml, away_ml, run_line_spread,
                run_line_home_price, run_line_away_price, total, over_price, under_price, bookmaker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_pk, now, odds["home_ml"], odds["away_ml"], odds["run_line_spread"],
              odds["run_line_home_price"], odds["run_line_away_price"],
              odds["total"], odds["over_price"], odds["under_price"], odds["bookmaker"]))
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_odds.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/data/odds.py tests/test_odds.py
git commit -m "feat: odds module with The Odds API (game lines, K props, NRFI)"
```

---

## Task 4: Pitcher Stats Module (pybaseball + MLB API)

**Files:**
- Create: `modules/data/pitcher_stats.py`
- Create: `modules/data/cache.py`

- [ ] **Step 1: Implement cache.py**

```python
import pandas as pd
from datetime import datetime, date
from pybaseball import pitching_stats, batting_stats
from pybaseball import statcast_pitcher_expected_stats
from modules.database import get_connection
from config import SEASON_YEAR


_pitcher_fg_cache = None
_pitcher_savant_cache = None
_batter_fg_cache = None
_batter_savant_cache = None
_cache_date = None


def refresh_daily_caches(target_date=None, force=False):
    """Fetch FanGraphs and Savant leaderboards once per day."""
    global _pitcher_fg_cache, _pitcher_savant_cache, _batter_fg_cache, _batter_savant_cache, _cache_date

    today = target_date or date.today().isoformat()
    if _cache_date == today and not force:
        return

    print("  Fetching FanGraphs pitcher leaderboard...")
    try:
        _pitcher_fg_cache = pitching_stats(SEASON_YEAR, qual=1)
    except Exception as e:
        print(f"  WARNING: FanGraphs pitcher fetch failed: {e}")
        _pitcher_fg_cache = pd.DataFrame()

    print("  Fetching Savant expected stats (pitchers)...")
    try:
        _pitcher_savant_cache = statcast_pitcher_expected_stats(SEASON_YEAR, minPA=50)
    except Exception as e:
        print(f"  WARNING: Savant pitcher fetch failed: {e}")
        _pitcher_savant_cache = pd.DataFrame()

    print("  Fetching FanGraphs batter leaderboard...")
    try:
        _batter_fg_cache = batting_stats(SEASON_YEAR, qual=1)
    except Exception as e:
        print(f"  WARNING: FanGraphs batter fetch failed: {e}")
        _batter_fg_cache = pd.DataFrame()

    print("  Fetching Savant expected stats (batters)...")
    try:
        from pybaseball import statcast_batter_expected_stats
        _batter_savant_cache = statcast_batter_expected_stats(SEASON_YEAR, minPA=50)
    except Exception as e:
        print(f"  WARNING: Savant batter fetch failed: {e}")
        _batter_savant_cache = pd.DataFrame()

    _cache_date = today
    print(f"  Caches loaded: {len(_pitcher_fg_cache)} pitchers, {len(_batter_fg_cache)} batters")


def get_pitcher_fg(name=None, team=None):
    """Lookup a pitcher in the FanGraphs cache by name and/or team."""
    if _pitcher_fg_cache is None or _pitcher_fg_cache.empty:
        return None
    df = _pitcher_fg_cache
    if name:
        df = df[df["Name"].str.contains(name, case=False, na=False)]
    if team and not df.empty:
        df = df[df["Team"].str.contains(team, case=False, na=False)]
    return df.iloc[0].to_dict() if not df.empty else None


def get_pitcher_savant(player_id):
    """Lookup a pitcher in the Savant cache by MLB player ID."""
    if _pitcher_savant_cache is None or _pitcher_savant_cache.empty:
        return None
    df = _pitcher_savant_cache
    matches = df[df["player_id"] == player_id]
    return matches.iloc[0].to_dict() if not matches.empty else None


def get_batter_fg(name=None, team=None):
    """Lookup a batter in the FanGraphs cache."""
    if _batter_fg_cache is None or _batter_fg_cache.empty:
        return None
    df = _batter_fg_cache
    if name:
        df = df[df["Name"].str.contains(name, case=False, na=False)]
    if team and not df.empty:
        df = df[df["Team"].str.contains(team, case=False, na=False)]
    return df.iloc[0].to_dict() if not df.empty else None


def get_batter_savant(player_id):
    """Lookup a batter in the Savant cache by MLB player ID."""
    if _batter_savant_cache is None or _batter_savant_cache.empty:
        return None
    df = _batter_savant_cache
    matches = df[df["player_id"] == player_id]
    return matches.iloc[0].to_dict() if not matches.empty else None
```

- [ ] **Step 2: Implement pitcher_stats.py**

```python
import statsapi
from modules.data.cache import get_pitcher_fg, get_pitcher_savant
from modules.database import get_connection
from config import SEASON_YEAR
from datetime import date


def fetch_pitcher_stats(player_id, player_name, team=None):
    """Aggregate pitcher stats from MLB API + FanGraphs + Savant."""
    stats = {
        "player_id": player_id,
        "player_name": player_name,
        "team": team,
    }

    # MLB Stats API — season stats
    try:
        mlb_stats = statsapi.player_stat_data(player_id, group="pitching", type="season")
        if mlb_stats and mlb_stats.get("stats"):
            s = mlb_stats["stats"][0].get("stats", {})
            stats["era"] = float(s.get("era", 0))
            stats["k_per_9"] = float(s.get("strikeoutsPer9Inn", 0))
            stats["whip"] = float(s.get("whip", 0))
            stats["innings_pitched"] = float(s.get("inningsPitched", "0").replace(".", ""))
            stats["games_started"] = int(s.get("gamesStarted", 0))
            total_ks = int(s.get("strikeOuts", 0))
            batters_faced = int(s.get("battersFaced", 1))
            stats["k_rate"] = round(total_ks / batters_faced * 100, 1) if batters_faced else 0
            stats["bb_rate"] = round(int(s.get("baseOnBalls", 0)) / batters_faced * 100, 1) if batters_faced else 0
    except Exception as e:
        print(f"    WARNING: MLB API stats failed for {player_name}: {e}")

    # FanGraphs — FIP, xFIP, SIERA, SwStr%
    fg = get_pitcher_fg(player_name, team)
    if fg:
        stats["fip"] = fg.get("FIP")
        stats["xfip"] = fg.get("xFIP")
        stats["siera"] = fg.get("SIERA")
        stats["swstr"] = fg.get("SwStr%")
        stats["f_strike_pct"] = fg.get("F-Strike%")
        stats["csw"] = fg.get("CSW%")  # May not be in default leaderboard

    # Baseball Savant — xERA, barrel rate, expected stats
    savant = get_pitcher_savant(player_id)
    if savant:
        stats["xera"] = savant.get("xera")
        stats["barrel_rate_against"] = savant.get("barrel_batted_rate")
        if not stats.get("k_rate"):
            stats["k_rate"] = savant.get("k_percent")

    # MLB API — game log for recent form + first-inning stats
    try:
        game_log = statsapi.player_stat_data(player_id, group="pitching", type="gameLog")
        if game_log and game_log.get("stats"):
            recent_starts = [
                g["stats"] for g in game_log["stats"][:5]
                if int(g["stats"].get("gamesStarted", 0)) > 0
            ]
            if recent_starts:
                recent_ks = sum(int(g.get("strikeOuts", 0)) for g in recent_starts)
                recent_ip = sum(float(g.get("inningsPitched", "0")) for g in recent_starts)
                stats["recent_k_per_9"] = round(recent_ks / recent_ip * 9, 1) if recent_ip else 0
                recent_er = sum(int(g.get("earnedRuns", 0)) for g in recent_starts)
                stats["recent_era"] = round(recent_er / recent_ip * 9, 2) if recent_ip else 0
    except Exception:
        pass

    return stats


def save_pitcher_stats(stats):
    """Cache pitcher stats to database."""
    conn = get_connection()
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO pitcher_stats_cache
        (player_id, player_name, team, date_cached, era, fip, xfip, siera, xera,
         k_rate, bb_rate, csw, swstr, barrel_rate_against, first_inning_era,
         f_strike_pct, innings_pitched, games_started, k_per_9, whip, nrfi_rate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stats.get("player_id"), stats.get("player_name"), stats.get("team"), today,
        stats.get("era"), stats.get("fip"), stats.get("xfip"), stats.get("siera"),
        stats.get("xera"), stats.get("k_rate"), stats.get("bb_rate"), stats.get("csw"),
        stats.get("swstr"), stats.get("barrel_rate_against"), stats.get("first_inning_era"),
        stats.get("f_strike_pct"), stats.get("innings_pitched"), stats.get("games_started"),
        stats.get("k_per_9"), stats.get("whip"), stats.get("nrfi_rate"),
    ))
    conn.commit()
    conn.close()
```

- [ ] **Step 3: Commit**

```bash
git add modules/data/pitcher_stats.py modules/data/cache.py
git commit -m "feat: pitcher stats module with pybaseball + MLB API aggregation"
```

---

## Task 5: Batter Stats, Park Factors, Umpires, Weather, Injuries, Bullpen

**Files:**
- Create: `modules/data/batter_stats.py`
- Create: `modules/data/park_factors.py`
- Create: `modules/data/umpires.py`
- Create: `modules/data/weather.py`
- Create: `modules/data/injuries.py`
- Create: `modules/data/bullpen.py`

- [ ] **Step 1: Implement batter_stats.py**

```python
import statsapi
from modules.data.cache import get_batter_fg, get_batter_savant
from modules.database import get_connection
from config import SEASON_YEAR
from datetime import date


def fetch_batter_stats(player_id, player_name, team=None):
    """Aggregate batter stats from MLB API + FanGraphs + Savant."""
    stats = {"player_id": player_id, "player_name": player_name, "team": team}

    try:
        mlb_stats = statsapi.player_stat_data(player_id, group="hitting", type="season")
        if mlb_stats and mlb_stats.get("stats"):
            s = mlb_stats["stats"][0].get("stats", {})
            stats["ops"] = float(s.get("ops", 0))
            pa = int(s.get("plateAppearances", 1))
            stats["k_rate"] = round(int(s.get("strikeOuts", 0)) / pa * 100, 1) if pa else 0
            stats["bb_rate"] = round(int(s.get("baseOnBalls", 0)) / pa * 100, 1) if pa else 0
    except Exception:
        pass

    # Splits vs LHP/RHP
    try:
        splits = statsapi.player_stat_data(player_id, group="hitting", type="statSplits")
        if splits and splits.get("stats"):
            for split in splits["stats"]:
                split_name = split.get("split", {}).get("description", "")
                s = split.get("stats", {})
                if "Left" in split_name:
                    stats["vs_lhp_ops"] = float(s.get("ops", 0))
                    pa = int(s.get("plateAppearances", 1))
                    stats["vs_lhp_k_rate"] = round(int(s.get("strikeOuts", 0)) / pa * 100, 1) if pa else 0
                elif "Right" in split_name:
                    stats["vs_rhp_ops"] = float(s.get("ops", 0))
                    pa = int(s.get("plateAppearances", 1))
                    stats["vs_rhp_k_rate"] = round(int(s.get("strikeOuts", 0)) / pa * 100, 1) if pa else 0
    except Exception:
        pass

    fg = get_batter_fg(player_name, team)
    if fg:
        stats["wrc_plus"] = fg.get("wRC+")
        stats["barrel_rate"] = fg.get("Barrel%")

    savant = get_batter_savant(player_id)
    if savant:
        stats["xba"] = savant.get("xba")
        stats["xslg"] = savant.get("xslg")
        stats["xwoba"] = savant.get("xwoba")
        if not stats.get("barrel_rate"):
            stats["barrel_rate"] = savant.get("barrel_batted_rate")

    return stats


def fetch_team_batting_stats(team_id):
    """Fetch aggregate team batting stats."""
    try:
        data = statsapi.get("team_stats", {"teamId": team_id, "stats": "season", "group": "hitting"})
        if data and data.get("stats"):
            s = data["stats"][0].get("splits", [{}])[0].get("stat", {})
            pa = int(s.get("plateAppearances", 1))
            return {
                "team_ops": float(s.get("ops", 0)),
                "team_k_rate": round(int(s.get("strikeOuts", 0)) / pa * 100, 1) if pa else 0,
                "team_bb_rate": round(int(s.get("baseOnBalls", 0)) / pa * 100, 1) if pa else 0,
            }
    except Exception:
        pass
    return {}
```

- [ ] **Step 2: Implement park_factors.py**

```python
from pybaseball import team_batting as fg_team_batting
from modules.database import get_connection
from config import SEASON_YEAR
import requests
from bs4 import BeautifulSoup
import statsapi


# Hardcoded MLB venue coordinates for weather lookups
VENUE_COORDS = {}  # Populated from MLB API on first call

DOME_VENUES = {
    "Tropicana Field", "Minute Maid Park", "Rogers Centre",
    "T-Mobile Park", "loanDepot park", "Globe Life Field",
    "Chase Field", "American Family Field",
}


def fetch_park_factors():
    """Fetch park factors from FanGraphs guts page."""
    url = "https://www.fangraphs.com/guts.aspx?type=pf&teamid=0&season=" + str(SEASON_YEAR)
    try:
        resp = requests.get(url, headers={"User-Agent": "MLBBot/1.0"}, timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"class": "rgMasterTable"})
        if not table:
            return []

        factors = []
        rows = table.find_all("tr")[1:]  # Skip header
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 10:
                factors.append({
                    "team": cols[0].text.strip(),
                    "run_factor": int(cols[1].text.strip()) if cols[1].text.strip().isdigit() else 100,
                    "hr_factor": int(cols[6].text.strip()) if cols[6].text.strip().isdigit() else 100,
                    "k_factor": int(cols[8].text.strip()) if cols[8].text.strip().isdigit() else 100,
                    "bb_factor": int(cols[7].text.strip()) if cols[7].text.strip().isdigit() else 100,
                })
        return factors
    except Exception as e:
        print(f"  WARNING: Park factors fetch failed: {e}")
        return []


def get_venue_coords(venue_id):
    """Get venue coordinates from MLB API for weather lookup."""
    try:
        data = statsapi.get("venue", {"venueId": venue_id, "hydrate": "location"})
        venues = data.get("venues", [])
        if venues:
            loc = venues[0].get("location", {}).get("defaultCoordinates", {})
            return loc.get("latitude"), loc.get("longitude")
    except Exception:
        pass
    return None, None


def is_dome(venue_name):
    """Check if venue has a roof (weather irrelevant)."""
    return venue_name in DOME_VENUES


def save_park_factors(factors, venue_id_map):
    """Save park factors to database."""
    conn = get_connection()
    for f in factors:
        venue_id = venue_id_map.get(f["team"])
        if venue_id:
            conn.execute("""
                INSERT OR REPLACE INTO park_factors
                (venue_id, venue_name, season, run_factor, hr_factor, k_factor, bb_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (venue_id, f["team"], SEASON_YEAR, f["run_factor"], f["hr_factor"],
                  f["k_factor"], f["bb_factor"]))
    conn.commit()
    conn.close()
```

- [ ] **Step 3: Implement umpires.py**

```python
import requests
from bs4 import BeautifulSoup
from modules.database import get_connection
from config import SEASON_YEAR


def fetch_umpire_stats(umpire_name):
    """Fetch umpire stats from Umpire Scorecards."""
    slug = umpire_name.lower().replace(" ", "-")
    url = f"https://umpscorecards.com/umpires/{slug}/"
    try:
        resp = requests.get(url, headers={"User-Agent": "MLBBot/1.0"}, timeout=15)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        scripts = soup.find_all("script", {"type": "application/json"})

        for script in scripts:
            try:
                import json
                data = json.loads(script.string)
                return {
                    "umpire_name": umpire_name,
                    "accuracy_pct": data.get("accuracy"),
                    "consistency_pct": data.get("consistency"),
                    "k_plus": data.get("k_plus"),
                    "favor": data.get("favor"),
                    "games_behind_plate": data.get("games"),
                }
            except (json.JSONDecodeError, AttributeError):
                continue
    except Exception:
        pass
    return None


def get_umpire_from_boxscore(game_pk):
    """Get home plate umpire from the box score officials array."""
    import statsapi
    try:
        boxscore = statsapi.boxscore_data(game_pk)
        officials = boxscore.get("gameBoxInfo", [])
        for info in officials:
            if "Home Plate" in str(info):
                # Parse umpire name from the info string
                return info
    except Exception:
        pass
    return None


def save_umpire_stats(umpire_id, stats):
    """Save umpire stats to database."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO umpire_stats
        (umpire_id, umpire_name, season, accuracy_pct, consistency_pct, k_plus, favor, games_behind_plate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (umpire_id, stats["umpire_name"], SEASON_YEAR, stats.get("accuracy_pct"),
          stats.get("consistency_pct"), stats.get("k_plus"), stats.get("favor"),
          stats.get("games_behind_plate")))
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Implement weather.py**

```python
import requests
from config import OPENWEATHERMAP_API_KEY, WEATHER_API_BASE
from modules.data.park_factors import get_venue_coords, is_dome


def fetch_weather(venue_id, venue_name, game_time_utc=None):
    """Fetch weather for a venue. Returns None for dome stadiums."""
    if is_dome(venue_name):
        return {"dome": True, "wind_speed": 0, "wind_dir": 0, "temp_f": 72, "humidity": 50}

    if not OPENWEATHERMAP_API_KEY:
        return None

    lat, lon = get_venue_coords(venue_id)
    if not lat or not lon:
        return None

    try:
        url = f"{WEATHER_API_BASE}/weather"
        params = {"lat": lat, "lon": lon, "appid": OPENWEATHERMAP_API_KEY, "units": "imperial"}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        wind = data.get("wind", {})
        main = data.get("main", {})

        return {
            "dome": False,
            "temp_f": main.get("temp", 72),
            "humidity": main.get("humidity", 50),
            "wind_speed": wind.get("speed", 0),
            "wind_dir": wind.get("deg", 0),
            "description": data.get("weather", [{}])[0].get("description", ""),
        }
    except Exception:
        return None


def wind_run_impact(wind_speed, wind_dir, venue_name=None):
    """Estimate wind impact on run scoring.
    Wind blowing out (to CF, ~180deg) increases runs.
    Wind blowing in (from CF, ~0deg) decreases runs.
    Returns adjustment in runs (positive = more runs expected).
    """
    if wind_speed < 5:
        return 0.0

    # Normalize to how much wind is blowing "out" vs "in"
    # 180 degrees = blowing out to CF, 0 = blowing in
    import math
    out_component = math.cos(math.radians(wind_dir - 180))
    impact = out_component * (wind_speed / 10) * 0.5

    return round(impact, 2)


def temp_run_impact(temp_f):
    """Temperature impact on run scoring.
    Every 10°F above 70 adds ~0.5 runs to expected total.
    """
    if temp_f is None:
        return 0.0
    return round((temp_f - 70) / 10 * 0.5, 2)
```

- [ ] **Step 5: Implement injuries.py**

```python
import statsapi
from config import SEASON_YEAR


def fetch_team_injuries(team_id):
    """Fetch injured list from MLB API roster status codes."""
    try:
        roster = statsapi.roster(team_id, rosterType="40Man", season=SEASON_YEAR)
        # statsapi.roster returns a formatted string, use the API directly
        data = statsapi.get("team_roster", {"teamId": team_id, "rosterType": "active"})
        injuries = []
        for player in data.get("roster", []):
            status = player.get("status", {})
            if status.get("code") != "A":  # Not active
                injuries.append({
                    "player_id": player["person"]["id"],
                    "player_name": player["person"]["fullName"],
                    "status_code": status.get("code"),
                    "status_desc": status.get("description"),
                    "position": player.get("position", {}).get("abbreviation"),
                })
        return injuries
    except Exception:
        return []


def fetch_recent_transactions(team_id, days=7):
    """Fetch recent IL transactions."""
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        data = statsapi.get("transactions", {"teamId": team_id, "startDate": start, "endDate": end})
        il_moves = []
        for txn in data.get("transactions", []):
            if txn.get("typeCode") in ("DL", "REL", "ASG"):
                il_moves.append({
                    "player_id": txn["person"]["id"],
                    "player_name": txn["person"]["fullName"],
                    "type": txn.get("typeDesc"),
                    "description": txn.get("description"),
                    "date": txn.get("date"),
                })
        return il_moves
    except Exception:
        return []
```

- [ ] **Step 6: Implement bullpen.py**

```python
import statsapi
from modules.database import get_connection
from config import SEASON_YEAR
from datetime import date


def fetch_bullpen_status(team_id):
    """Fetch bullpen pitcher stats and recent usage."""
    try:
        data = statsapi.get("team_roster", {"teamId": team_id, "rosterType": "active"})
        relievers = []
        for player in data.get("roster", []):
            pos = player.get("position", {}).get("abbreviation", "")
            if pos == "P":
                pid = player["person"]["id"]
                name = player["person"]["fullName"]
                try:
                    pstats = statsapi.player_stat_data(pid, group="pitching", type="season")
                    if pstats and pstats.get("stats"):
                        s = pstats["stats"][0].get("stats", {})
                        gs = int(s.get("gamesStarted", 0))
                        if gs == 0:  # Reliever only
                            relievers.append({
                                "pitcher_id": pid,
                                "pitcher_name": name,
                                "era": float(s.get("era", 0)),
                                "innings_pitched": float(s.get("inningsPitched", "0")),
                                "games": int(s.get("gamesPlayed", 0)),
                                "saves": int(s.get("saves", 0)),
                                "holds": int(s.get("holds", 0)),
                                "k_per_9": float(s.get("strikeoutsPer9Inn", 0)),
                                "whip": float(s.get("whip", 0)),
                            })
                except Exception:
                    continue
        return relievers
    except Exception:
        return []


def calc_bullpen_aggregate(relievers):
    """Calculate aggregate bullpen metrics."""
    if not relievers:
        return {"bullpen_era": None, "bullpen_k_per_9": None, "bullpen_whip": None, "reliever_count": 0}

    total_ip = sum(r["innings_pitched"] for r in relievers)
    if total_ip == 0:
        return {"bullpen_era": None, "bullpen_k_per_9": None, "bullpen_whip": None, "reliever_count": len(relievers)}

    weighted_era = sum(r["era"] * r["innings_pitched"] for r in relievers) / total_ip
    weighted_k9 = sum(r["k_per_9"] * r["innings_pitched"] for r in relievers) / total_ip
    weighted_whip = sum(r["whip"] * r["innings_pitched"] for r in relievers) / total_ip

    return {
        "bullpen_era": round(weighted_era, 2),
        "bullpen_k_per_9": round(weighted_k9, 1),
        "bullpen_whip": round(weighted_whip, 2),
        "reliever_count": len(relievers),
    }
```

- [ ] **Step 7: Commit**

```bash
git add modules/data/batter_stats.py modules/data/park_factors.py modules/data/umpires.py modules/data/weather.py modules/data/injuries.py modules/data/bullpen.py
git commit -m "feat: data modules — batters, park factors, umpires, weather, injuries, bullpen"
```

---

## Task 6: Game Predictor (13-Factor Model)

**Files:**
- Create: `modules/models/game_predictor.py`
- Create: `modules/models/confidence.py`
- Create: `tests/test_game_predictor.py`

- [ ] **Step 1: Implement confidence.py (shared grading)**

```python
from config import (BET_MIN_CONFIDENCE, BET_MIN_EDGE, LEAN_MIN_CONFIDENCE, LEAN_MIN_EDGE,
                     K_BET_MIN_EDGE, K_LEAN_MIN_EDGE, NRFI_BET_MIN_EDGE, NRFI_LEAN_MIN_EDGE)


def grade_pick(confidence, edge, bet_type="game"):
    """Assign BET / LEAN / PASS grade based on confidence and edge."""
    if bet_type == "game":
        if confidence >= BET_MIN_CONFIDENCE and edge >= BET_MIN_EDGE:
            return "BET"
        elif confidence >= LEAN_MIN_CONFIDENCE and edge >= LEAN_MIN_EDGE:
            return "LEAN"
    elif bet_type == "strikeout":
        if confidence >= BET_MIN_CONFIDENCE and edge >= K_BET_MIN_EDGE:
            return "BET"
        elif confidence >= LEAN_MIN_CONFIDENCE and edge >= K_LEAN_MIN_EDGE:
            return "LEAN"
    elif bet_type == "nrfi":
        if confidence >= BET_MIN_CONFIDENCE and edge >= NRFI_BET_MIN_EDGE:
            return "BET"
        elif confidence >= LEAN_MIN_CONFIDENCE and edge >= NRFI_LEAN_MIN_EDGE:
            return "LEAN"
    return "PASS"


def calc_game_confidence(data_flags, signal_agreement, contradictions):
    """Calculate confidence score for game predictions (0-100)."""
    score = 0

    # Data availability (max 75)
    if data_flags.get("pitcher_stats"):
        score += 20
    if data_flags.get("lineup_confirmed"):
        score += 15
    if data_flags.get("bullpen_data"):
        score += 10
    if data_flags.get("umpire_known"):
        score += 10
    if data_flags.get("weather_data"):
        score += 10
    if data_flags.get("odds_available"):
        score += 10

    # Signal agreement bonuses (max 37)
    if signal_agreement.get("xera_fip_agree"):
        score += 15
    if signal_agreement.get("three_plus_aligned"):
        score += 12
    if signal_agreement.get("market_agrees"):
        score += 10

    # Penalties
    if not data_flags.get("lineup_confirmed"):
        score -= 15
    score -= contradictions * 6
    if data_flags.get("park_extreme"):
        score -= 10
    if not data_flags.get("umpire_known"):
        score -= 5

    return max(0, min(100, score))


def calc_k_confidence(data_flags, signal_agreement):
    """Calculate confidence score for K prop predictions (0-100)."""
    score = 0

    if data_flags.get("csw_data"):
        score += 25
    if data_flags.get("opposing_k_rate"):
        score += 20
    if data_flags.get("recent_form"):
        score += 15
    if data_flags.get("umpire_zone"):
        score += 10

    if signal_agreement.get("csw_swstr_elite"):
        score += 15
    if signal_agreement.get("opposing_k_high"):
        score += 10
    if signal_agreement.get("k_friendly_park"):
        score += 10

    if data_flags.get("pitch_count_concern"):
        score -= 15
    if data_flags.get("k_trending_down"):
        score -= 10
    if not data_flags.get("opposing_k_rate"):
        score -= 10

    return max(0, min(100, score))


def calc_nrfi_confidence(data_flags, signal_agreement):
    """Calculate confidence score for NRFI predictions (0-100)."""
    score = 0

    if data_flags.get("both_fips_known"):
        score += 25
    if data_flags.get("first_inning_era"):
        score += 20
    if data_flags.get("leadoff_data"):
        score += 15
    if data_flags.get("umpire_known"):
        score += 10

    if signal_agreement.get("both_fip_low"):
        score += 15
    if signal_agreement.get("both_nrfi_high"):
        score += 12
    if signal_agreement.get("k_park_ump_combo"):
        score += 10

    if data_flags.get("pitcher_bad_first_inning"):
        score -= 15
    if data_flags.get("elite_leadoff"):
        score -= 10
    if data_flags.get("hitter_park_warm"):
        score -= 10

    return max(0, min(100, score))
```

- [ ] **Step 2: Implement game_predictor.py**

```python
from modules.data.odds import american_to_implied
from modules.models.confidence import calc_game_confidence, grade_pick
from modules.data.weather import wind_run_impact, temp_run_impact
from config import MARKET_WEIGHT, MODEL_WEIGHT, HOME_ADVANTAGE_RUNS


def predict_game(game, home_pitcher, away_pitcher, home_batting, away_batting,
                 bullpen_home, bullpen_away, park, umpire, weather, odds):
    """Run the 13-factor game prediction model.

    Returns a prediction dict with projected winner, edge, confidence, grade.
    """
    reasons = []
    risks = []
    contradictions = 0

    # --- Signal 1: Starting pitcher quality (xERA primary, ERA fallback) ---
    home_p_quality = _pitcher_quality_score(home_pitcher)
    away_p_quality = _pitcher_quality_score(away_pitcher)
    pitcher_edge = away_p_quality - home_p_quality  # Positive = away pitcher better
    # From perspective of home team: negative pitcher_edge means home pitcher is better

    if abs(pitcher_edge) > 0.5:
        better = "home" if pitcher_edge < 0 else "away"
        reasons.append(f"Pitcher edge: {game[f'{better}_pitcher_name']} "
                       f"(xERA {home_pitcher.get('xera') or home_pitcher.get('era', '?')})")

    # --- Signal 2: Lineup strength vs handedness ---
    home_lineup_score = _lineup_score(home_batting, away_pitcher)
    away_lineup_score = _lineup_score(away_batting, home_pitcher)
    lineup_edge = home_lineup_score - away_lineup_score

    # --- Signal 3: Barrel rate matchup ---
    home_barrel = home_batting.get("barrel_rate", 0) or 0
    away_barrel = away_batting.get("barrel_rate", 0) or 0
    home_barrel_against = home_pitcher.get("barrel_rate_against", 0) or 0
    away_barrel_against = away_pitcher.get("barrel_rate_against", 0) or 0

    home_barrel_matchup = away_barrel - home_barrel_against  # How much damage away lineup does to home pitcher
    away_barrel_matchup = home_barrel - away_barrel_against

    if home_barrel_matchup > 3 or away_barrel_matchup > 3:
        risks.append("Elevated barrel rate matchup — potential blowout risk")

    # --- Signal 4: Bullpen ---
    bp_home_era = bullpen_home.get("bullpen_era", 4.0) or 4.0
    bp_away_era = bullpen_away.get("bullpen_era", 4.0) or 4.0
    bp_edge = bp_away_era - bp_home_era  # Positive = home bullpen better

    if abs(bp_edge) > 0.5:
        better = "home" if bp_edge > 0 else "away"
        reasons.append(f"Bullpen edge: {game[f'{better}_team_name']} ({min(bp_home_era, bp_away_era):.2f} ERA)")

    # --- Signal 5: Park factors ---
    run_factor = (park.get("run_factor", 100) or 100) / 100
    park_adjustment = (run_factor - 1.0) * 4.5  # Scale to runs

    if run_factor > 1.05:
        risks.append(f"Hitter-friendly park (run factor {park.get('run_factor', 100)})")
    elif run_factor < 0.95:
        reasons.append(f"Pitcher-friendly park (run factor {park.get('run_factor', 100)})")

    # --- Signal 6: Weather ---
    weather_adj = 0
    if weather and not weather.get("dome"):
        weather_adj += wind_run_impact(weather.get("wind_speed", 0), weather.get("wind_dir", 0))
        weather_adj += temp_run_impact(weather.get("temp_f"))
        if abs(weather_adj) > 0.5:
            direction = "increases" if weather_adj > 0 else "decreases"
            risks.append(f"Weather {direction} run expectancy by {abs(weather_adj):.1f}")

    # --- Signal 7: Home advantage ---
    home_adj = HOME_ADVANTAGE_RUNS

    # --- Combine model signals into projected run differential ---
    # Pitcher quality differential (scaled to runs, ~1 xERA diff = ~1 run/game)
    pitcher_run_diff = -pitcher_edge  # Negative pitcher_edge = home pitcher better = positive for home

    # Lineup contribution
    lineup_run_diff = lineup_edge * 0.3  # Scale lineup score to partial runs

    # Bullpen contribution
    bp_run_diff = bp_edge * 0.2  # Scale

    model_home_runs_edge = (
        pitcher_run_diff +
        lineup_run_diff +
        bp_run_diff +
        home_adj +
        park_adjustment * 0.1 +
        weather_adj * 0.1
    )

    # --- Signal 11: Vegas blending ---
    market_implied_home = None
    if odds and odds.get("home_ml") is not None:
        market_implied_home = american_to_implied(odds["home_ml"])

    model_implied_home = _runs_edge_to_probability(model_home_runs_edge)

    if market_implied_home is not None:
        blended_home_prob = (MARKET_WEIGHT * market_implied_home) + (MODEL_WEIGHT * model_implied_home)
    else:
        blended_home_prob = model_implied_home

    # --- Check for contradictions ---
    if market_implied_home is not None:
        if (model_implied_home > 0.5 and market_implied_home < 0.45) or \
           (model_implied_home < 0.5 and market_implied_home > 0.55):
            contradictions += 1
            risks.append("Model and market disagree on winner")

    # --- Determine pick ---
    pick_team = game["home_team_name"] if blended_home_prob > 0.5 else game["away_team_name"]
    pick_prob = blended_home_prob if blended_home_prob > 0.5 else (1 - blended_home_prob)

    edge = 0
    if market_implied_home is not None:
        market_prob = market_implied_home if blended_home_prob > 0.5 else (1 - market_implied_home)
        edge = round((pick_prob - market_prob) * 100, 1)

    # --- Confidence ---
    data_flags = {
        "pitcher_stats": bool(home_pitcher.get("era") and away_pitcher.get("era")),
        "lineup_confirmed": bool(home_batting.get("ops")),
        "bullpen_data": bool(bullpen_home.get("bullpen_era")),
        "umpire_known": bool(umpire),
        "weather_data": bool(weather),
        "odds_available": bool(odds and odds.get("home_ml")),
        "park_extreme": abs((park.get("run_factor", 100) or 100) - 100) > 10,
    }
    signal_agreement = {
        "xera_fip_agree": _xera_fip_agree(home_pitcher, away_pitcher, blended_home_prob > 0.5),
        "three_plus_aligned": sum([
            pitcher_run_diff > 0 if blended_home_prob > 0.5 else pitcher_run_diff < 0,
            lineup_run_diff > 0 if blended_home_prob > 0.5 else lineup_run_diff < 0,
            bp_run_diff > 0 if blended_home_prob > 0.5 else bp_run_diff < 0,
        ]) >= 3,
        "market_agrees": market_implied_home is not None and (
            (blended_home_prob > 0.5 and market_implied_home > 0.5) or
            (blended_home_prob < 0.5 and market_implied_home < 0.5)
        ),
    }

    confidence = calc_game_confidence(data_flags, signal_agreement, contradictions)
    grade = grade_pick(confidence, abs(edge), "game")

    return {
        "game_pk": game["game_pk"],
        "bet_type": "game",
        "pick": pick_team,
        "pick_detail": f"{'ML' if abs(edge) < 3 else 'Run Line'} {pick_team}",
        "confidence": confidence,
        "edge": edge,
        "model_value": round(pick_prob * 100, 1),
        "market_value": round((market_prob if market_implied_home else pick_prob) * 100, 1),
        "grade": grade,
        "reasons": reasons[:5],
        "risks": risks[:3],
        "blended_home_prob": round(blended_home_prob, 3),
        "model_home_prob": round(model_implied_home, 3),
    }


def _pitcher_quality_score(pitcher):
    """Score pitcher quality. Lower = better pitcher. Uses xERA primary, FIP secondary, ERA fallback."""
    xera = pitcher.get("xera")
    fip = pitcher.get("fip")
    era = pitcher.get("era")

    if xera and fip:
        return xera * 0.6 + fip * 0.4
    elif xera:
        return xera
    elif fip:
        return fip
    elif era:
        return era
    return 4.50  # League average fallback


def _lineup_score(batting, opposing_pitcher):
    """Score a lineup's expected output against the opposing pitcher."""
    ops = batting.get("ops", 0.700) or 0.700
    wrc = batting.get("wrc_plus", 100) or 100
    k_rate = batting.get("k_rate", 22) or 22

    # Adjust for handedness matchup
    pitcher_hand = opposing_pitcher.get("throws")  # L or R
    if pitcher_hand == "L":
        split_ops = batting.get("vs_lhp_ops")
        if split_ops:
            ops = split_ops

    score = (ops - 0.700) * 10 + (wrc - 100) / 20 - (k_rate - 22) / 10
    return score


def _runs_edge_to_probability(runs_edge):
    """Convert a runs edge to a win probability. ~0.25 runs = ~55% win prob."""
    import math
    return 1 / (1 + math.exp(-runs_edge * 0.35))


def _xera_fip_agree(home_p, away_p, home_favored):
    """Check if xERA and FIP signals agree with the pick direction."""
    home_quality = _pitcher_quality_score(home_p)
    away_quality = _pitcher_quality_score(away_p)
    return (home_quality < away_quality) == home_favored
```

- [ ] **Step 3: Write test_game_predictor.py**

```python
from modules.models.game_predictor import predict_game, _pitcher_quality_score, _runs_edge_to_probability
from modules.models.confidence import grade_pick


def test_pitcher_quality_prefers_xera():
    pitcher = {"xera": 3.00, "fip": 3.50, "era": 4.00}
    score = _pitcher_quality_score(pitcher)
    assert score == 3.00 * 0.6 + 3.50 * 0.4  # xERA weighted 60%


def test_pitcher_quality_fallback_to_era():
    pitcher = {"era": 3.50}
    assert _pitcher_quality_score(pitcher) == 3.50


def test_runs_edge_to_probability_positive():
    prob = _runs_edge_to_probability(1.0)
    assert prob > 0.5


def test_runs_edge_to_probability_zero():
    prob = _runs_edge_to_probability(0.0)
    assert abs(prob - 0.5) < 0.01


def test_grade_pick_bet():
    assert grade_pick(70, 3.0, "game") == "BET"


def test_grade_pick_lean():
    assert grade_pick(50, 1.0, "game") == "LEAN"


def test_grade_pick_pass():
    assert grade_pick(20, 0.1, "game") == "PASS"


def test_predict_game_returns_required_fields():
    game = {"game_pk": 1, "home_team_name": "Red Sox", "away_team_name": "Yankees",
            "home_pitcher_name": "Bello", "away_pitcher_name": "Cole"}
    home_p = {"era": 3.80, "xera": 3.45, "fip": 3.62, "barrel_rate_against": 7.0}
    away_p = {"era": 2.51, "xera": 2.89, "fip": 3.01, "barrel_rate_against": 5.0}
    home_bat = {"ops": 0.730, "k_rate": 22, "wrc_plus": 102, "barrel_rate": 8.5}
    away_bat = {"ops": 0.750, "k_rate": 24, "wrc_plus": 108, "barrel_rate": 9.0}
    bp_home = {"bullpen_era": 3.90}
    bp_away = {"bullpen_era": 3.50}
    park = {"run_factor": 105}
    umpire = None
    weather = {"dome": False, "temp_f": 72, "wind_speed": 8, "wind_dir": 180}
    odds = {"home_ml": 108, "away_ml": -128}

    result = predict_game(game, home_p, away_p, home_bat, away_bat,
                          bp_home, bp_away, park, umpire, weather, odds)

    assert "pick" in result
    assert "confidence" in result
    assert "edge" in result
    assert "grade" in result
    assert result["grade"] in ("BET", "LEAN", "PASS")
    assert 0 <= result["confidence"] <= 100
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_game_predictor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/models/game_predictor.py modules/models/confidence.py tests/test_game_predictor.py
git commit -m "feat: 13-factor game predictor with xERA-primary model and confidence scoring"
```

---

## Task 7: Strikeout Predictor (7-Factor Weighted Model)

**Files:**
- Create: `modules/models/strikeout_predictor.py`
- Create: `tests/test_strikeout_predictor.py`

- [ ] **Step 1: Implement strikeout_predictor.py**

```python
from modules.data.odds import american_to_implied
from modules.models.confidence import calc_k_confidence, grade_pick


# Factor weights (sum to 1.0)
W_CSW = 0.25
W_SWSTR = 0.15
W_K_RATE = 0.15
W_OPP_K_RATE = 0.20
W_PITCH_COUNT = 0.10
W_RECENT_FORM = 0.10
W_PARK_UMP = 0.05


def predict_strikeouts(game, pitcher, opposing_batting, park, umpire, weather, k_prop_odds):
    """Predict starting pitcher strikeout total using 7-factor weighted model.

    Returns prediction dict with model Ks, edge vs line, confidence, grade.
    """
    reasons = []

    # --- Factor 1: CSW% (Called Strikes + Whiffs) ---
    csw = pitcher.get("csw")
    csw_ks = _csw_to_expected_ks(csw) if csw else None

    # --- Factor 2: SwStr% ---
    swstr = pitcher.get("swstr")
    swstr_ks = _swstr_to_expected_ks(swstr) if swstr else None

    # --- Factor 3: Season K% ---
    k_rate = pitcher.get("k_rate")
    season_ks = _k_rate_to_expected_ks(k_rate, pitcher) if k_rate else None

    # --- Factor 4: Opposing lineup K% ---
    opp_k_rate = opposing_batting.get("k_rate") or opposing_batting.get("team_k_rate")
    opp_adjustment = _opposing_k_adjustment(opp_k_rate) if opp_k_rate else 0

    if opp_k_rate and opp_k_rate > 25:
        reasons.append(f"Opposing lineup K rate: {opp_k_rate:.1f}% (above average)")

    # --- Factor 5: Pitch count / innings expectation ---
    expected_batters = _estimate_batters_faced(pitcher)
    pitch_count_cap = expected_batters * (k_rate / 100) if k_rate else None

    # --- Factor 6: Recent form (last 3 starts) ---
    recent_k9 = pitcher.get("recent_k_per_9")
    season_k9 = pitcher.get("k_per_9", 0)
    form_adjustment = 0
    if recent_k9 and season_k9:
        form_adjustment = (recent_k9 - season_k9) / 9  # Scale to per-game
        if form_adjustment > 0.3:
            reasons.append(f"K rate trending up (recent {recent_k9:.1f} K/9 vs season {season_k9:.1f})")
        elif form_adjustment < -0.3:
            reasons.append(f"K rate trending down (recent {recent_k9:.1f} K/9 vs season {season_k9:.1f})")

    # --- Factor 7: Park + umpire ---
    park_k_factor = (park.get("k_factor", 100) or 100) / 100
    ump_k_adjustment = 0
    if umpire and umpire.get("k_plus"):
        ump_k_adjustment = umpire["k_plus"] * 0.1  # Scale K+ to fractional Ks

    # --- Weighted combination ---
    components = []
    weights_used = []

    if csw_ks is not None:
        components.append(csw_ks * W_CSW)
        weights_used.append(W_CSW)
        if csw > 30:
            reasons.append(f"Elite CSW: {csw:.1f}%")
    if swstr_ks is not None:
        components.append(swstr_ks * W_SWSTR)
        weights_used.append(W_SWSTR)
        if swstr > 12:
            reasons.append(f"High SwStr: {swstr:.1f}%")
    if season_ks is not None:
        components.append(season_ks * W_K_RATE)
        weights_used.append(W_K_RATE)
    if opp_k_rate is not None:
        components.append((season_ks or csw_ks or 6) * (1 + opp_adjustment) * W_OPP_K_RATE)
        weights_used.append(W_OPP_K_RATE)
    if pitch_count_cap is not None:
        components.append(pitch_count_cap * W_PITCH_COUNT)
        weights_used.append(W_PITCH_COUNT)

    # Recent form
    base_ks = (season_ks or csw_ks or 6)
    components.append((base_ks + form_adjustment) * W_RECENT_FORM)
    weights_used.append(W_RECENT_FORM)

    # Park + umpire
    components.append(base_ks * park_k_factor * W_PARK_UMP)
    weights_used.append(W_PARK_UMP)

    if not weights_used:
        return _empty_prediction(game, "Insufficient data for K prediction")

    # Normalize weights
    total_weight = sum(weights_used)
    model_ks = sum(components) / total_weight if total_weight > 0 else 6.0

    # Apply adjustments
    model_ks += ump_k_adjustment
    model_ks = round(model_ks, 1)

    # --- Edge calculation ---
    line = None
    edge = 0
    if k_prop_odds:
        line = k_prop_odds.get("line")
        if line:
            edge = round(model_ks - line, 1)

    pick = "OVER" if edge > 0 else "UNDER" if edge < 0 else "PASS"
    pick_detail = f"{pick} {line}" if line else f"Model: {model_ks} Ks"

    # --- Confidence ---
    data_flags = {
        "csw_data": csw is not None,
        "opposing_k_rate": opp_k_rate is not None,
        "recent_form": recent_k9 is not None,
        "umpire_zone": umpire is not None and umpire.get("k_plus") is not None,
        "pitch_count_concern": expected_batters < 22,
        "k_trending_down": form_adjustment < -0.3,
    }
    signal_agreement = {
        "csw_swstr_elite": (csw or 0) > 30 and (swstr or 0) > 12,
        "opposing_k_high": (opp_k_rate or 0) > 25,
        "k_friendly_park": (park.get("k_factor", 100) or 100) > 102,
    }
    confidence = calc_k_confidence(data_flags, signal_agreement)
    grade = grade_pick(confidence, abs(edge), "strikeout")

    return {
        "game_pk": game["game_pk"],
        "bet_type": "strikeout",
        "pitcher_id": pitcher.get("player_id"),
        "pitcher_name": pitcher.get("player_name"),
        "pick": pick,
        "pick_detail": pick_detail,
        "model_ks": model_ks,
        "line": line,
        "confidence": confidence,
        "edge": edge,
        "grade": grade,
        "reasons": reasons[:5],
        "expected_batters": expected_batters,
    }


def _csw_to_expected_ks(csw, avg_batters=24):
    """Convert CSW% to expected strikeouts. ~30% CSW ≈ 7 Ks per 24 batters."""
    if not csw:
        return None
    return round(csw / 100 * avg_batters * 1.1, 1)  # CSW slightly overestimates pure Ks


def _swstr_to_expected_ks(swstr, avg_batters=24):
    """Convert SwStr% to expected Ks. ~12% SwStr ≈ 7 Ks."""
    if not swstr:
        return None
    return round(swstr / 100 * avg_batters * 2.4, 1)


def _k_rate_to_expected_ks(k_rate, pitcher):
    """Convert K% to expected Ks based on estimated batters faced."""
    batters = _estimate_batters_faced(pitcher)
    return round(k_rate / 100 * batters, 1)


def _estimate_batters_faced(pitcher):
    """Estimate batters faced based on innings pitched and games started."""
    ip = pitcher.get("innings_pitched", 0) or 0
    gs = pitcher.get("games_started", 1) or 1
    if gs > 0 and ip > 0:
        avg_ip = ip / gs
        return round(avg_ip * 4.3)  # ~4.3 batters per inning
    return 24  # Default ~5.5 innings


def _opposing_k_adjustment(opp_k_rate):
    """Adjustment factor based on opposing lineup K rate. League avg ~22%."""
    if not opp_k_rate:
        return 0
    return (opp_k_rate - 22) / 100  # +0.05 per percentage point above average


def _empty_prediction(game, reason):
    return {
        "game_pk": game["game_pk"], "bet_type": "strikeout",
        "pick": "PASS", "pick_detail": reason,
        "model_ks": None, "line": None, "confidence": 0,
        "edge": 0, "grade": "PASS", "reasons": [reason], "expected_batters": 0,
    }
```

- [ ] **Step 2: Write test_strikeout_predictor.py**

```python
from modules.models.strikeout_predictor import (
    predict_strikeouts, _csw_to_expected_ks, _swstr_to_expected_ks,
    _estimate_batters_faced, _opposing_k_adjustment,
)


def test_csw_to_expected_ks_elite():
    ks = _csw_to_expected_ks(32.0)
    assert 7 < ks < 10


def test_swstr_to_expected_ks():
    ks = _swstr_to_expected_ks(13.0)
    assert 6 < ks < 9


def test_estimate_batters_faced():
    pitcher = {"innings_pitched": 30.0, "games_started": 5}
    batters = _estimate_batters_faced(pitcher)
    assert 24 < batters < 30  # 6 IP/start * 4.3 = ~26


def test_opposing_k_adjustment_high():
    adj = _opposing_k_adjustment(27)
    assert adj > 0  # Above average = positive adjustment


def test_opposing_k_adjustment_low():
    adj = _opposing_k_adjustment(18)
    assert adj < 0  # Below average = negative adjustment


def test_predict_strikeouts_returns_fields():
    game = {"game_pk": 1, "home_team_name": "Red Sox", "away_team_name": "Yankees"}
    pitcher = {"player_id": 543037, "player_name": "Gerrit Cole", "csw": 32.1,
               "swstr": 13.8, "k_rate": 30.2, "k_per_9": 11.4,
               "innings_pitched": 32.0, "games_started": 5, "recent_k_per_9": 12.0}
    opp_batting = {"k_rate": 26.8}
    park = {"k_factor": 98}
    umpire = {"k_plus": 0.4}
    weather = None
    k_odds = {"line": 7.5, "over_price": -115, "under_price": -105}

    result = predict_strikeouts(game, pitcher, opp_batting, park, umpire, weather, k_odds)
    assert result["pick"] in ("OVER", "UNDER", "PASS")
    assert result["model_ks"] is not None
    assert result["model_ks"] > 5  # Cole should project high
    assert result["grade"] in ("BET", "LEAN", "PASS")
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_strikeout_predictor.py -v
```

- [ ] **Step 4: Commit**

```bash
git add modules/models/strikeout_predictor.py tests/test_strikeout_predictor.py
git commit -m "feat: 7-factor weighted strikeout predictor with CSW-primary model"
```

---

## Task 8: NRFI Predictor (FIP-Primary Model)

**Files:**
- Create: `modules/models/nrfi_predictor.py`
- Create: `tests/test_nrfi_predictor.py`

- [ ] **Step 1: Implement nrfi_predictor.py**

```python
from modules.data.odds import american_to_implied
from modules.models.confidence import calc_nrfi_confidence, grade_pick


def predict_nrfi(game, home_pitcher, away_pitcher, home_batting_top,
                 away_batting_top, park, umpire, weather, nrfi_odds):
    """Predict NRFI probability using FIP-primary ensemble model.

    Returns prediction with NRFI probability, edge vs implied odds, confidence, grade.
    """
    reasons = []
    risks = []

    # --- Primary signal: FIP for both pitchers ---
    home_fip = home_pitcher.get("fip") or home_pitcher.get("era") or 4.50
    away_fip = away_pitcher.get("fip") or away_pitcher.get("era") or 4.50

    # Convert FIP to first-inning scoreless probability
    # Lower FIP = higher probability of scoreless inning
    # League avg FIP ~4.20, league avg NRFI rate ~72% per half-inning
    home_scoreless_prob = _fip_to_scoreless_prob(home_fip)
    away_scoreless_prob = _fip_to_scoreless_prob(away_fip)

    # --- First-inning ERA adjustment ---
    home_1st_era = home_pitcher.get("first_inning_era")
    away_1st_era = away_pitcher.get("first_inning_era")

    if home_1st_era is not None:
        home_1st_adj = _first_inning_era_adjustment(home_1st_era)
        home_scoreless_prob *= (1 + home_1st_adj)

    if away_1st_era is not None:
        away_1st_adj = _first_inning_era_adjustment(away_1st_era)
        away_scoreless_prob *= (1 + away_1st_adj)

    # --- First-pitch strike rate ---
    home_fstrike = home_pitcher.get("f_strike_pct")
    away_fstrike = away_pitcher.get("f_strike_pct")

    if home_fstrike and home_fstrike > 65:
        home_scoreless_prob *= 1.03
        reasons.append(f"{game['home_pitcher_name']} F-Strike: {home_fstrike:.0f}%")
    if away_fstrike and away_fstrike > 65:
        away_scoreless_prob *= 1.03

    # --- Historical NRFI rate ---
    home_nrfi = home_pitcher.get("nrfi_rate")
    away_nrfi = away_pitcher.get("nrfi_rate")

    if home_nrfi and home_nrfi > 70:
        reasons.append(f"{game['home_pitcher_name']} NRFI rate: {home_nrfi:.0f}%")
    if away_nrfi and away_nrfi > 70:
        reasons.append(f"{game['away_pitcher_name']} NRFI rate: {away_nrfi:.0f}%")

    # --- Leadoff hitter quality ---
    away_leadoff = away_batting_top[0] if away_batting_top else {}
    home_leadoff = home_batting_top[0] if home_batting_top else {}

    away_leadoff_obp = away_leadoff.get("ops", 0.700)
    home_leadoff_obp = home_leadoff.get("ops", 0.700)

    if away_leadoff_obp > 0.850:
        home_scoreless_prob *= 0.95
        risks.append(f"Elite away leadoff hitter (OPS {away_leadoff_obp:.3f})")
    if home_leadoff_obp > 0.850:
        away_scoreless_prob *= 0.95
        risks.append(f"Elite home leadoff hitter (OPS {home_leadoff_obp:.3f})")

    # --- Park factors ---
    run_factor = (park.get("run_factor", 100) or 100)
    if run_factor > 105:
        home_scoreless_prob *= 0.97
        away_scoreless_prob *= 0.97
        risks.append(f"Hitter-friendly park (factor {run_factor})")
    elif run_factor < 95:
        home_scoreless_prob *= 1.03
        away_scoreless_prob *= 1.03
        reasons.append(f"Pitcher-friendly park (factor {run_factor})")

    # --- Umpire ---
    if umpire and umpire.get("k_plus"):
        k_plus = umpire["k_plus"]
        if k_plus > 0.3:
            home_scoreless_prob *= 1.02
            away_scoreless_prob *= 1.02
            reasons.append(f"Umpire {umpire['umpire_name']} K+ = {k_plus:.1f}")

    # --- Weather ---
    if weather and not weather.get("dome"):
        temp = weather.get("temp_f", 72)
        if temp < 55:
            home_scoreless_prob *= 1.03
            away_scoreless_prob *= 1.03
            reasons.append(f"Cold weather ({temp:.0f}°F) suppresses offense")
        elif temp > 85:
            home_scoreless_prob *= 0.97
            away_scoreless_prob *= 0.97
            risks.append(f"Hot weather ({temp:.0f}°F) favors hitters")

    # --- Combined NRFI probability ---
    # NRFI requires BOTH half-innings to be scoreless
    nrfi_prob = home_scoreless_prob * away_scoreless_prob
    nrfi_prob = max(0.30, min(0.85, nrfi_prob))  # Clamp to realistic range

    # --- Edge vs market ---
    implied_prob = None
    edge = 0
    if nrfi_odds and nrfi_odds.get("nrfi_price"):
        implied_prob = american_to_implied(nrfi_odds["nrfi_price"])
        edge = round((nrfi_prob - implied_prob) * 100, 1)

    pick = "NRFI" if edge > 0 or (not implied_prob and nrfi_prob > 0.60) else "YRFI" if edge < -3 else "PASS"

    # --- FIP quality flags ---
    if home_fip < 3.50 and away_fip < 3.50:
        reasons.append(f"Both pitchers FIP < 3.50 ({home_fip:.2f} / {away_fip:.2f})")
    if home_fip > 4.50:
        risks.append(f"{game['home_pitcher_name']} FIP {home_fip:.2f} — shaky first inning risk")
    if away_fip > 4.50:
        risks.append(f"{game['away_pitcher_name']} FIP {away_fip:.2f} — shaky first inning risk")

    # --- Confidence ---
    data_flags = {
        "both_fips_known": home_pitcher.get("fip") is not None and away_pitcher.get("fip") is not None,
        "first_inning_era": home_1st_era is not None or away_1st_era is not None,
        "leadoff_data": bool(away_leadoff.get("ops")) or bool(home_leadoff.get("ops")),
        "umpire_known": umpire is not None,
        "pitcher_bad_first_inning": (home_1st_era or 0) > 4.50 or (away_1st_era or 0) > 4.50,
        "elite_leadoff": away_leadoff_obp > 0.850 or home_leadoff_obp > 0.850,
        "hitter_park_warm": run_factor > 105 and (weather or {}).get("temp_f", 72) > 80,
    }
    signal_agreement = {
        "both_fip_low": home_fip < 3.50 and away_fip < 3.50,
        "both_nrfi_high": (home_nrfi or 0) > 65 and (away_nrfi or 0) > 65,
        "k_park_ump_combo": (park.get("k_factor", 100) or 100) > 100 and
                            umpire is not None and (umpire.get("k_plus", 0) or 0) > 0,
    }
    confidence = calc_nrfi_confidence(data_flags, signal_agreement)
    grade = grade_pick(confidence, abs(edge), "nrfi")

    return {
        "game_pk": game["game_pk"],
        "bet_type": "nrfi",
        "pick": pick,
        "pick_detail": f"{pick} ({nrfi_prob*100:.1f}% vs {(implied_prob or 0)*100:.1f}% implied)",
        "nrfi_probability": round(nrfi_prob, 3),
        "implied_probability": round(implied_prob, 3) if implied_prob else None,
        "confidence": confidence,
        "edge": edge,
        "grade": grade,
        "reasons": reasons[:5],
        "risks": risks[:3],
        "home_fip": home_fip,
        "away_fip": away_fip,
    }


def _fip_to_scoreless_prob(fip):
    """Convert FIP to probability of a scoreless half-inning.
    League avg FIP ~4.20 -> ~72% scoreless rate per half-inning.
    Each 1.0 FIP improvement -> ~5% better scoreless rate.
    """
    base_rate = 0.72
    adjustment = (4.20 - fip) * 0.05
    return max(0.50, min(0.92, base_rate + adjustment))


def _first_inning_era_adjustment(era_1st):
    """Adjustment based on first-inning ERA vs league average (~4.20).
    Returns multiplier adjustment (-0.10 to +0.10).
    """
    diff = 4.20 - era_1st
    return max(-0.10, min(0.10, diff * 0.025))
```

- [ ] **Step 2: Write test_nrfi_predictor.py**

```python
from modules.models.nrfi_predictor import predict_nrfi, _fip_to_scoreless_prob, _first_inning_era_adjustment


def test_fip_to_scoreless_elite():
    prob = _fip_to_scoreless_prob(2.50)
    assert prob > 0.78  # Elite pitcher = high scoreless rate


def test_fip_to_scoreless_bad():
    prob = _fip_to_scoreless_prob(5.50)
    assert prob < 0.68  # Bad pitcher = lower scoreless rate


def test_fip_to_scoreless_average():
    prob = _fip_to_scoreless_prob(4.20)
    assert abs(prob - 0.72) < 0.02  # League average


def test_first_inning_era_good():
    adj = _first_inning_era_adjustment(2.00)
    assert adj > 0  # Good 1st inning = positive adjustment


def test_first_inning_era_bad():
    adj = _first_inning_era_adjustment(6.00)
    assert adj < 0  # Bad 1st inning = negative adjustment


def test_predict_nrfi_both_aces():
    game = {"game_pk": 1, "home_team_name": "Red Sox", "away_team_name": "Yankees",
            "home_pitcher_name": "Bello", "away_pitcher_name": "Cole"}
    home_p = {"fip": 2.80, "first_inning_era": 2.10, "f_strike_pct": 68, "nrfi_rate": 75}
    away_p = {"fip": 3.01, "first_inning_era": 2.50, "f_strike_pct": 66, "nrfi_rate": 71}
    park = {"run_factor": 100, "k_factor": 100}
    umpire = {"umpire_name": "Test Ump", "k_plus": 0.3}
    weather = {"dome": False, "temp_f": 65}
    nrfi_odds = {"nrfi_price": -120, "yrfi_price": 100}

    result = predict_nrfi(game, home_p, away_p, [], [], park, umpire, weather, nrfi_odds)
    assert result["nrfi_probability"] > 0.55
    assert result["pick"] in ("NRFI", "YRFI", "PASS")
    assert result["grade"] in ("BET", "LEAN", "PASS")


def test_predict_nrfi_bad_pitchers():
    game = {"game_pk": 2, "home_team_name": "Rockies", "away_team_name": "Reds",
            "home_pitcher_name": "BadP1", "away_pitcher_name": "BadP2"}
    home_p = {"fip": 5.20, "first_inning_era": 5.80}
    away_p = {"fip": 5.50, "first_inning_era": 6.10}
    park = {"run_factor": 115, "k_factor": 90}  # Coors-like
    umpire = None
    weather = {"dome": False, "temp_f": 88}
    nrfi_odds = {"nrfi_price": 110, "yrfi_price": -130}

    result = predict_nrfi(game, home_p, away_p, [], [], park, umpire, weather, nrfi_odds)
    assert result["nrfi_probability"] < 0.55  # Bad pitchers at Coors in heat
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_nrfi_predictor.py -v
```

- [ ] **Step 4: Commit**

```bash
git add modules/models/nrfi_predictor.py tests/test_nrfi_predictor.py
git commit -m "feat: FIP-primary NRFI predictor with ensemble scoring"
```

---

## Task 9: Report Generation

**Files:**
- Create: `modules/output/reporting.py`

- [ ] **Step 1: Implement reporting.py**

```python
import os
from datetime import datetime
from config import REPORTS_DIR
from colorama import Fore, Style, init

init()


def generate_report(games, predictions, target_date):
    """Generate the full daily report."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    lines = []
    lines.append(f"MLB Prediction Bot — {target_date}")
    lines.append("=" * 60)

    game_preds = [p for p in predictions if p["bet_type"] == "game"]
    k_preds = [p for p in predictions if p["bet_type"] == "strikeout"]
    nrfi_preds = [p for p in predictions if p["bet_type"] == "nrfi"]

    # Game Predictions
    if game_preds:
        lines.append("\nGAME PREDICTIONS")
        lines.append("─" * 40)
        for pred in game_preds:
            game = _find_game(games, pred["game_pk"])
            if not game:
                continue
            lines.extend(_format_game_prediction(game, pred))

    # Strikeout Props
    if k_preds:
        lines.append("\nPITCHER STRIKEOUT PROPS")
        lines.append("─" * 40)
        for pred in k_preds:
            game = _find_game(games, pred["game_pk"])
            if not game:
                continue
            lines.extend(_format_k_prediction(game, pred))

    # NRFI Picks
    if nrfi_preds:
        lines.append("\nNRFI PICKS")
        lines.append("─" * 40)
        for pred in nrfi_preds:
            game = _find_game(games, pred["game_pk"])
            if not game:
                continue
            lines.extend(_format_nrfi_prediction(game, pred))

    # Best Picks Summary
    lines.extend(_format_best_picks(predictions))

    report_text = "\n".join(lines)

    # Save to file
    filepath = os.path.join(REPORTS_DIR, f"{target_date}.txt")
    with open(filepath, "w") as f:
        f.write(report_text)

    # Print to console with color
    _print_colored(report_text)

    return report_text


def _find_game(games, game_pk):
    for g in games:
        if g["game_pk"] == game_pk:
            return g
    return None


def _format_game_prediction(game, pred):
    lines = []
    grade_color = _grade_color(pred["grade"])
    lines.append(f"{game['away_team_name']} @ {game['home_team_name']} | {game.get('venue_name', '')}")
    lines.append(f"  Starter: {game.get('away_pitcher_name', 'TBD')} vs {game.get('home_pitcher_name', 'TBD')}")
    lines.append(f"  Model: {pred.get('model_value', '?')}% | Market: {pred.get('market_value', '?')}%")
    lines.append(f"  Pick: {pred['pick']} — {grade_color}{pred['grade']}{Style.RESET_ALL}")
    lines.append(f"  Edge: {pred['edge']:.1f}% | Confidence: {pred['confidence']}/100")
    if pred.get("reasons"):
        lines.append(f"  Top Factors: {', '.join(pred['reasons'][:3])}")
    if pred.get("risks"):
        lines.append(f"  Risks: {', '.join(pred['risks'][:2])}")
    lines.append("")
    return lines


def _format_k_prediction(game, pred):
    lines = []
    grade_color = _grade_color(pred["grade"])
    lines.append(f"{pred.get('pitcher_name', '?')} ({game['away_team_name']} @ {game['home_team_name']})")
    lines.append(f"  Model: {pred.get('model_ks', '?')} Ks | Line: O/U {pred.get('line', '?')}")
    lines.append(f"  Pick: {pred['pick']} — {grade_color}{pred['grade']}{Style.RESET_ALL}")
    lines.append(f"  Edge: {pred['edge']:+.1f} Ks | Confidence: {pred['confidence']}/100")
    if pred.get("reasons"):
        lines.append(f"  Why: {', '.join(pred['reasons'][:3])}")
    lines.append("")
    return lines


def _format_nrfi_prediction(game, pred):
    lines = []
    grade_color = _grade_color(pred["grade"])
    lines.append(f"{game['away_team_name']} @ {game['home_team_name']}")
    nrfi_pct = pred.get('nrfi_probability', 0) * 100
    implied_pct = (pred.get('implied_probability') or 0) * 100
    lines.append(f"  NRFI Probability: {nrfi_pct:.1f}% | Implied: {implied_pct:.1f}%")
    lines.append(f"  Pick: {pred['pick']} — {grade_color}{pred['grade']}{Style.RESET_ALL}")
    lines.append(f"  Edge: {pred['edge']:.1f}% | Confidence: {pred['confidence']}/100")
    if pred.get("reasons"):
        lines.append(f"  Why: {', '.join(pred['reasons'][:3])}")
    if pred.get("risks"):
        lines.append(f"  Risks: {', '.join(pred['risks'][:2])}")
    lines.append("")
    return lines


def _format_best_picks(predictions):
    lines = ["\nTODAY'S BEST PICKS", "=" * 40]

    bets = [p for p in predictions if p["grade"] == "BET"]
    leans = [p for p in predictions if p["grade"] == "LEAN"]

    if bets:
        lines.append(f"{Fore.GREEN}BET:{Style.RESET_ALL}")
        for p in sorted(bets, key=lambda x: x["confidence"], reverse=True):
            lines.append(f"  - {p['bet_type'].upper()}: {p['pick']} ({p['confidence']}/100, {p['edge']:.1f}% edge)")

    if leans:
        lines.append(f"{Fore.YELLOW}LEAN:{Style.RESET_ALL}")
        for p in sorted(leans, key=lambda x: x["confidence"], reverse=True):
            lines.append(f"  - {p['bet_type'].upper()}: {p['pick']} ({p['confidence']}/100)")

    if not bets and not leans:
        lines.append("  No actionable picks today.")

    return lines


def _grade_color(grade):
    if grade == "BET":
        return Fore.GREEN
    elif grade == "LEAN":
        return Fore.YELLOW
    return Fore.RED


def _print_colored(text):
    print(text)
```

- [ ] **Step 2: Commit**

```bash
git add modules/output/reporting.py
git commit -m "feat: report generation with colored console output and file export"
```

---

## Task 10: Results Tracker + Record Keeping

**Files:**
- Create: `modules/output/results_tracker.py`

- [ ] **Step 1: Implement results_tracker.py**

```python
import statsapi
from datetime import datetime
from modules.database import get_connection


def grade_results(date_str):
    """Grade predictions from a given date against actual results."""
    conn = get_connection()
    predictions = conn.execute(
        "SELECT * FROM predictions WHERE game_pk IN (SELECT game_pk FROM games WHERE game_date = ?)",
        (date_str,)
    ).fetchall()

    if not predictions:
        print(f"No predictions found for {date_str}")
        return []

    results = []
    for pred in predictions:
        game_pk = pred["game_pk"]
        bet_type = pred["bet_type"]

        try:
            if bet_type == "game":
                result = _grade_game_pick(game_pk, pred)
            elif bet_type == "strikeout":
                result = _grade_k_pick(game_pk, pred)
            elif bet_type == "nrfi":
                result = _grade_nrfi_pick(game_pk, pred)
            else:
                continue

            if result:
                results.append(result)
                _save_result(result)
        except Exception as e:
            print(f"  Error grading {bet_type} for game {game_pk}: {e}")

    conn.close()
    _print_grade_summary(results, date_str)
    return results


def _grade_game_pick(game_pk, pred):
    """Grade a game prediction against the final score."""
    boxscore = statsapi.boxscore_data(game_pk)
    if not boxscore:
        return None

    away_score = boxscore.get("awayBattingTotals", {}).get("r", 0)
    home_score = boxscore.get("homeBattingTotals", {}).get("r", 0)

    if away_score == home_score:
        return None  # Game not final or tied (shouldn't happen)

    winner = pred["pick"]  # Team name
    home_name = boxscore.get("teamInfo", {}).get("home", {}).get("teamName", "")
    away_name = boxscore.get("teamInfo", {}).get("away", {}).get("teamName", "")

    actual_winner = home_name if home_score > away_score else away_name
    result = "WIN" if winner in actual_winner or actual_winner in winner else "LOSS"

    return {
        "game_pk": game_pk,
        "bet_type": "game",
        "pick": pred["pick"],
        "result": result,
        "actual_outcome": f"{away_name} {away_score} - {home_name} {home_score}",
        "edge_at_pick": pred["edge"],
        "confidence_at_pick": pred["confidence"],
    }


def _grade_k_pick(game_pk, pred):
    """Grade a K prop against actual starter strikeouts."""
    boxscore = statsapi.boxscore_data(game_pk)
    if not boxscore:
        return None

    # Find the starter's actual Ks from boxscore
    pick_detail = pred.get("pick_detail", "")
    pick = pred["pick"]  # OVER or UNDER

    # Search both teams for the pitcher
    actual_ks = None
    for side in ["away", "home"]:
        pitchers = boxscore.get(f"{side}Pitchers", [])
        if pitchers:
            # First pitcher listed is usually the starter
            starter = pitchers[0] if pitchers else {}
            actual_ks = int(starter.get("k", 0))
            break

    if actual_ks is None:
        return None

    line = pred.get("model_value")  # The O/U line
    if pick == "OVER":
        result = "WIN" if actual_ks > line else "LOSS" if actual_ks < line else "PUSH"
    else:
        result = "WIN" if actual_ks < line else "LOSS" if actual_ks > line else "PUSH"

    return {
        "game_pk": game_pk,
        "bet_type": "strikeout",
        "pick": pred["pick"],
        "result": result,
        "actual_outcome": f"{actual_ks} Ks",
        "edge_at_pick": pred["edge"],
        "confidence_at_pick": pred["confidence"],
    }


def _grade_nrfi_pick(game_pk, pred):
    """Grade NRFI pick against first-inning scoring."""
    try:
        linescore = statsapi.linescore(game_pk)
        # Parse first inning runs
        # statsapi.linescore returns formatted string, use API directly
        data = statsapi.get("game_linescore", {"gamePk": game_pk})
        innings = data.get("innings", [])
        if not innings:
            return None

        first = innings[0]
        away_runs = first.get("away", {}).get("runs", 0)
        home_runs = first.get("home", {}).get("runs", 0)
        first_inning_runs = away_runs + home_runs

        actual_nrfi = first_inning_runs == 0
        pick = pred["pick"]  # NRFI or YRFI

        if pick == "NRFI":
            result = "WIN" if actual_nrfi else "LOSS"
        else:
            result = "WIN" if not actual_nrfi else "LOSS"

        return {
            "game_pk": game_pk,
            "bet_type": "nrfi",
            "pick": pred["pick"],
            "result": result,
            "actual_outcome": f"1st inning: {away_runs}-{home_runs} ({'NRFI' if actual_nrfi else 'YRFI'})",
            "edge_at_pick": pred["edge"],
            "confidence_at_pick": pred["confidence"],
        }
    except Exception:
        return None


def _save_result(result):
    conn = get_connection()
    conn.execute("""
        INSERT INTO results (game_pk, bet_type, pick, result, actual_outcome,
            edge_at_pick, confidence_at_pick, graded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (result["game_pk"], result["bet_type"], result["pick"], result["result"],
          result["actual_outcome"], result["edge_at_pick"], result["confidence_at_pick"],
          datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def show_record(days=0):
    """Show season or rolling record."""
    conn = get_connection()
    query = "SELECT bet_type, result, COUNT(*) as cnt FROM results"
    if days > 0:
        query += f" WHERE graded_at >= date('now', '-{days} days')"
    query += " GROUP BY bet_type, result"
    rows = conn.execute(query).fetchall()
    conn.close()

    if not rows:
        print("No graded results yet.")
        return

    totals = {"game": {"WIN": 0, "LOSS": 0, "PUSH": 0},
              "strikeout": {"WIN": 0, "LOSS": 0, "PUSH": 0},
              "nrfi": {"WIN": 0, "LOSS": 0, "PUSH": 0}}

    for row in rows:
        bt = row["bet_type"]
        if bt in totals and row["result"] in totals[bt]:
            totals[bt][row["result"]] = row["cnt"]

    period = f"Last {days} days" if days else "Season"
    print(f"\n{period} Record")
    print("=" * 50)

    overall_w, overall_l = 0, 0
    for bt, label in [("game", "Games"), ("strikeout", "K Props"), ("nrfi", "NRFI")]:
        w, l, p = totals[bt]["WIN"], totals[bt]["LOSS"], totals[bt]["PUSH"]
        total = w + l
        pct = f"{w/(w+l)*100:.1f}%" if total > 0 else "N/A"
        print(f"  {label}: {w}-{l}-{p} ({pct})")
        overall_w += w
        overall_l += l

    total = overall_w + overall_l
    pct = f"{overall_w/total*100:.1f}%" if total > 0 else "N/A"
    print(f"\n  Overall: {overall_w}-{overall_l} ({pct})")


def _print_grade_summary(results, date_str):
    wins = sum(1 for r in results if r["result"] == "WIN")
    losses = sum(1 for r in results if r["result"] == "LOSS")
    pushes = sum(1 for r in results if r["result"] == "PUSH")
    print(f"\nResults for {date_str}: {wins}W - {losses}L - {pushes}P")
    for r in results:
        icon = "✓" if r["result"] == "WIN" else "✗" if r["result"] == "LOSS" else "—"
        print(f"  {icon} {r['bet_type'].upper()}: {r['pick']} → {r['result']} ({r['actual_outcome']})")
```

- [ ] **Step 2: Commit**

```bash
git add modules/output/results_tracker.py
git commit -m "feat: results tracker with game/K/NRFI grading and season record"
```

---

## Task 11: Wire Up main.py Pipeline

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update main.py with full pipeline**

Replace the skeleton `main.py` with the full pipeline that connects all modules: schedule fetch -> odds fetch -> cache refresh -> per-game analysis (game predictor + K predictor + NRFI predictor) -> reporting -> database save. Use `concurrent.futures.ThreadPoolExecutor(max_workers=4)` for parallel per-game analysis. Handle the `--game-only`, `--strikeouts`, `--nrfi`, `--grade-results`, `--record` flags. Wire up all the module imports and call sequences.

The main pipeline loop per game:
1. Fetch pitcher stats for both starters
2. Fetch team batting stats
3. Fetch bullpen data for both teams
4. Get park factors for venue
5. Get umpire data (if available)
6. Get weather for venue
7. Get injuries for both teams
8. Run enabled predictors (game, K, NRFI)
9. Collect predictions

After all games: generate report, save predictions to DB.

- [ ] **Step 2: Test end-to-end with today's date**

```bash
python main.py --date 2026-03-30
```

Verify it fetches schedule, attempts stats, and generates a report (even with missing data it should degrade gracefully).

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: wire up full pipeline in main.py with parallel game analysis"
```

---

## Task 12: Cron Scheduling + Run Script

**Files:**
- Create: `run_daily.sh`
- Create: `setup_cron.sh`

- [ ] **Step 1: Create run_daily.sh**

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
source .env 2>/dev/null || true

LOG_DIR="./logs"
mkdir -p "$LOG_DIR"

DATE=$(date +%Y-%m-%d)
echo "[$DATE] Starting MLB Bot daily run..."

python main.py 2>&1 | tee "$LOG_DIR/daily_${DATE}.log"

echo "[$DATE] Done."
```

- [ ] **Step 2: Create setup_cron.sh**

```bash
#!/bin/bash
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up MLB Bot cron jobs..."
echo "Bot directory: $BOT_DIR"

# Morning analysis at 10 AM ET (14:00 UTC)
CRON_RUN="0 14 * * * cd $BOT_DIR && bash run_daily.sh >> $BOT_DIR/logs/cron.log 2>&1"

# Grade results at midnight ET (04:00 UTC)
CRON_GRADE="0 4 * * * cd $BOT_DIR && python main.py --grade-results >> $BOT_DIR/logs/grade.log 2>&1"

(crontab -l 2>/dev/null | grep -v "mlb-bot"; echo "$CRON_RUN"; echo "$CRON_GRADE") | crontab -

echo "Cron jobs installed:"
echo "  10:00 AM ET — Daily analysis"
echo "  12:00 AM ET — Grade results"
echo ""
echo "View with: crontab -l"
```

- [ ] **Step 3: Make scripts executable**

```bash
chmod +x run_daily.sh setup_cron.sh
```

- [ ] **Step 4: Commit**

```bash
git add run_daily.sh setup_cron.sh
git commit -m "feat: cron scheduling with daily run and results grading"
```

---

## Task 13: Integration Test — Full Pipeline

- [ ] **Step 1: Run the bot for today**

```bash
python main.py
```

Verify:
- Schedule fetches games
- Stats are loaded from pybaseball caches
- Predictions are generated for each game
- Report is printed and saved to `reports/`
- Predictions are saved to `data/mlb.db`

- [ ] **Step 2: Test specific date**

```bash
python main.py --date 2026-03-30
```

- [ ] **Step 3: Test individual bet types**

```bash
python main.py --nrfi
python main.py --strikeouts
python main.py --game-only
```

- [ ] **Step 4: Test grade-results (will be empty until games complete)**

```bash
python main.py --grade-results
python main.py --record
```

- [ ] **Step 5: Fix any issues found during integration testing**

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "fix: integration test fixes and polish"
```
