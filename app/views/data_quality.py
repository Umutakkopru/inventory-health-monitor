"""Data Quality: what the checks found, what was done about it, and a score per material."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import components, state
from app.i18n import fmt_date, fmt_number, fmt_pct, t
from app.theme import SEVERITY_COLORS, SEVERITY_SYMBOLS
from inventory_monitor import pipeline

SCORE_ROWS = 15
LABEL_ROOM = 1.35


def render() -> None:
    """Render the page."""
    analysis = state.result()
    st.title(t("dq.title"))
    st.caption(t("dq.caption"))
    if not components.require_plants():
        return
    issues = analysis.issues[analysis.issues["plant"].isin(state.selected_plants())]
    _counts(issues)
    _issue_table(issues)
    _scores(state.plant_metrics(analysis))


def _check_label(check_id: str) -> str:
    return f"{check_id} · {t(f'dq.check.{check_id}')}"


def _severity_label(severity: str) -> str:
    return f"{SEVERITY_SYMBOLS[severity]} {t(f'dq.severity.{severity}')}"


def _counts(issues: pd.DataFrame) -> None:
    counts = pipeline.issue_counts(issues)
    fig = go.Figure(
        go.Bar(
            x=counts["count"],
            y=[_check_label(c) for c in counts["check_id"]],
            orientation="h",
            marker_color=counts["severity"].map(SEVERITY_COLORS),
            text=[
                f"{fmt_number(n)} · {_severity_label(s)}"
                for n, s in zip(counts["count"], counts["severity"], strict=True)
            ],
            textposition="outside",
            cliponaxis=False,
            hovertemplate=t("dq.counts.hover") + "<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    # Room on the right for the count and severity label next to the longest bar.
    fig.update_xaxes(range=[0, max(counts["count"].max(), 1) * LABEL_ROOM])
    components.style_figure(fig, t("dq.counts.title"), t("dq.counts.x"), "", height=440)
    components.show_figure(fig, key="dq_counts")


def _issue_table(issues: pd.DataFrame) -> None:
    st.subheader(t("dq.table.title"))
    check_col, search_col = st.columns([3, 2])
    with check_col:
        st.multiselect(
            t("dq.table.checks"),
            options=list(pipeline.issue_counts(issues)["check_id"]),
            format_func=_check_label,
            placeholder=t("alerts.filter.all"),
            key=state.DQ_CHECKS,
            select_all=False,
        )
    with search_col:
        st.text_input(
            t("alerts.filter.search"), placeholder=t("dq.table.search_hint"), key=state.DQ_SEARCH
        )
    rows = issues
    if st.session_state[state.DQ_CHECKS]:
        rows = rows[rows["check_id"].isin(st.session_state[state.DQ_CHECKS])]
    search = st.session_state[state.DQ_SEARCH].strip()
    if search:
        rows = rows[rows["material_id"].str.contains(search, regex=False, na=False)]
    st.caption(t("dq.table.count", shown=fmt_number(len(rows)), total=fmt_number(len(issues))))
    if rows.empty:
        components.empty_state()
        return
    table = pd.DataFrame(
        {
            t("dq.table.check"): rows["check_id"].map(_check_label),
            t("dq.table.severity"): rows["severity"].map(_severity_label),
            t("dq.table.sheet"): rows["sheet"],
            t("col.material_id"): rows["material_id"],
            t("col.plant"): rows["plant"],
            t("dq.table.date"): rows["date"].map(fmt_date),
            t("dq.table.detail"): rows["detail"],
            t("dq.table.action"): rows["action_taken"].map(lambda a: t(f"dq.action.{a}")),
        }
    )
    st.dataframe(table, hide_index=True, height=380, key="dq_issue_table")


def _scores(metrics: pd.DataFrame) -> None:
    st.subheader(t("dq.score.title"))
    st.caption(t("dq.score.caption"))
    if metrics.empty:
        components.empty_state()
        return
    lowest = metrics.sort_values(["dq_score", "material_id"]).head(SCORE_ROWS)
    table = pd.DataFrame(
        {
            t("col.material_id"): lowest["material_id"],
            t("col.description"): lowest["description"],
            t("col.plant"): lowest["plant"],
            t("dq.score.score"): lowest["dq_score"].map(lambda v: fmt_pct(v, 1)),
        }
    )
    st.dataframe(table, hide_index=True, key="dq_score_table")
