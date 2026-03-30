from modules.data.odds import american_to_implied
from modules.models.confidence import calc_k_confidence, grade_pick


# Factor weights (sum to 1.0)
W_CSW = 0.25
W_SWSTR = 0.15
W_K_RATE = 0.15
W_OPP_K_RATE = 0.20
W_PITCH_COUNT = 0.10
W_RECENT_FORM = 0.10
W_PARK_UMP = 0.05


def predict_strikeouts(game, pitcher, opposing_batting, park, umpire, weather, k_prop_odds):
    """Predict starting pitcher strikeout total using 7-factor weighted model."""
    reasons = []

    # --- Factor 1: CSW% (Called Strikes + Whiffs) ---
    csw = pitcher.get("csw")
    csw_ks = _csw_to_expected_ks(csw) if csw else None

    # --- Factor 2: SwStr% ---
    swstr = pitcher.get("swstr")
    swstr_ks = _swstr_to_expected_ks(swstr) if swstr else None

    # --- Factor 3: Season K% ---
    k_rate = pitcher.get("k_rate")
    season_ks = _k_rate_to_expected_ks(k_rate, pitcher) if k_rate else None

    # --- Factor 4: Opposing lineup K% ---
    opp_k_rate = opposing_batting.get("k_rate") or opposing_batting.get("team_k_rate")
    opp_adjustment = _opposing_k_adjustment(opp_k_rate) if opp_k_rate else 0

    if opp_k_rate and opp_k_rate > 25:
        reasons.append(f"Opposing lineup K rate: {opp_k_rate:.1f}% (above average)")

    # --- Factor 5: Pitch count / innings expectation ---
    expected_batters = _estimate_batters_faced(pitcher)
    pitch_count_cap = expected_batters * (k_rate / 100) if k_rate else None

    # --- Factor 6: Recent form (last 3 starts) ---
    recent_k9 = pitcher.get("recent_k_per_9")
    season_k9 = pitcher.get("k_per_9", 0)
    form_adjustment = 0
    if recent_k9 and season_k9:
        form_adjustment = (recent_k9 - season_k9) / 9
        if form_adjustment > 0.3:
            reasons.append(f"K rate trending up (recent {recent_k9:.1f} K/9 vs season {season_k9:.1f})")
        elif form_adjustment < -0.3:
            reasons.append(f"K rate trending down (recent {recent_k9:.1f} K/9 vs season {season_k9:.1f})")

    # --- Factor 7: Park + umpire ---
    park_k_factor = (park.get("k_factor", 100) or 100) / 100
    ump_k_adjustment = 0
    if umpire and umpire.get("k_plus"):
        ump_k_adjustment = umpire["k_plus"] * 0.1

    # --- Weighted combination ---
    components = []
    weights_used = []

    if csw_ks is not None:
        components.append(csw_ks * W_CSW)
        weights_used.append(W_CSW)
        if csw > 30:
            reasons.append(f"Elite CSW: {csw:.1f}%")
    if swstr_ks is not None:
        components.append(swstr_ks * W_SWSTR)
        weights_used.append(W_SWSTR)
        if swstr > 12:
            reasons.append(f"High SwStr: {swstr:.1f}%")
    if season_ks is not None:
        components.append(season_ks * W_K_RATE)
        weights_used.append(W_K_RATE)
    if opp_k_rate is not None:
        components.append((season_ks or csw_ks or 6) * (1 + opp_adjustment) * W_OPP_K_RATE)
        weights_used.append(W_OPP_K_RATE)
    if pitch_count_cap is not None:
        components.append(pitch_count_cap * W_PITCH_COUNT)
        weights_used.append(W_PITCH_COUNT)

    # Recent form
    base_ks = (season_ks or csw_ks or 6)
    components.append((base_ks + form_adjustment) * W_RECENT_FORM)
    weights_used.append(W_RECENT_FORM)

    # Park + umpire
    components.append(base_ks * park_k_factor * W_PARK_UMP)
    weights_used.append(W_PARK_UMP)

    if not weights_used:
        return _empty_prediction(game, "Insufficient data for K prediction")

    # Normalize weights
    total_weight = sum(weights_used)
    model_ks = sum(components) / total_weight if total_weight > 0 else 6.0

    # Apply adjustments
    model_ks += ump_k_adjustment
    model_ks = max(1.0, min(15.0, round(model_ks, 1)))  # Cap to sane range

    # --- Edge calculation ---
    line = None
    edge = 0
    if k_prop_odds:
        line = k_prop_odds.get("line")
        if line:
            edge = round(model_ks - line, 1)

    pick = "OVER" if edge > 0.5 else "UNDER" if edge < -0.5 else "PASS"
    if not line:
        # No market line — still express a directional view for high-confidence projections
        pick = "PASS"
    pick_detail = f"{pick} {line}" if line else f"Model: {model_ks} Ks"

    # --- Confidence ---
    data_flags = {
        "csw_data": csw is not None,
        "swstr_data": swstr is not None,
        "opposing_k_rate": opp_k_rate is not None,
        "recent_form": recent_k9 is not None,
        "umpire_zone": umpire is not None and umpire.get("k_plus") is not None,
        "line_available": line is not None,
        "pitch_count_concern": expected_batters < 18,
        "k_trending_down": form_adjustment < -0.3,
    }
    signal_agreement = {
        "csw_swstr_elite": (csw or 0) > 30 and (swstr or 0) > 12,
        "opposing_k_high": (opp_k_rate or 0) > 25,
        "k_friendly_park": (park.get("k_factor", 100) or 100) > 102,
    }
    confidence = calc_k_confidence(data_flags, signal_agreement)
    grade = grade_pick(confidence, edge, "strikeout")

    return {
        "game_pk": game["game_pk"],
        "bet_type": "strikeout",
        "pitcher_id": pitcher.get("player_id"),
        "pitcher_name": pitcher.get("player_name"),
        "pick": pick,
        "pick_detail": pick_detail,
        "model_ks": model_ks,
        "line": line,
        "confidence": confidence,
        "edge": edge,
        "grade": grade,
        "reasons": reasons[:5],
        "expected_batters": expected_batters,
    }


def _csw_to_expected_ks(csw, avg_batters=24):
    """Convert CSW% to expected strikeouts. ~30% CSW = 7 Ks per 24 batters."""
    if not csw:
        return None
    return round(csw / 100 * avg_batters * 1.1, 1)


def _swstr_to_expected_ks(swstr, avg_batters=24):
    """Convert SwStr% to expected Ks. ~12% SwStr = 7 Ks."""
    if not swstr:
        return None
    return round(swstr / 100 * avg_batters * 2.4, 1)


def _k_rate_to_expected_ks(k_rate, pitcher):
    """Convert K% to expected Ks based on estimated batters faced."""
    batters = _estimate_batters_faced(pitcher)
    return round(k_rate / 100 * batters, 1)


def _estimate_batters_faced(pitcher):
    """Estimate batters faced based on innings pitched and games started."""
    ip = pitcher.get("innings_pitched", 0) or 0
    gs = pitcher.get("games_started", 1) or 1
    if gs > 0 and ip > 0:
        avg_ip = ip / gs
        avg_ip = min(avg_ip, 9.0)  # Cap at 9 innings per start
        return max(15, min(30, round(avg_ip * 4.3)))  # 15-30 batters
    return 24  # Default ~5.5 innings


def _opposing_k_adjustment(opp_k_rate):
    """Adjustment factor based on opposing lineup K rate. League avg ~22%."""
    if not opp_k_rate:
        return 0
    return (opp_k_rate - 22) / 100


def _empty_prediction(game, reason):
    return {
        "game_pk": game["game_pk"], "bet_type": "strikeout",
        "pick": "PASS", "pick_detail": reason,
        "model_ks": None, "line": None, "confidence": 0,
        "edge": 0, "grade": "PASS", "reasons": [reason], "expected_batters": 0,
    }
