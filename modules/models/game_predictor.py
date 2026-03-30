from modules.data.odds import american_to_implied
from modules.models.confidence import calc_game_confidence, grade_pick
from modules.data.weather import wind_run_impact, temp_run_impact
from config import MARKET_WEIGHT, MODEL_WEIGHT, HOME_ADVANTAGE_RUNS


def predict_game(game, home_pitcher, away_pitcher, home_batting, away_batting,
                 bullpen_home, bullpen_away, park, umpire, weather, odds):
    """Run the 13-factor game prediction model.

    Returns a prediction dict with projected winner, edge, confidence, grade.
    """
    reasons = []
    risks = []
    contradictions = 0

    # --- Signal 1: Starting pitcher quality (xERA primary, ERA fallback) ---
    home_p_quality = _pitcher_quality_score(home_pitcher)
    away_p_quality = _pitcher_quality_score(away_pitcher)
    pitcher_edge = away_p_quality - home_p_quality  # Positive = away pitcher better

    if abs(pitcher_edge) > 0.5:
        better = "home" if pitcher_edge < 0 else "away"
        reasons.append(f"Pitcher edge: {game[f'{better}_pitcher_name']} "
                       f"(xERA {home_pitcher.get('xera') or home_pitcher.get('era', '?')})")

    # --- Signal 2: Lineup strength vs handedness ---
    home_lineup_score = _lineup_score(home_batting, away_pitcher)
    away_lineup_score = _lineup_score(away_batting, home_pitcher)
    lineup_edge = home_lineup_score - away_lineup_score

    # --- Signal 3: Barrel rate matchup ---
    home_barrel = home_batting.get("barrel_rate", 0) or 0
    away_barrel = away_batting.get("barrel_rate", 0) or 0
    home_barrel_against = home_pitcher.get("barrel_rate_against", 0) or 0
    away_barrel_against = away_pitcher.get("barrel_rate_against", 0) or 0

    home_barrel_matchup = away_barrel - home_barrel_against
    away_barrel_matchup = home_barrel - away_barrel_against

    if home_barrel_matchup > 3 or away_barrel_matchup > 3:
        risks.append("Elevated barrel rate matchup — potential blowout risk")

    # --- Signal 4: Bullpen ---
    bp_home_era = bullpen_home.get("bullpen_era", 4.0) or 4.0
    bp_away_era = bullpen_away.get("bullpen_era", 4.0) or 4.0
    bp_edge = bp_away_era - bp_home_era  # Positive = home bullpen better

    if abs(bp_edge) > 0.5:
        better = "home" if bp_edge > 0 else "away"
        reasons.append(f"Bullpen edge: {game[f'{better}_team_name']} ({min(bp_home_era, bp_away_era):.2f} ERA)")

    # --- Signal 5: Park factors ---
    run_factor = (park.get("run_factor", 100) or 100) / 100
    park_adjustment = (run_factor - 1.0) * 4.5

    if run_factor > 1.05:
        risks.append(f"Hitter-friendly park (run factor {park.get('run_factor', 100)})")
    elif run_factor < 0.95:
        reasons.append(f"Pitcher-friendly park (run factor {park.get('run_factor', 100)})")

    # --- Signal 6: Weather ---
    weather_adj = 0
    if weather and not weather.get("dome"):
        weather_adj += wind_run_impact(weather.get("wind_speed", 0), weather.get("wind_dir", 0))
        weather_adj += temp_run_impact(weather.get("temp_f"))
        if abs(weather_adj) > 0.5:
            direction = "increases" if weather_adj > 0 else "decreases"
            risks.append(f"Weather {direction} run expectancy by {abs(weather_adj):.1f}")

    # --- Signal 7: Home advantage ---
    home_adj = HOME_ADVANTAGE_RUNS

    # --- Combine model signals into projected run differential ---
    pitcher_run_diff = -pitcher_edge
    lineup_run_diff = lineup_edge * 0.3
    bp_run_diff = bp_edge * 0.2

    model_home_runs_edge = (
        pitcher_run_diff +
        lineup_run_diff +
        bp_run_diff +
        home_adj +
        park_adjustment * 0.1 +
        weather_adj * 0.1
    )

    # --- Signal 11: Vegas blending ---
    market_implied_home = None
    if odds and odds.get("home_ml") is not None:
        market_implied_home = american_to_implied(odds["home_ml"])

    model_implied_home = _runs_edge_to_probability(model_home_runs_edge)

    if market_implied_home is not None:
        blended_home_prob = (MARKET_WEIGHT * market_implied_home) + (MODEL_WEIGHT * model_implied_home)
    else:
        blended_home_prob = model_implied_home

    # --- Check for contradictions ---
    if market_implied_home is not None:
        if (model_implied_home > 0.5 and market_implied_home < 0.45) or \
           (model_implied_home < 0.5 and market_implied_home > 0.55):
            contradictions += 1
            risks.append("Model and market disagree on winner")

    # --- Determine pick: find where the VALUE is ---
    # Start with the blended favorite
    pick_home = blended_home_prob > 0.5
    pick_team = game["home_team_name"] if pick_home else game["away_team_name"]
    pick_prob = blended_home_prob if pick_home else (1 - blended_home_prob)

    edge = 0
    if market_implied_home is not None:
        market_prob = market_implied_home if pick_home else (1 - market_implied_home)
        edge = round((pick_prob - market_prob) * 100, 1)

        # If edge is negative, the value is on the OTHER side (underdog)
        if edge < -2.0:
            pick_home = not pick_home
            pick_team = game["home_team_name"] if pick_home else game["away_team_name"]
            pick_prob = blended_home_prob if pick_home else (1 - blended_home_prob)
            market_prob = market_implied_home if pick_home else (1 - market_implied_home)
            edge = round((pick_prob - market_prob) * 100, 1)
            # Edge is now positive (model says underdog is undervalued)
            if edge > 0:
                reasons.append(f"Value on underdog — market overvalues favorite by {edge:.1f}%")

    # --- Confidence ---
    data_flags = {
        "pitcher_stats": bool(home_pitcher.get("era") and away_pitcher.get("era")),
        "lineup_confirmed": bool(home_batting.get("ops") or home_batting.get("team_ops")),
        "bullpen_data": bool(bullpen_home.get("bullpen_era")),
        "umpire_known": bool(umpire),
        "weather_data": bool(weather),
        "odds_available": bool(odds and odds.get("home_ml")),
        "park_extreme": abs((park.get("run_factor", 100) or 100) - 100) > 10,
    }
    signal_agreement = {
        "xera_fip_agree": _xera_fip_agree(home_pitcher, away_pitcher, pick_home),
        "three_plus_aligned": sum([
            pitcher_run_diff > 0 if pick_home else pitcher_run_diff < 0,
            lineup_run_diff > 0 if pick_home else lineup_run_diff < 0,
            bp_run_diff > 0 if pick_home else bp_run_diff < 0,
        ]) >= 3,
        "market_agrees": market_implied_home is not None and (
            (pick_home and market_implied_home > 0.5) or
            (not pick_home and market_implied_home < 0.5)
        ),
    }

    confidence = calc_game_confidence(data_flags, signal_agreement, contradictions)
    grade = grade_pick(confidence, edge, "game")

    # --- Spread recommendation ---
    spread = None
    spread_price = None
    total = None
    over_price = None
    under_price = None
    bet_type_rec = "ML"
    if odds:
        spread = odds.get("run_line_spread")
        total = odds.get("total")
        if pick_home:
            spread_price = odds.get("run_line_home_price")
        else:
            # Away team spread is the inverse
            spread_price = odds.get("run_line_away_price") if odds.get("run_line_away_price") else None
            if spread is not None:
                spread = -spread  # Flip for away pick
        # Recommend spread vs ML based on edge size and probability
        if edge > 5 and pick_prob > 0.58:
            bet_type_rec = "Run Line"  # Big edge + strong favorite = take the spread
        elif edge > 0 and pick_prob < 0.45:
            bet_type_rec = "ML"  # Underdog value = take moneyline for bigger payout

    return {
        "game_pk": game["game_pk"],
        "bet_type": "game",
        "pick": pick_team,
        "pick_detail": f"{bet_type_rec} {pick_team}",
        "confidence": confidence,
        "edge": edge,
        "model_value": round(pick_prob * 100, 1),
        "market_value": round((market_prob if market_implied_home else pick_prob) * 100, 1),
        "grade": grade,
        "reasons": reasons[:5],
        "risks": risks[:3],
        "blended_home_prob": round(blended_home_prob, 3),
        "model_home_prob": round(model_implied_home, 3),
        "spread": spread,
        "spread_price": spread_price,
        "total": total,
        "home_ml": odds.get("home_ml") if odds else None,
        "away_ml": odds.get("away_ml") if odds else None,
    }


def _pitcher_quality_score(pitcher):
    """Score pitcher quality. Lower = better pitcher. Uses xERA primary, FIP secondary, ERA fallback."""
    xera = pitcher.get("xera")
    fip = pitcher.get("fip")
    era = pitcher.get("era")

    if xera and fip:
        return xera * 0.6 + fip * 0.4
    elif xera:
        return xera
    elif fip:
        return fip
    elif era:
        return era
    return 4.50  # League average fallback


def _lineup_score(batting, opposing_pitcher):
    """Score a lineup's expected output against the opposing pitcher."""
    ops = batting.get("ops") or batting.get("team_ops") or 0.700
    wrc = batting.get("wrc_plus", 100) or 100
    k_rate = batting.get("k_rate") or batting.get("team_k_rate") or 22

    pitcher_hand = opposing_pitcher.get("throws")
    if pitcher_hand == "L":
        split_ops = batting.get("vs_lhp_ops")
        if split_ops:
            ops = split_ops

    score = (ops - 0.700) * 10 + (wrc - 100) / 20 - (k_rate - 22) / 10
    return score


def _runs_edge_to_probability(runs_edge):
    """Convert a runs edge to a win probability. ~0.25 runs = ~55% win prob."""
    import math
    return 1 / (1 + math.exp(-runs_edge * 0.35))


def _xera_fip_agree(home_p, away_p, home_favored):
    """Check if xERA and FIP signals agree with the pick direction."""
    home_quality = _pitcher_quality_score(home_p)
    away_quality = _pitcher_quality_score(away_p)
    return (home_quality < away_quality) == home_favored
