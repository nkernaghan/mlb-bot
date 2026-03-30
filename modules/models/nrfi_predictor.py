from modules.data.odds import american_to_implied
from modules.models.confidence import calc_nrfi_confidence, grade_pick


def predict_nrfi(game, home_pitcher, away_pitcher, home_batting_top,
                 away_batting_top, park, umpire, weather, nrfi_odds):
    """Predict NRFI probability using FIP-primary ensemble model."""
    reasons = []
    risks = []

    # --- Primary signal: FIP for both pitchers ---
    home_fip = home_pitcher.get("fip") or home_pitcher.get("era") or 4.50
    away_fip = away_pitcher.get("fip") or away_pitcher.get("era") or 4.50

    home_scoreless_prob = _fip_to_scoreless_prob(home_fip)
    away_scoreless_prob = _fip_to_scoreless_prob(away_fip)

    # --- First-inning ERA adjustment ---
    home_1st_era = home_pitcher.get("first_inning_era")
    away_1st_era = away_pitcher.get("first_inning_era")

    if home_1st_era is not None:
        home_1st_adj = _first_inning_era_adjustment(home_1st_era)
        home_scoreless_prob *= (1 + home_1st_adj)

    if away_1st_era is not None:
        away_1st_adj = _first_inning_era_adjustment(away_1st_era)
        away_scoreless_prob *= (1 + away_1st_adj)

    # --- First-pitch strike rate ---
    home_fstrike = home_pitcher.get("f_strike_pct")
    away_fstrike = away_pitcher.get("f_strike_pct")

    if home_fstrike and home_fstrike > 65:
        home_scoreless_prob *= 1.03
        reasons.append(f"{game['home_pitcher_name']} F-Strike: {home_fstrike:.0f}%")
    if away_fstrike and away_fstrike > 65:
        away_scoreless_prob *= 1.03

    # --- Historical NRFI rate ---
    home_nrfi = home_pitcher.get("nrfi_rate")
    away_nrfi = away_pitcher.get("nrfi_rate")

    if home_nrfi and home_nrfi > 70:
        reasons.append(f"{game['home_pitcher_name']} NRFI rate: {home_nrfi:.0f}%")
    if away_nrfi and away_nrfi > 70:
        reasons.append(f"{game['away_pitcher_name']} NRFI rate: {away_nrfi:.0f}%")

    # --- Leadoff hitter quality ---
    away_leadoff = away_batting_top[0] if away_batting_top else {}
    home_leadoff = home_batting_top[0] if home_batting_top else {}

    away_leadoff_obp = away_leadoff.get("ops", 0.700)
    home_leadoff_obp = home_leadoff.get("ops", 0.700)

    if away_leadoff_obp > 0.850:
        home_scoreless_prob *= 0.95
        risks.append(f"Elite away leadoff hitter (OPS {away_leadoff_obp:.3f})")
    if home_leadoff_obp > 0.850:
        away_scoreless_prob *= 0.95
        risks.append(f"Elite home leadoff hitter (OPS {home_leadoff_obp:.3f})")

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

    # --- Edge vs market ---
    implied_prob = None
    edge = 0
    if nrfi_odds and nrfi_odds.get("nrfi_price"):
        implied_prob = american_to_implied(nrfi_odds["nrfi_price"])
        edge = round((nrfi_prob - implied_prob) * 100, 1)
    elif nrfi_prob > 0.55:
        # No market odds — estimate edge from model probability vs league average (~52% NRFI rate)
        edge = round((nrfi_prob - 0.52) * 100, 1)

    pick = "NRFI" if nrfi_prob > 0.58 or edge > 2 else "YRFI" if nrfi_prob < 0.42 or edge < -3 else "PASS"

    # --- FIP quality flags ---
    if home_fip < 3.50 and away_fip < 3.50:
        reasons.append(f"Both pitchers FIP < 3.50 ({home_fip:.2f} / {away_fip:.2f})")
    if home_fip > 4.50:
        risks.append(f"{game['home_pitcher_name']} FIP {home_fip:.2f} — shaky first inning risk")
    if away_fip > 4.50:
        risks.append(f"{game['away_pitcher_name']} FIP {away_fip:.2f} — shaky first inning risk")

    # --- Confidence ---
    data_flags = {
        "both_fips_known": home_pitcher.get("fip") is not None and away_pitcher.get("fip") is not None,
        "first_inning_era": home_1st_era is not None or away_1st_era is not None,
        "leadoff_data": bool(away_leadoff.get("ops")) or bool(home_leadoff.get("ops")),
        "umpire_known": umpire is not None,
        "odds_available": implied_prob is not None,
        "fstrike_data": home_fstrike is not None or away_fstrike is not None,
        "pitcher_bad_first_inning": (home_1st_era or 0) > 4.50 or (away_1st_era or 0) > 4.50,
        "elite_leadoff": away_leadoff_obp > 0.850 or home_leadoff_obp > 0.850,
        "hitter_park_warm": run_factor > 105 and (weather or {}).get("temp_f", 72) > 80,
    }
    signal_agreement = {
        "both_fip_low": home_fip < 3.50 and away_fip < 3.50,
        "both_fstrike_high": (home_fstrike or 0) > 63 and (away_fstrike or 0) > 63,
        "both_nrfi_high": (home_nrfi or 0) > 65 and (away_nrfi or 0) > 65,
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


def _fip_to_scoreless_prob(fip):
    """Convert FIP to probability of a scoreless half-inning.
    League avg FIP ~4.20 -> ~72% scoreless rate per half-inning.
    """
    base_rate = 0.72
    adjustment = (4.20 - fip) * 0.05
    return max(0.50, min(0.92, base_rate + adjustment))


def _first_inning_era_adjustment(era_1st):
    """Adjustment based on first-inning ERA vs league average (~4.20)."""
    diff = 4.20 - era_1st
    return max(-0.10, min(0.10, diff * 0.025))
