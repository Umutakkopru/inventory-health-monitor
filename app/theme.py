"""Colours, icons, symbols and patterns: the one place every chart and badge takes them from.

The visual world is warehouse floor marking: a concrete ground, signal black and safety
yellow. Safety yellow belongs to the shell (marking rule, active page, material-code tags)
and never stands for a status. Status colours follow the Okabe-Ito palette, which stays
distinguishable with red-green colour blindness and reads on light and dark grounds; the
warning amber is a deeper ochre so it never reads as the shell yellow. Status is never shown
by colour alone: cards and spec sheets add a Material icon, tables and charts a text
symbol, critical and warning bars a fill pattern, and everything the translated label.
"""

from inventory_monitor.models import Status

STATUS_COLORS: dict[str, str] = {
    Status.SHORTAGE_CRITICAL: "#D55E00",  # vermillion
    Status.SHORTAGE_WARNING: "#C98500",  # ochre, kept apart from the shell yellow
    Status.DEAD_STOCK: "#CC79A7",  # reddish purple
    Status.OVERSTOCK: "#0072B2",  # blue
    Status.INACTIVE: "#8E8A82",  # concrete grey
    Status.INSUFFICIENT_DATA: "#56B4E9",  # sky blue
    Status.OK: "#009E73",  # bluish green
}

# Material Symbols for the status icons on cards and spec sheets (components.status_icon).
STATUS_ICONS: dict[str, str] = {
    Status.SHORTAGE_CRITICAL: ":material/error:",
    Status.SHORTAGE_WARNING: ":material/warning:",
    Status.DEAD_STOCK: ":material/hourglass_bottom:",
    Status.OVERSTOCK: ":material/inventory_2:",
    Status.INACTIVE: ":material/block:",
    Status.INSUFFICIENT_DATA: ":material/help:",
    Status.OK: ":material/check_circle:",
}

# Plain-text symbols for table cells and chart labels, where icons cannot be rendered.
STATUS_SYMBOLS: dict[str, str] = {
    Status.SHORTAGE_CRITICAL: "‼",
    Status.SHORTAGE_WARNING: "!",
    Status.DEAD_STOCK: "⌛",
    Status.OVERSTOCK: "▲",
    Status.INACTIVE: "○",
    Status.INSUFFICIENT_DATA: "?",
    Status.OK: "✓",
}

# Lines and bars of the Material Detail chart.
SERIES_COLORS: dict[str, str] = {
    "stock": "#0072B2",
    "safety_stock": "#D55E00",
    "reorder_point": "#C98500",
    "max_target": "#CC79A7",
    "receipts": "#009E73",
    "consumption": "#8E8A82",
    "projection": "#56B4E9",
    "imputed": "#8E8A82",
}

# Projection band on the Material Detail chart: the projection colour, mostly transparent.
BAND_FILL = "rgba(86, 180, 233, 0.2)"

ABC_COLORS: dict[str, str] = {"A": "#0072B2", "B": "#56B4E9", "C": "#8E8A82"}

# Data-quality severities: colour plus symbol plus translated label.
SEVERITY_COLORS: dict[str, str] = {"error": "#D55E00", "warning": "#C98500", "info": "#56B4E9"}
SEVERITY_SYMBOLS: dict[str, str] = {"error": "‼", "warning": "!", "info": "i"}

NEUTRAL_LINE = "#8E8A82"

# Plotly bar fill patterns: the form cue that carries status without colour. Critical bays
# are hatched like floor marking, warnings dotted; every other status stays solid.
STATUS_PATTERNS: dict[str, str] = {
    Status.SHORTAGE_CRITICAL: "/",
    Status.SHORTAGE_WARNING: ".",
}

# Chart typography and rules. Grid and axis lines are translucent so they read on both the
# concrete (light) and asphalt (dark) ground without knowing which theme is active.
CHART_FONT = "Barlow, sans-serif"
CHART_TITLE_FONT = "Barlow Condensed, Barlow, sans-serif"
CHART_GRID = "rgba(142, 138, 130, 0.35)"

# Hatching drawn over critical bars: light stripes read as floor marking on the vermillion.
PATTERN_INK = "rgba(255, 255, 255, 0.6)"

# Shell colours, for the few places styles.css cannot reach (cells styled through pandas).
SHELL_YELLOW = "#F2C200"
SIGNAL_BLACK = "#161616"

# ABC/XYZ matrix: concrete from pale to dark grey, so a fuller bay reads darker. The text
# stays signal black, which keeps at least 7:1 contrast on the darkest cell in both themes.
MATRIX_SCALE: list[list[float | str]] = [[0.0, "#F4F2EC"], [1.0, "#A8A398"]]
MATRIX_TEXT = SIGNAL_BLACK
