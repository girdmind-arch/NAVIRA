from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from backend.app import main
from backend.app.services.weather import OpenWeatherAgent


def test_openweather_route_weather_fetches_current_and_forecast():
    urls = []

    def fetch(url):
        urls.append(url)
        if "/weather?" in url:
            return {
                "cod": 200,
                "name": "Delhi",
                "dt": 1793340000,
                "main": {"temp": 28.4, "feels_like": 31.2, "humidity": 61},
                "wind": {"speed": 3.0},
                "weather": [{"description": "light rain", "icon": "10d"}],
            }
        return {"cod": "200", "list": [
            {"dt_txt": "2026-10-30 12:00:00", "main": {"temp": 27}, "weather": [{"description": "rain", "icon": "10d"}], "pop": 0.65}
        ]}

    result = OpenWeatherAgent(api_key="test-secret", fetcher=fetch).route_weather([[77.2, 28.6], [77.3, 28.7]])

    assert len(urls) == 4
    assert result["status"] == "available"
    assert result["locations"][0]["location"] == "Delhi"
    assert result["locations"][0]["current"]["temperature_c"] == 28
    assert result["locations"][0]["current"]["wind_speed_kmh"] == 10.8
    assert result["locations"][0]["forecast"][0]["rain_probability"] == 65
    assert result["locations"][0]["rain_probability_percent"] == 65
    assert all(parse_qs(urlparse(url).query)["appid"] == ["test-secret"] for url in urls)


def test_openweather_missing_key_and_cache():
    def fail(_url):
        raise AssertionError("provider must not be called without a key")

    assert OpenWeatherAgent(api_key="", fetcher=fail).route_weather([[77, 28], [77.1, 28.1]])["status"] == "unconfigured"

    calls = []
    def fetch(url):
        calls.append(url)
        if "/weather?" in url:
            return {"name": "Delhi", "main": {"temp": 28, "feels_like": 29, "humidity": 60}, "weather": [{"description": "clear sky"}]}
        return {"list": []}

    agent = OpenWeatherAgent(api_key="key", fetcher=fetch)
    agent.route_weather([[77, 28], [77.1, 28.1]])
    agent.route_weather([[77, 28], [77.1, 28.1]])
    assert len(calls) == 4


def test_route_weather_validates_coordinates_and_endpoint_is_registered(monkeypatch):
    with pytest.raises(ValidationError):
        main.RouteWeatherIn(coordinates=[[181, 28], [77, 28]])
    with pytest.raises(ValidationError):
        main.RouteWeatherIn(coordinates=[[77, 28], [float("nan"), 28]])
    assert "/api/v1/routes/weather" in main.app.openapi()["paths"]
    monkeypatch.setattr(main, "get_route_weather", lambda coordinates: {"status": "unconfigured"})
    body = main.RouteWeatherIn(coordinates=[[77, 28], [77.1, 28.1]])
    assert main.route_weather(body) == {"status": "unconfigured"}
