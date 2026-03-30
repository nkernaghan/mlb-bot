import requests
from config import OPENWEATHERMAP_API_KEY, WEATHER_API_BASE
from modules.data.park_factors import get_venue_coords, is_dome


def fetch_weather(venue_id, venue_name, game_time_utc=None):
    """Fetch weather for a venue. Returns None for dome stadiums."""
    if is_dome(venue_name):
        return {"dome": True, "wind_speed": 0, "wind_dir": 0, "temp_f": 72, "humidity": 50}

    if not OPENWEATHERMAP_API_KEY:
        return None

    lat, lon = get_venue_coords(venue_id)
    if not lat or not lon:
        return None

    try:
        url = f"{WEATHER_API_BASE}/weather"
        params = {"lat": lat, "lon": lon, "appid": OPENWEATHERMAP_API_KEY, "units": "imperial"}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        wind = data.get("wind", {})
        main = data.get("main", {})

        return {
            "dome": False,
            "temp_f": main.get("temp", 72),
            "humidity": main.get("humidity", 50),
            "wind_speed": wind.get("speed", 0),
            "wind_dir": wind.get("deg", 0),
            "description": data.get("weather", [{}])[0].get("description", ""),
        }
    except Exception:
        return None


def wind_run_impact(wind_speed, wind_dir, venue_name=None):
    """Estimate wind impact on run scoring.

    Wind blowing out (to CF, ~180deg) increases runs.
    Wind blowing in (from CF, ~0deg) decreases runs.
    Returns adjustment in runs (positive = more runs expected).
    """
    if wind_speed < 5:
        return 0.0

    # Normalize to how much wind is blowing "out" vs "in"
    # 180 degrees = blowing out to CF, 0 = blowing in
    import math
    out_component = math.cos(math.radians(wind_dir - 180))
    impact = out_component * (wind_speed / 10) * 0.5

    return round(impact, 2)


def temp_run_impact(temp_f):
    """Temperature impact on run scoring.

    Every 10F above 70 adds ~0.5 runs to expected total.
    """
    if temp_f is None:
        return 0.0
    return round((temp_f - 70) / 10 * 0.5, 2)
