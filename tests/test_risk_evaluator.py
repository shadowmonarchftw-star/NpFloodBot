"""Unit tests for Risk Assessment Engine."""

from datetime import datetime, timezone
import pytest
from services.hydrology import RiverReading
from services.risk_evaluator import evaluate_risk, SeverityLevel
from services.weather import CatchmentForecast


@pytest.fixture
def base_reading():
    return RiverReading(
        station_id="bagmati_balkhu",
        station_name="Bagmati at Balkhu (Kathmandu)",
        river_name="Bagmati",
        basin="Bagmati Basin",
        current_level=3.0,
        warning_level=5.5,
        danger_level=7.0,
        rising_velocity=0.02,
        status="STEADY",
        upstream_catchment="Shivapuri",
        upstream_lat=27.8,
        upstream_lon=85.39,
        vulnerable_areas_ne="बल्खु, सुकुम्बासी बस्ती",
        vulnerable_areas_en="Balkhu, squatter settlements",
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def base_weather():
    return CatchmentForecast(
        catchment_name="Shivapuri",
        latitude=27.8,
        longitude=85.39,
        current_rain_mm=1.0,
        forecast_1h_mm=2.0,
        forecast_3h_mm=5.0,
        max_hourly_rain_mm=2.0,
        is_heavy_rain=False,
        weather_description="Light rain",
        timestamp=datetime.now(timezone.utc),
    )


def test_evaluate_risk_normal(base_reading, base_weather):
    risk = evaluate_risk(base_reading, base_weather)
    assert risk.severity == SeverityLevel.NORMAL
    assert not risk.compound_risk
    assert not risk.is_surging
    assert not risk.requires_immediate_alert


def test_evaluate_risk_advisory_water_elevated(base_reading, base_weather):
    # 82% of warning (5.5 * 0.82 = 4.51m)
    elevated_reading = base_reading.model_copy(update={"current_level": 4.55})
    risk = evaluate_risk(elevated_reading, base_weather)
    assert risk.severity == SeverityLevel.ADVISORY


def test_evaluate_risk_warning_level_exceeded(base_reading, base_weather):
    warn_reading = base_reading.model_copy(update={"current_level": 5.8})
    risk = evaluate_risk(warn_reading, base_weather)
    assert risk.severity == SeverityLevel.WARNING
    assert risk.requires_immediate_alert is True


def test_evaluate_risk_danger_breach_emergency(base_reading, base_weather):
    danger_reading = base_reading.model_copy(update={"current_level": 7.3, "rising_velocity": 0.45})
    risk = evaluate_risk(danger_reading, base_weather)
    assert risk.severity == SeverityLevel.EMERGENCY
    assert risk.requires_immediate_alert is True
    assert any("CRITICAL DANGER BREACH" in r for r in risk.risk_reasons)


def test_compound_risk_escalates_to_emergency(base_reading, base_weather):
    # Water is at warning level (5.6m), and torrential upstream rain (35mm/hr)
    warn_reading = base_reading.model_copy(update={"current_level": 5.6, "rising_velocity": 0.38})
    cloudburst_weather = base_weather.model_copy(
        update={
            "forecast_1h_mm": 35.0,
            "max_hourly_rain_mm": 35.0,
            "is_heavy_rain": True,
        }
    )
    risk = evaluate_risk(warn_reading, cloudburst_weather)
    assert risk.compound_risk is True
    # Compound threat must escalate to EMERGENCY immediately
    assert risk.severity == SeverityLevel.EMERGENCY
    assert any("COMPOUND EXTREME RISK" in r for r in risk.risk_reasons)


def test_rapid_surge_detection(base_reading, base_weather):
    surging_reading = base_reading.model_copy(update={"current_level": 4.9, "rising_velocity": 0.45})
    risk = evaluate_risk(surging_reading, base_weather)
    assert risk.is_surging is True
    assert risk.severity == SeverityLevel.WARNING
