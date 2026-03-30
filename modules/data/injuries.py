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
