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


def fetch_bullpen_usage(team_id, days=3):
    """Fetch recent bullpen usage over the last N days.

    Args:
        team_id: MLB team ID.
        days: Number of days to look back for usage data.

    Returns:
        List of dicts with pitcher_id, name, pitches_thrown, innings_pitched,
        days_rest, era, and fip for each relief pitcher with recent appearances.
    """
    from datetime import datetime, timedelta
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    end_str = end_dt.strftime("%Y-%m-%d")
    start_str = start_dt.strftime("%Y-%m-%d")

    usage = []
    try:
        # Fetch recent game logs for the team to find reliever appearances
        schedule = statsapi.schedule(
            start_date=start_str,
            end_date=end_str,
            team=team_id,
        )
        game_pks = [g["game_id"] for g in schedule if g.get("status") == "Final"]

        # Collect pitcher appearances across recent games
        pitcher_appearances: dict[int, dict] = {}
        for game_pk in game_pks:
            try:
                boxscore = statsapi.boxscore_data(game_pk)
                # Determine which side is our team
                for side in ("away", "home"):
                    team_info = boxscore.get(side, {})
                    team_data = boxscore.get(f"{side}TeamStats", {})
                    players = boxscore.get(f"{side}Pitchers", [])
                    if not players:
                        continue
                    # Check if this side matches our team
                    side_team_id = (
                        boxscore.get("away_id") if side == "away" else boxscore.get("home_id")
                    )
                    if side_team_id != team_id:
                        continue
                    # Skip the first pitcher (starter) — keep relievers
                    for pitcher in players[1:]:
                        pid = pitcher.get("personId")
                        if not pid:
                            continue
                        ip_str = pitcher.get("ip", "0.0")
                        try:
                            ip = float(ip_str)
                        except (ValueError, TypeError):
                            ip = 0.0
                        pitches = pitcher.get("p", 0) or 0
                        if pid not in pitcher_appearances:
                            pitcher_appearances[pid] = {
                                "pitcher_id": pid,
                                "name": pitcher.get("name", ""),
                                "pitches_thrown": 0,
                                "innings_pitched": 0.0,
                                "last_appearance_date": None,
                            }
                        pitcher_appearances[pid]["pitches_thrown"] += int(pitches)
                        pitcher_appearances[pid]["innings_pitched"] += ip
                        # Track most recent appearance for days_rest calc
                        game_date = next(
                            (g["game_date"] for g in schedule if g["game_id"] == game_pk), None
                        )
                        if game_date:
                            existing = pitcher_appearances[pid]["last_appearance_date"]
                            if existing is None or game_date > existing:
                                pitcher_appearances[pid]["last_appearance_date"] = game_date
            except Exception:
                continue

        # Enrich with season ERA/FIP from MLB API
        today_str = end_dt.strftime("%Y-%m-%d")
        for pid, entry in pitcher_appearances.items():
            days_rest = None
            if entry["last_appearance_date"]:
                try:
                    last = datetime.strptime(entry["last_appearance_date"], "%Y-%m-%d")
                    days_rest = (end_dt - last).days
                except Exception:
                    days_rest = None

            era = 0.0
            fip = 0.0
            try:
                pstats = statsapi.player_stat_data(pid, group="pitching", type="season")
                if pstats and pstats.get("stats"):
                    s = pstats["stats"][0].get("stats", {})
                    era = float(s.get("era", 0))
                    # FIP not in MLB API; default to ERA as proxy
                    fip = era
            except Exception:
                pass

            usage.append({
                "pitcher_id": pid,
                "name": entry["name"],
                "pitches_thrown": entry["pitches_thrown"],
                "innings_pitched": round(entry["innings_pitched"], 1),
                "days_rest": days_rest,
                "era": era,
                "fip": fip,
            })

    except Exception:
        return []

    return usage


def save_bullpen_usage(team_id, usage_list):
    """Persist bullpen usage records to the database.

    Args:
        team_id: MLB team ID the usage belongs to.
        usage_list: List of dicts as returned by fetch_bullpen_usage.
    """
    conn = get_connection()
    today = date.today().isoformat()
    for entry in usage_list:
        conn.execute("""
            INSERT OR REPLACE INTO bullpen_usage
            (team_id, pitcher_id, pitcher_name, fetch_date, pitches_thrown,
             innings_pitched, days_rest, era, fip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            team_id,
            entry["pitcher_id"],
            entry["name"],
            today,
            entry["pitches_thrown"],
            entry["innings_pitched"],
            entry["days_rest"],
            entry["era"],
            entry["fip"],
        ))
    conn.commit()
    conn.close()


def calc_bullpen_aggregate(relievers):
    """Calculate aggregate bullpen metrics.

    Args:
        relievers: List of reliever dicts as returned by fetch_bullpen_status.

    Returns:
        Dict with bullpen_era, bullpen_k_per_9, bullpen_whip, and reliever_count.
    """
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
