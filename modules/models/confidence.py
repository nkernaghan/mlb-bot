from config import (
    BET_MIN_CONFIDENCE, BET_MIN_EDGE, LEAN_MIN_CONFIDENCE, LEAN_MIN_EDGE,
    K_BET_MIN_CONFIDENCE, K_BET_MIN_EDGE, K_LEAN_MIN_CONFIDENCE, K_LEAN_MIN_EDGE,
    NRFI_BET_MIN_CONFIDENCE, NRFI_BET_MIN_EDGE, NRFI_LEAN_MIN_CONFIDENCE, NRFI_LEAN_MIN_EDGE,
)


def grade_pick(confidence, edge, bet_type="game"):
    """Assign BET / LEAN / PASS grade based on confidence and edge.

    Edge must be positive (model sees value vs market) to qualify for BET/LEAN.
    K props and NRFI use lower confidence thresholds because they have a narrower
    data footprint than full game predictions.
    """
    if edge <= 0:
        return "PASS"
    if bet_type == "game":
        if confidence >= BET_MIN_CONFIDENCE and edge >= BET_MIN_EDGE:
            return "BET"
        elif confidence >= LEAN_MIN_CONFIDENCE and edge >= LEAN_MIN_EDGE:
            return "LEAN"
    elif bet_type == "strikeout":
        if confidence >= K_BET_MIN_CONFIDENCE and edge >= K_BET_MIN_EDGE:
            return "BET"
        elif confidence >= K_LEAN_MIN_CONFIDENCE and edge >= K_LEAN_MIN_EDGE:
            return "LEAN"
    elif bet_type == "nrfi":
        if confidence >= NRFI_BET_MIN_CONFIDENCE and edge >= NRFI_BET_MIN_EDGE:
            return "BET"
        elif confidence >= NRFI_LEAN_MIN_CONFIDENCE and edge >= NRFI_LEAN_MIN_EDGE:
            return "LEAN"
    return "PASS"


def calc_game_confidence(data_flags, signal_agreement, contradictions):
    """Calculate confidence score for game predictions (0-100)."""
    score = 0

    # Data availability (max 75)
    if data_flags.get("pitcher_stats"):
        score += 20
    if data_flags.get("lineup_confirmed"):
        score += 15
    if data_flags.get("bullpen_data"):
        score += 10
    if data_flags.get("umpire_known"):
        score += 10
    if data_flags.get("weather_data"):
        score += 10
    if data_flags.get("odds_available"):
        score += 10

    # Signal agreement bonuses (max 37)
    if signal_agreement.get("xera_fip_agree"):
        score += 15
    if signal_agreement.get("three_plus_aligned"):
        score += 12
    if signal_agreement.get("market_agrees"):
        score += 10

    # Penalties
    score -= contradictions * 8
    if data_flags.get("park_extreme"):
        score -= 10

    return max(0, min(100, score))


def calc_k_confidence(data_flags, signal_agreement):
    """Calculate confidence score for K prop predictions (0-100).

    Base data availability awards up to ~75 points; signal agreement bonuses up to
    an additional ~35.  Penalties are applied last.  Lineup-specific batter K-rates
    and market blending are worth extra because they meaningfully narrow uncertainty.
    """
    score = 0

    # Early-season penalty: blended stats are better than nothing, but less
    # reliable than mid-season data.  Discount confidence when sample is thin.
    if data_flags.get("early_season"):
        score -= 10

    # Data availability
    if data_flags.get("csw_data"):
        score += 20
    if data_flags.get("swstr_data"):
        score += 10
    if data_flags.get("opposing_k_rate"):
        score += 10  # team-level K rate
    if data_flags.get("lineup_batter_k_rates"):
        score += 10  # individual top-of-lineup batter K rates (more specific)
    if data_flags.get("recent_form"):
        score += 8
    if data_flags.get("umpire_zone"):
        score += 5
    if data_flags.get("line_available"):
        score += 7  # market line lets us measure edge
    if data_flags.get("market_blended"):
        score += 5  # model was blended with market implied — tighter estimate
    if data_flags.get("pitcher_bb_rate"):
        score += 5  # walk rate adjusts the batters-faced estimate — more precise

    # Signal agreement bonuses
    if signal_agreement.get("csw_swstr_elite"):
        score += 15
    if signal_agreement.get("opposing_k_high"):
        score += 8
    if signal_agreement.get("lineup_k_high"):
        score += 7  # top batters have above-average individual K rates
    if signal_agreement.get("k_friendly_park"):
        score += 5
    if signal_agreement.get("strong_model_market_agreement"):
        score += 10  # model >= 1.0 K above the market line — strong directional edge

    # Penalties
    if data_flags.get("pitch_count_concern"):
        score -= 10
    if data_flags.get("k_trending_down"):
        score -= 8

    return max(0, min(100, score))


def calc_nrfi_confidence(data_flags, signal_agreement):
    """Calculate confidence score for NRFI predictions (0-100).

    Data completeness awards up to ~75 points; agreement bonuses up to ~47.
    Penalties reduce score for known risk factors.  Leadoff K-rate and fstrike
    data are given more weight because they directly model first-inning outcomes.
    """
    score = 0

    # Early-season penalty: blended stats fill gaps but are less reliable
    if data_flags.get("early_season"):
        score -= 10

    # Data availability
    if data_flags.get("both_fips_known"):
        score += 22
    if data_flags.get("first_inning_era"):
        score += 15
    if data_flags.get("leadoff_data"):
        score += 8
    if data_flags.get("leadoff_k_rate_known"):
        score += 7  # individual leadoff batter K rate narrows first-PA outcome
    if data_flags.get("umpire_known"):
        score += 5
    if data_flags.get("odds_available"):
        score += 8
    if data_flags.get("fstrike_data"):
        score += 10  # first-pitch strike % is a direct first-inning predictor

    # Signal agreement bonuses
    if signal_agreement.get("both_fip_low"):
        score += 15
    if signal_agreement.get("both_fstrike_high"):
        score += 12  # raised — strong first-inning predictor
    if signal_agreement.get("both_nrfi_high"):
        score += 12
    if signal_agreement.get("leadoff_k_high"):
        score += 8   # high-K leadoff batter benefits NRFI (likely 1st PA is an out)
    if signal_agreement.get("k_park_ump_combo"):
        score += 8

    # Penalties
    if data_flags.get("pitcher_bad_first_inning"):
        score -= 15
    if data_flags.get("elite_leadoff"):
        score -= 10
    if data_flags.get("hitter_park_warm"):
        score -= 10

    return max(0, min(100, score))
