"""Unit tests for Visual Chart Generator."""

from datetime import datetime, timezone
import pytest
from services.chart_generator import generate_station_chart, generate_basin_overview_chart
from services.risk_evaluator import RiskAssessment, SeverityLevel


@pytest.fixture
def sample_assessments():
    a1 = RiskAssessment(
        station_id="bagmati_balkhu",
        station_name="Bagmati at Balkhu (Kathmandu)",
        river_name="Bagmati",
        basin="Bagmati River Basin",
        severity=SeverityLevel.WARNING,
        current_level=5.9,
        warning_level=5.5,
        danger_level=7.0,
        rising_velocity=0.35,
        is_surging=True,
        upstream_catchment="Shivapuri",
        upstream_current_rain_mm=12.0,
        upstream_forecast_1h_mm=15.0,
        upstream_forecast_3h_mm=30.0,
        is_heavy_rain=False,
        compound_risk=False,
        risk_reasons=["Warning level reached"],
        vulnerable_areas_ne="बल्खु, सुकुम्बासी बस्ती",
        vulnerable_areas_en="Balkhu settlements",
        assessed_at=datetime.now(timezone.utc),
    )
    a2 = a1.model_copy(
        update={
            "station_id": "roshi_panauti",
            "station_name": "Roshi Khola at Panauti",
            "river_name": "Roshi Khola",
            "severity": SeverityLevel.NORMAL,
            "current_level": 2.1,
            "warning_level": 4.2,
            "danger_level": 5.5,
        }
    )
    return [a1, a2]


def test_generate_station_chart(sample_assessments):
    chart_path = generate_station_chart(sample_assessments[0])
    assert chart_path.exists()
    assert chart_path.stat().st_size > 1000  # Non-empty PNG image


def test_generate_basin_overview_chart(sample_assessments):
    chart_path = generate_basin_overview_chart(sample_assessments)
    assert chart_path.exists()
    assert chart_path.stat().st_size > 1000  # Non-empty PNG image
