"""Unit tests for Telegram Dispatcher and Alert Fatigue Prevention."""

from datetime import datetime, timezone, timedelta
import pytest
from services.ai_advisory import AdvisoryResult
from services.risk_evaluator import RiskAssessment, SeverityLevel
from services.telegram_notifier import (
    should_send_alert,
    StationAlertState,
    format_telegram_html,
    send_telegram_alert,
)


@pytest.fixture
def base_assessment():
    return RiskAssessment(
        station_id="bagmati_balkhu",
        station_name="Bagmati at Balkhu (Kathmandu)",
        river_name="Bagmati",
        basin="Bagmati Basin",
        severity=SeverityLevel.WARNING,
        current_level=5.8,
        warning_level=5.5,
        danger_level=7.0,
        rising_velocity=0.25,
        is_surging=False,
        upstream_catchment="Shivapuri Ridge",
        upstream_current_rain_mm=10.0,
        upstream_forecast_1h_mm=12.0,
        upstream_forecast_3h_mm=25.0,
        is_heavy_rain=False,
        compound_risk=False,
        risk_reasons=["Warning level exceeded"],
        vulnerable_areas_ne="बल्खु, सुकुम्बासी बस्ती",
        vulnerable_areas_en="Balkhu, squatter settlements",
        assessed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_advisory():
    return AdvisoryResult(
        english_summary="Warning: River level is elevated. Communities should prepare.",
        nepali_advisory="सतर्कता: बल्खु, सुकुम्बासी बस्तीका बासिन्दा उच्च सतर्कतामा रहनुहोस्।",
        is_ai_generated=False,
        model_used="Test Engine",
    )


def test_should_send_alert_initial_warning(base_assessment):
    state = {}
    should_alert, reason = should_send_alert(base_assessment, state)
    assert should_alert is True
    assert "Initial detection" in reason


def test_should_send_alert_normal_no_prior(base_assessment):
    normal_assessment = base_assessment.model_copy(update={"severity": SeverityLevel.NORMAL})
    state = {}
    should_alert, reason = should_send_alert(normal_assessment, state)
    assert should_alert is False


def test_should_send_alert_suppress_during_cooldown(base_assessment):
    recent_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    state = {
        "bagmati_balkhu": StationAlertState(
            last_severity="WARNING",
            last_level=5.7,
            last_alert_time=recent_time,
            alert_count=1,
        )
    }
    # Same severity, only 30m elapsed (cooldown is 120m), small level diff (0.1m)
    should_alert, reason = should_send_alert(base_assessment, state, cooldown_minutes=120)
    assert should_alert is False
    assert "suppressed by cooldown" in reason


def test_should_send_alert_escalation_bypasses_cooldown(base_assessment):
    recent_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    state = {
        "bagmati_balkhu": StationAlertState(
            last_severity="WARNING",
            last_level=5.8,
            last_alert_time=recent_time,
            alert_count=1,
        )
    }
    # Escalation to EMERGENCY
    emergency_assessment = base_assessment.model_copy(
        update={"severity": SeverityLevel.EMERGENCY, "current_level": 7.2}
    )
    should_alert, reason = should_send_alert(emergency_assessment, state, cooldown_minutes=120)
    assert should_alert is True
    assert "Severity escalated from WARNING to EMERGENCY" in reason


def test_should_send_alert_rapid_surge_bypasses_cooldown(base_assessment):
    recent_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    state = {
        "bagmati_balkhu": StationAlertState(
            last_severity="WARNING",
            last_level=5.8,
            last_alert_time=recent_time,
            alert_count=1,
        )
    }
    # Water surged by +0.50m (from 5.8 to 6.3m)
    surged_assessment = base_assessment.model_copy(update={"current_level": 6.3})
    should_alert, reason = should_send_alert(surged_assessment, state, cooldown_minutes=120)
    assert should_alert is True
    assert "Rapid water surge detected" in reason


def test_should_send_alert_deescalation_all_clear(base_assessment):
    yesterday = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state = {
        "bagmati_balkhu": StationAlertState(
            last_severity="EMERGENCY",
            last_level=7.4,
            last_alert_time=yesterday,
            alert_count=2,
        )
    }
    normal_assessment = base_assessment.model_copy(
        update={"severity": SeverityLevel.NORMAL, "current_level": 3.2}
    )
    should_alert, reason = should_send_alert(normal_assessment, state)
    assert should_alert is True
    assert "All Clear recovery" in reason


def test_format_telegram_html(base_assessment, sample_advisory):
    html_msg = format_telegram_html(base_assessment, sample_advisory)
    assert "NEPAL FLOOD EARLY WARNING" in html_msg
    assert "Bagmati at Balkhu (Kathmandu)" in html_msg
    assert "5.80 m" in html_msg
    assert "सतर्कता: बल्खु, सुकुम्बासी बस्तीका बासिन्दा" in html_msg
    assert "<b>" in html_msg
    assert "<code>" in html_msg
    assert "नेपाल प्रहरी १००" in html_msg


def test_send_telegram_alert_dry_run(base_assessment, sample_advisory):
    success = send_telegram_alert(base_assessment, sample_advisory, dry_run=True)
    assert success is True


def test_format_basin_summary_html(base_assessment, sample_advisory):
    from services.telegram_notifier import format_basin_summary_html, send_telegram_summary
    summary_html = format_basin_summary_html([base_assessment], sample_advisory)
    assert "NEPAL RIVER BASIN BULLETIN" in summary_html
    assert "Bagmati at Balkhu" in summary_html
    assert "लाइभ नक्सा" in summary_html
    assert len(summary_html) <= 1024

    # Test dry run summary dispatch
    success = send_telegram_summary([base_assessment], sample_advisory, dry_run=True)
    assert success is True
