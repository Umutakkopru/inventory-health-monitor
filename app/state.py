"""Session-state keys, defaults and the cached pipeline calls.

Every `st.session_state` key is a constant here and every widget uses one of them, so
filters and the selected material survive page changes and language switches.
"""

import dataclasses
import datetime as dt

import pandas as pd
import streamlit as st

from inventory_monitor import pipeline
from inventory_monitor.config import DEFAULT_THRESHOLDS, SAMPLE_WORKBOOK, Thresholds
from inventory_monitor.models import AnalysisResult, PreparedData

LANG = "lang"
PLANTS = "plants"
AS_OF = "as_of"
MATERIAL = "material"  # "material_id|plant" of the material shown on Material Detail
ALERT_STATUS = "alert_status"
ALERT_ABC = "alert_abc"
ALERT_XYZ = "alert_xyz"
ALERT_SEARCH = "alert_search"
ALERT_TABLE = "alert_table"
DETAIL_SLOC = "detail_sloc"
DQ_CHECKS = "dq_checks"
DQ_SEARCH = "dq_search"
THRESHOLD_PREFIX = "threshold_"
PAGES = "_pages"  # url_path -> st.Page of this run, for st.switch_page

DEFAULT_LANG = "de"
LANGUAGES = ("de", "en")

# Widgets whose values must survive a page change. Streamlit drops the state of a widget
# that is not rendered in a run; writing the value back to itself on every run keeps it.
PERSISTENT_KEYS = (
    LANG,
    PLANTS,
    AS_OF,
    MATERIAL,
    ALERT_STATUS,
    ALERT_ABC,
    ALERT_XYZ,
    ALERT_SEARCH,
    DETAIL_SLOC,
    DQ_CHECKS,
    DQ_SEARCH,
)

# Slider range and step per threshold. Ranges of paired cutoffs do not overlap, so the
# A cutoff is always below the B cutoff and X below Y.
THRESHOLD_SLIDERS: dict[str, tuple[float, float, float]] = {
    "demand_window_days": (30, 180, 10),
    "variability_window_weeks": (8, 52, 1),
    "min_history_days": (14, 120, 7),
    "service_level_a": (0.80, 0.995, 0.005),
    "service_level_b": (0.80, 0.995, 0.005),
    "service_level_c": (0.80, 0.995, 0.005),
    "abc_cutoff_a": (0.50, 0.90, 0.05),
    "abc_cutoff_b": (0.91, 0.99, 0.01),
    "xyz_cutoff_x": (0.20, 0.90, 0.05),
    "xyz_cutoff_y": (1.00, 2.00, 0.10),
    "overstock_days_a": (30, 180, 10),
    "overstock_days_b": (30, 240, 10),
    "overstock_days_c": (60, 365, 15),
    "dead_stock_days": (30, 365, 10),
    "anomaly_iqr_factor": (1.5, 5.0, 0.5),
    "ewma_alpha": (0.10, 0.90, 0.05),
    "projection_horizon_days": (14, 120, 7),
}


def threshold_key(field: str) -> str:
    return f"{THRESHOLD_PREFIX}{field}"


@st.cache_data(show_spinner=False)
def _prepare(source: str) -> PreparedData:
    return pipeline.prepare(source)


@st.cache_data(show_spinner=False, max_entries=64)
def _analyse(
    _prepared: PreparedData, source: str, as_of: dt.date, thresholds: Thresholds
) -> AnalysisResult:
    # `_prepared` is not hashed (leading underscore); `source` identifies it instead.
    return pipeline.analyse(_prepared, pd.Timestamp(as_of), thresholds)


def prepared() -> PreparedData:
    """The prepared sample data, computed once and shared by all sessions."""
    return _prepare(str(SAMPLE_WORKBOOK))


def result() -> AnalysisResult:
    """The analysis for the current as-of date and thresholds (cached per combination)."""
    return _analyse(prepared(), str(SAMPLE_WORKBOOK), st.session_state[AS_OF], thresholds())


def init() -> None:
    """Set defaults on the first run and keep widget values across page changes."""
    data = prepared()
    defaults = {
        LANG: DEFAULT_LANG,
        PLANTS: sorted(data.clean.materials["plant"].unique()),
        AS_OF: data.last_date.date(),
        ALERT_STATUS: [],
        ALERT_ABC: [],
        ALERT_XYZ: [],
        ALERT_SEARCH: "",
        DQ_CHECKS: [],
        DQ_SEARCH: "",
        DETAIL_SLOC: False,
    } | {threshold_key(f): v for f, v in dataclasses.asdict(DEFAULT_THRESHOLDS).items()}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    for key in (*PERSISTENT_KEYS, *map(threshold_key, THRESHOLD_SLIDERS)):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def lang() -> str:
    return st.session_state.get(LANG, DEFAULT_LANG)


def thresholds() -> Thresholds:
    """Thresholds from the sliders, with integer fields kept as integers."""
    values = {}
    for field in dataclasses.fields(Thresholds):
        value = st.session_state.get(
            threshold_key(field.name), getattr(DEFAULT_THRESHOLDS, field.name)
        )
        values[field.name] = int(round(value)) if field.type is int else float(value)
    return Thresholds(**values)


def reset_thresholds() -> None:
    """Button callback: put every threshold slider back to its default."""
    for field, value in dataclasses.asdict(DEFAULT_THRESHOLDS).items():
        st.session_state[threshold_key(field)] = value


def selected_plants() -> list[str]:
    return list(st.session_state.get(PLANTS, []))


def plant_metrics(analysis: AnalysisResult) -> pd.DataFrame:
    """The metrics of the plants chosen in the sidebar."""
    m = analysis.metrics
    return m[m["plant"].isin(selected_plants())]


def material_key(material_id: str, plant: str) -> str:
    return f"{material_id}|{plant}"


def split_material_key(key: str) -> tuple[str, str]:
    material_id, plant = key.split("|")
    return material_id, plant


def register_pages(pages: list[st.Page]) -> None:
    """Remember this run's page objects so views can switch to another page."""
    st.session_state[PAGES] = {page.url_path: page for page in pages}


def page(url_path: str) -> st.Page:
    return st.session_state[PAGES][url_path]
