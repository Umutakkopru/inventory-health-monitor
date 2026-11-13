"""Status colours, icons and symbols: the one place every chart and badge takes them from.

Colours follow the Okabe-Ito palette, which stays distinguishable with red-green colour
blindness and reads on light and dark backgrounds. Status is never shown by colour alone:
badges add a Material icon, tables and charts a text symbol, and both the translated label.
"""

from inventory_monitor.models import Status

STATUS_COLORS: dict[str, str] = {
    Status.SHORTAGE_CRITICAL: "#D55E00",  # vermillion
    Status.SHORTAGE_WARNING: "#E69F00",  # orange
    Status.DEAD_STOCK: "#CC79A7",  # reddish purple
    Status.OVERSTOCK: "#0072B2",  # blue
    Status.INACTIVE: "#8C8C8C",  # grey
    Status.INSUFFICIENT_DATA: "#56B4E9",  # sky blue
    Status.OK: "#009E73",  # bluish green
}

# Material Symbols for st.badge, st.metric and markdown.
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

# st.badge accepts a fixed set of colour names; the closest match per status.
STATUS_BADGE_COLORS: dict[str, str] = {
    Status.SHORTAGE_CRITICAL: "red",
    Status.SHORTAGE_WARNING: "orange",
    Status.DEAD_STOCK: "violet",
    Status.OVERSTOCK: "blue",
    Status.INACTIVE: "gray",
    Status.INSUFFICIENT_DATA: "blue",
    Status.OK: "green",
}

# Lines and bars of the Material Detail chart.
SERIES_COLORS: dict[str, str] = {
    "stock": "#0072B2",
    "safety_stock": "#D55E00",
    "reorder_point": "#E69F00",
    "max_target": "#CC79A7",
    "receipts": "#009E73",
    "consumption": "#8C8C8C",
    "projection": "#56B4E9",
    "imputed": "#8C8C8C",
}

ABC_COLORS: dict[str, str] = {"A": "#0072B2", "B": "#56B4E9", "C": "#8C8C8C"}

# Data-quality severities: colour plus symbol plus translated label.
SEVERITY_COLORS: dict[str, str] = {"error": "#D55E00", "warning": "#E69F00", "info": "#56B4E9"}
SEVERITY_SYMBOLS: dict[str, str] = {"error": "‼", "warning": "!", "info": "i"}

NEUTRAL_LINE = "#8C8C8C"
