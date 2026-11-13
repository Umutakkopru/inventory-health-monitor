"""Material Detail: the story behind one material's status.

Top chart: stock over time with safety stock, reorder point and maximum, receipts as bars,
imputed days marked, and the projection "if no further receipt arrives" with its band.
Bottom chart: derived consumption per day. Key figures and master data sit beside it.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app import components, state
from app.i18n import (
    fmt_coverage,
    fmt_date,
    fmt_eur,
    fmt_number,
    fmt_pct,
    plotly_date_format,
    plotly_separators,
    t,
)
from app.theme import BAND_FILL, SERIES_COLORS
from inventory_monitor import pipeline
from inventory_monitor.models import MaterialHistory

CHART_HEIGHT = 620
ROW_HEIGHTS = [0.72, 0.28]
LIMIT_LINES = ("safety_stock", "reorder_point", "max_target")
PIECES = "ST"  # counted in whole pieces, shown without decimals


def render() -> None:
    """Render the page."""
    analysis = state.result()
    st.title(t("detail.title"))
    if not components.require_plants():
        return
    metrics = pipeline.sort_by_urgency(state.plant_metrics(analysis))
    if metrics.empty:
        components.empty_state()
        return
    options = [
        state.material_key(m, p)
        for m, p in zip(metrics["material_id"], metrics["plant"], strict=True)
    ]
    labels = dict(zip(options, _option_labels(metrics), strict=True))
    if st.session_state.get(state.MATERIAL) not in labels:
        st.session_state[state.MATERIAL] = options[0]  # most urgent material of the selection
    st.selectbox(t("detail.select"), options, format_func=labels.get, key=state.MATERIAL)

    material_id, plant = state.split_material_key(st.session_state[state.MATERIAL])
    history = pipeline.material_history(state.prepared(), analysis, material_id, plant)
    chart_col, facts_col = st.columns([2.5, 1.2])
    with chart_col:
        _chart(history)
    with facts_col:
        _facts(history.metrics)
    _storage_locations(history)


def _option_labels(metrics: pd.DataFrame) -> list[str]:
    return [
        f"{m} · {p} · {d} · {components.status_text(s)}"
        for m, p, d, s in zip(
            metrics["material_id"],
            metrics["plant"],
            metrics["description"],
            metrics["status"],
            strict=True,
        )
    ]


def _hover(label: str, unit: str) -> str:
    return f"%{{x|{plotly_date_format()}}}<br>{label}: %{{y:,.1f}} {unit}<extra></extra>"


def _chart(history: MaterialHistory) -> None:
    m, daily, projection = history.metrics, history.daily, history.projection
    unit = m["unit"]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=ROW_HEIGHTS, vertical_spacing=0.06
    )

    fig.add_bar(
        x=daily["date"],
        y=daily["receipt_qty"].where(daily["receipt_qty"] > 0),
        name=t("detail.series.receipts"),
        marker_color=SERIES_COLORS["receipts"],
        opacity=0.6,
        hovertemplate=_hover(t("detail.series.receipts"), unit),
        row=1,
        col=1,
    )
    fig.add_scatter(
        x=daily["date"],
        y=daily["stock_filled"],
        mode="lines",
        line_shape="hv",
        name=t("detail.series.stock"),
        line={"color": SERIES_COLORS["stock"], "width": 2},
        hovertemplate=_hover(t("detail.series.stock"), unit),
        row=1,
        col=1,
    )
    imputed = daily[~daily["is_observed"]]
    fig.add_scatter(
        x=imputed["date"],
        y=imputed["stock_filled"],
        mode="markers",
        name=t("detail.series.missing"),
        marker={"symbol": "x", "size": 7, "color": SERIES_COLORS["imputed"]},
        hovertemplate=_hover(t("detail.series.missing"), unit),
        row=1,
        col=1,
    )
    _projection(fig, projection, unit)
    end = projection["date"].max()
    for name in LIMIT_LINES:
        if pd.notna(m[name]):
            fig.add_scatter(
                x=[daily["date"].min(), end],
                y=[m[name], m[name]],
                mode="lines",
                name=t(f"col.{name}"),
                line={"color": SERIES_COLORS[name], "dash": "dot", "width": 1.5},
                hovertemplate=_hover(t(f"col.{name}"), unit),
                row=1,
                col=1,
            )
    fig.add_bar(
        x=daily["date"],
        y=daily["consumption"],
        name=t("detail.series.consumption"),
        marker_color=SERIES_COLORS["consumption"],
        hovertemplate=_hover(t("detail.series.consumption"), unit),
        row=2,
        col=1,
    )

    fig.update_layout(
        title={"text": t("detail.chart.title", material=m.name[0], plant=m.name[1])},
        height=CHART_HEIGHT,
        separators=plotly_separators(),
        barmode="overlay",
        legend={"orientation": "h", "yanchor": "top", "y": -0.12},
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        hovermode="x unified",
    )
    fig.update_xaxes(tickformat=plotly_date_format())
    fig.update_xaxes(title_text=t("detail.chart.x"), row=2, col=1)
    fig.update_yaxes(
        title_text=t("detail.chart.y_stock", unit=unit), tickformat=",.0f", row=1, col=1
    )
    fig.update_yaxes(
        title_text=t("detail.chart.y_consumption", unit=unit), tickformat=",.0f", row=2, col=1
    )
    components.apply_type(fig)
    components.show_figure(fig, key="detail_chart")
    st.caption(t("detail.chart.caption"))


def _projection(fig: go.Figure, projection: pd.DataFrame, unit: str) -> None:
    """Band first (filled between upper and lower), then the projected line on top."""
    label = t("detail.series.projection")
    fig.add_scatter(
        x=projection["date"],
        y=projection["upper"],
        mode="lines",
        line={"width": 0},
        showlegend=False,
        hoverinfo="skip",
        row=1,
        col=1,
    )
    fig.add_scatter(
        x=projection["date"],
        y=projection["lower"],
        mode="lines",
        line={"width": 0},
        fill="tonexty",
        fillcolor=BAND_FILL,
        name=t("detail.series.band"),
        hoverinfo="skip",
        row=1,
        col=1,
    )
    fig.add_scatter(
        x=projection["date"],
        y=projection["projected_stock"],
        mode="lines",
        name=label,
        line={"color": SERIES_COLORS["projection"], "dash": "dash", "width": 2},
        hovertemplate=_hover(label, unit),
        row=1,
        col=1,
    )


def _facts(m: pd.Series) -> None:
    components.status_badge(m["status"])
    unit = m["unit"]

    decimals = 0 if unit == PIECES else 1

    def qty(value: float) -> str:
        return f"{fmt_number(value, decimals)} {unit}"

    facts = [
        ("col.stock", qty(m["stock"])),
        ("col.safety_stock", qty(m["safety_stock"])),
        ("col.reorder_point", qty(m["reorder_point"])),
        ("col.max_target", qty(m["max_target"])),
        ("col.coverage_days", fmt_coverage(m["coverage_days"])),
        ("detail.fact.avg_demand", qty(m["avg_daily_demand"])),
        ("detail.fact.sigma_weekly", qty(m["sigma_weekly"])),
        ("detail.fact.classes", f"{m['abc']} / {m['xyz']}"),
        ("col.value_at_risk", fmt_eur(m["value_at_risk"])),
        ("col.projected_below_safety_date", fmt_date(m["projected_below_safety_date"])),
        ("col.projected_stockout_date", fmt_date(m["projected_stockout_date"])),
        ("detail.fact.last_consumption", fmt_date(m["last_consumption_date"])),
        ("detail.fact.dq_score", fmt_pct(m["dq_score"])),
    ]
    components.spec_sheet(t("detail.facts.title"), [(t(key), value) for key, value in facts])
    master = [
        ("col.description", m["description"]),
        ("detail.master.price", fmt_eur(m["unit_price_eur"])),
        ("detail.master.lead_time", t("detail.days", days=fmt_number(m["lead_time_days"]))),
        ("detail.master.min_stock", qty(m["min_stock"]) if pd.notna(m["min_stock"]) else "–"),
        ("detail.master.max_stock", qty(m["max_stock"]) if pd.notna(m["max_stock"]) else "–"),
        ("detail.master.safety_calc", qty(m["safety_stock_calc"])),
        ("detail.master.deviation", fmt_pct(m["min_stock_deviation_pct"] / 100)),
    ]
    components.spec_sheet(t("detail.master.title"), [(t(key), value) for key, value in master])
    if m["demand_anomaly"] or m["receipt_anomaly"]:
        st.warning(t("detail.anomaly"), icon=":material/troubleshoot:")


def _storage_locations(history: MaterialHistory) -> None:
    st.toggle(t("detail.sloc.toggle"), key=state.DETAIL_SLOC)
    if not st.session_state[state.DETAIL_SLOC]:
        return
    by_sloc = history.by_sloc
    unit = history.metrics["unit"]
    fig = go.Figure()
    for sloc, part in by_sloc.groupby("storage_location"):
        fig.add_scatter(
            x=part["date"],
            y=part["stock_qty"],
            mode="lines",
            line_shape="hv",
            name=t("detail.sloc.name", sloc=sloc),
            hovertemplate=_hover(t("detail.sloc.name", sloc=sloc), unit),
        )
    fig.update_xaxes(tickformat=plotly_date_format())
    fig.update_yaxes(tickformat=",.0f")
    components.style_figure(
        fig, t("detail.sloc.title"), t("detail.chart.x"), t("detail.chart.y_stock", unit=unit)
    )
    components.show_figure(fig, key="detail_sloc_chart")
