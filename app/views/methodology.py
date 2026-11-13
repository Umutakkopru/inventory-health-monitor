"""Methodology: every formula, assumption and limitation in plain language.

The current threshold values are filled into the text, so the page always describes the
settings the user is looking at.
"""

import streamlit as st

from app import state
from app.i18n import fmt_number, fmt_pct, t

SECTIONS = (
    "intro",
    "data",
    "consumption",
    "kpis",
    "classes",
    "status",
    "projection",
    "quality",
    "limits",
)


def render() -> None:
    """Render the page."""
    th = state.thresholds()
    values = {
        "demand_window": fmt_number(th.demand_window_days),
        "variability_weeks": fmt_number(th.variability_window_weeks),
        "min_history": fmt_number(th.min_history_days),
        "sl_a": fmt_pct(th.service_level_a, 1),
        "sl_b": fmt_pct(th.service_level_b, 1),
        "sl_c": fmt_pct(th.service_level_c, 1),
        "abc_a": fmt_pct(th.abc_cutoff_a),
        "abc_b": fmt_pct(th.abc_cutoff_b),
        "xyz_x": fmt_number(th.xyz_cutoff_x, 2),
        "xyz_y": fmt_number(th.xyz_cutoff_y, 2),
        "over_a": fmt_number(th.overstock_days_a),
        "over_b": fmt_number(th.overstock_days_b),
        "over_c": fmt_number(th.overstock_days_c),
        "dead_days": fmt_number(th.dead_stock_days),
        "iqr": fmt_number(th.anomaly_iqr_factor, 1),
        "alpha": fmt_number(th.ewma_alpha, 2),
        "horizon": fmt_number(th.projection_horizon_days),
    }
    st.title(t("method.title"))
    for section in SECTIONS:
        st.subheader(t(f"method.{section}.title"))
        st.markdown(t(f"method.{section}.body", **values))
