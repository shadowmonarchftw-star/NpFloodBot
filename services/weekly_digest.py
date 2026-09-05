import csv
import datetime
from pathlib import Path
from collections import defaultdict

from services.telegram_notifier import send_telegram_summary

# Path to the rolling history CSV (same as used in main.py)
HISTORY_FILE = Path(__file__).resolve().parents[2] / "data" / "history.csv"

def _load_history() -> list[dict]:
    """Load the CSV history into a list of dicts.
    Expected columns: timestamp, station_id, current_level, warning_level, danger_level, rising_velocity, status
    """
    rows = []
    if not HISTORY_FILE.exists():
        return rows
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def _weekly_stats(rows: list[dict]) -> dict:
    """Calculate simple weekly stats per station.
    Returns a dict keyed by station_id with:
      - max_level: highest observed water level
      - alerts: count of any status other than 'NORMAL' or 'STEADY'
    """
    stats = defaultdict(lambda: {"max_level": 0.0, "alerts": 0})
    for r in rows:
        try:
            lvl = float(r["current_level"])
            sta = r["station_id"]
            status = r["status"].upper()
            if lvl > stats[sta]["max_level"]:
                stats[sta]["max_level"] = lvl
            if status not in ("NORMAL", "STEADY"):
                stats[sta]["alerts"] += 1
        except Exception:
            continue
    return stats

def _format_digest(stats: dict) -> str:
    """Create a short markdown‑style digest for Telegram.
    Shows stations with max level > warning and total alerts.
    """
    lines = ["*📊 Weekly Flood Digest*", ""]
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=45)))
    lines.append(f"_Week ending {now.strftime('%d %b %Y')}_\n")
    total_alerts = 0
    for station, data in sorted(stats.items()):
        if data["alerts"] > 0 or data["max_level"] > 0:
            total_alerts += data["alerts"]
            lines.append(f"• `{station}` – max level: {data['max_level']:.2f} m, alerts: {data['alerts']}")
    lines.append("\nTotal alerts this week: " + str(total_alerts))
    lines.append("\nStay safe! 🙏")
    return "\n".join(lines)

def run_weekly_digest() -> None:
    """Load history, compute stats, and send a Telegram message.
    Intended for a GitHub Actions scheduled job.
    """
    rows = _load_history()
    if not rows:
        return
    stats = _weekly_stats(rows)
    msg = _format_digest(stats)
    # Use existing notifier to send a plain text message (no photo)
    send_telegram_summary(text=msg, photo_path=None, dry_run=False)

if __name__ == "__main__":
    run_weekly_digest()
