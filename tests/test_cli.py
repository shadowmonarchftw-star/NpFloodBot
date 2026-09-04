"""Unit tests for CLI Entry Point."""

from main import run_monitoring_cycle, run_test_alert, print_status_table


def test_cli_status_table():
    # Verify print_status_table runs without errors
    print_status_table(force_mock=True)


def test_cli_test_alert_dry_run():
    exit_code = run_test_alert(station_id="bagmati_balkhu", dry_run=True)
    assert exit_code == 0


def test_cli_single_station_cycle():
    exit_code = run_monitoring_cycle(
        station_id="roshi_panauti",
        force_mock=True,
        dry_run=True,
    )
    assert exit_code == 0


def test_cli_full_cycle_mock():
    exit_code = run_monitoring_cycle(
        force_mock=True,
        dry_run=True,
    )
    assert exit_code == 0
