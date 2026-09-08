"""Unit tests for Open GeoJSON & RSS Feeds and Sparkline Forward Projections."""

import json
from pathlib import Path
from main import export_geojson_feed, export_rss_feed
from services.sparkline_generator import generate_sparkline


def test_export_geojson_feed(tmp_path):
    sample_payload = [
        {
            "station_id": "bagmati_balkhu",
            "station_name": "Bagmati at Balkhu",
            "river_name": "Bagmati",
            "basin": "Bagmati Basin",
            "current_level": 3.2,
            "warning_level": 5.5,
            "danger_level": 7.0,
            "latitude": 27.6833,
            "longitude": 85.2972,
            "severity": "NORMAL",
            "projected_levels_6h": [3.3, 3.4, 3.5, 3.4, 3.3, 3.2],
        }
    ]
    export_geojson_feed(sample_payload, tmp_path)
    geojson_file = tmp_path / "feed.geojson"
    assert geojson_file.exists()

    data = json.loads(geojson_file.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    feat = data["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["coordinates"] == [85.2972, 27.6833]
    assert feat["properties"]["station_id"] == "bagmati_balkhu"


def test_export_rss_feed(tmp_path):
    sample_payload = [
        {
            "station_id": "bagmati_balkhu",
            "station_name": "Bagmati at Balkhu",
            "river_name": "Bagmati",
            "current_level": 3.2,
            "warning_level": 5.5,
            "danger_level": 7.0,
            "rising_velocity": 0.05,
            "severity": "NORMAL",
            "latitude": 27.6833,
            "longitude": 85.2972,
        }
    ]
    export_rss_feed(sample_payload, tmp_path)
    rss_file = tmp_path / "feed.rss"
    assert rss_file.exists()

    content = rss_file.read_text(encoding="utf-8")
    assert "<rss version=\"2.0\"" in content
    assert "<channel>" in content
    assert "<title><![CDATA[[NORMAL] Bagmati at Balkhu (Bagmati) - Level: 3.20m (v: +0.05m/h)]]></title>" in content
    assert "<geo:lat>27.6833</geo:lat>" in content


def test_sparkline_generator_with_projections():
    # If history.csv has rows for bagmati_balkhu, test rendering with projection
    res = generate_sparkline("bagmati_balkhu", hours=24, projected_levels=[3.2, 3.5, 3.8, 3.6, 3.4, 3.1])
    if res and res.exists():
        assert res.name == "bagmati_balkhu_spark.png"
        assert res.stat().st_size > 0
