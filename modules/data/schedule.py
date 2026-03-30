import statsapi
from datetime import datetime
from modules.database import get_connection


# Cache for player ID lookups
_player_id_cache = {}


def lookup_player_id(player_name):
    """Look up a player's MLB ID by name using the Stats API."""
    if not player_name:
        return None
    if player_name in _player_id_cache:
        return _player_id_cache[player_name]
    try:
        results = statsapi.lookup_player(player_name)
        if results:
            pid = results[0]["id"]
            _player_id_cache[player_name] = pid
            return pid
    except Exception:
        pass
    return None


def fetch_games(date_str):
    """Fetch today's MLB games from the Stats API with hydrated data."""
    raw = statsapi.schedule(
        date=date_str,
        sportId=1,
    )
    games = []
    # statsapi.schedule() may return a flat list (already parsed) or a raw
    # {"dates": [...]} dict from the underlying API. Handle both shapes.
    if isinstance(raw, dict):
        date_entries = raw.get("dates", [])
        for date_entry in date_entries:
            for game_data in date_entry.get("games", []):
                game = parse_game(game_data)
                if game:
                    games.append(game)
    else:
        for game_data in raw:
            game = parse_schedule_entry(game_data)
            if game:
                games.append(game)

    # Resolve missing pitcher IDs by name lookup
    for game in games:
        if game.get("home_pitcher_name") and not game.get("home_pitcher_id"):
            game["home_pitcher_id"] = lookup_player_id(game["home_pitcher_name"])
        if game.get("away_pitcher_name") and not game.get("away_pitcher_id"):
            game["away_pitcher_id"] = lookup_player_id(game["away_pitcher_name"])

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
