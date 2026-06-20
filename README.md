# Graph Animator

Small uv app that renders animated graph videos from time-series text files.

The video shows the full available time window in the background and a moving
foreground marker for the current time/value.

## Setup

```bash
cd ~/Python_APP/graph_animator
uv sync
```

Install it as an editable uv tool:

```bash
uv tool install --editable .
```

After that, edits to `graph_animator.py` are picked up without reinstalling.

## Run

List the columns detected in a file:

```bash
uv run python graph_animator.py /path/to/file.dat --list-columns
```

Render selected value columns with respect to the default `Time` column:

```bash
uv run python graph_animator.py /path/to/residuals.dat --y Ux Uy Uz -o residuals.mp4
```

Overlay the same selected value column from multiple files in one animation:

```bash
graph-animator /path/to/run1.dat /path/to/run2.dat --y 2 -o comparison.mp4
```

After installing it as an editable uv tool, the same command can be run from
any folder:

```bash
graph-animator /path/to/residuals.dat --y Ux Uy Uz -o residuals.mp4
```

For files with a text/category column, filter rows before plotting:

```bash
graph-animator /path/to/yPlus.dat --where patch=outlet_duct --y max average -o yplus.mp4
```

Use column indexes instead of names when needed:

```bash
graph-animator /path/to/file.dat --x 0 --y 2 3 -o selected_columns.mp4
```

Show only the current time in the foreground annotation, move it to the
south-east corner, and keep the legend fixed in the north-west corner:

```bash
graph-animator /path/to/file.dat --y 2 \
  --value-label time \
  --value-position se \
  --legend-position nw \
  -o time_only.mp4
```

Limit foreground annotation text updates to every `0.5` time units while the
marker and vertical time line segment keep moving every frame:

```bash
graph-animator /path/to/file.dat --y 2 --value-update-interval 0.5 -o throttled_text.mp4
```

Hide the foreground time/value annotation:

```bash
graph-animator /path/to/file.dat --y 2 --no-time-value-legend -o no_text.mp4
```

Render the first 100 data frames in 5 seconds, then render the remaining data
frames in 20 seconds:

```bash
graph-animator /path/to/file.dat --y 2 --duration-split 100 5 20 -o paced.mp4
```

Write a GIF by using a `.gif` output path. GIFs are saved with `loop=0`, which
means loop forever:

```bash
graph-animator /path/to/file.dat --y 2 --fps 12 --dpi 100 -o animation.gif
```

Highlight a point on the x-axis after the current time reaches that value:

```bash
graph-animator /path/to/file.dat --y 2 --x-marker 4.5 -o marker.mp4
```

Render only data up to an x-axis/time value:

```bash
graph-animator /path/to/file.dat --y 2 --end-time 10.0 -o until_10s.mp4
```

Set the visible x-axis and y-axis ranges:

```bash
graph-animator /path/to/file.dat --y 2 --x-range 0 10 --y-range -1 1 -o ranged.mp4
```

Set the colors used for plotted curves:

```bash
graph-animator /path/to/file.dat --y 2 3 --colors tab:blue "#d55e00" -o colored.mp4
```

## Main Options

- input files: pass one or more `.dat` files. Multiple files are plotted together in the same animation.
- `--y`: one or more value columns to animate with respect to time. Defaults to the last numeric non-x column in each input file.
- `--x`: time/x-axis column. Defaults to `Time`.
- `--colors COLOR [COLOR ...]`: colors to cycle through for plotted curves. Accepts Matplotlib color names, hex colors, and other Matplotlib color specs.
- `--end-time`: keep only rows whose x-axis/time value is less than or equal to this value. Defaults to no upper limit.
- `--x-range MIN MAX`: visible x-axis range. Requires `MIN < MAX`.
- `--y-range MIN MAX`: visible y-axis range. Requires `MIN < MAX`; `MIN` must be positive with `--logy`.
- `--all-y`: plot all numeric columns except the x-axis column. Defaults to off.
- `--where COLUMN=VALUE`: keep only matching rows. Can be repeated.
- `--logy`: use a logarithmic y-axis. Defaults to off.
- `--trail`: emphasize the elapsed part of each selected curve. Defaults to off.
- `--value-fontsize`: font size for the foreground time/value annotation. Defaults to `10`.
- `--value-position`: corner for the foreground time/value annotation: `nw`, `ne`, `sw`, or `se`. Defaults to `nw`.
- `--value-label`: annotation content: `time-value` or `time`. Defaults to `time-value`. Displayed numbers are rounded to two decimal places and left-aligned inside the annotation box.
- `--no-time-value-legend`: hide the foreground time/value annotation. Defaults to off.
- `--value-update-interval`: minimum x-axis/time interval between annotation text updates. Use `0` to update every frame.
- `--legend-position`: fixed legend corner: `nw`, `ne`, `sw`, or `se`. Defaults to `ne`.
- `--no-legend`: hide the curve legend. Defaults to off.
- `--time-line-style`: style for the current-time vertical line segment from the x-axis to the current value: `-`, `--`, `:`, or `-.`. Defaults to `--`.
- `--no-time-line`: hide the current-time vertical line segment. Defaults to off.
- `--x-marker`: x-axis/time value to highlight with a blue inverted triangle after the current time reaches or passes it.
- `--fps`: video frames per second. Defaults to `30`.
- `--duration`: target video duration in seconds for long files. Defaults to `12`.
- `--frames`: exact maximum number of animation frames. Overrides `--duration`.
- `--duration-split FIRST_FRAMES FIRST_SECONDS REMAINING_SECONDS`: pace the first `FIRST_FRAMES` data frames over `FIRST_SECONDS`, then pace the remaining data frames over `REMAINING_SECONDS`. Overrides `--duration` and `--frames`.
- `--dpi`: video DPI. Defaults to `150`.

The output format is selected from the extension passed to `-o`: use `.mp4` for
video or `.gif` for a looping GIF.
