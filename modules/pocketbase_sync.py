"""Sync MLB bot data to PocketBase after each run."""
import sqlite3
import requests

PB_URL = "http://127.0.0.1:8090/api"
PB_EMAIL = "admin@demo.com"
PB_PASSWORD = "password123"


def get_token():
    """Authenticate and get a PocketBase token."""
    try:
        resp = requests.post(
            f"{PB_URL}/collections/_superusers/auth-with-password",
            json={"identity": PB_EMAIL, "password": PB_PASSWORD},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["token"]
    except Exception as e:
        print(f"  PocketBase auth failed: {e}")
        return None


def clear_collection(token, collection):
    """Delete all records from a collection."""
    headers = {"Authorization": f"Bearer {token}"}
    page = 1
    while True:
        resp = requests.get(
            f"{PB_URL}/collections/{collection}/records?perPage=200&page={page}",
            headers=headers, timeout=10,
        )
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            requests.delete(
                f"{PB_URL}/collections/{collection}/records/{item['id']}",
                headers=headers, timeout=5,
            )
        if page >= data.get("totalPages", 1):
            break
        page += 1


def sync_to_pocketbase(db_path="data/mlb.db", target_date=None):
    """Sync games, predictions, and odds for target_date to PocketBase."""
    token = get_token()
    if not token:
        print("  Skipping PocketBase sync (not running)")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Clear and re-sync today's data
    print("  Syncing to PocketBase...")

    # --- Games ---
    clear_collection(token, "mlb_games")
    cur = conn.cursor()
    if target_date:
        cur.execute("SELECT * FROM games WHERE game_date = ?", (target_date,))
    else:
        cur.execute("SELECT * FROM games")
    games = cur.fetchall()
    gc = 0
    for g in games:
        try:
            requests.post(f"{PB_URL}/collections/mlb_games/records", headers=headers, json={
                "game_pk": g["game_pk"], "game_date": g["game_date"] or "",
                "home_team_name": g["home_team_name"] or "", "away_team_name": g["away_team_name"] or "",
                "venue_name": g["venue_name"] or "", "game_time_utc": g["game_time_utc"] or "",
                "day_night": g["day_night"] or "", "status": g["status"] or "",
                "home_score": g["home_score"] or 0, "away_score": g["away_score"] or 0,
                "home_pitcher_name": g["home_pitcher_name"] or "", "away_pitcher_name": g["away_pitcher_name"] or "",
                "umpire_name": g["umpire_name"] or "",
            }, timeout=5)
            gc += 1
        except Exception:
            pass
    print(f"    Games: {gc}")

    # --- Predictions ---
    clear_collection(token, "mlb_predictions")
    game_pks = [g["game_pk"] for g in games]
    if game_pks:
        placeholders = ",".join("?" * len(game_pks))
        cur.execute(f"SELECT * FROM predictions WHERE game_pk IN ({placeholders})", game_pks)
    else:
        cur.execute("SELECT * FROM predictions")
    preds = cur.fetchall()
    pc = 0
    for p in preds:
        try:
            requests.post(f"{PB_URL}/collections/mlb_predictions/records", headers=headers, json={
                "game_pk": p["game_pk"], "bet_type": p["bet_type"] or "",
                "pick": p["pick"] or "", "pick_detail": p["pick_detail"] or "",
                "confidence": p["confidence"] or 0, "edge": p["edge"] or 0,
                "model_value": p["model_value"] or 0, "market_value": p["market_value"] or 0,
                "grade": p["grade"] or "", "reasons": p["reasons"] or "",
                "risks": p["risks"] or "", "created_at": p["created_at"] or "",
            }, timeout=5)
            pc += 1
        except Exception:
            pass
    print(f"    Predictions: {pc}")

    # --- Odds ---
    clear_collection(token, "mlb_odds")
    if game_pks:
        cur.execute(f"SELECT * FROM odds WHERE game_pk IN ({placeholders})", game_pks)
    else:
        cur.execute("SELECT * FROM odds")
    odds = cur.fetchall()
    oc = 0
    for o in odds:
        try:
            requests.post(f"{PB_URL}/collections/mlb_odds/records", headers=headers, json={
                "game_pk": o["game_pk"], "fetched_at": o["fetched_at"] or "",
                "home_ml": o["home_ml"] or 0, "away_ml": o["away_ml"] or 0,
                "run_line_spread": o["run_line_spread"] or 0, "total": o["total"] or 0,
                "over_price": o["over_price"] or 0, "under_price": o["under_price"] or 0,
                "bookmaker": o["bookmaker"] or "",
            }, timeout=5)
            oc += 1
        except Exception:
            pass
    print(f"    Odds: {oc}")

    # --- Results (append-only, don't clear — these are historical) ---
    cur.execute("SELECT * FROM results")
    results = cur.fetchall()
    if results:
        # Get existing result game_pks to avoid duplicates
        try:
            existing = requests.get(
                f"{PB_URL}/collections/mlb_results/records?perPage=200",
                headers=headers, timeout=10
            ).json()
            existing_keys = set()
            for item in existing.get("items", []):
                existing_keys.add(f"{item['game_pk']}_{item['bet_type']}_{item['pick']}")
        except Exception:
            existing_keys = set()

        rc = 0
        for r in results:
            key = f"{r['game_pk']}_{r['bet_type']}_{r['pick']}"
            if key in existing_keys:
                continue

            # Calculate units based on confidence and edge
            conf = r["confidence_at_pick"] or 0
            edge = r["edge_at_pick"] or 0
            # Calculate grade directly from stored confidence/edge
            from modules.models.confidence import grade_pick
            grade = grade_pick(conf, edge, r["bet_type"] or "game")

            # Get moneyline for game bets
            pick_ml = None
            if r["bet_type"] == "game":
                odds_row = cur.execute(
                    "SELECT home_ml, away_ml FROM odds WHERE game_pk=? LIMIT 1",
                    (r["game_pk"],)
                ).fetchone()
                if odds_row:
                    game_row2 = cur.execute(
                        "SELECT home_team_name, away_team_name FROM games WHERE game_pk=? LIMIT 1",
                        (r["game_pk"],)
                    ).fetchone()
                    if game_row2:
                        pick_lower = (r["pick"] or "").lower()
                        home_lower = (game_row2["home_team_name"] or "").lower()
                        away_lower = (game_row2["away_team_name"] or "").lower()
                        if pick_lower and (pick_lower in home_lower or home_lower in pick_lower):
                            pick_ml = odds_row["home_ml"]
                        elif pick_lower and (pick_lower in away_lower or away_lower in pick_lower):
                            pick_ml = odds_row["away_ml"]

            # Get game date (needed for unit sizing and PB record)
            game_row = cur.execute(
                "SELECT game_date FROM games WHERE game_pk=? LIMIT 1",
                (r["game_pk"],)
            ).fetchone()
            game_date = game_row["game_date"] if game_row else ""

            # Unit sizing — underdogs capped, favorites use edge tiers
            # Games before 2026-04-02 use legacy edge-only tiers;
            # 2026-04-02+ require edge + confidence to exceed 1u
            use_new_sizing = game_date >= "2026-04-02"
            units = 0
            if grade == "BET":
                if pick_ml is not None and pick_ml >= 150:
                    units = 0.5  # Big underdog
                elif pick_ml is not None and pick_ml >= 100:
                    units = 1  # Small underdog
                elif use_new_sizing:
                    if edge >= 5 and conf >= 70:
                        units = 2
                    elif edge >= 3 and conf >= 65:
                        units = 1.5
                    else:
                        units = 1
                else:
                    if edge >= 5:
                        units = 2
                    elif edge >= 3:
                        units = 1.5
                    else:
                        units = 1
            elif grade == "LEAN":
                units = 0.5

            # PnL calculation
            result = r["result"] or ""
            if result == "WIN":
                pnl_units = units
            elif result == "LOSS":
                pnl_units = -units
            else:  # PUSH or unknown
                pnl_units = 0
            pnl_dollars = pnl_units * 100

            try:
                requests.post(f"{PB_URL}/collections/mlb_results/records", headers=headers, json={
                    "game_pk": r["game_pk"], "game_date": game_date,
                    "bet_type": r["bet_type"] or "", "pick": r["pick"] or "",
                    "pick_detail": "", "grade": grade,
                    "result": result, "actual_outcome": r["actual_outcome"] or "",
                    "confidence": conf, "edge": edge,
                    "units": units, "pnl_units": pnl_units, "pnl_dollars": pnl_dollars,
                    "graded_at": r["graded_at"] or "",
                }, timeout=5)
                rc += 1
            except Exception:
                pass
        print(f"    Results: {rc} new")

    conn.close()
    print("  PocketBase sync complete.")
