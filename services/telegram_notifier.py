"""Telegram Alert Dispatcher Module.

Broadcasts bilingual flood early warnings to Telegram channels/chats ($0 cost)
with intelligent state-tracking and cooldown logic to eliminate alert fatigue.
"""

from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from pydantic import BaseModel

from services.ai_advisory import AdvisoryResult
from services.risk_evaluator import RiskAssessment, SeverityLevel

logger = logging.getLogger(__name__)

# Nepal Standard Time (UTC + 5:45)
NPT_TIMEZONE = timezone(timedelta(hours=5, minutes=45), name="NPT")


def format_npt_time(dt: Optional[datetime] = None) -> str:
    """Format datetime into Nepal Standard Time (NPT, UTC+5:45)."""
    target = dt or datetime.now(timezone.utc)
    npt_dt = target.astimezone(NPT_TIMEZONE)
    return npt_dt.strftime("%Y-%m-%d %I:%M:%S %p NPT (नेपाल समय)")


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "data" / "state.json"

# Default cooldown: 120 minutes for repeat alerts at same severity level
DEFAULT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "120"))
# Water level change threshold (meters) that forces an alert even inside cooldown
SURGE_DELTA_THRESHOLD_METERS = 0.40


class StationAlertState(BaseModel):
    last_severity: str
    last_level: float
    last_alert_time: str
    alert_count: int = 1


def load_alert_state() -> Dict[str, StationAlertState]:
    """Load persistent alert state from disk."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k: StationAlertState(**v) for k, v in raw.items()}
    except Exception as e:
        logger.warning(f"Failed to read state file {STATE_FILE} ({e}), initializing fresh state.")
        return {}


def save_alert_state(state: Dict[str, StationAlertState]) -> None:
    """Save persistent alert state to disk atomically."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = STATE_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({k: v.model_dump() for k, v in state.items()}, f, indent=2)
        temp_file.replace(STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to write state file {STATE_FILE}: {e}")


def should_send_alert(
    assessment: RiskAssessment,
    state: Dict[str, StationAlertState],
    force_alert: bool = False,
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
) -> Tuple[bool, str]:
    """Evaluate whether an alert should be dispatched based on cooldown and severity rules.

    Returns:
        (should_alert, reason_string)
    """
    if force_alert:
        return True, "Forced alert via test mode or explicit flag."

    station_id = assessment.station_id
    curr_sev = assessment.severity

    # Station not previously recorded
    if station_id not in state:
        if curr_sev in (SeverityLevel.WARNING, SeverityLevel.EMERGENCY, SeverityLevel.ADVISORY):
            return True, f"Initial detection of elevated threat level: {curr_sev.value}."
        return False, "Normal conditions; no prior alert state."

    prev_state = state[station_id]
    prev_sev = SeverityLevel(prev_state.last_severity) if prev_state.last_severity in SeverityLevel.__members__ else SeverityLevel.NORMAL

    # Escalation check (e.g. NORMAL -> WARNING, WARNING -> EMERGENCY)
    if curr_sev.rank > prev_sev.rank:
        return True, f"Severity escalated from {prev_sev.value} to {curr_sev.value}."

    # De-escalation recovery notification:
    # If previously EMERGENCY or WARNING and now dropped back to NORMAL
    if prev_sev in (SeverityLevel.WARNING, SeverityLevel.EMERGENCY) and curr_sev == SeverityLevel.NORMAL:
        return True, f"All Clear recovery: River level has safely receded back from {prev_sev.value} to NORMAL."

    # Normal conditions when previous was also NORMAL
    if curr_sev == SeverityLevel.NORMAL:
        return False, "River within normal parameters; no alert required."

    # Advisory condition: only alert if escalated or initial, not repeatedly spamming advisory
    if curr_sev == SeverityLevel.ADVISORY and prev_sev == SeverityLevel.ADVISORY:
        return False, "Advisory already dispatched; suppressing repeat advisory."

    # Calculate time elapsed since last alert
    try:
        last_dt = datetime.fromisoformat(prev_state.last_alert_time)
        now_dt = datetime.now(timezone.utc)
        elapsed_minutes = (now_dt - last_dt).total_seconds() / 60.0
    except Exception:
        elapsed_minutes = 99999.0

    # Surge check: Water rose significantly (+0.4m) since last alert even if severity is unchanged
    level_diff = assessment.current_level - prev_state.last_level
    if level_diff >= SURGE_DELTA_THRESHOLD_METERS:
        return True, f"Rapid water surge detected (+{level_diff:.2f}m rise since last alert)."

    # Cooldown window check
    if elapsed_minutes >= cooldown_minutes:
        return True, f"Cooldown window ({cooldown_minutes}m) elapsed; dispatching periodic status update."

    return False, f"Alert suppressed by cooldown ({elapsed_minutes:.1f}/{cooldown_minutes} mins elapsed, delta: {level_diff:+.2f}m)."


def format_telegram_html(assessment: RiskAssessment, advisory: AdvisoryResult) -> str:
    """Format a clean, high-impact HTML message for Telegram."""
    emoji = assessment.severity.emoji
    badge_ne = assessment.severity.badge_ne
    badge_en = assessment.severity.badge_en

    # Format header
    msg_parts = [
        f"<b>{emoji} NEPAL FLOOD EARLY WARNING | बाढी पूर्वसूचना</b>",
        f"<b>तीव्रता तह / SEVERITY:</b> {badge_ne} | {badge_en}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📍 <b>नदी तथा स्टेसन:</b> {html.escape(assessment.station_name)}",
        f"🌊 <b>नदी प्रणाली:</b> {html.escape(assessment.river_name)} ({html.escape(assessment.basin)})",
        f"📏 <b>वर्तमान जलसतह (Level):</b> <code>{assessment.current_level:.2f} m</code>",
        f"⚠️ <b>सतर्कता तह (Warning):</b> <code>{assessment.warning_level:.2f} m</code> | 🔴 <b>खतरा तह (Danger):</b> <code>{assessment.danger_level:.2f} m</code>",
        f"📈 <b>जलसतहको गति (Trend):</b> <code>{'+' if assessment.rising_velocity > 0 else ''}{assessment.rising_velocity:.2f} m/hr</code> ({assessment.rising_velocity and 'RISING' or 'STEADY'})",
    ]

    # Upstream rain
    rain_icon = "⛈️" if assessment.is_heavy_rain else "🌧️"
    msg_parts.append(
        f"{rain_icon} <b>माथिल्लो तटीय वर्षा ({html.escape(assessment.upstream_catchment)}):</b> "
        f"हाल: <code>{assessment.upstream_current_rain_mm:.1f} mm</code> | १ घण्टा: <code>{assessment.upstream_forecast_1h_mm:.1f} mm</code>"
    )

    if assessment.compound_risk:
        msg_parts.append("\n⚡ <b>चेतावनी: दोहोरो जोखिम (Compound Flood Threat)!</b> उच्च जलसतह + माथिल्लो तटीय भीषण वर्षा।")

    # Nepali Section
    msg_parts.append("\n🇳🇵 <b>नेपाली सतर्कता सन्देश (Actionable Advisory):</b>")
    msg_parts.append(html.escape(advisory.nepali_advisory))

    # English Section
    msg_parts.append("\n🇬🇧 <b>ENGLISH SUMMARY:</b>")
    msg_parts.append(html.escape(advisory.english_summary))

    # Downstream areas
    msg_parts.append("\n🚨 <b>उच्च जोखिमयुक्त तटीय क्षेत्रहरू (Vulnerable Downstream Areas):</b>")
    msg_parts.append(f"• {html.escape(assessment.vulnerable_areas_ne)}")

    # Footer
    time_str = format_npt_time(assessment.assessed_at)
    msg_parts.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    msg_parts.append(
        f"📡 <i>स्रोत: DHM Telemetry & Open-Meteo | AI: {html.escape(advisory.model_used)}</i>\n"
        f"🕒 <i>अपडेट समय: {time_str}</i>\n"
        f"🆘 <i>आपतकालीन नम्बरहरू: नेपाल प्रहरी १०० | सशस्त्र प्रहरी बल १११४</i>"
    )

    return "\n".join(msg_parts)


def send_telegram_alert(
    assessment: RiskAssessment,
    advisory: AdvisoryResult,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """Send alert to Telegram channel or print to console if dry_run."""
    message = format_telegram_html(assessment, advisory)

    if dry_run:
        print("\n" + "=" * 60)
        print("📢 [DRY RUN] TELEGRAM ALERT PAYLOAD:")
        print("=" * 60)
        print(message)
        print("=" * 60 + "\n")
        return True

    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not target_chat:
        logger.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in environment. Skipping network dispatch."
        )
        print("\n⚠️ [NOTICE] Telegram credentials not configured. Displaying alert preview:\n")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        dispatched = False
        if resp.status_code == 200:
            logger.info(f"Telegram alert successfully dispatched for {assessment.station_id} to {target_chat}.")
            dispatched = True
        else:
            # Check if group was upgraded to supergroup
            try:
                err_data = resp.json()
                migrate_id = err_data.get("parameters", {}).get("migrate_to_chat_id")
                if migrate_id:
                    logger.info(f"Group migrated to supergroup {migrate_id}. Retrying delivery...")
                    payload["chat_id"] = str(migrate_id)
                    retry_resp = requests.post(url, json=payload, timeout=8.0)
                    if retry_resp.status_code == 200:
                        logger.info(f"Telegram alert delivered to migrated chat {migrate_id}.")
                        dispatched = True
                    else:
                        logger.error(f"Retry to migrated chat {migrate_id} failed with {retry_resp.status_code}: {retry_resp.text}")
            except Exception:
                pass

        if dispatched:
            # Dispatch visual hydrograph chart photo
            try:
                from services.chart_generator import generate_station_chart
                chart_path = generate_station_chart(assessment)
                caption = f"📊 <b>जलसतह ग्राफ / Hydrograph:</b> {assessment.station_name} | {assessment.severity.badge_ne}"
                send_telegram_photo(chart_path, caption=caption, bot_token=token, chat_id=payload["chat_id"], dry_run=dry_run)
            except Exception as e:
                logger.debug(f"Could not generate/send station chart: {e}")
            return True

        logger.error(f"Telegram API responded with {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Failed to transmit Telegram message: {e}")
        return False


def send_telegram_photo(
    photo_path: Path,
    caption: str = "",
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """Send a generated chart photo to Telegram channel/group."""
    if dry_run:
        print(f"\n🖼️ [DRY RUN] Sent Telegram photo: {photo_path} (Caption length: {len(caption)})\n")
        return True

    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not target_chat or not photo_path.exists():
        return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    data = {
        "chat_id": target_chat,
        "caption": caption[:1024],  # Telegram caption max limit
        "parse_mode": "HTML",
    }

    try:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            resp = requests.post(url, data=data, files=files, timeout=12.0)

        if resp.status_code == 200:
            logger.info(f"Telegram photo successfully dispatched: {photo_path.name}")
            return True
        else:
            try:
                err_data = resp.json()
                migrate_id = err_data.get("parameters", {}).get("migrate_to_chat_id")
                if migrate_id:
                    data["chat_id"] = str(migrate_id)
                    with open(photo_path, "rb") as f:
                        retry_resp = requests.post(url, data=data, files={"photo": f}, timeout=12.0)
                    if retry_resp.status_code == 200:
                        logger.info(f"Telegram photo delivered to migrated chat {migrate_id}.")
                        return True
            except Exception:
                pass
            logger.error(f"Telegram sendPhoto failed ({resp.status_code}): {resp.text}")
            return False
    except Exception as err:
        logger.error(f"Error sending photo to Telegram: {err}")
        return False



def update_station_state(
    assessment: RiskAssessment,
    state: Dict[str, StationAlertState],
) -> None:
    """Record state update after sending an alert."""
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = state.get(assessment.station_id)
    count = (existing.alert_count + 1) if existing else 1

    state[assessment.station_id] = StationAlertState(
        last_severity=assessment.severity.value,
        last_level=assessment.current_level,
        last_alert_time=now_iso,
        alert_count=count,
    )
    save_alert_state(state)


def format_basin_summary_html(assessments: List[RiskAssessment], advisory: AdvisoryResult) -> str:
    """Format an informative, real-time bulletin for all monitored stations."""
    highest_severity = max((a.severity for a in assessments), key=lambda s: s.rank, default=SeverityLevel.NORMAL)
    now_str = format_npt_time()

    parts = [
        "<b>🌊 NEPAL RIVER BASINS - REAL-TIME STATUS BULLETIN</b>",
        "<b>नेपाल नदी प्रणाली तथा वर्षा वास्तविक विवरण</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"<b>समग्र अवस्था / Overall Status:</b> {highest_severity.emoji} {highest_severity.badge_ne}",
        f"<b>अनुगमन गरिएका स्टेसनहरू:</b> {len(assessments)} प्रमुख नदी स्टेसनहरू",
        "\n📊 <b>वास्तविक जलसतह तथा वर्षा (Real-Time Gauges):</b>",
    ]

    for a in assessments:
        trend_symbol = "+" if a.rising_velocity > 0 else ""
        parts.append(
            f"📍 <b>{html.escape(a.station_name)}</b>\n"
            f"• जलसतह (Level): <code>{a.current_level:.2f} m</code> (सतर्कता: {a.warning_level:.2f}m | खतरा: {a.danger_level:.2f}m)\n"
            f"• बहाव गति (Trend): <code>{trend_symbol}{a.rising_velocity:.2f} m/hr</code> | अवस्था: {a.severity.emoji} {a.severity.value}\n"
            f"• माथिल्लो तटीय वर्षा: <code>{a.upstream_forecast_1h_mm:.1f} mm/hr</code> ({html.escape(a.upstream_catchment)})\n"
        )

    parts.append("━━━━━━━━━━━━━━━━━━━━━━")
    parts.append("🇳🇵 <b>नेपाली स्थिति सारांश (Nepali Overview):</b>")
    parts.append(html.escape(advisory.nepali_advisory))

    parts.append("\n🇬🇧 <b>ENGLISH SUMMARY:</b>")
    parts.append(html.escape(advisory.english_summary))

    parts.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    parts.append(
        f"📡 <i>स्रोत: नेपाल जल तथा मौसम विज्ञान विभाग (DHM) & Open-Meteo Live API | AI: {html.escape(advisory.model_used)}</i>\n"
        f"🕒 <i>बुलेटिन समय: {now_str}</i>\n"
        f"🆘 <i>आपतकालीन सम्पर्क: नेपाल प्रहरी १०० | सशस्त्र प्रहरी १११४</i>"
    )

    return "\n".join(parts)


def send_telegram_summary(
    assessments: List[RiskAssessment],
    advisory: AdvisoryResult,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """Send live basin status bulletin to Telegram channel."""
    message = format_basin_summary_html(assessments, advisory)

    if dry_run:
        print("\n" + "=" * 60)
        print("📢 [DRY RUN] REAL-TIME TELEGRAM STATUS BULLETIN:")
        print("=" * 60)
        print(message)
        print("=" * 60 + "\n")
        return True

    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not target_chat:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        print("\n⚠️ Telegram credentials not configured. Status bulletin preview:\n")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10.0)
        dispatched = False
        if resp.status_code == 200:
            logger.info(f"Real-time status bulletin successfully dispatched to {target_chat}.")
            dispatched = True
        else:
            # Check if group was upgraded to supergroup
            try:
                err_data = resp.json()
                migrate_id = err_data.get("parameters", {}).get("migrate_to_chat_id")
                if migrate_id:
                    logger.info(f"Group migrated to supergroup {migrate_id}. Retrying bulletin delivery...")
                    payload["chat_id"] = str(migrate_id)
                    retry_resp = requests.post(url, json=payload, timeout=10.0)
                    if retry_resp.status_code == 200:
                        logger.info(f"Status bulletin successfully delivered to migrated chat {migrate_id}.")
                        dispatched = True
                    else:
                        logger.error(f"Retry to migrated chat {migrate_id} failed with {retry_resp.status_code}: {retry_resp.text}")
            except Exception:
                pass

        if dispatched:
            # Dispatch visual basin overview chart photo
            try:
                from services.chart_generator import generate_basin_overview_chart
                chart_path = generate_basin_overview_chart(assessments)
                now_str = format_npt_time()
                caption = f"📊 <b>नेपाल नदी प्रणाली वास्तविक जलसतह तुलना</b> ({now_str})"
                send_telegram_photo(chart_path, caption=caption, bot_token=token, chat_id=payload["chat_id"], dry_run=dry_run)
            except Exception as e:
                logger.debug(f"Could not generate/send overview chart: {e}")
            return True

        logger.error(f"Telegram API responded with {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Failed to transmit Telegram status bulletin: {e}")
        return False

