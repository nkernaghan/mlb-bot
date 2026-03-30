import statsapi
from datetime import datetime
from modules.database import get_connection


def grade_results(date_str):
    """Grade predictions from a given date against actual results."""
    conn = get_connection()
    predictions = conn.execute(
        "SELECT * FROM predictions WHERE game_pk IN (SELECT game_pk FROM games WHERE game_date = ?)",
        (date_str,)
    ).fetchall()

    if not predictions:
        print(f"No predictions found for {date_str}")
        return []

    results = []
    for pred in predictions:
        game_pk = pred["game_pk"]
        bet_type = pred["bet_type"]

        try:
            if bet_type == "game":
                result = _grade_game_pick(game_pk, pred)
            elif bet_type == "strikeout":
                result = _grade_k_pick(game_pk, pred)
            elif bet_type == "nrfi":
                result = _grade_nrfi_pick(game_pk, pred)
            else:
                continue

            if result:
                results.append(result)
                _save_result(result)
        except Exception as e:
            print(f"  Error grading {bet_type} for game {game_pk}: {e}")

    conn.close()
    _print_grade_summary(results, date_str)
    return results


def _grade_game_pick(game_pk, pred):
    """Grade a game prediction against the final score."""
    boxscore = statsapi.boxscore_data(game_pk)
    if not boxscore:
        return None

    away_score = boxscore.get("awayBattingTotals", {}).get("r", 0)
    home_score = boxscore.get("homeBattingTotals", {}).get("r", 0)

    if away_score == home_score:
        return None

    winner = pred["pick"]
    home_name = boxscore.get("teamInfo", {}).get("home", {}).get("teamName", "")
    away_name = boxscore.get("teamInfo", {}).get("away", {}).get("teamName", "")

    actual_winner = home_name if home_score > away_score else away_name
    result = "WIN" if winner in actual_winner or actual_winner in winner else "LOSS"

    return {
        "game_pk": game_pk,
        "bet_type": "game",
        "pick": pred["pick"],
        "result": result,
        "actual_outcome": f"{away_name} {away_score} - {home_name} {home_score}",
        "edge_at_pick": pred["edge"],
        "confidence_at_pick": pred["confidence"],
    }


def _grade_k_pick(game_pk, pred):
    """Grade a K prop against actual starter strikeouts."""
    boxscore = statsapi.boxscore_data(game_pk)
    if not boxscore:
        return None

    pick = pred["pick"]
    actual_ks = None
    for side in ["away", "home"]:
        pitchers = boxscore.get(f"{side}Pitchers", [])
        if pitchers:
            starter = pitchers[0] if pitchers else {}
            actual_ks = int(starter.get("k", 0))
            break

    if actual_ks is None:
        return None

    line = pred.get("model_value")
    if pick == "OVER":
        result = "WIN" if actual_ks > line else "LOSS" if actual_ks < line else "PUSH"
    else:
        result = "WIN" if actual_ks < line else "LOSS" if actual_ks > line else "PUSH"

    return {
        "game_pk": game_pk,
        "bet_type": "strikeout",
        "pick": pred["pick"],
        "result": result,
        "actual_outcome": f"{actual_ks} Ks",
        "edge_at_pick": pred["edge"],
        "confidence_at_pick": pred["confidence"],
    }


def _grade_nrfi_pick(game_pk, pred):
    """Grade NRFI pick against first-inning scoring."""
    try:
        data = statsapi.get("game_linescore", {"gamePk": game_pk})
        innings = data.get("innings", [])
        if not innings:
            return None

        first = innings[0]
        away_runs = first.get("away", {}).get("runs", 0)
        home_runs = first.get("home", {}).get("runs", 0)
        first_inning_runs = away_runs + home_runs

        actual_nrfi = first_inning_runs == 0
        pick = pred["pick"]

        if pick == "NRFI":
            result = "WIN" if actual_nrfi else "LOSS"
        else:
            result = "WIN" if not actual_nrfi else "LOSS"

        return {
            "game_pk": game_pk,
            "bet_type": "nrfi",
            "pick": pred["pick"],
            "result": result,
            "actual_outcome": f"1st inning: {away_runs}-{home_runs} ({'NRFI' if actual_nrfi else 'YRFI'})",
            "edge_at_pick": pred["edge"],
            "confidence_at_pick": pred["confidence"],
        }
    except Exception:
        return None


def _save_result(result):
    conn = get_connection()
    conn.execute("""
        INSERT INTO results (game_pk, bet_type, pick, result, actual_outcome,
            edge_at_pick, confidence_at_pick, graded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (result["game_pk"], result["bet_type"], result["pick"], result["result"],
          result["actual_outcome"], result["edge_at_pick"], result["confidence_at_pick"],
          datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def show_record(days=0):
    """Show season or rolling record."""
    conn = get_connection()
    query = "SELECT bet_type, result, COUNT(*) as cnt FROM results"
    if days > 0:
        query += f" WHERE graded_at >= date('now', '-{days} days')"
    query += " GROUP BY bet_type, result"
    rows = conn.execute(query).fetchall()
    conn.close()

    if not rows:
        print("No graded results yet.")
        return

    totals = {"game": {"WIN": 0, "LOSS": 0, "PUSH": 0},
              "strikeout": {"WIN": 0, "LOSS": 0, "PUSH": 0},
              "nrfi": {"WIN": 0, "LOSS": 0, "PUSH": 0}}

    for row in rows:
        bt = row["bet_type"]
        if bt in totals and row["result"] in totals[bt]:
            totals[bt][row["result"]] = row["cnt"]

    period = f"Last {days} days" if days else "Season"
    print(f"\n{period} Record")
    print("=" * 50)

    overall_w, overall_l = 0, 0
    for bt, label in [("game", "Games"), ("strikeout", "K Props"), ("nrfi", "NRFI")]:
        w, l, p = totals[bt]["WIN"], totals[bt]["LOSS"], totals[bt]["PUSH"]
        total = w + l
        pct = f"{w/(w+l)*100:.1f}%" if total > 0 else "N/A"
        print(f"  {label}: {w}-{l}-{p} ({pct})")
        overall_w += w
        overall_l += l

    total = overall_w + overall_l
    pct = f"{overall_w/total*100:.1f}%" if total > 0 else "N/A"
    print(f"\n  Overall: {overall_w}-{overall_l} ({pct})")


def _print_grade_summary(results, date_str):
    wins = sum(1 for r in results if r["result"] == "WIN")
    losses = sum(1 for r in results if r["result"] == "LOSS")
    pushes = sum(1 for r in results if r["result"] == "PUSH")
    print(f"\nResults for {date_str}: {wins}W - {losses}L - {pushes}P")
    for r in results:
        icon = "+" if r["result"] == "WIN" else "x" if r["result"] == "LOSS" else "-"
        print(f"  {icon} {r['bet_type'].upper()}: {r['pick']} -> {r['result']} ({r['actual_outcome']})")
