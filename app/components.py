"""Shared UI building blocks: status labels and badges, KPI cards, chart layout, guards."""

import functools
import html
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from app import state
from app.i18n import plotly_separators, status_label, t
from app.theme import (
    CHART_FONT,
    CHART_GRID,
    CHART_TITLE_FONT,
    SHELL_YELLOW,
    SIGNAL_BLACK,
    STATUS_BADGE_COLORS,
    STATUS_ICONS,
    STATUS_SYMBOLS,
)

CHART_HEIGHT = 360
CHART_MARGIN = {"l": 10, "r": 10, "t": 50, "b": 10}
STYLESHEET = Path(__file__).with_name("styles.css")


def status_text(code: str) -> str:
    """Symbol plus translated label, for table cells and chart labels."""
    return f"{STATUS_SYMBOLS[code]} {status_label(code)}"


def status_badge(code: str) -> None:
    """Colour, icon and text together: status is never shown by colour alone."""
    st.badge(status_label(code), icon=STATUS_ICONS[code], color=STATUS_BADGE_COLORS[code])


def kpi(
    label: str, value: str, proof: str, *, help_text: str = "", status: str | None = None
) -> None:
    """A rack label: black title strip, one large figure and the reason it means what it says.

    `status` adds that status's symbol to the strip and its form to the card (critical
    hatched, warning dashed; see styles.css), so the card never depends on colour alone.
    The full explanation stays available as the native tooltip.
    """
    modifier = f" rack-label--{status.lower()}" if status else ""
    symbol = html.escape(STATUS_SYMBOLS[status]) if status else ""
    st.html(
        f'<div class="rack-label{modifier}" title="{html.escape(help_text)}">'
        f'<div class="rack-label__title"><span>{html.escape(label)}</span>'
        f'<span class="rack-label__symbol" aria-hidden="true">{symbol}</span></div>'
        '<div class="rack-label__band"></div>'
        f'<div class="rack-label__value">{html.escape(value)}</div>'
        f'<div class="rack-label__proof">{html.escape(proof)}</div>'
        "</div>"
    )


def tags(labels: list[str]) -> None:
    """A row of location tags (plants) under a page title."""
    spans = "".join(f'<span class="loc-tag">{html.escape(label)}</span>' for label in labels)
    st.html(f'<div class="loc-tags">{spans}</div>')


def code_tag_style(_: object) -> str:
    """Cell style for material numbers: the yellow code tag of a rack label."""
    return f"background-color: {SHELL_YELLOW}; color: {SIGNAL_BLACK}"


def style_figure(
    fig: go.Figure, title: str, x_title: str, y_title: str, height: int = CHART_HEIGHT
) -> go.Figure:
    """Title, axis titles with units, language-specific separators and the world's type.

    Text colours are left to Streamlit's chart theme so they follow light and dark; only the
    faces, sizes and the translucent rules are set here.
    """
    fig.update_layout(
        title={"text": title, "font": {"family": CHART_TITLE_FONT, "size": 16}},
        xaxis_title=x_title,
        yaxis_title=y_title,
        separators=plotly_separators(),
        height=height,
        margin=CHART_MARGIN,
        font={"family": CHART_FONT, "size": 13},
        legend={"orientation": "h", "yanchor": "top", "y": -0.25, "title": {"text": ""}},
        hoverlabel={"namelength": -1, "font": {"family": CHART_FONT}},
    )
    fig.update_xaxes(gridcolor=CHART_GRID, zerolinecolor=CHART_GRID)
    fig.update_yaxes(gridcolor=CHART_GRID, zerolinecolor=CHART_GRID)
    return fig


def inject_styles() -> None:
    """Load the few rules Streamlit's theme config cannot express (app/styles.css)."""
    st.html(f"<style>{_stylesheet()}</style>")


@functools.cache
def _stylesheet() -> str:
    return STYLESHEET.read_text(encoding="utf-8")


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
