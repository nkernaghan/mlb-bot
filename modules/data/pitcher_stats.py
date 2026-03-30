import statsapi
from modules.data.cache import get_pitcher_fg, get_pitcher_savant
from modules.database import get_connection
from config import SEASON_YEAR
from datetime import date


def _parse_innings(ip_str):
    """Parse MLB API innings pitched format. '5.1' = 5⅓, '5.2' = 5⅔."""
    try:
        if "." in str(ip_str):
            whole, frac = str(ip_str).split(".")
            return int(whole) + int(frac) / 3
        return float(ip_str)
    except (ValueError, TypeError):
        return 0


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
            stats["innings_pitched"] = _parse_innings(s.get("inningsPitched", "0"))
            stats["games_started"] = int(s.get("gamesStarted", 0))
            total_ks = int(s.get("strikeOuts", 0))
            batters_faced = int(s.get("battersFaced", 1))
            stats["k_rate"] = round(total_ks / batters_faced * 100, 1) if batters_faced else 0
            stats["bb_rate"] = round(int(s.get("baseOnBalls", 0)) / batters_faced * 100, 1) if batters_faced else 0
    except Exception as e:
        print(f"    WARNING: MLB API stats failed for {player_name}: {e}")

    # FanGraphs — FIP, xFIP, SIERA, SwStr%, ERA fallback
    fg = get_pitcher_fg(player_name, team)
    if fg:
        stats["fip"] = fg.get("FIP")
        stats["xfip"] = fg.get("xFIP")
        stats["siera"] = fg.get("SIERA")
        # FanGraphs stores percentages as decimals (0.114 = 11.4%)
        swstr = fg.get("SwStr%")
        stats["swstr"] = round(swstr * 100, 1) if swstr and swstr < 1 else swstr
        fstrike = fg.get("F-Strike%")
        stats["f_strike_pct"] = round(fstrike * 100, 1) if fstrike and fstrike < 1 else fstrike
        csw = fg.get("CSW%")
        stats["csw"] = round(csw * 100, 1) if csw and csw < 1 else csw
        # Fill ERA/K-rate/IP from FG if MLB API had no data
        if not stats.get("era"):
            stats["era"] = fg.get("ERA")
        if not stats.get("k_per_9"):
            stats["k_per_9"] = fg.get("K/9")
        if not stats.get("whip"):
            stats["whip"] = fg.get("WHIP")
        if not stats.get("innings_pitched"):
            stats["innings_pitched"] = fg.get("IP")
        if not stats.get("games_started"):
            stats["games_started"] = fg.get("GS")
        # K rate from FG
        fg_k_rate = fg.get("K%")
        if fg_k_rate is not None:
            stats["k_rate"] = round(fg_k_rate * 100, 1) if fg_k_rate < 1 else fg_k_rate
        fg_bb_rate = fg.get("BB%")
        if fg_bb_rate is not None and not stats.get("bb_rate"):
            stats["bb_rate"] = round(fg_bb_rate * 100, 1) if fg_bb_rate < 1 else fg_bb_rate

    # Baseball Savant — xERA, barrel rate, expected stats
    savant = get_pitcher_savant(player_id)
    if savant:
        stats["xera"] = savant.get("xera")
        stats["barrel_rate_against"] = savant.get("barrel_batted_rate")
        if not stats.get("k_rate"):
            k_pct = savant.get("k_percent")
            if k_pct is not None:
                stats["k_rate"] = round(k_pct * 100, 1) if k_pct < 1 else k_pct

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
                recent_ip = sum(_parse_innings(g.get("inningsPitched", "0")) for g in recent_starts)
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
