"""The dashboard starts, and every page renders in German and English and when empty.

AppTest cannot switch to pages registered with st.navigation from functions, so each view's
render() is also run on its own through AppTest.from_function (CLAUDE.md section 10).
Translations run in strict mode (tests/conftest.py), so a missing key fails the page.
"""

import pytest
from streamlit.testing.v1 import AppTest

from inventory_monitor.config import REPO_ROOT

TIMEOUT = 60
VIEWS = ("overview", "alerts", "material_detail", "abc_xyz", "data_quality", "methodology")
TITLES = {
    "overview": (
        "Engpässe und Überbestände auf einen Blick",
        "Shortages and overstock at a glance",
    ),
    "alerts": ("Warnungen", "Alerts"),
    "material_detail": ("Materialdetail", "Material detail"),
    "abc_xyz": ("ABC/XYZ-Analyse", "ABC/XYZ analysis"),
    "data_quality": ("Datenqualität", "Data quality"),
    "methodology": ("Methodik", "Methodology"),
}


def _page(view: str) -> None:
    """Runs one view the way streamlit_app.py does, without the navigation."""
    import importlib

    from app import state

    state.init()
    importlib.import_module(f"app.views.{view}").render()


def _run(view: str, **session: object) -> AppTest:
    at = AppTest.from_function(_page, args=(view,), default_timeout=TIMEOUT)
    for key, value in session.items():
        at.session_state[key] = value
    return at.run()


# --- The real entry point ------------------------------------------------------------------


def test_app_starts_on_the_overview() -> None:
    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=TIMEOUT).run()
    assert not at.exception
    assert at.title[0].value == TITLES["overview"][0]
    assert len(at.sidebar.slider) == 17


def test_language_switch_keeps_the_sidebar_filters() -> None:
    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=TIMEOUT).run()
    at.sidebar.multiselect(key="plants").set_value(["1020"]).run()
    at.sidebar.segmented_control(key="lang").set_value("en").run()
    assert at.title[0].value == TITLES["overview"][1]
    assert at.sidebar.multiselect(key="plants").value == ["1020"]


def test_threshold_reset_restores_defaults() -> None:
    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=TIMEOUT).run()
    at.sidebar.slider(key="threshold_dead_stock_days").set_value(180).run()
    at.sidebar.button(key="threshold_reset").click().run()
    assert at.sidebar.slider(key="threshold_dead_stock_days").value == 90
    assert not at.exception


# --- Every page, both languages ------------------------------------------------------------


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("view", VIEWS)
def test_every_page_renders(view: str, lang: str) -> None:
    at = _run(view, lang=lang)
    assert not at.exception
    assert at.title[0].value == TITLES[view][0 if lang == "de" else 1]


@pytest.mark.parametrize("view", VIEWS[:-1])  # Methodology does not depend on the plants
def test_no_plant_selected_shows_a_hint(view: str) -> None:
    at = _run(view, plants=[])
    assert not at.exception
    assert [i.value for i in at.info] == ["Bitte mindestens ein Werk auswählen."]


@pytest.mark.parametrize(
    ("view", "key"), [("alerts", "alert_search"), ("data_quality", "dq_search")]
)
def test_filter_without_result_shows_the_empty_state(view: str, key: str) -> None:
    at = _run(view, lang="en", **{key: "no such material"})
    assert not at.exception
    assert "There is no data for the current selection." in [i.value for i in at.info]


def test_alert_filters_survive_a_language_switch() -> None:
    at = _run("alerts", alert_status=["SHORTAGE_CRITICAL"], alert_abc=["A"])
    count_de = at.caption[1].value
    at.session_state["lang"] = "en"
    at.run()
    assert at.multiselect(key="alert_status").value == ["SHORTAGE_CRITICAL"]
    assert at.multiselect(key="alert_abc").value == ["A"]
    # Same rows, other language: "4 von 90 Materialien" -> "4 of 90 materials"
    assert count_de.split()[0] == at.caption[1].value.split()[0]


def test_earlier_as_of_date_renders() -> None:
    import datetime as dt

    at = _run("overview", as_of=dt.date(2026, 5, 1))
    assert not at.exception
    assert "01.05.2026" in at.caption[0].value
