from modules.data.odds import american_to_implied
from modules.models.confidence import calc_game_confidence, grade_pick
from modules.data.weather import wind_run_impact, temp_run_impact
from config import MARKET_WEIGHT, MODEL_WEIGHT, HOME_ADVANTAGE_RUNS


def predict_game(game, home_pitcher, away_pitcher, home_batting, away_batting,
                 bullpen_home, bullpen_away, park, umpire, weather, odds,
                 home_injuries=None, away_injuries=None,
                 home_rest=None, away_rest=None):
    """Run the game prediction model.

    Returns a prediction dict with projected winner, edge, confidence, grade.
    """
    reasons = []
    risks = []
    contradictions = 0

    # --- Injury impact ---
    home_il_pitchers = [i for i in (home_injuries or []) if i.get("position") == "P"]
    away_il_pitchers = [i for i in (away_injuries or []) if i.get("position") == "P"]
    home_il_hitters = [i for i in (home_injuries or []) if i.get("position") != "P"]
    away_il_hitters = [i for i in (away_injuries or []) if i.get("position") != "P"]

    if len(home_il_hitters) >= 3:
        risks.append(f"{game['home_team_name']} has {len(home_il_hitters)} position players on IL")
    if len(away_il_hitters) >= 3:
        risks.append(f"{game['away_team_name']} has {len(away_il_hitters)} position players on IL")

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
    # Positive barrel_edge = away team has more barrel upside → hurts home team
    barrel_edge = (away_barrel_matchup - home_barrel_matchup) / 100

    if home_barrel_matchup > 3 or away_barrel_matchup > 3:
        risks.append("Elevated barrel rate matchup — potential blowup risk")

    # --- Signal 4: Bullpen (ERA + WHIP composite) ---
    bp_home_era = bullpen_home.get("bullpen_era", 4.0) or 4.0
    bp_away_era = bullpen_away.get("bullpen_era", 4.0) or 4.0
    bp_home_whip = bullpen_home.get("bullpen_whip", 1.30) or 1.30
    bp_away_whip = bullpen_away.get("bullpen_whip", 1.30) or 1.30

    # Composite: ERA (70%) + WHIP-derived run proxy (30%). WHIP 1.0 ≈ 3.0 ERA equivalent.
    bp_home_composite = bp_home_era * 0.7 + (bp_home_whip * 3.0) * 0.3
    bp_away_composite = bp_away_era * 0.7 + (bp_away_whip * 3.0) * 0.3
    bp_edge = bp_away_composite - bp_home_composite  # Positive = home bullpen better

    if abs(bp_edge) > 0.5:
        better = "home" if bp_edge > 0 else "away"
        reasons.append(f"Bullpen edge: {game[f'{better}_team_name']} ({min(bp_home_era, bp_away_era):.2f} ERA, {min(bp_home_whip, bp_away_whip):.2f} WHIP)")

    # Bullpen fatigue adjustment
    if bullpen_home.get("fatigued"):
        bp_edge -= 0.3  # Fatigued home bullpen = less reliable
        risks.append(f"{game['home_team_name']} bullpen fatigued ({bullpen_home.get('pitchers_no_rest', 0)} arms with 0 days rest)")
    if bullpen_away.get("fatigued"):
        bp_edge += 0.3  # Fatigued away bullpen = advantage for home
        risks.append(f"{game['away_team_name']} bullpen fatigued ({bullpen_away.get('pitchers_no_rest', 0)} arms with 0 days rest)")

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

    # --- Signal 8: Recent form (last 3-5 starts) ---
    recent_form_adj = 0
    home_recent_era = home_pitcher.get("recent_era")
    away_recent_era = away_pitcher.get("recent_era")
    home_season_era = home_pitcher.get("era")
    away_season_era = away_pitcher.get("era")

    if home_recent_era and home_season_era and home_season_era > 0:
        home_form_delta = home_season_era - home_recent_era  # Positive = pitching better recently
        recent_form_adj += home_form_delta * 0.15
        if home_form_delta > 1.0:
            reasons.append(f"{game['home_pitcher_name']} hot — recent ERA {home_recent_era:.2f} vs season {home_season_era:.2f}")
        elif home_form_delta < -1.0:
            risks.append(f"{game['home_pitcher_name']} struggling — recent ERA {home_recent_era:.2f} vs season {home_season_era:.2f}")

    if away_recent_era and away_season_era and away_season_era > 0:
        away_form_delta = away_season_era - away_recent_era
        recent_form_adj -= away_form_delta * 0.15  # Subtract because away pitcher improving hurts home team

    # --- Signal 9: Travel/rest ---
    travel_adj = 0
    home_rest = home_rest or {}
    away_rest = away_rest or {}

    # Away team traveled to a new city = slight disadvantage
    if away_rest.get("traveled"):
        travel_adj += 0.1  # Slight home advantage boost
        risks.append(f"{game['away_team_name']} traveled (new city)")

    # Team coming off a day off = slight advantage (fresher bullpen, rested lineup)
    if home_rest.get("days_off", 0) > 0 and away_rest.get("days_off", 0) == 0:
        travel_adj += 0.1
        reasons.append(f"{game['home_team_name']} rested (day off)")
    elif away_rest.get("days_off", 0) > 0 and home_rest.get("days_off", 0) == 0:
        travel_adj -= 0.1
        reasons.append(f"{game['away_team_name']} rested (day off)")

    # --- Combine model signals into projected run differential ---
    pitcher_run_diff = -pitcher_edge
    lineup_run_diff = lineup_edge * 0.3
    bp_run_diff = bp_edge * 0.2

    model_home_runs_edge = (
        pitcher_run_diff +
        lineup_run_diff +
        bp_run_diff +
        barrel_edge * 0.15 +        # barrel matchup (small but real HR/XBH signal)
        home_adj +
        recent_form_adj +
        travel_adj +
        park_adjustment * 0.08 +     # park: persistent but partially baked into pitcher ERA
        weather_adj * 0.05           # weather: noisy, smallest environment factor
    )

    # --- Signal 11: Vegas blending ---
    market_implied_home = None
    if odds and odds.get("home_ml") is not None:
        market_implied_home = american_to_implied(odds["home_ml"])

    model_implied_home = _runs_edge_to_probability(model_home_runs_edge)

    # Market-led blend: 60/40 market/model — Vegas is sharper than the model
    if market_implied_home is not None:
        blended_home_prob = MARKET_WEIGHT * market_implied_home + MODEL_WEIGHT * model_implied_home
    else:
        blended_home_prob = model_implied_home

    # --- Check for contradictions ---
    if market_implied_home is not None:
        if (model_implied_home > 0.5 and market_implied_home < 0.45) or \
           (model_implied_home < 0.5 and market_implied_home > 0.55):
            contradictions += 1
            risks.append("Model and market disagree on winner")

    # --- Reverse Line Movement (sharp money signal) ---
    rlm = odds.get("rlm_signal") if odds else None
    if rlm:
        rlm_dir = rlm["direction"]
        rlm_div = abs(rlm["divergence"])
        rlm_adj = rlm_div * 0.005
        if rlm_dir == "home":
            blended_home_prob = min(0.85, blended_home_prob + rlm_adj)
            reasons.append(f"Sharp money favors {game['home_team_name']} ({rlm_div:.1f}% book divergence)")
        else:
            blended_home_prob = max(0.15, blended_home_prob - rlm_adj)
            reasons.append(f"Sharp money favors {game['away_team_name']} ({rlm_div:.1f}% book divergence)")

    # --- Determine pick ---
    # Pick the side the MODEL independently favors, then check for market edge
    pick_home = model_implied_home > 0.5
    pick_team = game["home_team_name"] if pick_home else game["away_team_name"]
    pick_prob = blended_home_prob if pick_home else (1 - blended_home_prob)

    edge = 0
    market_prob = None
    if market_implied_home is not None:
        market_prob = market_implied_home if pick_home else (1 - market_implied_home)
        edge = round((pick_prob - market_prob) * 100, 1)

        # Only flip to underdog if model INDEPENDENTLY favors them (>52% pre-blend)
        if edge < 0:
            opp_model_prob = (1 - model_implied_home) if pick_home else model_implied_home
            if opp_model_prob >= 0.52:
                pick_home = not pick_home
                pick_team = game["home_team_name"] if pick_home else game["away_team_name"]
                pick_prob = blended_home_prob if pick_home else (1 - blended_home_prob)
                market_prob = market_implied_home if pick_home else (1 - market_implied_home)
                edge = round((pick_prob - market_prob) * 100, 1)
                if edge > 0:
                    reasons.append(f"Value on underdog — market overvalues favorite by {edge:.1f}%")
            else:
                edge = 0  # No conviction on either side — PASS

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
        "market_value": round((market_prob if market_implied_home is not None else pick_prob) * 100, 1),
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
    """Score pitcher quality. Lower = better pitcher.

    Weighted ensemble: xERA, FIP, xFIP, SIERA, ERA.
    Early season (<5 starts): ERA gets more weight, xERA gets less (noisy on small samples).
    """
    starts = pitcher.get("games_started") or 0
    early = starts < 5

    if early:
        # ERA is more stable with few starts; xERA needs 50+ batters faced
        metrics = {
            "xera": (pitcher.get("xera"), 0.10),
            "fip": (pitcher.get("fip"), 0.25),
            "xfip": (pitcher.get("xfip"), 0.20),
            "siera": (pitcher.get("siera"), 0.15),
            "era": (pitcher.get("era"), 0.30),
        }
    else:
        metrics = {
            "xera": (pitcher.get("xera"), 0.30),
            "fip": (pitcher.get("fip"), 0.25),
            "xfip": (pitcher.get("xfip"), 0.20),
            "siera": (pitcher.get("siera"), 0.15),
            "era": (pitcher.get("era"), 0.10),
        }

    total_weight = 0
    weighted_sum = 0
    for val, weight in metrics.values():
        if val and val > 0:
            weighted_sum += val * weight
            total_weight += weight

    if total_weight > 0:
        return weighted_sum / total_weight
    return 4.50  # League average fallback


def _lineup_score(batting, opposing_pitcher):
    """Score a lineup's expected output against the opposing pitcher.

    Uses platoon splits when available — lineups hit differently vs LHP and RHP.
    """
    ops = batting.get("ops") or batting.get("team_ops") or 0.700
    wrc = batting.get("wrc_plus", 100) or 100
    k_rate = batting.get("k_rate") or batting.get("team_k_rate") or 22

    pitcher_hand = opposing_pitcher.get("throws")
    if pitcher_hand == "L":
        split_ops = batting.get("vs_lhp_ops")
        split_k = batting.get("vs_lhp_k_rate")
        if split_ops and split_ops > 0:
            ops = split_ops
        if split_k and split_k > 0:
            k_rate = split_k
    elif pitcher_hand == "R":
        split_ops = batting.get("vs_rhp_ops")
        split_k = batting.get("vs_rhp_k_rate")
        if split_ops and split_ops > 0:
            ops = split_ops
        if split_k and split_k > 0:
            k_rate = split_k

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
