from modules.data.odds import american_to_implied
from modules.models.confidence import calc_nrfi_confidence, grade_pick
from config import LEAGUE_AVG_FIP, LEAGUE_AVG_NRFI_RATE, NRFI_FIRST_INNING_WEIGHT, NRFI_SEASON_WEIGHT


def predict_nrfi(game, home_pitcher, away_pitcher, home_batting_top,
                 away_batting_top, park, umpire, weather, nrfi_odds):
    """Predict NRFI probability using FIP-primary ensemble model."""
    reasons = []
    risks = []

    # --- Primary signal: FIP/xFIP/SIERA ensemble for both pitchers ---
    home_fip = _best_pitcher_metric(home_pitcher)
    away_fip = _best_pitcher_metric(away_pitcher)

    home_scoreless_prob = _fip_to_scoreless_prob(home_fip)
    away_scoreless_prob = _fip_to_scoreless_prob(away_fip)

    # --- First-inning ERA weighting ---
    # When first-inning ERA is available it is a stronger signal than season FIP
    # for the single half-inning we care about.  Blend: 60% first-inning ERA,
    # 40% season FIP probability.  Without first-inning ERA fall back to 100%
    # season FIP (original behaviour).
    home_1st_era = home_pitcher.get("first_inning_era")
    away_1st_era = away_pitcher.get("first_inning_era")

    if home_1st_era is not None:
        home_1st_scoreless = _fip_to_scoreless_prob(home_1st_era)
        home_scoreless_prob = (
            NRFI_FIRST_INNING_WEIGHT * home_1st_scoreless
            + NRFI_SEASON_WEIGHT * home_scoreless_prob
        )

    if away_1st_era is not None:
        away_1st_scoreless = _fip_to_scoreless_prob(away_1st_era)
        away_scoreless_prob = (
            NRFI_FIRST_INNING_WEIGHT * away_1st_scoreless
            + NRFI_SEASON_WEIGHT * away_scoreless_prob
        )

    # --- First-pitch strike rate ---
    # F-Strike% is a direct first-inning predictor: pitchers who throw more first-pitch
    # strikes work ahead in the count, generate more weak contact / strikeouts, and
    # face fewer full-count situations that lead to walks and big innings.
    # Threshold: league avg ~61%.  Each percentage point above 63% gives a 0.4%
    # boost to scoreless probability (was flat 3% for anything above 65%).
    home_fstrike = home_pitcher.get("f_strike_pct")
    away_fstrike = away_pitcher.get("f_strike_pct")

    if home_fstrike:
        if home_fstrike > 63:
            boost = min(0.06, (home_fstrike - 63) * 0.004)
            home_scoreless_prob *= (1 + boost)
            if home_fstrike > 65:
                reasons.append(f"{game['home_pitcher_name']} F-Strike: {home_fstrike:.0f}%")
        elif home_fstrike < 58:
            home_scoreless_prob *= 0.98
    if away_fstrike:
        if away_fstrike > 63:
            boost = min(0.06, (away_fstrike - 63) * 0.004)
            away_scoreless_prob *= (1 + boost)
            if away_fstrike > 65:
                reasons.append(f"{game['away_pitcher_name']} F-Strike: {away_fstrike:.0f}%")
        elif away_fstrike < 58:
            away_scoreless_prob *= 0.98

    # --- Historical NRFI rate ---
    # Pitchers with strong NRFI track records get a small probability boost;
    # pitchers who consistently give up first-inning runs get penalized.
    home_nrfi = home_pitcher.get("nrfi_rate")
    away_nrfi = away_pitcher.get("nrfi_rate")

    if home_nrfi and home_nrfi > 70:
        boost = min(0.04, (home_nrfi - 70) * 0.001)
        home_scoreless_prob *= (1 + boost)
        reasons.append(f"{game['home_pitcher_name']} NRFI rate: {home_nrfi:.0f}%")
    elif home_nrfi and home_nrfi < 40:
        home_scoreless_prob *= 0.97
    if away_nrfi and away_nrfi > 70:
        boost = min(0.04, (away_nrfi - 70) * 0.001)
        away_scoreless_prob *= (1 + boost)
        reasons.append(f"{game['away_pitcher_name']} NRFI rate: {away_nrfi:.0f}%")
    elif away_nrfi and away_nrfi < 40:
        away_scoreless_prob *= 0.97

    # --- Leadoff hitter quality ---
    away_leadoff = away_batting_top[0] if away_batting_top else {}
    home_leadoff = home_batting_top[0] if home_batting_top else {}

    away_leadoff_ops = away_leadoff.get("ops", 0.700)
    home_leadoff_ops = home_leadoff.get("ops", 0.700)

    if away_leadoff_ops > 0.850:
        home_scoreless_prob *= 0.95
        risks.append(f"Elite away leadoff hitter (OPS {away_leadoff_ops:.3f})")
    if home_leadoff_ops > 0.850:
        away_scoreless_prob *= 0.95
        risks.append(f"Elite home leadoff hitter (OPS {home_leadoff_ops:.3f})")

    # --- Leadoff K-rate adjustment ---
    # A high-K leadoff batter is likely to make an out in their first PA without
    # reaching base, which significantly lowers the chance of a first-inning run.
    # League avg batter K% ~22%.  For each pp above 28% we give a small boost;
    # for each pp below 16% (contact-heavy table-setter) we penalise.
    away_leadoff_k = away_leadoff.get("k_rate")
    home_leadoff_k = home_leadoff.get("k_rate")
    leadoff_k_rate_known = away_leadoff_k is not None and home_leadoff_k is not None

    if away_leadoff_k is not None:
        if away_leadoff_k > 28:
            k_boost = min(0.05, (away_leadoff_k - 28) * 0.003)
            home_scoreless_prob *= (1 + k_boost)
            if away_leadoff_k > 32:
                reasons.append(f"Away leadoff K-rate {away_leadoff_k:.0f}% — likely out in 1st PA")
        elif away_leadoff_k < 16:
            home_scoreless_prob *= 0.98

    if home_leadoff_k is not None:
        if home_leadoff_k > 28:
            k_boost = min(0.05, (home_leadoff_k - 28) * 0.003)
            away_scoreless_prob *= (1 + k_boost)
            if home_leadoff_k > 32:
                reasons.append(f"Home leadoff K-rate {home_leadoff_k:.0f}% — likely out in 1st PA")
        elif home_leadoff_k < 16:
            away_scoreless_prob *= 0.98

    # --- Team first-inning tendency ---
    # Teams with a strong offensive profile at the top of the order (high OPS,
    # low K-rate) put pressure on the first inning that FIP alone doesn't capture.
    # Proxy: top-3 OPS > .750 AND leadoff K% < 18% signals a table-setter lineup
    # that contacts the ball and gets on base — nudge YRFI probability by 4%.
    away_team_ops = (sum(b.get("ops", 0.0) for b in away_batting_top[:3]) / min(3, len(away_batting_top))) if away_batting_top else 0.0
    home_team_ops = (sum(b.get("ops", 0.0) for b in home_batting_top[:3]) / min(3, len(home_batting_top))) if home_batting_top else 0.0
    away_top_k = away_leadoff.get("k_rate")
    home_top_k = home_leadoff.get("k_rate")

    if away_team_ops > 0.750 and away_top_k is not None and away_top_k < 18:
        home_scoreless_prob *= 0.96
        risks.append(
            f"Away lineup: high OPS ({away_team_ops:.3f}) + contact leadoff "
            f"({away_top_k:.0f}% K) — 1st-inning scoring risk"
        )
    if home_team_ops > 0.750 and home_top_k is not None and home_top_k < 18:
        away_scoreless_prob *= 0.96
        risks.append(
            f"Home lineup: high OPS ({home_team_ops:.3f}) + contact leadoff "
            f"({home_top_k:.0f}% K) — 1st-inning scoring risk"
        )

    # --- Park factors ---
    run_factor = (park.get("run_factor", 100) or 100)
    if run_factor > 105:
        home_scoreless_prob *= 0.97
        away_scoreless_prob *= 0.97
        risks.append(f"Hitter-friendly park (factor {run_factor})")
    elif run_factor < 95:
        home_scoreless_prob *= 1.03
        away_scoreless_prob *= 1.03
        reasons.append(f"Pitcher-friendly park (factor {run_factor})")

    # --- Umpire ---
    if umpire and umpire.get("k_plus"):
        k_plus = umpire["k_plus"]
        if k_plus > 0.3:
            home_scoreless_prob *= 1.02
            away_scoreless_prob *= 1.02
            reasons.append(f"Umpire {umpire['umpire_name']} K+ = {k_plus:.1f}")

    # --- Weather ---
    if weather and not weather.get("dome"):
        temp = weather.get("temp_f", 72)
        if temp < 55:
            home_scoreless_prob *= 1.03
            away_scoreless_prob *= 1.03
            reasons.append(f"Cold weather ({temp:.0f}F) suppresses offense")
        elif temp > 85:
            home_scoreless_prob *= 0.97
            away_scoreless_prob *= 0.97
            risks.append(f"Hot weather ({temp:.0f}F) favors hitters")

    # --- Combined NRFI probability ---
    nrfi_prob = home_scoreless_prob * away_scoreless_prob
    nrfi_prob = max(0.30, min(0.85, nrfi_prob))

    # --- Market blending ---
    # When market NRFI odds exist, blend the model probability with the market-implied
    # probability (60% model, 40% market) so the final estimate is anchored to where
    # sharp books have set the line.
    implied_prob = None
    market_blended_nrfi = False
    if nrfi_odds and nrfi_odds.get("nrfi_price"):
        implied_prob = american_to_implied(nrfi_odds["nrfi_price"])
        blended_prob = round(0.60 * nrfi_prob + 0.40 * implied_prob, 3)
        nrfi_prob = max(0.30, min(0.85, blended_prob))
        market_blended_nrfi = True

    # --- Edge vs market ---
    edge = 0
    if implied_prob is not None:
        edge = round((nrfi_prob - implied_prob) * 100, 1)
    elif nrfi_prob > 0.55:
        # No market odds — estimate edge vs league average NRFI rate
        edge = round((nrfi_prob - LEAGUE_AVG_NRFI_RATE) * 100, 1)

    pick = "NRFI" if nrfi_prob > 0.58 or edge > 2 else "YRFI" if nrfi_prob < 0.42 or edge < -3 else "PASS"

    # --- FIP quality flags ---
    if home_fip < 3.50 and away_fip < 3.50:
        reasons.append(f"Both pitchers FIP < 3.50 ({home_fip:.2f} / {away_fip:.2f})")
    if home_fip > 4.50:
        risks.append(f"{game['home_pitcher_name']} FIP {home_fip:.2f} — shaky first inning risk")
    if away_fip > 4.50:
        risks.append(f"{game['away_pitcher_name']} FIP {away_fip:.2f} — shaky first inning risk")

    # --- Confidence ---
    home_ip = home_pitcher.get("innings_pitched") or 0
    away_ip = away_pitcher.get("innings_pitched") or 0
    data_flags = {
        "early_season": home_ip < 20 or away_ip < 20,
        "both_fips_known": (home_pitcher.get("fip") or home_pitcher.get("xfip") or home_pitcher.get("siera")) is not None and
                          (away_pitcher.get("fip") or away_pitcher.get("xfip") or away_pitcher.get("siera")) is not None,
        "first_inning_era": home_1st_era is not None or away_1st_era is not None,
        "leadoff_data": bool(away_leadoff.get("ops")) or bool(home_leadoff.get("ops")),
        "leadoff_k_rate_known": leadoff_k_rate_known,
        "umpire_known": umpire is not None,
        "odds_available": implied_prob is not None,
        "fstrike_data": home_fstrike is not None or away_fstrike is not None,
        "pitcher_bad_first_inning": (home_1st_era or 0) > 4.50 or (away_1st_era or 0) > 4.50,
        "elite_leadoff": away_leadoff_ops > 0.850 or home_leadoff_ops > 0.850,
        "hitter_park_warm": run_factor > 105 and (weather or {}).get("temp_f", 72) > 80,
    }
    signal_agreement = {
        "both_fip_low": home_fip < 3.50 and away_fip < 3.50,
        "both_fstrike_high": (home_fstrike or 0) > 63 and (away_fstrike or 0) > 63,
        "both_nrfi_high": (home_nrfi or 0) > 65 and (away_nrfi or 0) > 65,
        "leadoff_k_high": (
            (away_leadoff_k or 0) > 28 or (home_leadoff_k or 0) > 28
        ),
        "k_park_ump_combo": (park.get("k_factor", 100) or 100) > 100 and
                            umpire is not None and (umpire.get("k_plus", 0) or 0) > 0,
    }
    confidence = calc_nrfi_confidence(data_flags, signal_agreement)
    grade = grade_pick(confidence, edge, "nrfi")

    return {
        "game_pk": game["game_pk"],
        "bet_type": "nrfi",
        "pick": pick,
        "pick_detail": f"{pick} ({nrfi_prob*100:.1f}% vs {(implied_prob or 0)*100:.1f}% implied)",
        "nrfi_probability": round(nrfi_prob, 3),
        "implied_probability": round(implied_prob, 3) if implied_prob else None,
        "confidence": confidence,
        "edge": edge,
        "grade": grade,
        "reasons": reasons[:5],
        "risks": risks[:3],
        "home_fip": home_fip,
        "away_fip": away_fip,
    }


def _best_pitcher_metric(pitcher):
    """Get best available pitcher quality metric for NRFI. Prefers FIP > xFIP > SIERA > ERA."""
    fip = pitcher.get("fip")
    xfip = pitcher.get("xfip")
    siera = pitcher.get("siera")
    era = pitcher.get("era")

    available = [v for v in [fip, xfip, siera] if v and v > 0]
    if available:
        return sum(available) / len(available)  # Average of available advanced metrics
    return era or 4.50


def _fip_to_scoreless_prob(fip):
    """Convert FIP to probability of a scoreless half-inning.

    League avg FIP (LEAGUE_AVG_FIP) maps to ~72% scoreless rate per half-inning.
    Each point of FIP below average adds ~5pp to the scoreless probability.
    """
    base_rate = 0.72
    adjustment = (LEAGUE_AVG_FIP - fip) * 0.05
    return max(0.50, min(0.92, base_rate + adjustment))
