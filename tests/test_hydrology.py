"""Unit tests for Hydrology Data Ingestion Module."""

import pytest
from services.hydrology import (
    load_stations_metadata,
    generate_realistic_mock_reading,
    fetch_river_telemetry,
    RiverReading,
)


def test_load_stations_metadata():
    stations = load_stations_metadata()
    assert len(stations) >= 6
    station_ids = [s.station_id for s in stations]
    assert "bagmati_balkhu" in station_ids
    assert "roshi_panauti" in station_ids
    assert "koshi_chatara" in station_ids

    balkhu = next(s for s in stations if s.station_id == "bagmati_balkhu")
    assert balkhu.warning_level == 5.5
    assert balkhu.danger_level == 7.0
    assert "बल्खु" in balkhu.vulnerable_areas_ne


def test_generate_realistic_mock_reading_normal():
    stations = load_stations_metadata()
    balkhu = next(s for s in stations if s.station_id == "bagmati_balkhu")
    reading = generate_realistic_mock_reading(balkhu, force_breach=False)

    assert isinstance(reading, RiverReading)
    assert reading.station_id == "bagmati_balkhu"
    assert reading.is_mock is True
    assert reading.current_level < balkhu.warning_level
    assert not reading.is_above_warning
    assert not reading.is_above_danger


def test_generate_realistic_mock_reading_breach():
    stations = load_stations_metadata()
    balkhu = next(s for s in stations if s.station_id == "bagmati_balkhu")
    reading = generate_realistic_mock_reading(balkhu, force_breach=True)

    assert reading.current_level >= balkhu.danger_level
    assert reading.is_above_danger is True
    assert reading.is_above_warning is True
    assert reading.rising_velocity > 0.4


def test_fetch_river_telemetry_force_mock():
    readings = fetch_river_telemetry(force_mock=True)
    assert len(readings) >= 6
    for r in readings:
        assert r.current_level > 0
        assert r.warning_level > 0
        assert r.danger_level > r.warning_level


def test_fetch_single_station():
    readings = fetch_river_telemetry(station_id="roshi_panauti", force_mock=True)
    assert len(readings) == 1
    assert readings[0].station_id == "roshi_panauti"
    assert readings[0].river_name == "Roshi Khola"
