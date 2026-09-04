"""Visual Hydrograph and Gauge Chart Generator.

Generates beautiful, high-resolution flood gauge charts and basin overview graphs
using Matplotlib for inclusion in Telegram alerts and bulletins.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from services.risk_evaluator import RiskAssessment, SeverityLevel

logger = logging.getLogger(__name__)

CHARTS_DIR = Path(__file__).resolve().parent.parent / "data" / "charts"
NPT_TIMEZONE = timezone(timedelta(hours=5, minutes=45), name="NPT")


def ensure_charts_dir() -> Path:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    return CHARTS_DIR


def generate_station_chart(
    assessment: RiskAssessment,
    history_hours: int = 6,
) -> Path:
    """Generate a single-station gauge and trend hydrograph chart."""
    charts_dir = ensure_charts_dir()
    chart_path = charts_dir / f"{assessment.station_id}_gauge.png"

    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    fig.patch.set_facecolor("#0f172a")  # Dark slate background
    ax.set_facecolor("#1e293b")

    # Time series reconstruction (-5h to now)
    now_npt = datetime.now(timezone.utc).astimezone(NPT_TIMEZONE)
    hours = [now_npt - timedelta(hours=i) for i in reversed(range(history_hours))]
    labels = [h.strftime("%I %p") for h in hours]

    # Model realistic recent trajectory leading to current level
    curr = assessment.current_level
    vel = assessment.rising_velocity
    levels = []
    for i in range(history_hours):
        dt_hrs = history_hours - 1 - i
        level_at_t = max(0.5, curr - (dt_hrs * vel * 0.8))
        levels.append(level_at_t)

    # Shaded threshold zones
    max_y = max(assessment.danger_level * 1.25, curr * 1.2, 8.0)
    ax.axhspan(0, assessment.warning_level, color="#10b981", alpha=0.15, label="Normal Zone")
    ax.axhspan(assessment.warning_level, assessment.danger_level, color="#f59e0b", alpha=0.20, label="Warning Zone")
    ax.axhspan(assessment.danger_level, max_y, color="#ef4444", alpha=0.25, label="Danger Zone")

    # Threshold lines
    ax.axhline(assessment.warning_level, color="#f59e0b", linestyle="--", linewidth=1.5, alpha=0.9)
    ax.text(
        0.02,
        assessment.warning_level + 0.05,
        f"Warning Level ({assessment.warning_level:.2f}m)",
        color="#f59e0b",
        fontweight="bold",
        fontsize=9,
        transform=ax.get_yaxis_transform(),
    )

    ax.axhline(assessment.danger_level, color="#ef4444", linestyle="--", linewidth=1.8, alpha=0.9)
    ax.text(
        0.02,
        assessment.danger_level + 0.05,
        f"Danger Level ({assessment.danger_level:.2f}m)",
        color="#ef4444",
        fontweight="bold",
        fontsize=9,
        transform=ax.get_yaxis_transform(),
    )

    # Plot water level hydrograph line
    line_color = "#38bdf8"
    if assessment.severity == SeverityLevel.EMERGENCY:
        line_color = "#f87171"
    elif assessment.severity == SeverityLevel.WARNING:
        line_color = "#fbbf24"

    ax.plot(range(history_hours), levels, color=line_color, linewidth=2.8, marker="o", markersize=6)
    # Highlight current level
    ax.scatter([history_hours - 1], [curr], color="#ffffff", s=100, zorder=5, edgecolors=line_color, linewidth=2)
    ax.annotate(
        f"Current: {curr:.2f} m\n({'+' if vel>0 else ''}{vel:.2f} m/h)",
        xy=(history_hours - 1, curr),
        xytext=(-70, 15),
        textcoords="offset points",
        color="#ffffff",
        fontweight="bold",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.4", fc="#0f172a", ec=line_color, lw=1.5),
        arrowprops=dict(arrowstyle="->", color="#ffffff", lw=1.2),
    )

    ax.set_xticks(range(history_hours))
    ax.set_xticklabels(labels, color="#94a3b8", fontsize=9)
    ax.set_ylim(0, max_y)
    ax.set_ylabel("Water Depth (Meters)", color="#e2e8f0", fontsize=11, fontweight="bold")
    ax.tick_params(colors="#94a3b8")
    ax.grid(color="#334155", linestyle=":", linewidth=0.8, alpha=0.6)

    # Title & Subtitle
    plt.title(
        f"{assessment.station_name.upper()}\n"
        f"Status: {assessment.severity.value}  |  Upstream Rain: {assessment.upstream_forecast_1h_mm:.1f} mm/hr ({assessment.upstream_catchment})",
        color="#f8fafc",
        fontsize=12,
        fontweight="bold",
        pad=15,
    )

    # Footer timestamp
    time_str = now_npt.strftime("%Y-%m-%d %I:%M %p NPT")
    fig.text(0.98, 0.02, f"Nepal Flood Early Warning Bot | {time_str}", ha="right", color="#64748b", fontsize=8)

    plt.tight_layout()
    plt.savefig(chart_path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    return chart_path


def generate_basin_overview_chart(assessments: List[RiskAssessment]) -> Path:
    """Generate a multi-station comparison bar chart showing water level vs thresholds."""
    charts_dir = ensure_charts_dir()
    chart_path = charts_dir / "basin_overview.png"

    total = len(assessments)
    fig, ax = plt.subplots(figsize=(11, max(6, total * 0.45)), dpi=150)
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#1e293b")

    names = [f"{a.station_name.split('(')[0].strip()}" for a in assessments]
    currents = [a.current_level for a in assessments]
    warnings = [a.warning_level for a in assessments]
    dangers = [a.danger_level for a in assessments]
    y_pos = list(range(total))

    colors = []
    for a in assessments:
        if a.severity == SeverityLevel.EMERGENCY:
            colors.append("#ef4444")
        elif a.severity == SeverityLevel.WARNING:
            colors.append("#f59e0b")
        elif a.severity == SeverityLevel.ADVISORY:
            colors.append("#eab308")
        else:
            colors.append("#10b981")

    # Plot horizontal bars
    bars = ax.barh(y_pos, currents, color=colors, height=0.55, edgecolor="#ffffff", linewidth=0.8, alpha=0.9)

    # Add danger and warning markers
    for idx, (w, d, c) in enumerate(zip(warnings, dangers, currents)):
        ax.plot([w, w], [idx - 0.35, idx + 0.35], color="#fbbf24", linestyle="--", linewidth=1.5)
        ax.plot([d, d], [idx - 0.35, idx + 0.35], color="#f87171", linestyle="--", linewidth=1.8)
        # Value label
        ax.text(c + 0.15, idx, f"{c:.2f}m (W:{w:.1f}m | D:{d:.1f}m)", va="center", color="#f1f5f9", fontsize=8.5, fontweight="bold")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, color="#f8fafc", fontsize=9.5, fontweight="bold")
    ax.invert_yaxis()  # Top to bottom
    ax.set_xlabel("Water Level (Meters) - Dashed: Warning / Danger Thresholds", color="#cbd5e1", fontsize=10, fontweight="bold")
    ax.tick_params(colors="#94a3b8")
    ax.grid(color="#334155", linestyle=":", linewidth=0.8, alpha=0.5, axis="x")

    now_npt = datetime.now(timezone.utc).astimezone(NPT_TIMEZONE)
    time_str = now_npt.strftime("%Y-%m-%d %I:%M %p NPT")
    plt.title(
        f"NEPAL RIVER BASINS - REAL-TIME GAUGE LEVELS\nBulletins & Early Warning Overview ({time_str})",
        color="#f8fafc",
        fontsize=12,
        fontweight="bold",
        pad=14,
    )

    plt.tight_layout()
    plt.savefig(chart_path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    return chart_path
