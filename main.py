#!/usr/bin/env python3
"""Nepal River Basin Flood Early Warning Bot.

Automated 100% free early warning system for Nepal river basins using
DHM telemetry, Open-Meteo precipitation forecasts, Google Gemini Flash AI,
and Telegram channel broadcasts.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import json
from services.ai_advisory import generate_bilingual_advisory, generate_basin_overview_advisory
from services.hydrology import fetch_river_telemetry, load_stations_metadata
from services.risk_evaluator import evaluate_risk, SeverityLevel
from services.telegram_notifier import (
    load_alert_state,
    save_alert_state,
    send_telegram_alert,
    send_telegram_summary,
    should_send_alert,
    update_station_state,
)
from services.weather import fetch_catchment_weather

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("NepalFloodBot")

BASIN_CASCADES = {
    "bagmati_sundarijal": {
        "downstream_id": "bagmati_gaurighat",
        "transit_hours": 1.5,
        "upstream_label": "सुन्दरीजल (Sundarijal)",
    },
    "bagmati_gaurighat": {
        "downstream_id": "bagmati_balkhu",
        "transit_hours": 2.0,
        "upstream_label": "पशुपति / गौरीघाट (Gaurighat)",
    },
    "bagmati_balkhu": {
        "downstream_id": "bagmati_chobhar",
        "transit_hours": 1.0,
        "upstream_label": "बल्खु करिडोर (Balkhu)",
    },
    "melamchi_helambu": {
        "downstream_id": "koshi_chatara",
        "transit_hours": 5.0,
        "upstream_label": "मेलम्ची / हेलम्बु (Melamchi)",
    },
}


def get_cascade_alerts(readings: list) -> dict[str, tuple[str, str]]:
    """Detect upstream flood pulses and project downstream cascading impact."""
    alerts: dict[str, tuple[str, str]] = {}
    r_map = {r.station_id: r for r in readings}

    for up_id, info in BASIN_CASCADES.items():
        if up_id in r_map:
            up_r = r_map[up_id]
            # If upstream is surging or rising rapidly
            if up_r.rising_velocity >= 0.20 or up_r.current_level >= up_r.warning_level:
                down_id = info["downstream_id"]
                transit = info["transit_hours"]
                up_label = info["upstream_label"]
                vel = up_r.rising_velocity
                ne_msg = f"{up_label} मा जलसतह तीव्र गतिमा बढ्दैछ (+{vel:.2f} m/h)। करिब {transit} घण्टाभित्र यहाँ बाढीको बहाव आइपुग्ने पूर्वानुमान छ।"
                en_msg = f"Rapid rise detected upstream at {up_label} (+{vel:.2f} m/h); flood crest expected downstream within ~{transit} hours."
                alerts[down_id] = (ne_msg, en_msg)
    return alerts


def print_status_table(force_mock: bool = False) -> None:
    """Print an ASCII status table of all monitored stations and upstream weather."""
    print("\n" + "=" * 95)
    print("🌊 NEPAL RIVER BASIN FLOOD MONITORING - REAL-TIME STATUS")
    print("=" * 95)
    print(
        f"{'Station Name':<28} | {'Level':<8} | {'Warn':<6} | {'Dang':<6} | {'Trend':<9} | {'Upstream Rain':<14} | {'Risk Level'}"
    )
    print("-" * 95)

    readings = fetch_river_telemetry(force_mock=force_mock)
    for r in readings:
        weather = fetch_catchment_weather(
            catchment_name=r.upstream_catchment,
            latitude=r.upstream_lat,
            longitude=r.upstream_lon,
            force_mock=force_mock,
        )
        risk = evaluate_risk(r, weather)
        trend_str = f"{'+' if r.rising_velocity > 0 else ''}{r.rising_velocity:.2f}m/h"
        rain_str = f"{weather.forecast_1h_mm:.1f}mm/h ({weather.current_rain_mm:.1f}cur)"
        sev_str = f"{risk.severity.emoji} {risk.severity.value}"
        print(
            f"{r.station_name[:28]:<28} | {r.current_level:>5.2f}m  | {r.warning_level:>5.2f}m | {r.danger_level:>5.2f}m | {trend_str:<9} | {rain_str:<14} | {sev_str}"
        )
    print("=" * 95 + "\n")


def run_test_alert(station_id: str = "bagmati_balkhu", dry_run: bool = False) -> int:
    """Simulate a critical flood breach to verify Telegram and Gemini setup end-to-end."""
    print("\n🚨 SIMULATING CRITICAL FLOOD BREACH TEST SCENARIO...")
    print(f"Target Station: {station_id} (Simulated danger breach + Shivapuri torrential rain)\n")

    # Fetch with forced breach on chosen station
    readings = fetch_river_telemetry(
        station_id=station_id,
        force_mock=True,
        simulate_breach_stations=[station_id],
    )
    if not readings:
        logger.error(f"Station {station_id} not found.")
        return 1

    reading = readings[0]
    # Simulate heavy cloudburst in upstream catchment
    weather = fetch_catchment_weather(
        catchment_name=reading.upstream_catchment,
        latitude=reading.upstream_lat,
        longitude=reading.upstream_lon,
        force_mock=True,
        simulate_heavy_rain=True,
    )

    assessment = evaluate_risk(reading, weather)
    print(f"Risk Assessment: {assessment.severity.emoji} {assessment.severity.badge_en}")
    for reason in assessment.risk_reasons:
        print(f"  • {reason}")

    print("\n🤖 Generating Bilingual Advisory via Google Gemini Flash...")
    advisory = generate_bilingual_advisory(assessment)
    print(f"Advisory Source: {advisory.model_used}")

    print("\n📡 Dispatching Alert to Telegram...")
    success = send_telegram_alert(assessment, advisory, dry_run=dry_run)
    if success:
        print("✅ Test alert successfully executed!")
        return 0
    else:
        print("⚠️ Test alert encountered an issue (check credentials or logs).")
        return 1


def run_broadcast_status(force_mock: bool = False, dry_run: bool = False) -> int:
    """Fetch 100% real-time river gauges & weather, generate an AI summary, and broadcast to Telegram."""
    print("\n📡 INGESTING REAL-TIME BASIN TELEMETRY & UPSTREAM WEATHER FORECASTS...")
    readings = fetch_river_telemetry(force_mock=force_mock)
    cascade_alerts = get_cascade_alerts(readings)
    assessments = []

    for r in readings:
        weather = fetch_catchment_weather(
            catchment_name=r.upstream_catchment,
            latitude=r.upstream_lat,
            longitude=r.upstream_lon,
            force_mock=force_mock,
        )
        c_ne, c_en = cascade_alerts.get(r.station_id, (None, None))
        risk = evaluate_risk(r, weather, cascade_alert_ne=c_ne, cascade_alert_en=c_en)
        assessments.append(risk)

    export_stations_live(readings, assessments=assessments)

    print(f"📊 Evaluated {len(assessments)} river stations. Generating AI bilingual summary...")
    advisory = generate_basin_overview_advisory(assessments)

    print("🚀 Dispatching real-time status bulletin to Telegram...")
    sent = send_telegram_summary(assessments, advisory, dry_run=dry_run)
    if sent:
        print("✅ Live river basin status bulletin successfully sent to Telegram!")
        return 0
    else:
        print("⚠️ Failed to broadcast status bulletin to Telegram.")
        return 1


def export_stations_live(readings: list, assessments: list | None = None) -> None:
    """Save live stations snapshot for GitHub Pages interactive map dashboard."""
    try:
        docs_dir = BASE_DIR / "docs"
        if docs_dir.exists():
            payload = []
            assess_map = {a.station_id: a for a in assessments} if assessments else {}
            for r in readings:
                d = r.model_dump()
                d["timestamp"] = d["timestamp"].isoformat()

                if r.station_id in assess_map:
                    a = assess_map[r.station_id]
                    d["severity"] = a.severity.value
                    d["lead_time_formatted_en"] = a.lead_time_formatted_en
                    d["lead_time_formatted_ne"] = a.lead_time_formatted_ne
                    d["past_24h_rain_mm"] = a.past_24h_rain_mm
                    d["is_soil_saturated"] = a.is_soil_saturated
                    d["upstream_cascade_alert_ne"] = a.upstream_cascade_alert_ne
                    d["upstream_cascade_alert_en"] = a.upstream_cascade_alert_en
                    d["forecast_1h_mm"] = a.upstream_forecast_1h_mm
                    d["current_rain_mm"] = a.upstream_current_rain_mm

                # Generate sparkline PNG for this station and add its URL
                try:
                    from services.sparkline_generator import generate_sparkline
                    spark_path = generate_sparkline(r.station_id)
                    if spark_path and spark_path.exists():
                        d["sparkline_url"] = f"trends/{spark_path.name}"
                except Exception as e:
                    logger.debug(f"Sparkline generation failed for {r.station_id}: {e}")
                payload.append(d)
            with open(docs_dir / "stations_live.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
    except Exception as e:
        logger.debug(f"Could not export stations_live.json: {e}")


def append_history(readings: list) -> None:
    """Append current readings to a rolling CSV history file for trend analysis.

    Keeps a maximum of ~7 days of 15-minute readings (672 rows per station).
    The file is committed to the repo by GitHub Actions so the dashboard can
    render sparkline trends.
    """
    import csv

    history_file = BASE_DIR / "data" / "history.csv"
    header = ["timestamp", "station_id", "current_level", "warning_level", "danger_level", "rising_velocity", "status"]
    max_rows = 672 * 14  # ~7 days × 96 readings/day × 14 stations

    # Read existing rows
    existing_rows: list[list[str]] = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                file_header = next(reader, None)
                existing_rows = list(reader)
        except Exception:
            existing_rows = []

    # Append new readings
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in readings:
        existing_rows.append([
            now_iso,
            r.station_id,
            f"{r.current_level:.2f}",
            f"{r.warning_level:.2f}",
            f"{r.danger_level:.2f}",
            f"{r.rising_velocity:.3f}",
            r.status,
        ])

    # Trim to rolling window
    if len(existing_rows) > max_rows:
        existing_rows = existing_rows[-max_rows:]

    # Write back
    try:
        with open(history_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(existing_rows)
    except Exception as e:
        logger.debug(f"Could not write history.csv: {e}")


def run_monitoring_cycle(
    station_id: str | None = None,
    force_mock: bool = False,
    dry_run: bool = False,
    force_alert: bool = False,
) -> int:
    """Execute a single polling, evaluation, and alert cycle across all stations."""
    logger.info("Starting flood monitoring cycle...")
    state = load_alert_state()

    try:
        readings = fetch_river_telemetry(station_id=station_id, force_mock=force_mock)
        append_history(readings)
    except Exception as e:
        logger.error(f"Failed to fetch river telemetry: {e}")
        return 1

    cascade_alerts = get_cascade_alerts(readings)
    assessments = []
    alerts_dispatched = 0

    for reading in readings:
        try:
            weather = fetch_catchment_weather(
                catchment_name=reading.upstream_catchment,
                latitude=reading.upstream_lat,
                longitude=reading.upstream_lon,
                force_mock=force_mock,
            )
            c_ne, c_en = cascade_alerts.get(reading.station_id, (None, None))
            assessment = evaluate_risk(reading, weather, cascade_alert_ne=c_ne, cascade_alert_en=c_en)
            assessments.append(assessment)

            should_alert, reason = should_send_alert(
                assessment=assessment,
                state=state,
                force_alert=force_alert,
            )

            if should_alert:
                logger.warning(
                    f"TRIGGER ALERT for {reading.station_id}: {assessment.severity.badge_en} - Reason: {reason}"
                )
                advisory = generate_bilingual_advisory(assessment)
                sent = send_telegram_alert(assessment, advisory, dry_run=dry_run)
                if sent:
                    update_station_state(assessment, state)
                    alerts_dispatched += 1
            else:
                logger.info(
                    f"Station {reading.station_id}: {assessment.severity.emoji} {assessment.severity.value} ({reading.current_level:.2f}m/{reading.danger_level:.2f}m). {reason}"
                )
        except Exception as err:
            logger.error(f"Error evaluating station {reading.station_id}: {err}", exc_info=True)

    export_stations_live(readings, assessments=assessments)

    logger.info(
        f"Cycle completed. Monitored {len(readings)} stations; dispatched {alerts_dispatched} alerts."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nepal River Basin Flood Early Warning Bot with Gemini AI and Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--once",
        action="store_true",
        help="Run a single polling cycle, evaluate risk, send alerts if triggered, and exit (code 0).",
    )
    mode_group.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously as a background polling daemon.",
    )
    mode_group.add_argument(
        "--test-alert",
        action="store_true",
        help="Simulate a critical flood breach to verify Telegram and Gemini setup end-to-end.",
    )
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Print real-time gauge table and upstream weather overview, then exit.",
    )
    mode_group.add_argument(
        "--broadcast-status",
        action="store_true",
        help="Fetch 100% real-time river gauges & weather, generate an AI overview, and broadcast directly to Telegram.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Polling interval in seconds for daemon mode (default: 900 = 15 minutes).",
    )
    parser.add_argument(
        "--station",
        type=str,
        default=None,
        help="Limit execution to a single station ID (e.g. bagmati_balkhu, roshi_panauti).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate alert processing and output to console without making Telegram API calls.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force using realistic mock data instead of live network calls.",
    )
    parser.add_argument(
        "--force-alert",
        action="store_true",
        help="Bypass cooldown checks and force alert dispatch.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.status:
        print_status_table(force_mock=args.mock)
        return 0

    if args.broadcast_status:
        return run_broadcast_status(force_mock=args.mock, dry_run=args.dry_run)

    if args.test_alert:
        target_station = args.station or "bagmati_balkhu"
        return run_test_alert(station_id=target_station, dry_run=args.dry_run)

    if args.daemon:
        logger.info(f"Starting Nepal Flood Early Warning Daemon (polling every {args.interval}s)...")
        try:
            while True:
                run_monitoring_cycle(
                    station_id=args.station,
                    force_mock=args.mock,
                    dry_run=args.dry_run,
                    force_alert=args.force_alert,
                )
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Daemon interrupted by user. Exiting safely.")
            return 0

    # Default or explicit --once mode
    return run_monitoring_cycle(
        station_id=args.station,
        force_mock=args.mock,
        dry_run=args.dry_run,
        force_alert=args.force_alert,
    )


if __name__ == "__main__":
    sys.exit(main())
