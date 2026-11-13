"""Entry point: page configuration, shared sidebar and navigation.

Pages are registered with `st.navigation` from each view's `render` function, so their
titles can be translated (the legacy `pages/` folder takes titles from file names).
"""

import dataclasses

import streamlit as st

from app import state
from app.i18n import date_format, t
from app.views import abc_xyz, alerts, data_quality, material_detail, methodology, overview
from inventory_monitor.config import Thresholds


def _sidebar() -> None:
    data = state.prepared()
    with st.sidebar:
        st.segmented_control(
            t("sidebar.language"),
            options=list(state.LANGUAGES),
            format_func=lambda code: t(f"lang.{code}"),
            key=state.LANG,
            required=True,
        )
        st.multiselect(
            t("sidebar.plants"),
            options=sorted(data.clean.materials["plant"].unique()),
            key=state.PLANTS,
            select_all=False,
        )
        st.date_input(
            t("sidebar.as_of"),
            min_value=data.first_date.date(),
            max_value=data.last_date.date(),
            format=date_format(),
            key=state.AS_OF,
            help=t("sidebar.as_of_help"),
        )
        with st.expander(t("sidebar.thresholds"), icon=":material/tune:"):
            for field in dataclasses.fields(Thresholds):
                low, high, step = state.THRESHOLD_SLIDERS[field.name]
                is_int = field.type is int
                st.slider(
                    t(f"threshold.{field.name}"),
                    min_value=int(low) if is_int else float(low),
                    max_value=int(high) if is_int else float(high),
                    step=int(step) if is_int else float(step),
                    key=state.threshold_key(field.name),
                )
            st.button(
                t("sidebar.reset"),
                on_click=state.reset_thresholds,
                icon=":material/restart_alt:",
                key="threshold_reset",
            )
        st.caption(t("sidebar.synthetic_note"))


def main() -> None:
    st.set_page_config(page_title=t("app.title"), page_icon=":material/inventory:", layout="wide")
    state.init()
    _sidebar()
    pages = [
        st.Page(
            overview.render,
            title=t("nav.overview"),
            icon=":material/dashboard:",
            url_path="overview",
            default=True,
        ),
        st.Page(
            alerts.render, title=t("nav.alerts"), icon=":material/notifications:", url_path="alerts"
        ),
        st.Page(
            material_detail.render,
            title=t("nav.material_detail"),
            icon=":material/insights:",
            url_path="material",
        ),
        st.Page(
            abc_xyz.render, title=t("nav.abc_xyz"), icon=":material/grid_view:", url_path="abc-xyz"
        ),
        st.Page(
            data_quality.render,
            title=t("nav.data_quality"),
            icon=":material/rule:",
            url_path="data-quality",
        ),
        st.Page(
            methodology.render,
            title=t("nav.methodology"),
            icon=":material/menu_book:",
            url_path="methodology",
        ),
    ]
    state.register_pages(pages)
    st.navigation(pages).run()


main()
