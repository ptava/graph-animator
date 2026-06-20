#!/usr/bin/env python3
"""Render an animated time-series graph from an OpenFOAM-style .dat file."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter
import numpy as np


MISSING = {"", "N/A", "NA", "nan", "NaN", "None", "none"}


@dataclass(frozen=True)
class Curve:
    source: Path
    x_label: str
    y_label: str
    label: str
    x: np.ndarray
    y: np.ndarray


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """Show defaults while preserving example formatting."""


class LoopingGifWriter(PillowWriter):
    """Pillow GIF writer that explicitly loops forever."""

    def finish(self):
        self._frames[0].save(
            self.outfile,
            save_all=True,
            append_images=self._frames[1:],
            duration=int(1000 / self.fps),
            loop=0,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a video showing the full available time window in the "
            "background and the current time/value in the foreground."
        ),
        formatter_class=HelpFormatter,
        epilog="""Examples:
  graph-animator pressureLossVessel.region1/0/surfaceFieldValue.dat
  graph-animator residuals/0/residuals.dat --y Ux Uy Uz --logy -o residuals.mp4
  graph-animator yPlusWalls/0/yPlus.dat --where patch=outlet_duct --y max average

Columns may be selected by header name or by zero-based column index.
""",
    )
    parser.add_argument("dat_files", nargs="+", type=Path, help="Input .dat file(s)")
    parser.add_argument("-o", "--output", type=Path, help="Output video path")
    parser.add_argument("--x", default="Time", help="X/time column name or index")
    parser.add_argument(
        "--y",
        nargs="+",
        help="Y column name(s) or index(es). Defaults to the last numeric non-x column.",
    )
    parser.add_argument(
        "--all-y",
        action="store_true",
        help="Plot every numeric column except the x/time column.",
    )
    parser.add_argument(
        "--where",
        action="append",
        default=[],
        metavar="COLUMN=VALUE",
        help="Filter rows before plotting. Can be repeated, e.g. --where patch=outlet_duct.",
    )
    parser.add_argument(
        "--end-time",
        type=float,
        help="Keep only rows whose x/time value is less than or equal to this value.",
    )
    parser.add_argument(
        "--x-range",
        nargs=2,
        type=float,
        metavar=("MIN", "MAX"),
        help="Visible x-axis range.",
    )
    parser.add_argument(
        "--y-range",
        nargs=2,
        type=float,
        metavar=("MIN", "MAX"),
        help="Visible y-axis range.",
    )
    parser.add_argument("--title", help="Plot title. Defaults to the input path")
    parser.add_argument("--xlabel", help="X-axis label")
    parser.add_argument("--ylabel", help="Y-axis label")
    parser.add_argument("--fps", type=int, default=30, help="Video frames per second")
    parser.add_argument(
        "--duration",
        type=float,
        default=12.0,
        help="Target video duration in seconds for long files",
    )
    parser.add_argument(
        "--frames",
        type=int,
        help="Exact maximum number of animation frames. Overrides --duration sampling.",
    )
    parser.add_argument(
        "--duration-split",
        nargs=3,
        metavar=("FIRST_FRAMES", "FIRST_SECONDS", "REMAINING_SECONDS"),
        help=(
            "Render the first FIRST_FRAMES data frames over FIRST_SECONDS, "
            "then render the remaining data frames over REMAINING_SECONDS. "
            "Overrides --duration and --frames."
        ),
    )
    parser.add_argument("--dpi", type=int, default=150, help="Video DPI")
    parser.add_argument(
        "--value-fontsize",
        type=float,
        default=10.0,
        help="Font size for the foreground time/value annotation.",
    )
    parser.add_argument(
        "--value-position",
        choices=("nw", "ne", "sw", "se"),
        default="nw",
        help="Corner position for the foreground time/value annotation.",
    )
    parser.add_argument(
        "--value-label",
        choices=("time-value", "time"),
        default="time-value",
        help="Content shown in the foreground annotation.",
    )
    parser.add_argument(
        "--no-time-value-legend",
        action="store_false",
        dest="show_value_annotation",
        default=argparse.SUPPRESS,
        help="Hide the foreground time/value annotation.",
    )
    parser.add_argument(
        "--value-update-interval",
        type=float,
        default=0.0,
        help=(
            "Minimum x-axis/time interval between foreground annotation text "
            "updates. Use 0 to update every frame."
        ),
    )
    parser.add_argument(
        "--legend-position",
        choices=("nw", "ne", "sw", "se"),
        default="ne",
        help="Corner position for the legend.",
    )
    parser.add_argument(
        "--time-line-style",
        choices=("-", "--", ":", "-."),
        default="--",
        help="Line style for the current-time vertical line segment.",
    )
    parser.add_argument(
        "--no-time-line",
        action="store_false",
        dest="show_time_line",
        default=argparse.SUPPRESS,
        help="Hide the current-time vertical line segment.",
    )
    parser.add_argument(
        "--x-marker",
        type=float,
        help=(
            "X-axis/time value to highlight after the current time reaches "
            "or passes it."
        ),
    )
    parser.add_argument(
        "--figsize",
        nargs=2,
        type=float,
        default=(10.0, 5.5),
        metavar=("WIDTH", "HEIGHT"),
        help="Figure size in inches",
    )
    parser.add_argument("--logy", action="store_true", help="Use logarithmic y-axis")
    parser.add_argument(
        "--trail",
        action="store_true",
        help="Draw the elapsed part of each curve more strongly in the foreground.",
    )
    parser.add_argument(
        "--list-columns",
        action="store_true",
        help="Print detected columns and exit without rendering.",
    )
    args = parser.parse_args()
    for name in ("x_range", "y_range"):
        values = getattr(args, name)
        if values is not None and values[0] >= values[1]:
            parser.error(f"--{name.replace('_', '-')} requires MIN < MAX")
    if args.logy and args.y_range is not None and args.y_range[0] <= 0:
        parser.error("--y-range MIN must be positive when --logy is used")
    if not hasattr(args, "show_value_annotation"):
        args.show_value_annotation = True
    if not hasattr(args, "show_time_line"):
        args.show_time_line = True
    return args


def split_header(line: str) -> list[str]:
    return line.lstrip("#").strip().split()


def read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    header: list[str] | None = None
    rows: list[list[str]] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                tokens = split_header(line)
                if tokens and tokens[0].lower() == "time":
                    header = tokens
                continue
            rows.append(line.split())

    if not rows:
        raise ValueError(f"No data rows found in {path}")

    width = max(len(row) for row in rows)
    if header is None:
        header = [f"col{i}" for i in range(width)]
        header[0] = "Time"
    elif len(header) < width:
        header = header + [f"col{i}" for i in range(len(header), width)]

    header = make_unique(header[:width])
    normalized_rows = [row + [""] * (width - len(row)) for row in rows if row]
    return header, normalized_rows


def make_unique(names: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    unique: list[str] = []
    for name in names:
        if name not in counts:
            counts[name] = 0
            unique.append(name)
            continue
        counts[name] += 1
        unique.append(f"{name}_{counts[name]}")
    return unique


def resolve_column(spec: str, columns: list[str]) -> int:
    if spec in columns:
        return columns.index(spec)
    try:
        idx = int(spec)
    except ValueError as exc:
        available = ", ".join(columns)
        raise ValueError(f"Unknown column {spec!r}. Available columns: {available}") from exc
    if idx < 0 or idx >= len(columns):
        raise ValueError(f"Column index {idx} is outside 0..{len(columns) - 1}")
    return idx


def parse_filters(filters: list[str], columns: list[str]) -> list[tuple[int, str]]:
    parsed: list[tuple[int, str]] = []
    for condition in filters:
        if "=" not in condition:
            raise ValueError(f"Filter must look like COLUMN=VALUE, got {condition!r}")
        key, value = condition.split("=", 1)
        parsed.append((resolve_column(key.strip(), columns), value.strip()))
    return parsed


def apply_filters(
    rows: list[list[str]], filters: list[tuple[int, str]]
) -> list[list[str]]:
    if not filters:
        return rows
    filtered = [
        row
        for row in rows
        if all(row[column].strip() == expected for column, expected in filters)
    ]
    if not filtered:
        raise ValueError("No rows left after applying --where filters")
    return filtered


def to_float(value: str) -> float:
    if value in MISSING:
        return math.nan
    try:
        return float(value)
    except ValueError:
        return math.nan


def numeric_matrix(rows: list[list[str]]) -> np.ndarray:
    return np.array([[to_float(value) for value in row] for row in rows], dtype=float)


def numeric_columns(data: np.ndarray) -> list[int]:
    result: list[int] = []
    for idx in range(data.shape[1]):
        if np.isfinite(data[:, idx]).any():
            result.append(idx)
    return result


def default_y_column(data: np.ndarray, x_idx: int, numeric: list[int]) -> int:
    candidates = [idx for idx in numeric if idx != x_idx]
    if not candidates:
        raise ValueError("No numeric y columns found")

    non_constant: list[int] = []
    for idx in candidates:
        values = data[:, idx]
        finite = values[np.isfinite(values)]
        if finite.size > 1 and np.nanmax(finite) != np.nanmin(finite):
            non_constant.append(idx)

    return (non_constant or candidates)[-1]


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return cleaned or "animation"


def output_path(input_paths: list[Path], output: Path | None, y_names: list[str]) -> Path:
    if output is not None:
        return output
    if len(input_paths) == 1:
        input_name = input_paths[0].stem
    else:
        visible_names = "_".join(path.stem for path in input_paths[:3])
        suffix = "" if len(input_paths) <= 3 else f"_{len(input_paths)}files"
        input_name = f"{visible_names}{suffix}"
    stem = safe_name(f"{input_name}_{'_'.join(y_names)}")
    stem = stem[:180].rstrip("._-") or "animation"
    return Path(f"{stem}.mp4")


def parse_duration_split(spec: list[str] | None) -> tuple[int, float, float] | None:
    if spec is None:
        return None
    first_frames_text, first_seconds_text, remaining_seconds_text = spec
    try:
        first_frames = int(first_frames_text)
    except ValueError as exc:
        raise ValueError("FIRST_FRAMES in --duration-split must be an integer") from exc
    try:
        first_seconds = float(first_seconds_text)
        remaining_seconds = float(remaining_seconds_text)
    except ValueError as exc:
        raise ValueError(
            "FIRST_SECONDS and REMAINING_SECONDS in --duration-split must be numbers"
        ) from exc
    if first_frames < 1:
        raise ValueError("FIRST_FRAMES in --duration-split must be at least 1")
    if first_seconds <= 0 or remaining_seconds <= 0:
        raise ValueError(
            "FIRST_SECONDS and REMAINING_SECONDS in --duration-split must be greater than 0"
        )
    return first_frames, first_seconds, remaining_seconds


def paced_frame_indices(start: int, stop: int, count: int) -> np.ndarray:
    if stop < start:
        return np.array([], dtype=int)
    return np.rint(np.linspace(start, stop, count)).astype(int)


def choose_frame_indices(
    n_points: int,
    fps: int,
    duration: float,
    frames: int | None,
) -> np.ndarray:
    if n_points < 1:
        raise ValueError("No valid points to animate")
    max_frames = frames if frames is not None else max(1, int(round(fps * duration)))
    count = min(n_points, max_frames)
    return np.unique(np.linspace(0, n_points - 1, count, dtype=int))


def choose_frame_times(
    timeline: np.ndarray,
    fps: int,
    duration: float,
    frames: int | None,
    duration_split: tuple[int, float, float] | None,
) -> np.ndarray:
    if timeline.size < 1:
        raise ValueError("No valid points to animate")
    if duration_split is not None:
        first_frames, first_seconds, remaining_seconds = duration_split
        split_at = min(first_frames, timeline.size)
        first_count = max(1, int(round(fps * first_seconds)))
        first_segment = np.linspace(float(timeline[0]), float(timeline[split_at - 1]), first_count)
        if split_at >= timeline.size:
            return first_segment
        remaining_count = max(1, int(round(fps * remaining_seconds)))
        remaining_segment = np.linspace(
            float(timeline[split_at]),
            float(timeline[-1]),
            remaining_count,
        )
        return np.concatenate((first_segment, remaining_segment))
    frame_indices = choose_frame_indices(timeline.size, fps, duration, frames)
    return timeline[frame_indices]


def merge_close_times(values: np.ndarray) -> np.ndarray:
    values = np.sort(values[np.isfinite(values)])
    if values.size < 2:
        return values

    unique_values = np.unique(values)
    positive_diffs = np.diff(unique_values)
    positive_diffs = positive_diffs[positive_diffs > 0]
    if positive_diffs.size == 0:
        return unique_values

    tolerance = float(np.percentile(positive_diffs, 75) * 0.01)
    if tolerance <= 0:
        return unique_values

    merged = []
    cluster = [float(values[0])]
    for value in values[1:]:
        current = float(value)
        if current - cluster[-1] <= tolerance:
            cluster.append(current)
            continue
        merged.append(float(np.mean(cluster)))
        cluster = [current]
    merged.append(float(np.mean(cluster)))
    return np.array(merged, dtype=float)


def pad_limits(values: np.ndarray, logy: bool) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if logy:
        finite = finite[finite > 0]
    if finite.size == 0:
        return (0.0, 1.0)
    lo = float(np.nanmin(finite))
    hi = float(np.nanmax(finite))
    if lo == hi:
        delta = abs(lo) * 0.05 or 1.0
        return (lo - delta, hi + delta)
    if logy:
        return (lo * 0.8, hi * 1.2)
    padding = (hi - lo) * 0.08
    return (lo - padding, hi + padding)


def visible_values(values: np.ndarray, logy: bool) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if logy:
        finite = finite[finite > 0]
    return finite


def curve_y_at(curve: Curve, current_x: float, logy: bool) -> float | None:
    if curve.x.size == 0:
        return None
    finite = np.isfinite(curve.x) & np.isfinite(curve.y)
    if logy:
        finite &= curve.y > 0
    if not np.any(finite):
        return None
    x = curve.x[finite]
    y = curve.y[finite]
    if current_x < x[0] or current_x > x[-1]:
        return None
    return float(np.interp(current_x, x, y))


def first_visible_y(values: list[float | None], logy: bool) -> float | None:
    finite = np.array([value for value in values if value is not None], dtype=float)
    finite = visible_values(finite, logy)
    if finite.size == 0:
        return None
    return float(finite[0])


def annotation_position(corner: str) -> tuple[float, float, str, str]:
    positions = {
        "nw": (0.015, 0.97, "left", "top"),
        "ne": (0.985, 0.97, "right", "top"),
        "sw": (0.015, 0.03, "left", "bottom"),
        "se": (0.985, 0.03, "right", "bottom"),
    }
    return positions[corner]


def legend_location(corner: str) -> str:
    locations = {
        "nw": "upper left",
        "ne": "upper right",
        "sw": "lower left",
        "se": "lower right",
    }
    return locations[corner]


def select_y_indices(
    columns: list[str],
    data: np.ndarray,
    x_idx: int,
    numeric: list[int],
    args: argparse.Namespace,
) -> list[int]:
    if args.all_y:
        return [idx for idx in numeric if idx != x_idx]
    if args.y:
        return [resolve_column(spec, columns) for spec in args.y]
    return [default_y_column(data, x_idx, numeric)]


def load_curves(path: Path, args: argparse.Namespace, include_source: bool) -> list[Curve]:
    columns, rows = read_table(path)
    filters = parse_filters(args.where, columns)
    rows = apply_filters(rows, filters)
    data = numeric_matrix(rows)

    x_idx = resolve_column(args.x, columns)
    numeric = numeric_columns(data)
    if x_idx not in numeric:
        raise ValueError(f"{path}: X column {columns[x_idx]!r} is not numeric")

    y_indices = select_y_indices(columns, data, x_idx, numeric, args)
    non_numeric_y = [columns[idx] for idx in y_indices if idx not in numeric]
    if non_numeric_y:
        raise ValueError(f"{path}: Y columns are not numeric: {', '.join(non_numeric_y)}")

    x = data[:, x_idx]
    finite_x = np.isfinite(x)
    if args.end_time is not None:
        finite_x &= x <= args.end_time
    x = x[finite_x]
    y_values = data[finite_x][:, y_indices]

    order = np.argsort(x)
    x = x[order]
    y_values = y_values[order]

    curves = []
    for pos, y_idx in enumerate(y_indices):
        y = y_values[:, pos]
        if not np.isfinite(y).any():
            continue
        y_label = columns[y_idx]
        label = f"{path.stem}: {y_label}" if include_source else y_label
        curves.append(
            Curve(
                source=path,
                x_label=columns[x_idx],
                y_label=y_label,
                label=label,
                x=x,
                y=y,
            )
        )
    if not curves:
        raise ValueError(f"{path}: No valid points to animate")
    return curves


def unique_text(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def list_columns(paths: list[Path]) -> None:
    show_path = len(paths) > 1
    for path_idx, path in enumerate(paths):
        columns, _ = read_table(path)
        if show_path:
            if path_idx:
                print()
            print(f"{path}:")
            prefix = "  "
        else:
            prefix = ""
        for idx, name in enumerate(columns):
            print(f"{prefix}{idx}: {name}")


def render_animation(
    paths: list[Path],
    curves: list[Curve],
    args: argparse.Namespace,
) -> Path:
    timeline = merge_close_times(np.concatenate([curve.x for curve in curves]))
    if timeline.size == 0:
        raise ValueError("No valid points to animate")

    y_names = [curve.label for curve in curves]
    destination = output_path(paths, args.output, y_names)
    frame_times = choose_frame_times(
        timeline,
        args.fps,
        args.duration,
        args.frames,
        args.duration_split,
    )

    fig, ax = plt.subplots(figsize=tuple(args.figsize), constrained_layout=True)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    background_lines = []
    trail_lines = []
    markers = []

    for pos, curve in enumerate(curves):
        color = colors[pos % len(colors)]
        (background,) = ax.plot(curve.x, curve.y, color=color, alpha=0.28, lw=1.5)
        background_lines.append(background)
        if args.trail:
            (trail,) = ax.plot([], [], color=color, lw=2.2, label=curve.label)
        else:
            trail = None
            background.set_label(curve.label)
        trail_lines.append(trail)
        (marker,) = ax.plot([], [], "o", color=color, ms=7, mec="white", mew=0.8, zorder=5)
        markers.append(marker)

    current_line = None
    if args.show_time_line:
        (current_line,) = ax.plot(
            [],
            [],
            color="black",
            linestyle=args.time_line_style,
            lw=1.2,
            alpha=0.75,
            zorder=4,
        )
    x_marker = None
    if args.x_marker is not None:
        (x_marker,) = ax.plot(
            [args.x_marker],
            [0],
            marker="v",
            markersize=10,
            color="#0072B2",
            mec="white",
            mew=0.8,
            linestyle="None",
            transform=ax.get_xaxis_transform(),
            clip_on=False,
            visible=False,
            zorder=20,
        )
    text = None
    if args.show_value_annotation:
        text_x, text_y, text_ha, text_va = annotation_position(args.value_position)
        text = ax.text(
            text_x,
            text_y,
            "",
            transform=ax.transAxes,
            va=text_va,
            ha=text_ha,
            multialignment="left",
            fontsize=args.value_fontsize,
            zorder=10,
            bbox={
                "boxstyle": "round,pad=0.35",
                "fc": "white",
                "ec": "0.75",
                "alpha": 0.9,
            },
        )

    title = args.title or (str(paths[0]) if len(paths) == 1 else " + ".join(path.name for path in paths))
    x_labels = unique_text([curve.x_label for curve in curves])
    y_labels = unique_text([curve.y_label for curve in curves])
    all_y = np.concatenate([curve.y for curve in curves])

    ax.set_title(title)
    ax.set_xlabel(args.xlabel or ", ".join(x_labels))
    ax.set_ylabel(args.ylabel or ", ".join(y_labels))
    x_limits = tuple(args.x_range) if args.x_range is not None else (
        float(np.nanmin(timeline)),
        float(np.nanmax(timeline)),
    )
    y_limits = tuple(args.y_range) if args.y_range is not None else pad_limits(all_y, args.logy)
    ax.set_xlim(*x_limits)
    ax.set_ylim(*y_limits)
    if args.logy:
        ax.set_yscale("log")
    current_line_y0 = ax.get_ylim()[0]
    ax.grid(True, alpha=0.25)
    ax.legend(loc=legend_location(args.legend_position))

    last_label_x: float | None = None
    last_label_text = ""

    def update(current_x: float):
        nonlocal last_label_x, last_label_text
        current_x = float(current_x)
        current_y_values = [curve_y_at(curve, current_x, args.logy) for curve in curves]
        if current_line is not None:
            current_line_y1 = first_visible_y(current_y_values, args.logy)
            if current_line_y1 is None:
                current_line.set_data([], [])
            else:
                current_line.set_data([current_x, current_x], [current_line_y0, current_line_y1])
        if x_marker is not None:
            x_marker.set_visible(current_x >= args.x_marker)
        should_update_label = args.show_value_annotation and (
            last_label_x is None
            or args.value_update_interval <= 0
            or current_x - last_label_x >= args.value_update_interval
            or current_x >= timeline[-1]
        )
        label_lines = [f"{x_labels[0]} = {current_x:.2f}"] if should_update_label else []

        artists = []
        if text is not None:
            artists.append(text)
        if current_line is not None:
            artists.append(current_line)
        if x_marker is not None:
            artists.append(x_marker)
        for pos, curve in enumerate(curves):
            current_y = current_y_values[pos]
            if current_y is None:
                markers[pos].set_data([], [])
            else:
                markers[pos].set_data([current_x], [current_y])
            artists.append(markers[pos])
            if should_update_label and args.value_label == "time-value":
                if current_y is not None:
                    label_lines.append(f"{curve.label} = {current_y:.2f}")
                else:
                    label_lines.append(f"{curve.label} = N/A")
            if trail_lines[pos] is not None:
                elapsed = curve.x <= current_x
                trail_lines[pos].set_data(curve.x[elapsed], curve.y[elapsed])
                artists.append(trail_lines[pos])

        if should_update_label:
            last_label_x = float(current_x)
            last_label_text = "\n".join(label_lines)
        if text is not None:
            text.set_text(last_label_text)
        return artists

    animation = FuncAnimation(
        fig,
        update,
        frames=frame_times,
        interval=1000 / args.fps,
        blit=False,
        repeat=False,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".gif":
        writer = LoopingGifWriter(fps=args.fps)
    else:
        writer = FFMpegWriter(fps=args.fps, codec="libx264", bitrate=1800)
    animation.save(destination, writer=writer, dpi=args.dpi)
    plt.close(fig)
    return destination


def main() -> int:
    args = parse_args()
    args.duration_split = parse_duration_split(args.duration_split)

    if args.list_columns:
        list_columns(args.dat_files)
        return 0

    include_source = len(args.dat_files) > 1
    curves = []
    for path in args.dat_files:
        curves.extend(load_curves(path, args, include_source))

    destination = render_animation(args.dat_files, curves, args)
    print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
