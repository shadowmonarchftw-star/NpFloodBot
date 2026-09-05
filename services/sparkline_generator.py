import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta

# Directory for sparkline images (served via GitHub Pages)
SPARKS_DIR = Path(__file__).resolve().parent.parent / 'docs' / 'trends'
SPARKS_DIR.mkdir(parents=True, exist_ok=True)

def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp from history CSV into UTC datetime."""
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)

def generate_sparkline(station_id: str, hours: int = 48) -> Path:
    """Generate a minimal sparkline PNG for a station.

    Reads ``data/history.csv`` (the rolling log), extracts the most recent
    ``hours`` of 15‑minute samples for ``station_id`` (default 48 h), and writes
    a thin line chart to ``docs/trends/<station_id>_spark.png``. The image has
    a transparent background and no axes – ideal for embedding in Leaflet
    popups.
    """
    history_file = Path(__file__).resolve().parent.parent / 'data' / 'history.csv'
    if not history_file.exists():
        return Path()

    # Collect rows for this station
    rows = []
    with open(history_file, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['station_id'] == station_id:
                rows.append(row)
    if not rows:
        return Path()

    # Keep only the most recent ``hours`` worth of data (4 samples per hour)
    recent = rows[-(hours * 4):]
    times = [_parse_timestamp(r['timestamp']).astimezone(timezone(timedelta(hours=5, minutes=45))) for r in recent]
    levels = [float(r['current_level']) for r in recent]

    # Plot a tiny sparkline
    plt.figure(figsize=(2, 0.5), dpi=100)
    plt.plot(times, levels, color='#38bdf8', linewidth=1.5)
    plt.fill_between(times, levels, color='#38bdf8', alpha=0.2)
    plt.axis('off')
    spark_path = SPARKS_DIR / f"{station_id}_spark.png"
    plt.savefig(spark_path, transparent=True, bbox_inches='tight', pad_inches=0)
    plt.close()
    return spark_path

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('Usage: sparkline_generator.py <station_id>')
    else:
        path = generate_sparkline(sys.argv[1])
        print(f'Sparkline saved to {path}')
