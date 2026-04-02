import statsapi
import requests
import pandas as pd
from modules.data.cache import get_pitcher_fg, get_pitcher_savant, get_pitcher_savant_pitch
from modules.database import get_connection
from config import SEASON_YEAR, LEAGUE_AVG_FIP
from datetime import date


# FIP constant: league-average ERA minus league-average FIP components.
# Typical range 3.10-3.20. Updated each season alongside LEAGUE_AVG_FIP.
_FIP_CONSTANT = 3.15


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

    # MLB Stats API — season stats + pitcher handedness
    try:
        mlb_stats = statsapi.player_stat_data(player_id, group="pitching", type="season")
        if mlb_stats:
            # Get throwing hand from player info
            pitch_hand = mlb_stats.get("pitch_hand")
            if pitch_hand:
                stats["throws"] = pitch_hand
            if mlb_stats.get("stats"):
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
                # Store counting stats for FIP calculation
                stats["_hr"] = int(s.get("homeRuns", 0))
                stats["_bb"] = int(s.get("baseOnBalls", 0))
                stats["_hbp"] = int(s.get("hitBatsmen", 0))
                stats["_so"] = total_ks
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

    # Savant pitch-level stats — SwStr%, F-Strike%, CSW%, K%, BB%
    # Used as fallback when FanGraphs is unavailable (403 blocked)
    savant_pitch = get_pitcher_savant_pitch(player_id)
    if savant_pitch:
        if not stats.get("swstr"):
            whiff = savant_pitch.get("whiff_percent")
            if whiff is not None:
                stats["swstr"] = round(float(whiff), 1)
        if not stats.get("f_strike_pct"):
            fstrike = savant_pitch.get("f_strike_percent")
            if fstrike is not None:
                stats["f_strike_pct"] = round(float(fstrike), 1)
        if not stats.get("csw"):
            csw_val = savant_pitch.get("csw_rate")
            if csw_val is not None and not pd.isna(csw_val):
                stats["csw"] = round(float(csw_val), 1)
        if not stats.get("k_rate"):
            k_pct = savant_pitch.get("k_percent")
            if k_pct is not None:
                stats["k_rate"] = round(float(k_pct), 1)
        if not stats.get("bb_rate"):
            bb_pct = savant_pitch.get("bb_percent")
            if bb_pct is not None:
                stats["bb_rate"] = round(float(bb_pct), 1)

    # Calculate FIP from MLB API data when FanGraphs is unavailable.
    # Require minimum 10 IP — below that, FIP is pure noise (a single HR
    # swings FIP by ~3 points over 4 IP).
    ip = stats.get("innings_pitched") or 0
    if not stats.get("fip") and ip >= 10:
        stats["fip"] = _calc_fip(stats)

    # Use xERA as xFIP proxy when FanGraphs xFIP is unavailable
    if not stats.get("xfip") and stats.get("xera"):
        stats["xfip"] = stats["xera"]

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

    # MLB API — first-inning splits (sitCodes=i01) for NRFI model
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "statSplits", "group": "pitching", "season": SEASON_YEAR, "sitCodes": "i01"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            for stat_group in data.get("stats", []):
                for split in stat_group.get("splits", []):
                    st = split.get("stat", {})
                    ip_1st = _parse_innings(st.get("inningsPitched", "0"))
                    er_1st = int(st.get("earnedRuns", 0))
                    runs_1st = int(st.get("runs", 0))
                    if ip_1st > 0:
                        stats["first_inning_era"] = round(er_1st / ip_1st * 9, 2)
                        # NRFI rate: percentage of first innings with 0 runs allowed
                        # Total 1st innings ≈ IP (since each is 1 inning max)
                        total_1st_innings = round(ip_1st)  # Each clean 1st = 1.0 IP
                        scoreless_1st = total_1st_innings - runs_1st  # Approximate
                        if total_1st_innings > 0:
                            stats["nrfi_rate"] = round(max(0, scoreless_1st) / total_1st_innings * 100, 1)
    except Exception:
        pass

    return stats


def _calc_fip(stats):
    """Calculate FIP from MLB API counting stats: (13*HR + 3*(BB+HBP) - 2*K) / IP + constant."""
    ip = stats.get("innings_pitched", 0)
    if not ip or ip <= 0:
        return None
    hr = stats.get("_hr", 0)
    bb = stats.get("_bb", 0)
    hbp = stats.get("_hbp", 0)
    so = stats.get("_so", 0)
    fip = (13 * hr + 3 * (bb + hbp) - 2 * so) / ip + _FIP_CONSTANT
    return round(fip, 2)


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
