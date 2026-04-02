import sqlite3
import os
from config import DB_PATH


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            game_pk INTEGER PRIMARY KEY,
            game_date TEXT NOT NULL,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_team_name TEXT,
            away_team_name TEXT,
            venue_id INTEGER,
            venue_name TEXT,
            game_time_utc TEXT,
            day_night TEXT,
            status TEXT DEFAULT 'Scheduled',
            home_score INTEGER,
            away_score INTEGER,
            home_pitcher_id INTEGER,
            away_pitcher_id INTEGER,
            home_pitcher_name TEXT,
            away_pitcher_name TEXT,
            umpire_id INTEGER,
            umpire_name TEXT
        );

        CREATE TABLE IF NOT EXISTS odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            home_ml INTEGER,
            away_ml INTEGER,
            run_line_spread REAL,
            run_line_home_price INTEGER,
            run_line_away_price INTEGER,
            total REAL,
            over_price INTEGER,
            under_price INTEGER,
            bookmaker TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS k_prop_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            pitcher_id INTEGER NOT NULL,
            pitcher_name TEXT,
            fetched_at TEXT NOT NULL,
            line REAL,
            over_price INTEGER,
            under_price INTEGER,
            bookmaker TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS nrfi_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            nrfi_price INTEGER,
            yrfi_price INTEGER,
            bookmaker TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS pitcher_stats_cache (
            player_id INTEGER NOT NULL,
            player_name TEXT,
            team TEXT,
            date_cached TEXT NOT NULL,
            era REAL,
            fip REAL,
            xfip REAL,
            siera REAL,
            xera REAL,
            k_rate REAL,
            bb_rate REAL,
            csw REAL,
            swstr REAL,
            barrel_rate_against REAL,
            first_inning_era REAL,
            f_strike_pct REAL,
            innings_pitched REAL,
            games_started INTEGER,
            k_per_9 REAL,
            whip REAL,
            nrfi_rate REAL,
            PRIMARY KEY (player_id, date_cached)
        );

        CREATE TABLE IF NOT EXISTS batter_stats_cache (
            player_id INTEGER NOT NULL,
            player_name TEXT,
            team TEXT,
            date_cached TEXT NOT NULL,
            ops REAL,
            k_rate REAL,
            bb_rate REAL,
            barrel_rate REAL,
            xba REAL,
            xslg REAL,
            xwoba REAL,
            wrc_plus REAL,
            vs_lhp_ops REAL,
            vs_rhp_ops REAL,
            vs_lhp_k_rate REAL,
            vs_rhp_k_rate REAL,
            PRIMARY KEY (player_id, date_cached)
        );

        CREATE TABLE IF NOT EXISTS park_factors (
            venue_id INTEGER NOT NULL,
            venue_name TEXT,
            season INTEGER NOT NULL,
            run_factor INTEGER DEFAULT 100,
            hr_factor INTEGER DEFAULT 100,
            k_factor INTEGER DEFAULT 100,
            bb_factor INTEGER DEFAULT 100,
            PRIMARY KEY (venue_id, season)
        );

        CREATE TABLE IF NOT EXISTS umpire_stats (
            umpire_id INTEGER NOT NULL,
            umpire_name TEXT,
            season INTEGER NOT NULL,
            accuracy_pct REAL,
            consistency_pct REAL,
            k_plus REAL,
            favor REAL,
            games_behind_plate INTEGER,
            PRIMARY KEY (umpire_id, season)
        );

        CREATE TABLE IF NOT EXISTS bullpen_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            pitcher_id INTEGER NOT NULL,
            pitcher_name TEXT,
            pitches_thrown INTEGER,
            innings_pitched REAL,
            days_rest INTEGER,
            era REAL,
            fip REAL
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            bet_type TEXT NOT NULL,
            pick TEXT NOT NULL,
            pick_detail TEXT,
            pitcher_name TEXT,
            confidence INTEGER,
            edge REAL,
            model_value REAL,
            market_value REAL,
            grade TEXT,
            reasons TEXT,
            risks TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_pk INTEGER NOT NULL,
            bet_type TEXT NOT NULL,
            pick TEXT NOT NULL,
            result TEXT,
            actual_outcome TEXT,
            edge_at_pick REAL,
            confidence_at_pick INTEGER,
            grade TEXT,
            graded_at TEXT,
            FOREIGN KEY (game_pk) REFERENCES games(game_pk)
        );

        CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
        CREATE INDEX IF NOT EXISTS idx_odds_game ON odds(game_pk);
        CREATE INDEX IF NOT EXISTS idx_predictions_game ON predictions(game_pk);
        CREATE INDEX IF NOT EXISTS idx_predictions_type ON predictions(bet_type);
        CREATE INDEX IF NOT EXISTS idx_results_type ON results(bet_type);
        CREATE INDEX IF NOT EXISTS idx_results_date ON results(graded_at);
        CREATE INDEX IF NOT EXISTS idx_pitcher_cache ON pitcher_stats_cache(player_id, date_cached);
        CREATE INDEX IF NOT EXISTS idx_batter_cache ON batter_stats_cache(player_id, date_cached);
    """)

    # Migrations: add columns that may be missing from older databases
    for table, column, col_type in [
        ("predictions", "pitcher_name", "TEXT"),
        ("results", "grade", "TEXT"),
    ]:
        try:
            cursor.execute(f"SELECT {column} FROM {table} LIMIT 0")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
