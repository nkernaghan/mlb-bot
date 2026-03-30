from modules.models.nrfi_predictor import predict_nrfi, _fip_to_scoreless_prob, _first_inning_era_adjustment


def test_fip_to_scoreless_elite():
    prob = _fip_to_scoreless_prob(2.50)
    assert prob > 0.78


def test_fip_to_scoreless_bad():
    prob = _fip_to_scoreless_prob(5.50)
    assert prob < 0.68


def test_fip_to_scoreless_average():
    prob = _fip_to_scoreless_prob(4.20)
    assert abs(prob - 0.72) < 0.02


def test_first_inning_era_good():
    adj = _first_inning_era_adjustment(2.00)
    assert adj > 0


def test_first_inning_era_bad():
    adj = _first_inning_era_adjustment(6.00)
    assert adj < 0


def test_predict_nrfi_both_aces():
    game = {"game_pk": 1, "home_team_name": "Red Sox", "away_team_name": "Yankees",
            "home_pitcher_name": "Bello", "away_pitcher_name": "Cole"}
    home_p = {"fip": 2.80, "first_inning_era": 2.10, "f_strike_pct": 68, "nrfi_rate": 75}
    away_p = {"fip": 3.01, "first_inning_era": 2.50, "f_strike_pct": 66, "nrfi_rate": 71}
    park = {"run_factor": 100, "k_factor": 100}
    umpire = {"umpire_name": "Test Ump", "k_plus": 0.3}
    weather = {"dome": False, "temp_f": 65}
    nrfi_odds = {"nrfi_price": -120, "yrfi_price": 100}

    result = predict_nrfi(game, home_p, away_p, [], [], park, umpire, weather, nrfi_odds)
    assert result["nrfi_probability"] > 0.55
    assert result["pick"] in ("NRFI", "YRFI", "PASS")
    assert result["grade"] in ("BET", "LEAN", "PASS")


def test_predict_nrfi_bad_pitchers():
    game = {"game_pk": 2, "home_team_name": "Rockies", "away_team_name": "Reds",
            "home_pitcher_name": "BadP1", "away_pitcher_name": "BadP2"}
    home_p = {"fip": 5.20, "first_inning_era": 5.80}
    away_p = {"fip": 5.50, "first_inning_era": 6.10}
    park = {"run_factor": 115, "k_factor": 90}
    umpire = None
    weather = {"dome": False, "temp_f": 88}
    nrfi_odds = {"nrfi_price": 110, "yrfi_price": -130}

    result = predict_nrfi(game, home_p, away_p, [], [], park, umpire, weather, nrfi_odds)
    assert result["nrfi_probability"] < 0.55
