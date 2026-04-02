import pandas as pd
import requests as _requests
import io
from datetime import datetime, date
from pybaseball import pitching_stats, batting_stats
from pybaseball import statcast_pitcher_expected_stats
from modules.database import get_connection
from config import SEASON_YEAR


_pitcher_fg_cache = None
_pitcher_savant_cache = None
_pitcher_savant_pitch_cache = None   # Savant custom leaderboard: SwStr%, F-Strike%, CSW%, K%, BB%
_batter_fg_cache = None
_batter_savant_cache = None
_cache_date = None


def _fetch_with_fallback(fetch_fn, label, current_year, qual=1, minPA=50, use_qual=True):
    """Fetch current season and merge with previous season for full coverage."""
    current_df = pd.DataFrame()
    prev_df = pd.DataFrame()

    # Current season
    try:
        if use_qual:
            current_df = fetch_fn(current_year, qual=qual)
        else:
            current_df = fetch_fn(current_year, minPA=minPA)
        print(f"  {current_year} {label}: {len(current_df)} entries")
    except Exception:
        print(f"  {current_year} {label}: no data available")

    # Previous season — always fetch for full coverage early in the year
    prev_year = current_year - 1
    try:
        if use_qual:
            prev_df = fetch_fn(prev_year, qual=qual)
        else:
            prev_df = fetch_fn(prev_year, minPA=minPA)
        print(f"  {prev_year} {label}: {len(prev_df)} entries")
    except Exception:
        print(f"  {prev_year} {label}: no data available")

    # Merge: keep BOTH years for all players so we can blend at lookup time
    if not current_df.empty and not prev_df.empty:
        current_df = current_df.copy()
        prev_df = prev_df.copy()
        current_df["_source_year"] = current_year
        prev_df["_source_year"] = prev_year
        merged = pd.concat([current_df, prev_df], ignore_index=True)
        merged = _clean_names(merged)
        return merged, f"{current_year}+{prev_year}"
    elif not current_df.empty:
        current_df = current_df.copy()
        current_df["_source_year"] = current_year
        return _clean_names(current_df), current_year
    elif not prev_df.empty:
        prev_df = prev_df.copy()
        prev_df["_source_year"] = prev_year
        return _clean_names(prev_df), prev_year
    else:
        return pd.DataFrame(), None


def _clean_names(df):
    """Strip stray quotes from FanGraphs name columns."""
    if "Name" in df.columns:
        df = df.copy()
        df["Name"] = df["Name"].str.strip("'\"")
    return df


# IP threshold: below this, blend in previous year's stats
_BLEND_IP_THRESHOLD = 40


def _blend_fg_rows(rows):
    """Blend multiple years of FanGraphs data weighted by IP.

    If current year has < threshold IP, weight previous year's stats in.
    Current year always gets at least 50% weight when it exists.
    """
    if len(rows) == 1:
        return rows.iloc[0].to_dict()

    current_year = SEASON_YEAR
    current = rows[rows["_source_year"] == current_year]
    prev = rows[rows["_source_year"] != current_year]

    if current.empty:
        return prev.iloc[0].to_dict()
    if prev.empty:
        return current.iloc[0].to_dict()

    cur = current.iloc[0]
    prv = prev.iloc[0]

    cur_ip = float(cur.get("IP", 0) or 0)
    prv_ip = float(prv.get("IP", 0) or 0)

    if cur_ip >= _BLEND_IP_THRESHOLD or prv_ip == 0:
        return cur.to_dict()

    # Weight: current year gets 50-100% based on IP, previous fills the rest
    cur_weight = max(0.50, min(1.0, cur_ip / _BLEND_IP_THRESHOLD))
    prv_weight = 1.0 - cur_weight

    result = cur.to_dict()
    # Blend rate stats (not counting stats)
    blend_cols = ["ERA", "FIP", "xFIP", "SIERA", "K/9", "BB/9", "WHIP",
                  "K%", "BB%", "SwStr%", "F-Strike%", "CSW%",
                  "wRC+", "OPS", "Barrel%"]
    for col in blend_cols:
        cur_val = cur.get(col)
        prv_val = prv.get(col)
        # Treat NaN as missing
        cur_ok = cur_val is not None and not (isinstance(cur_val, float) and pd.isna(cur_val))
        prv_ok = prv_val is not None and not (isinstance(prv_val, float) and pd.isna(prv_val))
        if cur_ok and prv_ok:
            try:
                result[col] = float(cur_val) * cur_weight + float(prv_val) * prv_weight
            except (ValueError, TypeError):
                pass
        elif prv_ok and not cur_ok:
            result[col] = prv_val

    return result


def _blend_savant_rows(rows):
    """Blend multiple years of Savant data weighted by PA/batters faced."""
    if len(rows) == 1:
        return rows.iloc[0].to_dict()

    current_year = SEASON_YEAR
    current = rows[rows["_source_year"] == current_year]
    prev = rows[rows["_source_year"] != current_year]

    if current.empty:
        return prev.iloc[0].to_dict()
    if prev.empty:
        return current.iloc[0].to_dict()

    cur = current.iloc[0]
    prv = prev.iloc[0]

    cur_pa = float(cur.get("pa", 0) or cur.get("bip", 0) or 0)
    prv_pa = float(prv.get("pa", 0) or prv.get("bip", 0) or 0)

    # When PA data is missing (e.g. Savant custom leaderboard), use early-season
    # default weighting: 50% current, 50% prior.  This is better than returning
    # only the current-year small sample.
    no_pa_data = cur_pa == 0 and prv_pa == 0
    if not no_pa_data:
        if cur_pa >= 150 or prv_pa == 0:
            return cur.to_dict()
        cur_weight = max(0.50, min(1.0, cur_pa / 150))
    else:
        cur_weight = 0.50
    prv_weight = 1.0 - cur_weight

    result = cur.to_dict()
    blend_cols = ["xera", "xba", "xslg", "xwoba", "xobp", "xiso",
                  "barrel_batted_rate", "k_percent", "bb_percent",
                  "whiff_percent", "f_strike_percent", "csw_rate"]
    for col in blend_cols:
        cur_val = cur.get(col)
        prv_val = prv.get(col)
        # Treat NaN as missing
        cur_ok = cur_val is not None and not (isinstance(cur_val, float) and pd.isna(cur_val))
        prv_ok = prv_val is not None and not (isinstance(prv_val, float) and pd.isna(prv_val))
        if cur_ok and prv_ok:
            try:
                result[col] = float(cur_val) * cur_weight + float(prv_val) * prv_weight
            except (ValueError, TypeError):
                pass
        elif prv_ok and not cur_ok:
            result[col] = prv_val

    return result


def _fetch_savant_custom(year, player_type="pitcher", min_pa=1):
    """Fetch Savant custom leaderboard with pitch-level stats (SwStr%, F-Strike%, CSW%, K%, BB%)."""
    selections = "k_percent,bb_percent,whiff_percent,f_strike_percent,csw_rate"
    r = _requests.get(
        "https://baseballsavant.mlb.com/leaderboard/custom",
        params={
            "year": year, "type": player_type, "min": min_pa,
            "selections": selections,
            "chart": "false", "csv": "true",
        },
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        timeout=20,
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    return df


def _fetch_savant_custom_with_fallback(label, year, player_type="pitcher", min_pa=1):
    """Fetch current + previous year Savant custom leaderboard."""
    current_df = pd.DataFrame()
    prev_df = pd.DataFrame()

    try:
        current_df = _fetch_savant_custom(year, player_type, min_pa)
        print(f"  {year} {label}: {len(current_df)} entries")
    except Exception:
        print(f"  {year} {label}: no data available")

    prev_year = year - 1
    try:
        prev_df = _fetch_savant_custom(prev_year, player_type, min_pa)
        print(f"  {prev_year} {label}: {len(prev_df)} entries")
    except Exception:
        print(f"  {prev_year} {label}: no data available")

    if not current_df.empty and not prev_df.empty:
        current_df = current_df.copy()
        prev_df = prev_df.copy()
        current_df["_source_year"] = year
        prev_df["_source_year"] = prev_year
        merged = pd.concat([current_df, prev_df], ignore_index=True)
        return merged, f"{year}+{prev_year}"
    elif not current_df.empty:
        current_df = current_df.copy()
        current_df["_source_year"] = year
        return current_df, year
    elif not prev_df.empty:
        prev_df = prev_df.copy()
        prev_df["_source_year"] = prev_year
        return prev_df, prev_year
    return pd.DataFrame(), None


def refresh_daily_caches(target_date=None, force=False):
    """Fetch FanGraphs and Savant leaderboards once per day."""
    global _pitcher_fg_cache, _pitcher_savant_cache, _pitcher_savant_pitch_cache
    global _batter_fg_cache, _batter_savant_cache, _cache_date

    today = target_date or date.today().isoformat()
    if _cache_date == today and not force:
        return

    print("  Fetching FanGraphs pitcher leaderboard...")
    _pitcher_fg_cache, yr = _fetch_with_fallback(pitching_stats, "FG pitchers", SEASON_YEAR, qual=1)
    if yr:
        print(f"  Using {yr} FanGraphs pitcher data ({len(_pitcher_fg_cache)} pitchers)")

    print("  Fetching Savant expected stats (pitchers)...")
    _pitcher_savant_cache, yr = _fetch_with_fallback(
        statcast_pitcher_expected_stats, "Savant pitchers", SEASON_YEAR, minPA=50, use_qual=False)
    if yr:
        print(f"  Using {yr} Savant pitcher data ({len(_pitcher_savant_cache)} pitchers)")

    print("  Fetching Savant pitch-level stats (SwStr%, F-Strike%, CSW%)...")
    _pitcher_savant_pitch_cache, yr = _fetch_savant_custom_with_fallback(
        "Savant pitch stats", SEASON_YEAR, "pitcher", min_pa=1)
    if yr:
        print(f"  Using {yr} Savant pitch data ({len(_pitcher_savant_pitch_cache)} pitchers)")

    print("  Fetching FanGraphs batter leaderboard...")
    _batter_fg_cache, yr = _fetch_with_fallback(batting_stats, "FG batters", SEASON_YEAR, qual=1)
    if yr:
        print(f"  Using {yr} FanGraphs batter data ({len(_batter_fg_cache)} batters)")

    print("  Fetching Savant expected stats (batters)...")
    try:
        from pybaseball import statcast_batter_expected_stats
        _batter_savant_cache, yr = _fetch_with_fallback(
            statcast_batter_expected_stats, "Savant batters", SEASON_YEAR, minPA=50, use_qual=False)
        if yr:
            print(f"  Using {yr} Savant batter data ({len(_batter_savant_cache)} batters)")
    except Exception as e:
        print(f"  WARNING: Savant batter fetch failed: {e}")
        _batter_savant_cache = pd.DataFrame()

    _cache_date = today


def _name_match(df, name):
    """Try exact match, then last name match, stripping suffixes like Jr./Sr./III."""
    # Exact substring match first
    matches = df[df["Name"].str.contains(name, case=False, na=False)]
    if not matches.empty:
        return matches

    # Strip suffixes and try again
    clean = name.replace(" Jr.", "").replace(" Sr.", "").replace(" III", "").replace(" II", "").strip()
    if clean != name:
        matches = df[df["Name"].str.contains(clean, case=False, na=False)]
        if not matches.empty:
            return matches

    # Last name only (for cases like first-name mismatches)
    parts = name.split()
    if len(parts) >= 2:
        last = parts[-1].replace("Jr.", "").replace("Sr.", "").strip()
        if last:
            matches = df[df["Name"].str.contains(last, case=False, na=False)]
            if len(matches) == 1:  # Only use if unambiguous
                return matches

    return pd.DataFrame()


_TEAM_ABBREVS = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CHW",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KCR",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SDP", "San Francisco Giants": "SFG",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TBR",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSN",
}


def _team_match(df, team):
    """Match team name against FanGraphs abbreviations or full names."""
    if "Team" not in df.columns:
        return df
    # Try direct contains first (works if team is already an abbreviation)
    matches = df[df["Team"].str.contains(team, case=False, na=False)]
    if not matches.empty:
        return matches
    # Map full name to abbreviation
    abbrev = _TEAM_ABBREVS.get(team)
    if abbrev:
        matches = df[df["Team"].str.contains(abbrev, case=False, na=False)]
        if not matches.empty:
            return matches
    # Try matching the city/nickname portion
    for part in team.split():
        if len(part) > 3:
            matches = df[df["Team"].str.contains(part, case=False, na=False)]
            if not matches.empty:
                return matches
    return pd.DataFrame()


def get_pitcher_fg(name=None, team=None):
    """Lookup a pitcher in the FanGraphs cache by name and/or team, blending years by IP."""
    if _pitcher_fg_cache is None or _pitcher_fg_cache.empty:
        return None
    df = _pitcher_fg_cache
    if name:
        df = _name_match(df, name)
    if team and not df.empty:
        filtered = _team_match(df, team)
        if not filtered.empty:
            df = filtered
    if df.empty:
        return None
    return _blend_fg_rows(df)


def get_pitcher_savant(player_id):
    """Lookup a pitcher in the Savant cache by MLB player ID, blending years."""
    if _pitcher_savant_cache is None or _pitcher_savant_cache.empty:
        return None
    df = _pitcher_savant_cache
    matches = df[df["player_id"] == player_id]
    if matches.empty:
        return None
    return _blend_savant_rows(matches)


def get_pitcher_savant_pitch(player_id):
    """Lookup a pitcher in the Savant pitch-level cache (SwStr%, F-Strike%, CSW%, K%, BB%)."""
    if _pitcher_savant_pitch_cache is None or _pitcher_savant_pitch_cache.empty:
        return None
    df = _pitcher_savant_pitch_cache
    matches = df[df["player_id"] == player_id]
    if matches.empty:
        return None
    return _blend_savant_rows(matches)


def get_batter_fg(name=None, team=None):
    """Lookup a batter in the FanGraphs cache, blending years by IP."""
    if _batter_fg_cache is None or _batter_fg_cache.empty:
        return None
    df = _batter_fg_cache
    if name:
        df = _name_match(df, name)
    if team and not df.empty:
        filtered = _team_match(df, team)
        if not filtered.empty:
            df = filtered
    if df.empty:
        return None
    return _blend_fg_rows(df)


def get_batter_savant(player_id):
    """Lookup a batter in the Savant cache by MLB player ID, blending years."""
    if _batter_savant_cache is None or _batter_savant_cache.empty:
        return None
    df = _batter_savant_cache
    matches = df[df["player_id"] == player_id]
    if matches.empty:
        return None
    return _blend_savant_rows(matches)
