"""Export MLB bot data to static JSON files for GitHub Pages deployment."""
import sqlite3
import json
import os
from datetime import datetime, timedelta

SITE_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "data")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mlb.db")


def export_all():
    """Export games, predictions, odds, and results to JSON."""
    os.makedirs(SITE_DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Export games (last 7 days + next 3 days)
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

    games = [dict(r) for r in conn.execute(
        "SELECT * FROM games WHERE game_date >= ? AND game_date <= ?",
        (week_ago, future)
    ).fetchall()]

    # Export predictions for those games
    game_pks = [g["game_pk"] for g in games]
    predictions = []
    if game_pks:
        placeholders = ",".join("?" * len(game_pks))
        predictions = [dict(r) for r in conn.execute(
            f"SELECT * FROM predictions WHERE game_pk IN ({placeholders})", game_pks
        ).fetchall()]

    # Export odds for those games
    odds = []
    if game_pks:
        odds = [dict(r) for r in conn.execute(
            f"SELECT * FROM odds WHERE game_pk IN ({placeholders})", game_pks
        ).fetchall()]

    # Export ALL results (full season for P&L)
    results_raw = [dict(r) for r in conn.execute("SELECT * FROM results").fetchall()]

    # Calculate units and P&L for each result
    results = []
    for r in results_raw:
        conf = r.get("confidence_at_pick") or 0
        edge = r.get("edge_at_pick") or 0

        # Use grade stored directly on the result (most reliable)
        # Falls back to recalculating from confidence/edge if not stored
        grade = r.get("grade") or ""
        if not grade:
            from modules.models.confidence import grade_pick
            grade = grade_pick(conf, edge, r.get("bet_type") or "game")

        # Get moneyline for game bets to determine underdog sizing
        pick_ml = None
        if r.get("bet_type") == "game":
            odds_row = conn.execute(
                "SELECT home_ml, away_ml FROM odds WHERE game_pk=? LIMIT 1",
                (r["game_pk"],)
            ).fetchone()
            if odds_row:
                game_row2 = conn.execute(
                    "SELECT home_team_name, away_team_name FROM games WHERE game_pk=? LIMIT 1",
                    (r["game_pk"],)
                ).fetchone()
                if game_row2:
                    pick_lower = (r.get("pick") or "").lower()
                    home_lower = (game_row2["home_team_name"] or "").lower()
                    away_lower = (game_row2["away_team_name"] or "").lower()
                    if pick_lower and (pick_lower in home_lower or home_lower in pick_lower):
                        pick_ml = odds_row["home_ml"]
                    elif pick_lower and (pick_lower in away_lower or away_lower in pick_lower):
                        pick_ml = odds_row["away_ml"]

        # Unit sizing — favorites use edge tiers, underdogs capped
        units = 0
        if grade == "BET":
            if pick_ml is not None and pick_ml >= 150:
                units = 0.5  # Big underdog
            elif pick_ml is not None and pick_ml >= 100:
                units = 1  # Small underdog
            else:
                if edge >= 5:
                    units = 2
                elif edge >= 3:
                    units = 1.5
                else:
                    units = 1
        elif grade == "LEAN":
            units = 0.5

        # P&L
        result = r.get("result") or ""
        if result == "WIN":
            pnl_units = units
        elif result == "LOSS":
            pnl_units = -units
        else:
            pnl_units = 0

        # Get game date
        game_row = conn.execute(
            "SELECT game_date FROM games WHERE game_pk=? LIMIT 1", (r["game_pk"],)
        ).fetchone()

        results.append({
            "game_pk": r["game_pk"],
            "game_date": game_row["game_date"] if game_row else "",
            "bet_type": r["bet_type"],
            "pick": r["pick"],
            "grade": grade,
            "result": result,
            "actual_outcome": r.get("actual_outcome") or "",
            "confidence": conf,
            "edge": edge,
            "units": units,
            "pnl_units": pnl_units,
            "pnl_dollars": pnl_units * 100,
            "graded_at": r.get("graded_at") or "",
        })

    conn.close()

    # Write JSON files
    with open(os.path.join(SITE_DATA_DIR, "games.json"), "w") as f:
        json.dump(games, f)

    with open(os.path.join(SITE_DATA_DIR, "predictions.json"), "w") as f:
        json.dump(predictions, f)

    with open(os.path.join(SITE_DATA_DIR, "odds.json"), "w") as f:
        json.dump(odds, f)

    with open(os.path.join(SITE_DATA_DIR, "results.json"), "w") as f:
        json.dump(results, f)

    # Write metadata
    meta = {
        "exported_at": datetime.now().isoformat(),
        "games": len(games),
        "predictions": len(predictions),
        "odds": len(odds),
        "results": len(results),
        "date_range": {"from": week_ago, "to": future},
    }
    with open(os.path.join(SITE_DATA_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"  Exported: {len(games)} games, {len(predictions)} predictions, {len(odds)} odds, {len(results)} results")
    return meta


if __name__ == "__main__":
    export_all()
