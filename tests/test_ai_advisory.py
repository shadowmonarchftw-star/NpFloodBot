"""Unit tests for AI Bilingual Advisory Generator."""

from datetime import datetime, timezone
import pytest
from services.ai_advisory import generate_bilingual_advisory, _generate_fallback_advisory
from services.risk_evaluator import RiskAssessment, SeverityLevel


@pytest.fixture
def emergency_assessment():
    return RiskAssessment(
        station_id="bagmati_balkhu",
        station_name="Bagmati at Balkhu (Kathmandu)",
        river_name="Bagmati",
        basin="Bagmati River Basin",
        severity=SeverityLevel.EMERGENCY,
        current_level=7.8,
        warning_level=5.5,
        danger_level=7.0,
        rising_velocity=0.65,
        is_surging=True,
        upstream_catchment="Shivapuri Hilltops",
        upstream_current_rain_mm=30.0,
        upstream_forecast_1h_mm=35.0,
        upstream_forecast_3h_mm=85.0,
        is_heavy_rain=True,
        compound_risk=True,
        risk_reasons=["Critical danger breach", "Torrential upstream rain"],
        vulnerable_areas_ne="बल्खु, सुकुम्बासी बस्ती, सुन्दरीघाट",
        vulnerable_areas_en="Balkhu, informal squatter settlements, Sundarighat",
        assessed_at=datetime.now(timezone.utc),
    )


def test_fallback_emergency_advisory(emergency_assessment):
    advisory = _generate_fallback_advisory(emergency_assessment)
    assert advisory.is_ai_generated is False
    assert "बल्खु, सुकुम्बासी बस्ती, सुन्दरीघाट" in advisory.nepali_advisory
    assert "सुरक्षित" in advisory.nepali_advisory
    assert "CRITICAL FLOOD EMERGENCY" in advisory.english_summary
    assert "EVACUATE IMMEDIATELY" in advisory.english_summary


def test_fallback_warning_advisory(emergency_assessment):
    warn_assessment = emergency_assessment.model_copy(
        update={
            "severity": SeverityLevel.WARNING,
            "current_level": 5.9,
            "compound_risk": False,
        }
    )
    advisory = _generate_fallback_advisory(warn_assessment)
    assert "सतर्कता चेतावनी" in advisory.nepali_advisory
    assert "FLOOD WARNING" in advisory.english_summary


def test_generate_bilingual_advisory_without_key(monkeypatch, emergency_assessment):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    advisory = generate_bilingual_advisory(emergency_assessment)
    assert advisory is not None
    assert len(advisory.nepali_advisory) > 40
    assert len(advisory.english_summary) > 40
    assert "Balkhu" in advisory.english_summary
