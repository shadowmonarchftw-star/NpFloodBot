"""Risk Assessment Engine for Nepal River Basins.

Evaluates river gauge levels, rising velocity (m/hr), and upstream rainfall forecast
to detect compound flood threats and assign severity levels:
NORMAL (Green), ADVISORY (Yellow), WARNING (Orange), EMERGENCY (Red).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from services.hydrology import RiverReading
from services.weather import CatchmentForecast, HEAVY_RAIN_THRESHOLD_MM_HR

logger = logging.getLogger(__name__)


class SeverityLevel(str, Enum):
    NORMAL = "NORMAL"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    EMERGENCY = "EMERGENCY"

    @property
    def rank(self) -> int:
        """Numeric rank for severity comparison and escalation detection."""
        ranks = {
            SeverityLevel.NORMAL: 0,
            SeverityLevel.ADVISORY: 1,
            SeverityLevel.WARNING: 2,
            SeverityLevel.EMERGENCY: 3,
        }
        return ranks[self]

    @property
    def emoji(self) -> str:
        emojis = {
            SeverityLevel.NORMAL: "🟢",
            SeverityLevel.ADVISORY: "🟡",
            SeverityLevel.WARNING: "🟠",
            SeverityLevel.EMERGENCY: "🔴",
        }
        return emojis[self]

    @property
    def badge_en(self) -> str:
        badges = {
            SeverityLevel.NORMAL: "NORMAL",
            SeverityLevel.ADVISORY: "ADVISORY (Yellow)",
            SeverityLevel.WARNING: "WARNING (Orange)",
            SeverityLevel.EMERGENCY: "EMERGENCY (Red)",
        }
        return badges[self]

    @property
    def badge_ne(self) -> str:
        badges = {
            SeverityLevel.NORMAL: "सामान्य (Normal)",
            SeverityLevel.ADVISORY: "सजगता / सावधानी (Advisory)",
            SeverityLevel.WARNING: "सतर्कता चेतावनी (Warning)",
            SeverityLevel.EMERGENCY: "खतराको आपतकालीन चेतावनी (Emergency)",
        }
        return badges[self]


class RiskAssessment(BaseModel):
    station_id: str
    station_name: str
    river_name: str
    basin: str
    severity: SeverityLevel
    current_level: float
    warning_level: float
    danger_level: float
    rising_velocity: float = Field(
        ..., description="Rate of change in meters/hour."
    )
    is_surging: bool = Field(
        ..., description="True if river rising faster than 0.35m/hour."
    )
    upstream_catchment: str
    upstream_current_rain_mm: float
    upstream_forecast_1h_mm: float
    upstream_forecast_3h_mm: float
    is_heavy_rain: bool
    compound_risk: bool = Field(
        ...,
        description="True if high river water is coupled with heavy upstream catchment rainfall (>25mm/hr).",
    )
    risk_reasons: List[str]
    vulnerable_areas_ne: str
    vulnerable_areas_en: str
    assessed_at: datetime

    # Advanced Lead-Time & Hydrological Intelligence
    time_to_warning_hours: Optional[float] = None
    time_to_danger_hours: Optional[float] = None
    lead_time_formatted_en: Optional[str] = None
    lead_time_formatted_ne: Optional[str] = None
    past_24h_rain_mm: float = 0.0
    is_soil_saturated: bool = False
    upstream_cascade_alert_ne: Optional[str] = None
    upstream_cascade_alert_en: Optional[str] = None

    @property
    def requires_immediate_alert(self) -> bool:
        return self.severity in (SeverityLevel.WARNING, SeverityLevel.EMERGENCY)


from datetime import datetime, timezone, timedelta

NPT_TIMEZONE = timezone(timedelta(hours=5, minutes=45), name="NPT")
NEPALI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def to_nepali_digits(num_val: Any) -> str:
    """Convert western digits to Nepali Devanagari numerals."""
    return str(num_val).translate(NEPALI_DIGITS)


def evaluate_risk(
    reading: RiverReading,
    weather: CatchmentForecast,
    cascade_alert_ne: Optional[str] = None,
    cascade_alert_en: Optional[str] = None,
) -> RiskAssessment:
    """Assess multi-factor flood hazard and return structured risk evaluation.

    Considers:
    1. Official DHM thresholds (warning & danger marks).
    2. Rising velocity (flash flood surge detection).
    3. Upstream precipitation forecast & 24h soil saturation.
    4. Lead-time to breach calculation.
    5. Upstream hydrological cascade warnings.
    """
    reasons: List[str] = []
    compound_risk = False
    is_surging = reading.rising_velocity >= 0.35

    current = reading.current_level
    warn = reading.warning_level
    dang = reading.danger_level
    now_utc = datetime.now(timezone.utc)

    # Lead-time calculation (time-to-breach)
    time_to_warn: Optional[float] = None
    time_to_dang: Optional[float] = None
    lead_en: Optional[str] = None
    lead_ne: Optional[str] = None

    if reading.rising_velocity >= 0.05:
        if current < warn:
            time_to_warn = round((warn - current) / reading.rising_velocity, 1)
            total_mins = int(round(time_to_warn * 60))
            h, m = divmod(total_mins, 60)
            est_dt = (now_utc + timedelta(minutes=total_mins)).astimezone(NPT_TIMEZONE)
            clock_en = est_dt.strftime("%I:%M %p NPT")
            ampm_ne = "बिहान" if est_dt.hour < 12 else ("दिउँसो" if est_dt.hour < 16 else ("साँझ" if est_dt.hour < 20 else "राति"))
            clock_ne = f"{to_nepali_digits(est_dt.strftime('%I:%M'))} {ampm_ne}"
            lead_en = f"Warning mark in ~{h}h {m}m (~{clock_en})"
            lead_ne = f"सतर्कता सीमा उल्लङ्घन अनुमान: ~{to_nepali_digits(h)} घण्टा {to_nepali_digits(m)} मिनेट (करिब {clock_ne})"
            reasons.append(f"LEAD-TIME ESTIMATE: Warning threshold breach anticipated in ~{h}h {m}m at current velocity.")
        elif current < dang:
            time_to_dang = round((dang - current) / reading.rising_velocity, 1)
            total_mins = int(round(time_to_dang * 60))
            h, m = divmod(total_mins, 60)
            est_dt = (now_utc + timedelta(minutes=total_mins)).astimezone(NPT_TIMEZONE)
            clock_en = est_dt.strftime("%I:%M %p NPT")
            ampm_ne = "बिहान" if est_dt.hour < 12 else ("दिउँसो" if est_dt.hour < 16 else ("साँझ" if est_dt.hour < 20 else "राति"))
            clock_ne = f"{to_nepali_digits(est_dt.strftime('%I:%M'))} {ampm_ne}"
            lead_en = f"DANGER breach in ~{h}h {m}m (~{clock_en})"
            lead_ne = f"खतरा तह उल्लङ्घन अनुमान: ~{to_nepali_digits(h)} घण्टा {to_nepali_digits(m)} मिनेट (करिब {clock_ne})"
            reasons.append(f"LEAD-TIME WARNING: Critical danger level breach anticipated in ~{h}h {m}m at current velocity.")

    # Upstream rain metrics
    f_1h = weather.forecast_1h_mm
    past_24h = getattr(weather, "past_24h_rain_mm", 0.0)
    is_sat = getattr(weather, "is_soil_saturated", False)
    is_torrential = (
        weather.is_heavy_rain
        or f_1h >= HEAVY_RAIN_THRESHOLD_MM_HR
        or weather.max_hourly_rain_mm >= HEAVY_RAIN_THRESHOLD_MM_HR
    )

    if is_sat:
        reasons.append(
            f"HIGH SOIL SATURATION: Catchment received {past_24h:.1f}mm in past 24 hours, maximizing direct surface runoff and flash flood risk."
        )

    if cascade_alert_en:
        reasons.append(f"CASCADING UPSTREAM PULSE: {cascade_alert_en}")

    # Compound threat check: elevated river + heavy upstream rain
    if current >= warn and is_torrential:
        compound_risk = True
        reasons.append(
            f"COMPOUND EXTREME RISK: River level ({current:.2f}m) has reached/exceeded warning mark ({warn:.2f}m) "
            f"while torrential upstream rainfall ({f_1h:.1f}mm/hr) is forecasted in {weather.catchment_name}."
        )

    # 1. EMERGENCY (RED)
    if current >= dang:
        severity = SeverityLevel.EMERGENCY
        reasons.insert(
            0,
            f"CRITICAL DANGER BREACH: Gauge height {current:.2f}m exceeds official DHM danger level ({dang:.2f}m) by {current - dang:+.2f}m.",
        )
    elif compound_risk:
        severity = SeverityLevel.EMERGENCY
        # Escalated immediately due to deadly compound flash flood conditions

    # 2. WARNING (ORANGE)
    elif current >= warn:
        severity = SeverityLevel.WARNING
        reasons.append(
            f"WARNING THRESHOLD EXCEEDED: Gauge height {current:.2f}m is above DHM warning level ({warn:.2f}m)."
        )
    elif current >= (warn * 0.88) and (is_surging or is_torrential):
        severity = SeverityLevel.WARNING
        if is_surging:
            reasons.append(
                f"RAPID FLOOD SURGE: Approaching warning level at {current:.2f}m with rising velocity of +{reading.rising_velocity:.2f} m/hr."
            )
        if is_torrential:
            reasons.append(
                f"UPSTREAM CLOUDBURST INCOMING: Approaching warning mark with intense {f_1h:.1f}mm/hr upstream rain."
            )

    # 3. ADVISORY (YELLOW)
    elif current >= (warn * 0.80):
        severity = SeverityLevel.ADVISORY
        reasons.append(
            f"RIVER ELEVATED: Gauge height {current:.2f}m is within 80% of warning level ({warn:.2f}m)."
        )
    elif reading.rising_velocity >= 0.20:
        severity = SeverityLevel.ADVISORY
        reasons.append(
            f"STEADY WATER RISE: River water rising at +{reading.rising_velocity:.2f} m/hr."
        )
    elif weather.forecast_1h_mm >= 15.0 or weather.current_rain_mm >= 15.0:
        severity = SeverityLevel.ADVISORY
        reasons.append(
            f"MODERATE/HEAVY UPSTREAM RAIN: {weather.forecast_1h_mm:.1f} mm/hr forecasted in {weather.catchment_name}."
        )

    # 4. NORMAL (GREEN)
    else:
        severity = SeverityLevel.NORMAL
        reasons.append(
            f"NORMAL FLOW: Current level {current:.2f}m is safely below warning level ({warn:.2f}m). Upstream weather is stable."
        )

    if is_surging and "RAPID FLOOD SURGE" not in "".join(reasons):
        reasons.append(f"Flash flood alert: River level rising rapidly (+{reading.rising_velocity:.2f}m/hr).")

    return RiskAssessment(
        station_id=reading.station_id,
        station_name=reading.station_name,
        river_name=reading.river_name,
        basin=reading.basin,
        severity=severity,
        current_level=current,
        warning_level=warn,
        danger_level=dang,
        rising_velocity=reading.rising_velocity,
        is_surging=is_surging,
        upstream_catchment=weather.catchment_name,
        upstream_current_rain_mm=weather.current_rain_mm,
        upstream_forecast_1h_mm=weather.forecast_1h_mm,
        upstream_forecast_3h_mm=weather.forecast_3h_mm,
        is_heavy_rain=is_torrential,
        compound_risk=compound_risk,
        risk_reasons=reasons,
        vulnerable_areas_ne=reading.vulnerable_areas_ne,
        vulnerable_areas_en=reading.vulnerable_areas_en,
        assessed_at=now_utc,
        time_to_warning_hours=time_to_warn,
        time_to_danger_hours=time_to_dang,
        lead_time_formatted_en=lead_en,
        lead_time_formatted_ne=lead_ne,
        past_24h_rain_mm=past_24h,
        is_soil_saturated=is_sat,
        upstream_cascade_alert_ne=cascade_alert_ne,
        upstream_cascade_alert_en=cascade_alert_en,
    )
