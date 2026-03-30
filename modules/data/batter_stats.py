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
    """Fetch aggregate team batting stats for current + previous season."""
    result = {}

    for year in [SEASON_YEAR, SEASON_YEAR - 1]:
        try:
            data = statsapi.get("team_stats", {
                "teamId": team_id, "stats": "season", "group": "hitting", "season": year,
            })
            if data and data.get("stats"):
                splits = data["stats"][0].get("splits", [])
                if splits:
                    s = splits[0].get("stat", {})
                    pa = int(s.get("plateAppearances", 0))
                    if pa >= 50:
                        stats = {
                            "team_ops": float(s.get("ops", 0)),
                            "team_k_rate": round(int(s.get("strikeOuts", 0)) / pa * 100, 1),
                            "team_bb_rate": round(int(s.get("baseOnBalls", 0)) / pa * 100, 1),
                        }
                        if not result:
                            result = stats
                        else:
                            # Blend: current year weighted more if enough PA
                            cur_pa = result.get("_pa", 0)
                            if cur_pa < 500:
                                w = max(0.5, cur_pa / 500)
                                for k in ["team_ops", "team_k_rate", "team_bb_rate"]:
                                    if result.get(k) and stats.get(k):
                                        result[k] = round(result[k] * w + stats[k] * (1 - w), 3)
                        result["_pa"] = pa
                        if year == SEASON_YEAR and pa >= 500:
                            break  # Enough current year data, skip previous
        except Exception:
            pass

    result.pop("_pa", None)
    return result
