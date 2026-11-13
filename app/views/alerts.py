"""Alerts: the filterable, sortable table of every material with its key figures.

Values are formatted for the current language through a pandas Styler; the table still
sorts by the underlying numbers. Selecting a row offers a jump to Material Detail, and the
download button exports exactly the filtered rows.
"""

import pandas as pd
import streamlit as st

from app import components, state
from app.i18n import fmt_coverage, fmt_date, fmt_eur, fmt_number, t
from inventory_monitor import pipeline, report
from inventory_monitor.models import URGENCY_ORDER

TABLE_HEIGHT = 520
QTY_COLUMNS = ("stock", "safety_stock", "reorder_point", "max_target")
DATE_COLUMNS = ("projected_below_safety_date", "projected_stockout_date")
FLAG_COLUMNS = ("demand_anomaly", "receipt_anomaly")


def render() -> None:
    """Render the page."""
    analysis = state.result()
    st.title(t("alerts.title"))
    st.caption(t("alerts.caption"))
    if not components.require_plants():
        return
    metrics = state.plant_metrics(analysis)
    rows = _filtered(metrics)
    _filters_caption(len(rows), len(metrics))
    if rows.empty:
        components.empty_state()
        return
    ordered = pipeline.sort_by_urgency(rows).reset_index(drop=True)
    _table(ordered)
    _actions(analysis, ordered)


def _filtered(metrics: pd.DataFrame) -> pd.DataFrame:
    """Apply the filters above the table; an empty multiselect means "all"."""
    status_col, abc_col, xyz_col, search_col = st.columns([3, 1.2, 1.2, 2.6])
    with status_col:
        st.multiselect(
            t("alerts.filter.status"),
            options=[s.value for s in URGENCY_ORDER],
            format_func=components.status_text,
            placeholder=t("alerts.filter.all"),
            key=state.ALERT_STATUS,
        )
    with abc_col:
        st.multiselect(
            t("col.abc"), ["A", "B", "C"], placeholder=t("alerts.filter.all"), key=state.ALERT_ABC
        )
    with xyz_col:
        st.multiselect(
            t("col.xyz"), ["X", "Y", "Z"], placeholder=t("alerts.filter.all"), key=state.ALERT_XYZ
        )
    with search_col:
        st.text_input(
            t("alerts.filter.search"),
            placeholder=t("alerts.filter.search_hint"),
            key=state.ALERT_SEARCH,
        )
    keep = pd.Series(True, index=metrics.index)
    for key, column in (
        (state.ALERT_STATUS, "status"),
        (state.ALERT_ABC, "abc"),
        (state.ALERT_XYZ, "xyz"),
    ):
        chosen = st.session_state[key]
        if chosen:
            keep &= metrics[column].isin(chosen)
    search = st.session_state[state.ALERT_SEARCH].strip().lower()
    if search:
        text = (metrics["material_id"] + " " + metrics["description"]).str.lower()
        keep &= text.str.contains(search, regex=False)
    return metrics[keep]


def _filters_caption(shown: int, total: int) -> None:
    st.caption(t("alerts.count", shown=fmt_number(shown), total=fmt_number(total)))


def _table(rows: pd.DataFrame) -> None:
    names = list(report.COLUMN_LABELS["en"])  # canonical names in export order
    columns = ["status", *(c for c in names if c != "status")]  # status first on screen
    view = rows[columns].assign(status=rows["status"].map(components.status_text))
    formats = (
        {c: fmt_number for c in QTY_COLUMNS}
        | {c: fmt_date for c in DATE_COLUMNS}
        | {"coverage_days": fmt_coverage, "value_at_risk": fmt_eur, "stock_value": fmt_eur}
    )
    styled = view.style.format(formats, na_rep="–")
    config = {c: st.column_config.Column(t(f"col.{c}")) for c in columns}
    config |= {c: st.column_config.CheckboxColumn(t(f"col.{c}")) for c in FLAG_COLUMNS}
    config |= {"plant": st.column_config.Column(t("col.plant"), width=55)}
    config |= {c: st.column_config.Column(t(f"col.{c}"), width=45) for c in ("abc", "xyz")}
    st.dataframe(
        styled,
        hide_index=True,
        height=TABLE_HEIGHT,
        column_config=config,
        on_select="rerun",
        selection_mode="single-row",
        key=state.ALERT_TABLE,
    )


def _actions(analysis, rows: pd.DataFrame) -> None:
    left, right = st.columns([3, 1])
    selection = st.session_state.get(state.ALERT_TABLE)
    selected = selection.selection.rows if selection else []
    with left:
        if selected:
            row = rows.iloc[selected[0]]
            label = t("alerts.open_detail", material=f"{row['material_id']} · {row['description']}")
            if st.button(label, icon=":material/insights:", key="alerts_open_detail"):
                st.session_state[state.MATERIAL] = state.material_key(
                    row["material_id"], row["plant"]
                )
                st.switch_page(state.page("material"))
        else:
            st.caption(t("alerts.select_hint"))
    with right:
        lang = state.lang()
        st.download_button(
            t("alerts.download"),
            data=report.build_alert_workbook(analysis, lang, rows=rows),
            file_name=t("alerts.download_file", date=analysis.as_of.strftime("%Y-%m-%d")),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key="alerts_download",
            on_click="ignore",
        )
