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
    STATUS_ICONS,
    STATUS_SYMBOLS,
)

CHART_HEIGHT = 360
CHART_MARGIN = {"l": 10, "r": 10, "t": 50, "b": 10}
STYLESHEET = Path(__file__).with_name("styles.css")


def status_text(code: str) -> str:
    """Symbol plus translated label, for table cells and chart labels."""
    return f"{STATUS_SYMBOLS[code]} {status_label(code)}"


def status_icon(code: str) -> str:
    """The status's Material Symbol as an inline glyph for HTML built here.

    Streamlit already loads the Material Symbols font for its own icons; the ligature name
    renders as the drawn icon. Hidden from screen readers, since the label says the same.
    """
    name = STATUS_ICONS[code].removeprefix(":material/").removesuffix(":")
    return f'<span class="status-icon" aria-hidden="true" translate="no">{name}</span>'


def kpi(
    label: str, value: str, proof: str, *, help_text: str = "", status: str | None = None
) -> None:
    """A rack label: black title strip, one large figure and the reason it means what it says.

    `status` adds that status's icon to the strip and its form to the card (critical
    hatched, warning dashed; see styles.css), so the card never depends on colour alone.
    The full explanation stays available as the native tooltip.
    """
    modifier = f" rack-label--{status.lower()}" if status else ""
    icon = status_icon(status) if status else ""
    st.html(
        f'<div class="rack-label{modifier}" title="{html.escape(help_text)}">'
        f'<div class="rack-label__title"><span>{html.escape(label)}</span>{icon}</div>'
        '<div class="marking-band"></div>'
        f'<div class="rack-label__value">{html.escape(value)}</div>'
        f'<div class="rack-label__proof">{html.escape(proof)}</div>'
        "</div>"
    )


def tags(labels: list[str]) -> None:
    """A row of location tags (plants) under a page title."""
    spans = "".join(f'<span class="loc-tag">{html.escape(label)}</span>' for label in labels)
    st.html(f'<div class="loc-tags">{spans}</div>')


def spec_sheet(title: str, rows: list[tuple[str, str]], *, status: str | None = None) -> None:
    """Label and value pairs under a black title strip, values right-aligned in one column.

    With `status`, the strip carries the status icon and label and the sheet takes that
    status's form (critical hatched band, warning dashed outline), as the KPI cards do.
    """
    modifier = f" spec-sheet--{status.lower()}" if status else ""
    state_line = (
        f'<span class="spec-sheet__status">{status_icon(status)}'
        f"{html.escape(status_label(status))}</span>"
        if status
        else ""
    )
    items = "".join(
        f'<div class="spec-sheet__row"><dt>{html.escape(label)}</dt>'
        f"<dd>{html.escape(value)}</dd></div>"
        for label, value in rows
    )
    st.html(
        f'<section class="spec-sheet{modifier}"><div class="spec-sheet__title">'
        f"<span>{html.escape(title)}</span>{state_line}</div>"
        f'<div class="marking-band"></div><dl>{items}</dl></section>'
    )


def code_tag_style(value: object) -> str:
    """Cell style for material numbers: the yellow code tag of a rack label.

    Cells without a material number (some data-quality issues concern a whole sheet) stay
    plain, so an empty yellow tag never suggests a code that is not there.
    """
    if not isinstance(value, str) or not value:
        return ""
    return f"background-color: {SHELL_YELLOW}; color: {SIGNAL_BLACK}"


def style_figure(
    fig: go.Figure, title: str, x_title: str, y_title: str, height: int = CHART_HEIGHT
) -> go.Figure:
    """Title, axis titles with units, language-specific separators and the world's type.

    Text colours are left to Streamlit's chart theme so they follow light and dark; only the
    faces, sizes and the translucent rules are set here.
    """
    fig.update_layout(
        title={"text": title},
        xaxis_title=x_title,
        yaxis_title=y_title,
        separators=plotly_separators(),
        height=height,
        margin=CHART_MARGIN,
        legend={"orientation": "h", "yanchor": "top", "y": -0.25, "title": {"text": ""}},
    )
    return apply_type(fig)


def apply_type(fig: go.Figure) -> go.Figure:
    """The world's faces, sizes and translucent rules, for figures built with subplots too."""
    # Chart titles speak in the same uppercase label voice as the section headings.
    fig.update_layout(
        title_text=(fig.layout.title.text or "").upper(),
        title_font={"family": CHART_TITLE_FONT, "size": 16},
        font={"family": CHART_FONT, "size": 13},
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
