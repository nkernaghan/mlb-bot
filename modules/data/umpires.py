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


def get_umpire_from_feed(game_pk):
    """Get home plate umpire name from the live game feed (works for scheduled games too)."""
    import statsapi
    try:
        data = statsapi.get("game", {"gamePk": game_pk})
        officials = data.get("liveData", {}).get("boxscore", {}).get("officials", [])
        for official in officials:
            if official.get("officialType") == "Home Plate":
                person = official.get("official", {})
                return person.get("fullName")
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
