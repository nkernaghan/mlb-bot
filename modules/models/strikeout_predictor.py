from modules.data.odds import american_to_implied
from modules.models.confidence import calc_k_confidence, grade_pick
from config import (
    LEAGUE_AVG_K_RATE, LEAGUE_AVG_FIP,
    K_MARKET_WEIGHT, K_MODEL_WEIGHT,
    UMP_K_IMPACT_PER_POINT,
    TTOP_75_ADJUSTMENT, TTOP_85_ADJUSTMENT,
)


# Factor weights (sum to 1.0)
W_CSW = 0.20
W_SWSTR = 0.10
W_K_RATE = 0.20
W_OPP_K_RATE = 0.15
W_PITCH_COUNT = 0.10
W_RECENT_FORM = 0.10
W_PARK_UMP = 0.05
W_XFIP = 0.10  # xFIP-derived K expectation


def predict_strikeouts(
    game,
    pitcher,
    opposing_batting,
    park,
    umpire,
    weather,
    k_prop_odds,
    *,
    opp_batter_k_rates: list[float] | None = None,
    pitcher_bb_rate: float | None = None,
):
    """Predict starting pitcher strikeout total using 8-factor weighted model.

    Args:
        game: Game dict from the schedule.
        pitcher: Pitcher stats dict (from fetch_pitcher_stats).
        opposing_batting: Team batting stats dict for the opposing lineup.
        park: Park factor dict.
        umpire: Umpire stats dict or None.
        weather: Weather dict or None.
        k_prop_odds: Odds dict for this pitcher's K prop, or None.
        opp_batter_k_rates: Individual K-rates (float, %) for the top batters in
            the opposing lineup (typically top 3).  None if lineups not confirmed.
        pitcher_bb_rate: Pitcher's season walk rate (%).  Higher walk rate means
            more batters faced per inning, which creates additional K opportunities.
    """
    reasons = []

    # --- Opener / piggyback skip ---
    # Pitchers with < 3 games started and avg IP < 4.0 are likely openers who
    # won't work deep enough to hit high K lines.  Skip the prediction entirely.
    gs = pitcher.get("games_started", 0) or 0
    ip = pitcher.get("innings_pitched", 0) or 0
    avg_ip_check = (ip / gs) if gs > 0 else 0
    if gs < 3 and avg_ip_check < 4.0:
        return _empty_prediction(game, "Likely opener/piggyback — insufficient starts for K prediction")

    # --- Factor 1: CSW% (Called Strikes + Whiffs) ---
    csw = pitcher.get("csw")
    csw_ks = _csw_to_expected_ks(csw, _estimate_batters_faced(pitcher)) if csw else None

    # --- Factor 2: SwStr% ---
    swstr = pitcher.get("swstr")
    swstr_ks = _swstr_to_expected_ks(swstr, _estimate_batters_faced(pitcher)) if swstr else None

    # --- Factor 3: Season K% ---
    k_rate = pitcher.get("k_rate")
    season_ks = _k_rate_to_expected_ks(k_rate, pitcher) if k_rate else None

    # --- Factor 4: Opposing lineup K% ---
    # Prefer individual batter K-rates when available; fall back to team average.
    opp_k_rate = opposing_batting.get("k_rate") or opposing_batting.get("team_k_rate")
    top_batter_k_rates: list[float] = opp_batter_k_rates or []
    if top_batter_k_rates:
        # Blend individual top-of-order K-rates with the team average for a
        # more precise estimate of what this lineup will produce.
        avg_top_k = sum(top_batter_k_rates) / len(top_batter_k_rates)
        if opp_k_rate:
            opp_k_rate = round(avg_top_k * 0.5 + opp_k_rate * 0.5, 1)
        else:
            opp_k_rate = avg_top_k
        if avg_top_k > 25:
            reasons.append(
                f"Top-of-order K-rate avg {avg_top_k:.1f}% "
                f"({', '.join(f'{r:.0f}%' for r in top_batter_k_rates)})"
            )
    elif opp_k_rate and opp_k_rate > 25:
        reasons.append(f"Opposing lineup K rate: {opp_k_rate:.1f}% (above average)")

    opp_adjustment = _opposing_k_adjustment(opp_k_rate) if opp_k_rate else 0

    # --- Factor 4b: Walk-rate batters-faced adjustment ---
    # A higher BB rate means the pitcher works deeper into counts and faces more
    # batters per inning.  Each extra batter faced is a K opportunity.
    bb_rate = pitcher_bb_rate if pitcher_bb_rate is not None else pitcher.get("bb_rate")
    bb_batters_bonus = 0.0
    if bb_rate is not None:
        # League avg BB% ~8.5%.  Each extra percentage point above avg ≈ +0.12 extra
        # batters per start, which translates to roughly +0.03 expected Ks.
        bb_batters_bonus = max(-0.5, min(0.5, (bb_rate - 8.5) * 0.03))

    # --- Factor 5: Pitch count / innings expectation ---
    expected_batters = _estimate_batters_faced(pitcher)
    # Project Ks from batters-faced estimate alone (independent of K-rate factor)
    # Uses league-average K rate as baseline, adjusted by this pitcher's workload
    pitch_count_ks = round(expected_batters * (LEAGUE_AVG_K_RATE / 100), 1) if expected_batters else None

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
    ump_k_adjustment = 0.0
    ump_k_available = umpire is not None and umpire.get("k_plus") is not None
    if ump_k_available:
        # Empirical research: umpire K+ swings total Ks by 0.8–1.4 per start.
        # UMP_K_IMPACT_PER_POINT converts the normalised K+ score to actual Ks.
        ump_k_adjustment = umpire["k_plus"] * UMP_K_IMPACT_PER_POINT  # type: ignore[operator]
        if abs(ump_k_adjustment) >= 0.4:
            direction = "favors Ks" if ump_k_adjustment > 0 else "suppresses Ks"
            reasons.append(
                f"Umpire {umpire.get('umpire_name', 'unknown')} K+ = "
                f"{umpire['k_plus']:.1f} ({direction})"
            )

    # --- Factor 8: xFIP-derived K expectation ---
    xfip = pitcher.get("xfip")
    xfip_ks = _xfip_to_expected_ks(xfip, expected_batters) if xfip else None

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
        # Use expected_batters * league-avg K rate as neutral baseline, then apply
        # the opposing lineup adjustment. This avoids double-counting season_ks.
        neutral_ks = expected_batters * (LEAGUE_AVG_K_RATE / 100)
        components.append(neutral_ks * (1 + opp_adjustment) * W_OPP_K_RATE)
        weights_used.append(W_OPP_K_RATE)
    if pitch_count_ks is not None:
        components.append(pitch_count_ks * W_PITCH_COUNT)
        weights_used.append(W_PITCH_COUNT)
    if xfip_ks is not None:
        components.append(xfip_ks * W_XFIP)
        weights_used.append(W_XFIP)

    # Recent form
    base_ks = season_ks or csw_ks or 6.0
    components.append((base_ks + form_adjustment) * W_RECENT_FORM)
    weights_used.append(W_RECENT_FORM)

    # Park + umpire (park factor applied to the base; ump applied post-blend below)
    components.append(base_ks * park_k_factor * W_PARK_UMP)
    weights_used.append(W_PARK_UMP)

    if not weights_used:
        return _empty_prediction(game, "Insufficient data for K prediction")

    # Normalize weights
    total_weight = sum(weights_used)
    model_ks = sum(components) / total_weight if total_weight > 0 else 6.0

    # Apply post-blend additive adjustments
    model_ks += ump_k_adjustment
    model_ks += bb_batters_bonus
    model_ks = max(1.0, min(15.0, round(model_ks, 1)))  # cap to sane range

    # --- Times Through the Order (TTOP) adjustment for high K lines ---
    # Applied BEFORE market blending so the haircut reflects the model's view,
    # not a post-blend distortion that can flip OVER to UNDER.
    line = None
    risks = []
    if k_prop_odds:
        line = k_prop_odds.get("line")
    # Detect if line is from a real sportsbook — only DraftKings/FanDuel qualify
    # PrizePicks and Underdog are DFS platforms, not real books
    real_books = ("draftkings", "fanduel", "betmgm", "caesars", "pointsbet", "betrivers")
    is_real_book = k_prop_odds.get("bookmaker", "") in real_books if k_prop_odds else False

    if line is not None:
        if line >= 9.0:
            model_ks = round(model_ks * TTOP_85_ADJUSTMENT, 1)
            risks.append("High line (9.0+) — TTOP risk (12% haircut applied)")
        elif line >= 7.5:
            model_ks = round(model_ks * TTOP_75_ADJUSTMENT, 1)
            risks.append("High line (7.5+) — TTOP risk (8% haircut applied)")

    # --- Market blending ---
    # Only blend with real sportsbook lines. PrizePicks lines are generic
    # (often 4.5 for everyone) and would dilute the model's edge.
    market_blended = False
    if line is not None and is_real_book:
        blended_ks = round(
            K_MODEL_WEIGHT * model_ks + K_MARKET_WEIGHT * line, 1
        )
        model_ks = blended_ks
        market_blended = True

    # --- Edge calculation ---
    edge = 0
    if line is not None:
        edge = round(model_ks - line, 1)

    pick = "OVER" if edge > 0.5 else "UNDER" if edge < -0.5 else "PASS"
    if line is None:
        pick = "PASS"

    # Alternate line logic: when the over juice is worse than -110,
    # recommend the flat lower number (e.g., "6 Ks" instead of "OVER 6.5").
    alt_line = None
    if pick == "OVER" and line is not None and k_prop_odds:
        over_price = k_prop_odds.get("over_price")
        if over_price is not None and over_price < -110:
            alt_line = line - 0.5

    if alt_line is not None:
        pick_detail = f"OVER {int(alt_line)} Ks (juice on {line} is {over_price})"
    elif line:
        pick_detail = f"{pick} {line}"
    else:
        pick_detail = f"Model: {model_ks} Ks"

    # Strong signal agreement: model substantially above market line
    strong_agreement = line is not None and (model_ks - line) >= 1.0

    # --- Confidence ---
    pitcher_ip = pitcher.get("innings_pitched") or 0
    data_flags = {
        "early_season": pitcher_ip < 20,
        "csw_data": csw is not None,
        "swstr_data": swstr is not None,
        "opposing_k_rate": opp_k_rate is not None,
        "lineup_batter_k_rates": bool(top_batter_k_rates),
        "recent_form": recent_k9 is not None,
        "umpire_zone": ump_k_available,
        "line_available": line is not None,
        "market_blended": market_blended,
        "pitcher_bb_rate": bb_rate is not None,
        "pitch_count_concern": expected_batters < 18,
        "k_trending_down": form_adjustment < -0.3,
    }
    signal_agreement = {
        "csw_swstr_elite": (csw or 0) > 30 and (swstr or 0) > 12,
        "opposing_k_high": (opp_k_rate or 0) > 25,
        "lineup_k_high": bool(top_batter_k_rates) and (
            sum(top_batter_k_rates) / len(top_batter_k_rates) > 25
        ),
        "k_friendly_park": (park.get("k_factor", 100) or 100) > 102,
        "strong_model_market_agreement": strong_agreement,
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
        "risks": risks[:3],
        "expected_batters": expected_batters,
        "alt_line": alt_line,
    }


def _csw_to_expected_ks(csw, batters_faced=24):
    """Convert CSW% to expected strikeouts.

    Calibration: league avg CSW ~29% with ~22% K rate over ~24 batters ≈ 5.3 Ks.
    ~30% CSW ≈ ~23% K rate. CSW correlates with K rate at ~0.85.
    Formula: Ks = (CSW/100) * batters * 0.78 (empirical K-per-CSW-contact ratio).
    """
    if not csw:
        return None
    return round(csw / 100 * batters_faced * 0.78, 1)


def _swstr_to_expected_ks(swstr, batters_faced=24):
    """Convert SwStr% to expected Ks.

    Calibration: league avg SwStr ~11.5% with ~22% K rate.
    SwStr is a subset of total misses — roughly 1.9x multiplier to K rate.
    Formula: Ks = (SwStr/100) * batters * 1.9.
    """
    if not swstr:
        return None
    return round(swstr / 100 * batters_faced * 1.9, 1)


def _xfip_to_expected_ks(xfip, batters_faced=24):
    """Derive expected Ks from xFIP.

    xFIP normalizes HR/FB rate — lower xFIP correlates with higher K ability.
    League avg xFIP ~LEAGUE_AVG_FIP, avg K/9 ~8.5.
    Each 0.5 xFIP below avg ≈ +0.8 K/9.
    """
    if not xfip or xfip <= 0:
        return None
    k_per_9 = 8.5 + (LEAGUE_AVG_FIP - xfip) * 1.6
    avg_innings = batters_faced / 4.3  # ~4.3 batters per inning
    return round(max(1.0, k_per_9 * avg_innings / 9), 1)


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
    """Adjustment factor based on opposing lineup K rate.

    League avg is LEAGUE_AVG_K_RATE (~22%).  Returns a fractional multiplier
    so that a lineup 5pp above average adds ~5% to expected Ks.
    """
    if not opp_k_rate:
        return 0
    return (opp_k_rate - LEAGUE_AVG_K_RATE) / 100


def _empty_prediction(game, reason):
    return {
        "game_pk": game["game_pk"], "bet_type": "strikeout",
        "pitcher_name": None,
        "pick": "PASS", "pick_detail": reason,
        "model_ks": None, "line": None, "confidence": 0,
        "edge": 0, "grade": "PASS", "reasons": [reason], "risks": [],
        "expected_batters": 0,
    }
