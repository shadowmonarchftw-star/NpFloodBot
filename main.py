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
    assessments = []

    for r in readings:
        weather = fetch_catchment_weather(
            catchment_name=r.upstream_catchment,
            latitude=r.upstream_lat,
            longitude=r.upstream_lon,
            force_mock=force_mock,
        )
        risk = evaluate_risk(r, weather)
        assessments.append(risk)

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
    except Exception as e:
        logger.error(f"Failed to fetch river telemetry: {e}")
        return 1

    alerts_dispatched = 0

    for reading in readings:
        try:
            weather = fetch_catchment_weather(
                catchment_name=reading.upstream_catchment,
                latitude=reading.upstream_lat,
                longitude=reading.upstream_lon,
                force_mock=force_mock,
            )
            assessment = evaluate_risk(reading, weather)

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
