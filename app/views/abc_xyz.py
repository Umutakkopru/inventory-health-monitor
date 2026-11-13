"""ABC/XYZ: how value and regularity are spread, and which master data looks outdated."""

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app import components, state
from app.i18n import fmt_eur, fmt_eur_compact, fmt_number, fmt_pct, t
from app.theme import ABC_COLORS, MATRIX_SCALE, MATRIX_TEXT, NEUTRAL_LINE
from inventory_monitor import pipeline
from inventory_monitor.config import ABC_CLASSES, XYZ_CLASSES

PLANT_CHOICE = "abc_xyz_plant"
SHARE_TICKS = [0, 0.2, 0.4, 0.6, 0.8, 1.0]


def render() -> None:
    """Render the page."""
    analysis = state.result()
    st.title(t("abc.title"))
    st.caption(t("abc.caption"))
    if not components.require_plants():
        return
    metrics = state.plant_metrics(analysis)
    left, right = st.columns(2)
    with left:
        _matrix(metrics)
    with right:
        _pareto(metrics, analysis.thresholds)
    _deviations(metrics)


def _matrix(metrics) -> None:
    cells = pipeline.abc_xyz_matrix(metrics)
    counts = cells.pivot(index="abc", columns="xyz", values="count").loc[ABC_CLASSES, XYZ_CLASSES]
    values = cells.pivot(index="abc", columns="xyz", values="stock_value").loc[
        ABC_CLASSES, XYZ_CLASSES
    ]
    text = [
        [
            t(
                "abc.matrix.cell",
                count=fmt_number(counts.loc[a, x]),
                value=fmt_eur_compact(values.loc[a, x]),
            )
            for x in XYZ_CLASSES
        ]
        for a in ABC_CLASSES
    ]
    fig = go.Figure(
        go.Heatmap(
            z=counts.to_numpy(),
            x=[t(f"abc.xyz.{x}") for x in XYZ_CLASSES],
            y=[t(f"abc.abc.{a}") for a in ABC_CLASSES],
            text=text,
            texttemplate="%{text}",
            colorscale=MATRIX_SCALE,
            textfont={"color": MATRIX_TEXT},
            showscale=False,
            xgap=4,  # gaps between cells read as the aisles between rack bays
            ygap=4,
            hovertemplate=t("abc.matrix.hover") + "<extra></extra>",
            customdata=[[fmt_eur(values.loc[a, x]) for x in XYZ_CLASSES] for a in ABC_CLASSES],
        )
    )
    fig.update_yaxes(autorange="reversed")
    components.style_figure(fig, t("abc.matrix.title"), t("abc.matrix.x"), t("abc.matrix.y"))
    components.show_figure(fig, key="abc_matrix")


def _pareto(metrics, thresholds) -> None:
    plants = state.selected_plants()
    if st.session_state.get(PLANT_CHOICE) not in plants:
        st.session_state[PLANT_CHOICE] = plants[0]
    st.segmented_control(t("abc.pareto.plant"), plants, key=PLANT_CHOICE, required=True)
    rows = pipeline.pareto(metrics, st.session_state[PLANT_CHOICE])
    if rows.empty:
        components.empty_state()
        return
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    labels = rows["material_id"]
    fig.add_bar(
        x=labels,
        y=rows["annual_consumption_value"],
        marker_color=rows["abc"].map(ABC_COLORS),
        name=t("abc.pareto.value"),
        customdata=rows[["description", "abc"]].to_numpy(),
        hovertemplate=t("abc.pareto.hover") + "<extra></extra>",
    )
    fig.add_scatter(
        x=labels,
        y=rows["cumulative_share"],
        mode="lines",
        name=t("abc.pareto.share"),
        line={"color": NEUTRAL_LINE, "width": 2},
        hovertemplate=t("abc.pareto.share_hover") + "<extra></extra>",
        secondary_y=True,
    )
    for cutoff in (thresholds.abc_cutoff_a, thresholds.abc_cutoff_b):
        fig.add_hline(y=cutoff, line_dash="dot", line_color=NEUTRAL_LINE, secondary_y=True)
    # Material numbers look numeric; a category axis keeps the Pareto order.
    fig.update_xaxes(type="category", showticklabels=False)
    fig.update_yaxes(title_text=t("abc.pareto.y"), tickformat=",.0f", secondary_y=False)
    fig.update_yaxes(
        title_text=t("abc.pareto.y2"),
        tickformat=".0%",
        tickvals=SHARE_TICKS,
        range=[0, 1.02],
        showgrid=False,
        secondary_y=True,
    )
    components.style_figure(fig, t("abc.pareto.title"), t("abc.pareto.x"), t("abc.pareto.y"))
    components.show_figure(fig, key="abc_pareto")
    st.caption(t("abc.pareto.caption"))


def _deviations(metrics) -> None:
    st.subheader(t("abc.dev.title"))
    st.caption(t("abc.dev.caption"))
    rows = pipeline.master_data_deviations(metrics)
    if rows.empty:
        components.empty_state()
        return
    table = rows.assign(
        status=rows["status"].map(components.status_text),
        min_stock=rows["min_stock"].map(fmt_number),
        safety_stock_calc=rows["safety_stock_calc"].map(fmt_number),
        deviation=(rows["min_stock_deviation_pct"] / 100).map(lambda v: fmt_pct(v)),
    )
    columns = {
        "material_id": t("col.material_id"),
        "description": t("col.description"),
        "plant": t("col.plant"),
        "abc": t("col.abc"),
        "xyz": t("col.xyz"),
        "status": t("col.status"),
        "min_stock": t("abc.dev.master"),
        "safety_stock_calc": t("abc.dev.calc"),
        "deviation": t("abc.dev.deviation"),
    }
    shown = table[list(columns)].rename(columns=columns)
    styled = shown.style.map(components.code_tag_style, subset=[t("col.material_id")])
    st.dataframe(styled, hide_index=True, key="abc_deviation_table")
