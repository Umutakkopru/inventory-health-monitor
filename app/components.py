"""Shared UI building blocks: status labels and badges, KPI cards, chart layout, guards."""

import plotly.graph_objects as go
import streamlit as st

from app import state
from app.i18n import plotly_separators, status_label, t
from app.theme import STATUS_BADGE_COLORS, STATUS_ICONS, STATUS_SYMBOLS

CHART_HEIGHT = 360
NBSP = "&nbsp;"  # markdown entity; a raw U+00A0 is collapsed by the renderer
CHART_MARGIN = {"l": 10, "r": 10, "t": 50, "b": 10}


def status_text(code: str) -> str:
    """Symbol plus translated label, for table cells and chart labels."""
    return f"{STATUS_SYMBOLS[code]} {status_label(code)}"


def status_badge(code: str) -> None:
    """Colour, icon and text together: status is never shown by colour alone."""
    st.badge(status_label(code), icon=STATUS_ICONS[code], color=STATUS_BADGE_COLORS[code])


def kpi(label: str, value: str, *, help_text: str | None = None) -> None:
    """A bordered card whose label wraps instead of being cut off (st.metric truncates)."""
    with st.container(border=True):
        st.caption(label, help=help_text)
        # Non-breaking spaces keep "8,2 Mio. €" on one line in a narrow card.
        st.markdown(f"#### {value.replace(' ', NBSP)}")


def style_figure(
    fig: go.Figure, title: str, x_title: str, y_title: str, height: int = CHART_HEIGHT
) -> go.Figure:
    """Title, axis titles with units, language-specific number separators."""
    fig.update_layout(
        title={"text": title},
        xaxis_title=x_title,
        yaxis_title=y_title,
        separators=plotly_separators(),
        height=height,
        margin=CHART_MARGIN,
        legend={"orientation": "h", "yanchor": "top", "y": -0.25, "title": {"text": ""}},
        hoverlabel={"namelength": -1},
    )
    return fig


def show_figure(fig: go.Figure, key: str) -> None:
    st.plotly_chart(fig, key=key, config={"displaylogo": False})


def require_plants() -> bool:
    """Show a hint and return False when no plant is selected in the sidebar."""
    if state.selected_plants():
        return True
    st.info(t("common.no_plant"), icon=":material/info:")
    return False


def empty_state() -> None:
    st.info(t("common.empty"), icon=":material/filter_alt_off:")
