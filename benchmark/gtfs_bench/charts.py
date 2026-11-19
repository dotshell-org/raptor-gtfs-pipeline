"""The benchmark's figures, as static PNGs for the notebook and the report.

Colours come from the reference data-viz palette (light mode): categorical slots 1–3
only (blue, orange, aqua), the three that stay apart for colour-blind readers whatever
pairs are on screen. Text stays in neutral ink, grids are hairlines, lines are 2 px.
Every chart has its numbers in a CSV next to it (results/), which is its table view.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NEUTRAL_FILL = "#f0efec"
SERIES = {"metropole": "#2a78d6", "region": "#eb6834", "france": "#1baf7a"}
KIND_LABEL = {"metropole": "Métropole", "region": "Region", "france": "France"}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelcolor=INK_SECONDARY, labelsize=9)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.xaxis.label.set_color(INK_SECONDARY)


def coverage_chart(daily: pd.DataFrame, holidays: list[tuple[dt.date, dt.date]], reference: dt.date,
                   path: Path, feeds_total: int) -> Path:
    """Two stacked panels sharing dates: feeds with service, then trips (one axis each).

    `daily` has columns date, feeds (feeds running that day) and trips (all feeds).
    """
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True, facecolor=SURFACE,
                                      gridspec_kw={"hspace": 0.35})
    dates = pd.to_datetime(daily["date"])
    for ax, column, title in ((top, "feeds", f"Feeds running that day (of {feeds_total})"),
                              (bottom, "trips", "Trips that day, all feeds, before filters")):
        _style(ax)
        for start, end in holidays:
            ax.axvspan(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1), color=NEUTRAL_FILL, linewidth=0)
        ax.plot(dates, daily[column], color=SERIES["metropole"], linewidth=2)
        ax.axvline(pd.Timestamp(reference), color=INK, linewidth=1, linestyle=(0, (3, 3)))
        ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=8)
        ax.set_ylim(bottom=0)
    bottom.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:.0f} k"))
    bottom.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    top.annotate(f"reference day\n{reference:%a %d %b %Y}", xy=(pd.Timestamp(reference), top.get_ylim()[1] * 0.08),
                 xytext=(6, 0), textcoords="offset points", fontsize=8.5, color=INK_SECONDARY)
    if holidays:
        start, _ = holidays[0]
        top.annotate("school holidays", xy=(pd.Timestamp(start), top.get_ylim()[1] * 0.06), xytext=(5, 0),
                     textcoords="offset points", fontsize=8.5, color=MUTED, va="bottom")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def local_trips_chart(rows: pd.DataFrame, path: Path) -> Path:
    """Same trips, bigger networks: one panel per city, one bar per tier that holds the city.

    `rows` has columns query_set, kind (metropole | region | france), label and latency_p50_ms,
    latency_p95_ms, for the forward direction.
    """
    sets = list(dict.fromkeys(rows["query_set"]))
    fig, axes = plt.subplots(1, len(sets), figsize=(4.6 * len(sets), 4.2), facecolor=SURFACE, squeeze=False)
    for ax, name in zip(axes[0], sets):
        _style(ax)
        ax.grid(axis="x", visible=False)
        part = rows[rows["query_set"] == name].reset_index(drop=True)
        positions = range(len(part))
        ax.bar(positions, part["latency_p50_ms"], width=0.55, color=[SERIES[k] for k in part["kind"]], zorder=3)
        for i, row in part.iterrows():
            ax.annotate(f"{row.latency_p50_ms:.1f} ms", (i, row.latency_p50_ms), xytext=(0, 15), textcoords="offset points",
                        ha="center", fontsize=9, color=INK)
            ax.annotate(f"p95 {row.latency_p95_ms:.1f}", (i, row.latency_p50_ms), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=8, color=MUTED)
        ax.set_xticks(list(positions), part["label"], fontsize=9, color=INK_SECONDARY)
        ax.set_ylim(0, part["latency_p50_ms"].max() * 1.3)
        ax.set_title(f"{name.replace('-local', '').title()} trips, median time", loc="left", fontsize=10.5, color=INK, pad=8)
    axes[0][0].set_ylabel("Forward query, ms")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def scaling_chart(points: pd.DataFrame, x: str, y: str, xlabel: str, ylabel: str, title: str, path: Path,
                  labelled: dict | None = None, y_unit: str = "") -> Path:
    """One measure against network size, one dot per tier, log–log, coloured by tier kind.

    `points` has columns tier, kind and the two named in x and y. `labelled` maps a tier to
    its label, or to (label, dx, dy) to move it off a neighbour's.
    """
    labelled = labelled or {}
    fig, ax = plt.subplots(figsize=(8.5, 5.2), facecolor=SURFACE)
    _style(ax)
    for kind in ("metropole", "region", "france"):
        part = points[points["kind"] == kind]
        ax.scatter(part[x], part[y], s=46 if kind != "france" else 80, color=SERIES[kind], edgecolor=SURFACE,
                   linewidth=2, label=KIND_LABEL[kind], zorder=3)
    for row in points.itertuples():
        if row.tier in labelled:
            label = labelled[row.tier]
            text, dx, dy = (label, 7, -3) if isinstance(label, str) else label
            ax.annotate(text, (getattr(row, x), getattr(row, y)), xytext=(dx, dy), ha="left" if dx >= 0 else "right",
                        textcoords="offset points", fontsize=8.5, color=INK_SECONDARY)
    ax.set_xscale("log")
    ax.set_yscale("log")
    if y_unit:
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g} {y_unit}"))
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=8)
    legend = ax.legend(frameon=False, loc="upper left", fontsize=9)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def pipeline_chart(points: pd.DataFrame, path: Path, labelled: dict[str, str] | None = None) -> Path:
    """Pipeline peak memory against the stop_times it read, one dot per tier, log–log.

    `points` has columns tier, kind, stop_times (merged week, what the pipeline reads in
    full before keeping the reference day) and peak_memory_mb.
    """
    labelled = labelled or {}
    fig, ax = plt.subplots(figsize=(8.5, 5.2), facecolor=SURFACE)
    _style(ax)
    for kind in ("metropole", "region", "france"):
        part = points[points["kind"] == kind]
        ax.scatter(part["stop_times"], part["peak_memory_mb"] / 1024, s=46 if kind != "france" else 80,
                   color=SERIES[kind], edgecolor=SURFACE, linewidth=2, label=KIND_LABEL[kind], zorder=3)
    for row in points.itertuples():
        if row.tier in labelled:
            ax.annotate(labelled[row.tier], (row.stop_times, row.peak_memory_mb / 1024), xytext=(7, -3),
                        textcoords="offset points", fontsize=8.5, color=INK_SECONDARY)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g} GB"))
    ax.set_xlabel("stop_times read by the pipeline (merged week)")
    ax.set_ylabel("Peak memory of the pipeline's JVM")
    ax.set_title("Pipeline memory grows with the week it reads", loc="left", fontsize=10.5, color=INK, pad=8)
    legend = ax.legend(frameon=False, loc="upper left", fontsize=9)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def tiers_chart(stats: pd.DataFrame, path: Path, labelled: dict[str, str] | None = None) -> Path:
    """Stops against trips on the reference day, one dot per tier, log–log, coloured by kind.

    `stats` has columns tier, kind, name, stops_on_reference_date, trips_on_reference_date.
    `labelled` maps the few tiers worth naming on the chart to their label.
    """
    labelled = labelled or {}
    fig, ax = plt.subplots(figsize=(8.5, 5.6), facecolor=SURFACE)
    _style(ax)
    for kind in ("metropole", "region", "france"):
        part = stats[stats["kind"] == kind]
        ax.scatter(part["stops_on_reference_date"], part["trips_on_reference_date"], s=46 if kind != "france" else 80,
                   color=SERIES[kind], edgecolor=SURFACE, linewidth=2, label=KIND_LABEL[kind], zorder=3)
    for row in stats.itertuples():
        if row.tier in labelled:
            ax.annotate(labelled[row.tier], (row.stops_on_reference_date, row.trips_on_reference_date), xytext=(7, -3),
                        textcoords="offset points", fontsize=8.5, color=INK_SECONDARY)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Stops served on the reference day")
    ax.set_ylabel("Trips on the reference day")
    ax.set_title("Size of the merged tiers", loc="left", fontsize=10.5, color=INK, pad=8)
    legend = ax.legend(frameon=False, loc="upper left", fontsize=9)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


#: Travel-time classes for the reachability map: one blue, light (quick) to dark (long).
REACH_BINS = ((180, "under 3 h", "#a7c6ee"), (360, "3–6 h", "#78a7e4"), (540, "6–9 h", "#4a87d8"),
              (720, "9–12 h", "#2a5fa8"), (float("inf"), "over 12 h", "#173a6b"))


def reachability_map(reach: pd.DataFrame, outlines: list, titles: dict[str, str], day: dt.date, path: Path) -> Path:
    """Préfectures by travel time from Paris, one small map per network, side by side.

    `reach` has columns network, lat, lon, found, duration_min (connectivity.reachability).
    `outlines` is a list of (lons, lats) rings for the background; `titles` maps each network
    to its panel title, in panel order. Unreached préfectures are crosses: no shade for them.
    """
    networks = list(titles)
    fig, axes = plt.subplots(1, len(networks), figsize=(4.6 * len(networks), 5.2), facecolor=SURFACE)
    axes = list(axes) if len(networks) > 1 else [axes]
    for ax, network in zip(axes, networks):
        ax.set_facecolor(SURFACE)
        ax.set_aspect(1 / 0.67)  # degrees of longitude are ~0.67 of latitude's at 47° N
        ax.axis("off")
        for lons, lats in outlines:
            ax.plot(lons, lats, color=AXIS, linewidth=0.6, zorder=1)
        part = reach[reach["network"] == network]
        reached = part[part["found"]]
        lower = 0
        for upper, label, colour in REACH_BINS:
            group = reached[(reached["duration_min"] > lower) & (reached["duration_min"] <= upper)]
            ax.scatter(group["lon"], group["lat"], s=34, color=colour, edgecolor=SURFACE, linewidth=1.2, zorder=3,
                       label=label)
            lower = upper
        missed = part[~part["found"]]
        ax.scatter(missed["lon"], missed["lat"], s=22, marker="x", color=INK_SECONDARY, linewidth=1.1, zorder=3,
                   label="not reached that day")
        median = reached["duration_min"].median()
        ax.set_title(f"{titles[network]}\n{len(reached)}/{len(part)} reached"
                     + (f" · median {median / 60:.1f} h" if len(reached) else ""),
                     loc="left", fontsize=9.5, color=INK, pad=6)
    handles, labels = axes[-1].get_legend_handles_labels()
    legend = fig.legend(handles, labels, frameon=False, loc="lower center", ncol=len(labels), fontsize=8.5,
                        bbox_to_anchor=(0.5, 0.06))
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    fig.suptitle(f"From Paris (Châtelet) at 07:00 to every préfecture, {day:%A %d %B %Y}, by raptor-kmp",
                 x=0.02, ha="left", fontsize=10.5, color=INK)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path
