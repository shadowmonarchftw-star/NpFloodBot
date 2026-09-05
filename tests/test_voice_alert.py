"""Unit tests for Nepali Voice Alert Synthesizer."""

from datetime import datetime, timezone
from pathlib import Path

from services.risk_evaluator import RiskAssessment, SeverityLevel
from services.voice_alert import generate_nepali_voice_alert


def test_voice_alert_generation_emergency(tmp_path):
    assessment = RiskAssessment(
        station_id="test_balkhu",
        station_name="Bagmati at Balkhu (Kathmandu)",
        river_name="Bagmati",
        basin="Bagmati River Basin",
        severity=SeverityLevel.EMERGENCY,
        current_level=8.0,
        warning_level=5.5,
        danger_level=7.0,
        rising_velocity=0.5,
        is_surging=True,
        upstream_catchment="Shivapuri",
        upstream_current_rain_mm=25.0,
        upstream_forecast_1h_mm=40.0,
        upstream_forecast_3h_mm=75.0,
        is_heavy_rain=True,
        compound_risk=True,
        risk_reasons=["Danger breached"],
        vulnerable_areas_ne="बल्खु सुकुम्बासी बस्ती",
        vulnerable_areas_en="Balkhu squatter settlements",
        assessed_at=datetime.now(timezone.utc),
        lead_time_formatted_ne="खतरा तह उल्लङ्घन अनुमान: ~० घण्टा २० मिनेट",
    )

    path = generate_nepali_voice_alert(assessment)
    assert path is not None
    assert path.exists()
    assert path.stat().st_size > 1000


def test_voice_alert_normal_returns_none():
    assessment = RiskAssessment(
        station_id="test_normal",
        station_name="Bagmati at Sundarijal",
        river_name="Bagmati",
        basin="Bagmati River Basin",
        severity=SeverityLevel.NORMAL,
        current_level=2.0,
        warning_level=4.5,
        danger_level=5.8,
        rising_velocity=-0.05,
        is_surging=False,
        upstream_catchment="Shivapuri",
        upstream_current_rain_mm=0.0,
        upstream_forecast_1h_mm=0.0,
        upstream_forecast_3h_mm=0.0,
        is_heavy_rain=False,
        compound_risk=False,
        risk_reasons=["Safe level"],
        vulnerable_areas_ne="सुन्दरीजल",
        vulnerable_areas_en="Sundarijal",
        assessed_at=datetime.now(timezone.utc),
    )
    path = generate_nepali_voice_alert(assessment)
    assert path is None
