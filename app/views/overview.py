"""Overview: the answer to the challenge on one screen.

Six headline figures, the status distribution, the most urgent materials and the total
stock value over time, all as of the date chosen in the sidebar.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import components, state
from app.i18n import (
    fmt_date,
    fmt_eur,
    fmt_eur_compact,
    fmt_number,
    plotly_date_format,
    t,
)
from app.theme import PATTERN_INK, STATUS_COLORS, STATUS_PATTERNS
from inventory_monitor import pipeline
from inventory_monitor.models import Status

TOP_N = 10
VALUE_LABEL_ROOM = 1.15
STATUS_CHART_MARGIN_RIGHT = 60  # pixels
KPI_WIDTHS = [1, 1, 1, 1, 1.5, 1.5]
# Pixel widths that add up to the table's slot beside the status bays at 1280 px (530 px), so
# the frame ends on a column edge; wider screens stretch them. Long short texts get "…".
COLUMN_WIDTHS = {
    "col.material_id": 80,
    "col.status": 135,
    "col.description": 125,
    "col.value_at_risk": 100,
    "col.plant": 50,
    "col.abc": 40,
}


def render() -> None:
    """Render the page."""
    analysis = state.result()
    st.title(t("overview.title"))
    st.caption(t("overview.subtitle", date=fmt_date(analysis.as_of)))
    if not components.require_plants():
        return
    components.tags([t("overview.plant_tag", plant=p) for p in state.selected_plants()])
    metrics = state.plant_metrics(analysis)
    _kpi_row(metrics, analysis.thresholds.dead_stock_days)
    # First viewport: status bays on the left, the most urgent materials on the right.
    left, right = st.columns([2, 3])
    with left:
        _status_chart(metrics)
    with right:
        _most_urgent(metrics)
    _stock_value_chart(analysis.as_of)


def _kpi_row(metrics: pd.DataFrame, dead_stock_days: int) -> None:
    figures = pipeline.kpis(metrics)
    # (key, figure, proof arguments, status whose symbol and form the card carries)
    cards = [
        ("critical", fmt_number(figures["critical"]), {}, Status.SHORTAGE_CRITICAL),
        ("warning", fmt_number(figures["warning"]), {}, Status.SHORTAGE_WARNING),
        ("overstock", fmt_number(figures["overstock"]), {}, Status.OVERSTOCK),
        (
            "dead_stock",
            fmt_number(figures["dead_stock"]),
            {"days": dead_stock_days},
            Status.DEAD_STOCK,
        ),
        (
            "stock_value",
            fmt_eur_compact(figures["stock_value"]),
            {"count": fmt_number(len(metrics))},
            None,
        ),
        ("excess_value", fmt_eur_compact(figures["excess_value"]), {}, None),
    ]
    # The two amount cards get more room than the four counts.
    for column, (name, value, proof_args, status) in zip(
        st.columns(KPI_WIDTHS), cards, strict=True
    ):
        key = f"overview.kpi.{name}"
        with column:
            components.kpi(
                t(key),
                value,
                t(f"{key}_proof", **proof_args),
                help_text=t(f"{key}_help"),
                status=status,
            )


def _status_chart(metrics: pd.DataFrame) -> None:
    counts = pipeline.status_counts(metrics)
    labels = [components.status_text(code) for code in counts.index]
    fig = go.Figure(
        go.Bar(
            x=counts.to_numpy(),
            y=labels,
            orientation="h",
            marker={
                "color": [STATUS_COLORS[code] for code in counts.index],
                # Form as well as colour: critical hatched, warning dotted (theme.py).
                "pattern": {
                    "shape": [STATUS_PATTERNS.get(code, "") for code in counts.index],
                    "fgcolor": PATTERN_INK,
                    "fillmode": "overlay",
                    "size": 7,
                },
            },
            text=counts.to_numpy(),
            textposition="outside",
            cliponaxis=False,
            hovertemplate=t("overview.status_chart.hover") + "<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")  # most urgent at the top
    # Headroom on the right so the count beside the longest bar is never clipped.
    fig.update_xaxes(range=[0, max(int(counts.max()), 1) * VALUE_LABEL_ROOM])
    components.style_figure(
        fig,
        t("overview.status_chart.title"),
        t("overview.status_chart.x"),
        "",
    )
    # The long status labels push the plot right; a wider right margin keeps the centred
    # axis title inside the frame on a phone.
    fig.update_layout(margin_r=STATUS_CHART_MARGIN_RIGHT)
    components.show_figure(fig, key="overview_status_chart")


def _stock_value_chart(as_of: pd.Timestamp) -> None:
    history = pipeline.stock_value_history(state.prepared(), as_of, state.selected_plants())
    if history.empty:
        components.empty_state()
        return
    fig = go.Figure(
        go.Scatter(
            x=history["date"],
            y=history["stock_value"],
            mode="lines",
            line={"color": STATUS_COLORS["OVERSTOCK"], "width": 2},
            hovertemplate=t("overview.value_chart.hover", date_format=plotly_date_format())
            + "<extra></extra>",
        )
    )
    fig.update_xaxes(tickformat=plotly_date_format())
    fig.update_yaxes(tickformat=",.0f")  # full amounts with the language's separators
    components.style_figure(
        fig,
        t("overview.value_chart.title"),
        t("overview.value_chart.x"),
        t("overview.value_chart.y"),
    )
    components.show_figure(fig, key="overview_value_chart")


def _most_urgent(metrics: pd.DataFrame) -> None:
    st.subheader(t("overview.top.title"))
    st.caption(t("overview.top.caption"))
    alerts = metrics[metrics["status"].isin(pipeline.ALERT_STATUSES)]
    if alerts.empty:
        components.empty_state()
        return
    top = pipeline.sort_by_urgency(alerts).head(TOP_N)
    # Only what ranks the list fits beside the status bays; stock, safety stock and coverage
    # are one click away in Alerts and Material Detail.
    table = pd.DataFrame(
        {
            # The material code leads the row, as on a rack label.
            t("col.material_id"): top["material_id"],
            t("col.status"): top["status"].map(components.status_text),
            t("col.description"): top["description"],
            # Value at risk drives the order, so it sits next to the material.
            t("col.value_at_risk"): top["value_at_risk"].map(fmt_eur),
            t("col.plant"): top["plant"],
            t("col.abc"): top["abc"],
        }
    )
    widths = {t(c): st.column_config.TextColumn(width=w) for c, w in COLUMN_WIDTHS.items()}
    # Material numbers lead each row as yellow code tags, like the labels on a rack.
    styled = table.style.map(components.code_tag_style, subset=[t("col.material_id")])
    st.dataframe(styled, hide_index=True, column_config=widths, key="overview_top_table")
