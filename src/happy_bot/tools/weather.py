"""Weather tool: current conditions, the next days, sunrise and sunset for a place.

Uses Open-Meteo (open-meteo.com), a free public weather service that needs no
account or key: its geocoding API turns the place name into coordinates and
its forecast API returns the weather there in the place's own time zone. Only
the place name the user asked about is sent, nothing else from the computer;
the tool is left out when the user's "local only" setting is on
(``tools/catalog.py``). Requests time out after ``TIMEOUT_SECONDS``.

The answer is short text: now (temperature, conditions from the WMO weather
code, wind), then each day's high, low, chance of rain, sunrise and sunset.
``weather_card`` reads that same text back into the popup's weather card
(``{"kind": "weather", "place", "now", "days"}``, drawn by WeatherCard.qml),
so the format and its reader live together here. ``read``: it changes nothing.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from .registry import RISK_READ, Tool, ToolFailure, object_schema

GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10
CONDITIONS = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
              51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
              61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
              71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers",
              81: "showers", 82: "heavy showers", 85: "snow showers", 86: "heavy snow showers",
              95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _get(url: str, parameters: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(parameters)}",
                                     headers={"User-Agent": "happy-bot"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read(2_000_000))
    except (OSError, ValueError) as error:
        raise ToolFailure(f"the weather service could not be reached: {error}") from error


def weather(arguments: dict[str, Any]) -> str:
    place = " ".join(str(arguments.get("place") or "").split())
    if not place or len(place) > 100:
        raise ToolFailure("'place' is required: a city or town name")
    days = arguments.get("days", 3)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 7:
        raise ToolFailure("'days' must be a whole number from 1 to 7")
    found = (_get(GEOCODING, {"name": place.split(",")[0], "count": 5, "format": "json"}).get("results") or [])
    hint = place.split(",")[1].strip().lower() if "," in place else ""
    if hint:
        found = [item for item in found if hint in f"{item.get('country', '')} {item.get('admin1', '')} "
                 f"{item.get('country_code', '')}".lower()] or found
    if not found:
        raise ToolFailure(f"no place called '{place}' was found; add the country, for example 'Paris, France'")
    spot = found[0]
    data = _get(FORECAST, {
        "latitude": spot["latitude"], "longitude": spot["longitude"], "timezone": "auto", "forecast_days": days,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset",
    })
    now, daily = data.get("current") or {}, data.get("daily") or {}
    name = ", ".join(part for part in (spot.get("name"), spot.get("admin1"), spot.get("country")) if part)
    lines = [f"{name}: now {now.get('temperature_2m')}°C (feels {now.get('apparent_temperature')}°C), "
             f"{CONDITIONS.get(now.get('weather_code'), 'unknown')}, wind {now.get('wind_speed_10m')} km/h"]
    for index, day in enumerate(daily.get("time") or []):
        def value(key: str) -> Any:
            series = daily.get(key) or []
            return series[index] if index < len(series) else "?"
        lines.append(f"{day}: {value('temperature_2m_min')}–{value('temperature_2m_max')}°C, "
                     f"{CONDITIONS.get(value('weather_code'), 'unknown')}, rain {value('precipitation_probability_max')}%, "
                     f"sunrise {str(value('sunrise'))[-5:]}, sunset {str(value('sunset'))[-5:]}")
    return "\n".join(lines) + "\n(Open-Meteo)"


_NOW = re.compile(r"^(?P<place>.+): now (?P<temperature>-?[\d.]+)°C \(feels (?P<feels>-?[\d.]+)°C\), "
                  r"(?P<conditions>[^,]+), wind (?P<wind>[\d.]+) km/h$")
_DAY = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}): (?P<low>-?[\d.]+)–(?P<high>-?[\d.]+)°C, (?P<conditions>[^,]+), "
                  r"rain (?P<rain>[\d?]+)%, sunrise (?P<sunrise>[\d:?]+), sunset (?P<sunset>[\d:?]+)$")


def weather_card(text: str) -> dict[str, Any] | None:
    """The weather card for ``weather``'s text, or None if the text is not in its format."""
    lines = text.splitlines()
    now = _NOW.match(lines[0]) if lines else None
    if now is None:
        return None
    days = [match.groupdict() for match in (_DAY.match(line) for line in lines[1:]) if match]
    return {"kind": "weather", "place": now["place"],
            "now": {key: now[key] for key in ("temperature", "feels", "conditions", "wind")}, "days": days}


def weather_tools() -> list[Tool]:
    return [Tool("weather", "Current weather and the next days' forecast, with sunrise and sunset, for a place.",
                 object_schema({"place": {"type": "string", "description": "City, optionally ', Country'"},
                                "days": {"type": "integer", "description": "1 to 7, default 3"}}, ["place"]),
                 RISK_READ, weather, summarize=lambda a: f"Check the weather in {a.get('place', '?')}",
                 card=weather_card)]
