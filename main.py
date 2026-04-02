import argparse
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SEASON_YEAR
from modules.database import init_db, get_connection
from modules.data.schedule import fetch_games, fetch_lineups, fetch_rest_travel, save_games
from modules.data.odds import fetch_game_odds, fetch_event_props, parse_game_odds, parse_k_props, parse_nrfi_odds, get_consensus_odds, save_odds
from modules.data.cache import refresh_daily_caches
from modules.data.pitcher_stats import fetch_pitcher_stats, save_pitcher_stats
from modules.data.batter_stats import fetch_batter_stats, fetch_team_batting_stats
from modules.data.park_factors import load_park_factors, get_park_factor, is_dome
from modules.data.umpires import fetch_umpire_stats, get_umpire_from_feed
from modules.data.weather import fetch_weather
from modules.data.injuries import fetch_team_injuries
from modules.data.bullpen import fetch_bullpen_status, fetch_bullpen_usage, calc_bullpen_aggregate
from modules.models.game_predictor import predict_game
from modules.models.strikeout_predictor import predict_strikeouts
from modules.models.nrfi_predictor import predict_nrfi
from modules.models.confidence import grade_pick
from modules.output.reporting import generate_report
from modules.output.results_tracker import grade_results, show_record
from modules.pocketbase_sync import sync_to_pocketbase
from modules.export_static import export_all as export_static_site


def parse_args():
    parser = argparse.ArgumentParser(description="MLB Prediction Bot")
    parser.add_argument("--date", type=str, help="Analysis date (YYYY-MM-DD), default today")
    parser.add_argument("--game-only", action="store_true", help="Only run game predictions")
    parser.add_argument("--strikeouts", action="store_true", help="Only run K prop predictions")
    parser.add_argument("--nrfi", action="store_true", help="Only run NRFI predictions")
    parser.add_argument("--grade-results", action="store_true", help="Grade yesterday's picks")
    parser.add_argument("--record", action="store_true", help="Show season record")
    parser.add_argument("--days", type=int, default=0, help="Rolling N-day record (0=full season)")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch cached data")
    parser.add_argument("--notify", action="store_true", help="Send notifications")
    return parser.parse_args()


def analyze_game(game, odds_by_event, injuries_cache, bullpen_usage_cache, rest_travel, run_game, run_k, run_nrfi):
    """Analyze a single game across all enabled prediction types."""
    predictions = []
    game_pk = game["game_pk"]

    try:
        # Fetch pitcher stats
        home_pitcher = {}
        away_pitcher = {}
        if game.get("home_pitcher_id"):
            home_pitcher = fetch_pitcher_stats(
                game["home_pitcher_id"], game.get("home_pitcher_name"), game.get("home_team_name"))
        if game.get("away_pitcher_id"):
            away_pitcher = fetch_pitcher_stats(
                game["away_pitcher_id"], game.get("away_pitcher_name"), game.get("away_team_name"))

        # Team batting stats
        home_batting = fetch_team_batting_stats(game["home_team_id"]) if game.get("home_team_id") else {}
        away_batting = fetch_team_batting_stats(game["away_team_id"]) if game.get("away_team_id") else {}

        # Bullpen
        home_bp = calc_bullpen_aggregate(fetch_bullpen_status(game["home_team_id"])) if game.get("home_team_id") else {}
        away_bp = calc_bullpen_aggregate(fetch_bullpen_status(game["away_team_id"])) if game.get("away_team_id") else {}

        # Add fatigue info from pre-fetched usage cache
        home_bp_usage = bullpen_usage_cache.get(game.get("home_team_id"), {})
        away_bp_usage = bullpen_usage_cache.get(game.get("away_team_id"), {})
        home_bp["fatigued"] = home_bp_usage.get("fatigued", False)
        home_bp["pitchers_no_rest"] = home_bp_usage.get("pitchers_no_rest", 0)
        away_bp["fatigued"] = away_bp_usage.get("fatigued", False)
        away_bp["pitchers_no_rest"] = away_bp_usage.get("pitchers_no_rest", 0)

        # Injuries (from pre-fetched cache)
        home_injuries = injuries_cache.get(game.get("home_team_id"), [])
        away_injuries = injuries_cache.get(game.get("away_team_id"), [])

        # Rest/travel info
        home_rest = rest_travel.get(game.get("home_team_id"), {})
        away_rest = rest_travel.get(game.get("away_team_id"), {})

        # Park factors (from FanGraphs, loaded once per run)
        park = get_park_factor(game.get("venue_name"))

        # Weather
        weather = None
        if game.get("venue_id") and game.get("venue_name"):
            if not is_dome(game["venue_name"]):
                weather = fetch_weather(game["venue_id"], game["venue_name"], game.get("game_time_utc"))
            else:
                weather = {"dome": True, "wind_speed": 0, "wind_dir": 0, "temp_f": 72, "humidity": 50}

        # Umpire (best-effort — from live feed, may not be posted yet)
        umpire = None
        try:
            ump_name = get_umpire_from_feed(game_pk)
            if ump_name:
                umpire = fetch_umpire_stats(ump_name)
        except Exception:
            pass

        # Get odds for this game
        game_odds = odds_by_event.get(game_pk, {})
        consensus = game_odds.get("consensus")

        # Game prediction
        if run_game:
            try:
                pred = predict_game(game, home_pitcher, away_pitcher, home_batting, away_batting,
                                    home_bp, away_bp, park, umpire, weather, consensus,
                                    home_injuries=home_injuries, away_injuries=away_injuries,
                                    home_rest=home_rest, away_rest=away_rest)
                predictions.append(pred)
            except Exception as e:
                print(f"    Game prediction error for {game_pk}: {e}")

        # K prop predictions (for both starters)
        if run_k:
            # Pre-fetch top-3 batter K-rates for each side so the K model can use
            # individual lineup K-rates rather than just the team average.
            # Lineups may not be posted yet — fetch_lineups returns None gracefully.
            home_top_k_rates: list[float] = []
            away_top_k_rates: list[float] = []
            try:
                k_lineups = fetch_lineups(game_pk)
                if k_lineups:
                    for batter in (k_lineups.get("home") or [])[:3]:
                        bs = fetch_batter_stats(batter["id"], batter["name"], game.get("home_team_name"))
                        if bs.get("k_rate"):
                            home_top_k_rates.append(bs["k_rate"])
                    for batter in (k_lineups.get("away") or [])[:3]:
                        bs = fetch_batter_stats(batter["id"], batter["name"], game.get("away_team_name"))
                        if bs.get("k_rate"):
                            away_top_k_rates.append(bs["k_rate"])
            except Exception:
                pass  # lineups not yet available — model falls back to team average

            for pitcher, opp_batting, opp_top_k_rates, side in [
                (home_pitcher, away_batting, away_top_k_rates, "home"),
                (away_pitcher, home_batting, home_top_k_rates, "away"),
            ]:
                if not pitcher.get("player_id"):
                    continue
                k_odds = game_odds.get("k_props", {}).get(pitcher.get("player_name"))
                bb_rate = pitcher.get("bb_rate")
                try:
                    pred = predict_strikeouts(
                        game, pitcher, opp_batting, park, umpire, weather, k_odds,
                        opp_batter_k_rates=opp_top_k_rates or None,
                        pitcher_bb_rate=bb_rate,
                    )
                    predictions.append(pred)
                except Exception as e:
                    print(f"    K prediction error for {pitcher.get('player_name')}: {e}")

        # NRFI prediction
        if run_nrfi:
            nrfi_odds = game_odds.get("nrfi")
            # Fetch lineups for top-of-order batter stats
            home_batting_top = []
            away_batting_top = []
            try:
                lineups = fetch_lineups(game_pk)
                if lineups:
                    for batter in (lineups.get("away") or [])[:3]:
                        bstats = fetch_batter_stats(batter["id"], batter["name"], game.get("away_team_name"))
                        away_batting_top.append(bstats)
                    for batter in (lineups.get("home") or [])[:3]:
                        bstats = fetch_batter_stats(batter["id"], batter["name"], game.get("home_team_name"))
                        home_batting_top.append(bstats)
            except Exception:
                pass
            try:
                pred = predict_nrfi(game, home_pitcher, away_pitcher,
                                    home_batting_top, away_batting_top,
                                    park, umpire, weather, nrfi_odds)
                predictions.append(pred)
            except Exception as e:
                print(f"    NRFI prediction error for {game_pk}: {e}")

    except Exception as e:
        print(f"  Error analyzing game {game_pk}: {e}")

    return predictions


def save_predictions(predictions):
    """Save all predictions to the database. Clears old predictions for the same games first."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()

    # Clear ALL old predictions for these games to prevent duplicates from re-runs
    game_pks = list(set(p["game_pk"] for p in predictions))
    if game_pks:
        placeholders = ",".join("?" * len(game_pks))
        deleted = conn.execute(f"DELETE FROM predictions WHERE game_pk IN ({placeholders})", game_pks).rowcount
        conn.commit()
        if deleted:
            print(f"  Cleared {deleted} old predictions for re-run")

    for pred in predictions:
        reasons = ", ".join(pred.get("reasons", []))
        risks = ", ".join(pred.get("risks", []))
        conn.execute("""
            INSERT INTO predictions (game_pk, bet_type, pick, pick_detail, pitcher_name, confidence, edge,
                model_value, market_value, grade, reasons, risks, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pred["game_pk"], pred["bet_type"], pred["pick"], pred.get("pick_detail"),
            pred.get("pitcher_name"),
            pred.get("confidence", 0), pred.get("edge", 0),
            pred.get("model_value") or pred.get("model_ks") or pred.get("nrfi_probability"),
            pred.get("market_value") or pred.get("line") or pred.get("implied_probability"),
            pred.get("grade", "PASS"), reasons, risks, now,
        ))
    conn.commit()
    conn.close()


def main():
    args = parse_args()
    init_db()

    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    run_all = not (args.game_only or args.strikeouts or args.nrfi)
    run_game = run_all or args.game_only
    run_k = run_all or args.strikeouts
    run_nrfi = run_all or args.nrfi

    if args.grade_results:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"Grading results for {yesterday}...")
        grade_results(yesterday)
        return

    if args.record:
        show_record(args.days)
        return

    print(f"MLB Prediction Bot — {target_date}")
    print("=" * 60)

    # Step 1: Fetch schedule
    print("\n[1/8] Fetching schedule...")
    games = fetch_games(target_date)
    if not games:
        print("  No games found for this date.")
        return
    print(f"  Found {len(games)} games")
    save_games(games)

    # Step 2: Fetch odds
    print("[2/8] Fetching odds...")
    odds_by_event = {}
    try:
        raw_odds = fetch_game_odds()
        for event in raw_odds:
            event_id = event.get("id")
            home_team = event.get("home_team")
            away_team = event.get("away_team")

            all_book_odds = []
            for bookmaker in event.get("bookmakers", []):
                parsed = parse_game_odds(bookmaker, away_team, home_team)
                all_book_odds.append(parsed)

            # Match to our game by team names
            for game in games:
                if (home_team and home_team in game.get("home_team_name", "")) or \
                   (away_team and away_team in game.get("away_team_name", "")):
                    game_pk = game["game_pk"]
                    odds_by_event[game_pk] = {
                        "all_books": all_book_odds,
                        "consensus": get_consensus_odds(all_book_odds),
                        "event_id": event_id,
                        "k_props": {},
                        "nrfi": None,
                    }
                    save_odds(game_pk, all_book_odds)
                    break

        print(f"  Odds loaded for {len(odds_by_event)} games")

        # Fetch K props and NRFI odds per event
        import time
        prop_count = 0
        for game_pk, game_odds in odds_by_event.items():
            event_id = game_odds.get("event_id")
            if not event_id:
                continue
            try:
                time.sleep(1)  # Rate limit: 1 req/sec
                prop_data = fetch_event_props(event_id)
                if prop_data and prop_data.get("bookmakers"):
                    for bm in prop_data["bookmakers"]:
                        # K props
                        k_props = parse_k_props(bm)
                        for kp in k_props:
                            pname = kp.get("pitcher_name", "")
                            if pname and pname not in game_odds["k_props"]:
                                game_odds["k_props"][pname] = kp
                        # NRFI
                        if not game_odds["nrfi"]:
                            nrfi = parse_nrfi_odds(bm)
                            if nrfi:
                                game_odds["nrfi"] = nrfi
                    prop_count += 1
            except Exception as e:
                print(f"    Props fetch error for event {event_id}: {e}")
        if prop_count:
            print(f"  Props loaded for {prop_count} events")

    except Exception as e:
        print(f"  Odds fetch error (continuing without): {e}")

    # Step 3: Fetch stats (cached daily)
    print("[3/8] Fetching stats...")
    try:
        refresh_daily_caches(target_date, force=args.refresh)
    except Exception as e:
        print(f"  Cache refresh error (continuing with limited data): {e}")

    # Load park factors from FanGraphs (once per run)
    try:
        load_park_factors()
    except Exception as e:
        print(f"  Park factors load error (using defaults): {e}")

    # Fetch rest/travel info
    rest_travel = {}
    try:
        rest_travel = fetch_rest_travel(games, target_date)
        traveled = sum(1 for v in rest_travel.values() if v.get("traveled"))
        rested = sum(1 for v in rest_travel.values() if v.get("days_off", 0) > 0)
        print(f"  Rest/travel: {traveled} teams traveled, {rested} teams had day off")
    except Exception as e:
        print(f"  Rest/travel check error (continuing without): {e}")

    # Fetch bullpen usage for all teams (once per run)
    bullpen_usage_cache = {}
    try:
        team_ids = set()
        for game in games:
            if game.get("home_team_id"):
                team_ids.add(game["home_team_id"])
            if game.get("away_team_id"):
                team_ids.add(game["away_team_id"])
        for tid in team_ids:
            usage = fetch_bullpen_usage(tid, days=3)
            if usage:
                total_pitches = sum(u.get("pitches_thrown", 0) for u in usage)
                overworked = [u for u in usage if (u.get("days_rest") or 99) == 0]
                bullpen_usage_cache[tid] = {
                    "total_pitches_3d": total_pitches,
                    "pitchers_no_rest": len(overworked),
                    "fatigued": total_pitches > 200 or len(overworked) >= 3,
                }
        print(f"  Bullpen usage loaded for {len(bullpen_usage_cache)} teams")
    except Exception as e:
        print(f"  Bullpen usage error (continuing without): {e}")

    # Fetch injuries for all teams in today's games
    injuries_cache = {}
    try:
        team_ids = set()
        for game in games:
            if game.get("home_team_id"):
                team_ids.add(game["home_team_id"])
            if game.get("away_team_id"):
                team_ids.add(game["away_team_id"])
        for tid in team_ids:
            injuries_cache[tid] = fetch_team_injuries(tid)
        il_count = sum(len(v) for v in injuries_cache.values())
        print(f"  Injuries loaded: {il_count} players across {len(team_ids)} teams")
    except Exception as e:
        print(f"  Injuries fetch error (continuing without): {e}")

    # Step 4: Run predictions
    print("[4/8] Running predictions...")
    all_predictions = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for game in games:
            has_pitcher = (game.get("home_pitcher_id") or game.get("home_pitcher_name") or
                           game.get("away_pitcher_id") or game.get("away_pitcher_name"))
            if not has_pitcher:
                print(f"  Skipping {game.get('away_team_name', '?')} @ {game.get('home_team_name', '?')} — no probable pitchers")
                continue
            future = executor.submit(analyze_game, game, odds_by_event, injuries_cache, bullpen_usage_cache, rest_travel, run_game, run_k, run_nrfi)
            futures[future] = game

        for future in as_completed(futures):
            game = futures[future]
            try:
                preds = future.result()
                all_predictions.extend(preds)
                bet_count = sum(1 for p in preds if p["grade"] == "BET")
                lean_count = sum(1 for p in preds if p["grade"] == "LEAN")
                print(f"  {game.get('away_team_name', '?')} @ {game.get('home_team_name', '?')}: "
                      f"{len(preds)} predictions ({bet_count} BET, {lean_count} LEAN)")
            except Exception as e:
                print(f"  Error analyzing {game.get('home_team_name', '?')}: {e}")

    # Step 5: Generate report
    print("[5/8] Generating report...")
    if all_predictions:
        generate_report(games, all_predictions, target_date)
    else:
        print("  No predictions generated.")

    # Step 6: Save to database
    print("[6/8] Saving predictions...")
    if all_predictions:
        save_predictions(all_predictions)
        print(f"  Saved {len(all_predictions)} predictions to database")

    bets = sum(1 for p in all_predictions if p["grade"] == "BET")
    leans = sum(1 for p in all_predictions if p["grade"] == "LEAN")
    print(f"\nDone. {len(all_predictions)} total predictions: {bets} BET, {leans} LEAN")

    # Sync to PocketBase (local dashboard)
    print("\n[7/8] Syncing to PocketBase...")
    try:
        sync_to_pocketbase(target_date=target_date)
    except Exception as e:
        print(f"  PocketBase sync error: {e}")

    # Export static JSON for GitHub Pages
    print("[8/8] Exporting static site data...")
    try:
        export_static_site()
    except Exception as e:
        print(f"  Static export error: {e}")


if __name__ == "__main__":
    main()
