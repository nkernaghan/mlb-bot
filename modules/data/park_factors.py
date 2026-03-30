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

# FanGraphs team abbreviation → common venue name fragments for matching
_FG_TEAM_TO_VENUE = {
    "ARI": "Chase Field", "ATL": "Truist Park", "BAL": "Oriole Park",
    "BOS": "Fenway Park", "CHC": "Wrigley Field", "CHW": "Guaranteed Rate",
    "CIN": "Great American", "CLE": "Progressive Field", "COL": "Coors Field",
    "DET": "Comerica Park", "HOU": "Minute Maid", "KCR": "Kauffman Stadium",
    "LAA": "Angel Stadium", "LAD": "Dodger Stadium", "MIA": "loanDepot",
    "MIL": "American Family", "MIN": "Target Field", "NYM": "Citi Field",
    "NYY": "Yankee Stadium", "OAK": "Oakland", "PHI": "Citizens Bank",
    "PIT": "PNC Park", "SDP": "Petco Park", "SFG": "Oracle Park",
    "SEA": "T-Mobile Park", "STL": "Busch Stadium", "TBR": "Tropicana",
    "TEX": "Globe Life", "TOR": "Rogers Centre", "WSN": "Nationals Park",
}

# In-memory park factors cache (loaded once per run)
_park_factors_cache = {}  # venue_name_fragment -> {run_factor, hr_factor, k_factor, bb_factor}


def fetch_park_factors():
    """Fetch park factors from FanGraphs guts page."""
    url = "https://www.fangraphs.com/guts.aspx?type=pf&teamid=0&season=" + str(SEASON_YEAR)
    try:
        resp = requests.get(url, headers={"User-Agent": "MLBBot/1.0"}, timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"class": "rgMasterTable"})
        if not table:
            # Try previous season as fallback
            url_prev = "https://www.fangraphs.com/guts.aspx?type=pf&teamid=0&season=" + str(SEASON_YEAR - 1)
            resp = requests.get(url_prev, headers={"User-Agent": "MLBBot/1.0"}, timeout=30)
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


def load_park_factors():
    """Fetch park factors and populate the in-memory cache. Call once per run."""
    global _park_factors_cache
    factors = fetch_park_factors()
    for f in factors:
        team_abbr = f["team"].strip()
        venue_frag = _FG_TEAM_TO_VENUE.get(team_abbr)
        if venue_frag:
            _park_factors_cache[venue_frag.lower()] = {
                "run_factor": f["run_factor"],
                "hr_factor": f["hr_factor"],
                "k_factor": f["k_factor"],
                "bb_factor": f["bb_factor"],
            }
    print(f"  Park factors loaded for {len(_park_factors_cache)} venues")
    return _park_factors_cache


def get_park_factor(venue_name):
    """Look up park factors for a venue. Returns dict with run_factor, k_factor, etc."""
    if not venue_name or not _park_factors_cache:
        return {"run_factor": 100, "hr_factor": 100, "k_factor": 100, "bb_factor": 100}
    venue_lower = venue_name.lower()
    for frag, factors in _park_factors_cache.items():
        if frag in venue_lower:
            return factors
    return {"run_factor": 100, "hr_factor": 100, "k_factor": 100, "bb_factor": 100}


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
