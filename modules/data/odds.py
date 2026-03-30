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


def fetch_event_props(event_id, markets="pitcher_strikeouts,totals_1st_1_innings"):
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
        if market["key"] in ("1st_1_innings", "totals_1st_1_innings"):
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
