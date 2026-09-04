"""Unit tests for Weather Ingestion Module."""

import pytest
from services.weather import (
    fetch_catchment_weather,
    CatchmentForecast,
    HEAVY_RAIN_THRESHOLD_MM_HR,
)


def test_fetch_catchment_weather_normal():
    forecast = fetch_catchment_weather(
        catchment_name="Shivapuri Ridge",
        latitude=27.80,
        longitude=85.39,
        force_mock=True,
    )
    assert isinstance(forecast, CatchmentForecast)
    assert forecast.catchment_name == "Shivapuri Ridge"
    assert forecast.is_heavy_rain is False
    assert forecast.forecast_1h_mm < HEAVY_RAIN_THRESHOLD_MM_HR


def test_fetch_catchment_weather_simulated_heavy_rain():
    forecast = fetch_catchment_weather(
        catchment_name="Phulchowki / Roshi Hills",
        latitude=27.58,
        longitude=85.52,
        force_mock=True,
        simulate_heavy_rain=True,
    )
    assert forecast.is_heavy_rain is True
    assert forecast.max_hourly_rain_mm >= HEAVY_RAIN_THRESHOLD_MM_HR
    assert "Cloudburst" in forecast.source or "Torrential" in forecast.weather_description
