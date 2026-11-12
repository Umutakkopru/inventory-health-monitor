"""Tests for the Excel export (CLAUDE.md section 10, test_report.py)."""

import datetime as dt
import io

import numpy as np
import openpyxl
import pandas as pd
import pytest

from inventory_monitor.config import DEFAULT_THRESHOLDS
from inventory_monitor.models import AnalysisResult, Status
from inventory_monitor.report import (
    COLUMN_LABELS,
    EXPORT_TEXT,
    LANGUAGES,
    STATUS_LABELS,
    THRESHOLD_LABELS,
    build_alert_workbook,
)

AS_OF = pd.Timestamp("2026-10-31")


def _row(material_id: str, status: Status, **changes) -> dict:
    return {
        "material_id": material_id,
        "plant": "1010",
        "description": "Kugellager 6204",
        "status": status.value,
        "abc": "A",
        "xyz": "X",
        "stock": 50.0,
        "unit": "ST",
        "safety_stock": 10.0,
        "reorder_point": 30.0,
        "max_target": 100.0,
        "coverage_days": 25.0,
        "projected_below_safety_date": pd.NaT,
        "projected_stockout_date": pd.NaT,
        "value_at_risk": 0.0,
        "stock_value": 100.0,
        "demand_anomaly": False,
        "receipt_anomaly": False,
        "priority_score": 0.0,
    } | changes


@pytest.fixture
def result() -> AnalysisResult:
    metrics = pd.DataFrame(
        [
            _row("00000001", Status.OK),
            _row("00000002", Status.DEAD_STOCK, coverage_days=np.inf, value_at_risk=100.0),
            _row(
                "00000003",
                Status.SHORTAGE_CRITICAL,
                stock=5.0,
                projected_stockout_date=pd.Timestamp("2026-11-03"),
                demand_anomaly=True,
            ),
        ]
    )
    return AnalysisResult(
        metrics=metrics, issues=pd.DataFrame(), as_of=AS_OF, thresholds=DEFAULT_THRESHOLDS
    )


def _open(data: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(data))


def _rows(sheet) -> list[tuple]:
    return list(sheet.iter_rows(values_only=True))


@pytest.mark.parametrize(
    ("lang", "sheets", "first_headers"),
    [
        ("de", ["Warnungen", "Parameter"], ("Material", "Werk", "Materialkurztext", "Status")),
        ("en", ["Alerts", "Parameters"], ("Material", "Plant", "Description", "Status")),
    ],
)
def test_sheets_and_translated_headers(result, lang, sheets, first_headers) -> None:
    book = _open(build_alert_workbook(result, lang))
    assert book.sheetnames == sheets
    headers = _rows(book[sheets[0]])[0]
    assert headers[:4] == first_headers
    assert headers == tuple(COLUMN_LABELS[lang].values())
    assert book[sheets[0]].freeze_panes == "A2"


@pytest.mark.parametrize(
    ("lang", "critical", "yes", "no"),
    [("de", "Engpass (kritisch)", "Ja", "Nein"), ("en", "Shortage (critical)", "Yes", "No")],
)
def test_values_are_translated_and_most_urgent_first(result, lang, critical, yes, no) -> None:
    book = _open(build_alert_workbook(result, lang))
    rows = _rows(book.worksheets[0])[1:]
    # Order: critical shortage, dead stock, OK
    assert [r[0] for r in rows] == ["00000003", "00000002", "00000001"]
    assert rows[0][3] == critical
    assert rows[0][16] == yes and rows[1][16] == no  # demand anomaly


def test_unlimited_coverage_and_dates(result) -> None:
    book = _open(build_alert_workbook(result, "de"))
    sheet = book.worksheets[0]
    rows = _rows(sheet)[1:]
    assert rows[1][11] == "> 365"  # dead stock: no demand, coverage unlimited
    assert rows[0][13] == dt.datetime(2026, 11, 3)  # a real Excel date
    assert sheet.cell(row=2, column=14).number_format == "DD.MM.YYYY"
    assert rows[2][13] is None  # no projected stock-out: empty cell


def test_english_dates_use_iso_format(result) -> None:
    sheet = _open(build_alert_workbook(result, "en")).worksheets[0]
    assert sheet.cell(row=2, column=14).number_format == "YYYY-MM-DD"


def test_rows_parameter_exports_only_the_given_rows(result) -> None:
    subset = result.metrics[result.metrics["status"] == Status.OK.value]
    rows = _rows(_open(build_alert_workbook(result, "en", rows=subset)).worksheets[0])
    assert [r[0] for r in rows[1:]] == ["00000001"]


def test_empty_selection_still_has_headers(result) -> None:
    empty = result.metrics.iloc[0:0]
    rows = _rows(_open(build_alert_workbook(result, "de", rows=empty)).worksheets[0])
    assert rows == [tuple(COLUMN_LABELS["de"].values())]


def test_parameter_sheet_lists_as_of_and_every_threshold(result) -> None:
    rows = _rows(_open(build_alert_workbook(result, "de")).worksheets[1])
    assert rows[0] == ("Parameter", "Wert")
    assert rows[1] == ("Stichtag", dt.datetime(2026, 10, 31))
    assert rows[2] == ("Datenbasis", "Synthetische Beispieldaten")
    assert ("Bedarfsfenster (Tage)", 90) in rows
    assert len(rows) == 1 + 2 + 17  # header, as-of, data note, 17 thresholds


def test_unknown_language_is_rejected(result) -> None:
    with pytest.raises(ValueError, match="Unknown language"):
        build_alert_workbook(result, "fr")


def test_label_tables_cover_both_languages_completely() -> None:
    for table in (STATUS_LABELS, COLUMN_LABELS, THRESHOLD_LABELS, EXPORT_TEXT):
        assert set(table) == set(LANGUAGES)
        assert set(table["de"]) == set(table["en"])
        assert all(table[lang][key] for lang in LANGUAGES for key in table[lang])
    assert set(STATUS_LABELS["de"]) == set(Status)
    assert set(THRESHOLD_LABELS["de"]) == set(DEFAULT_THRESHOLDS.__dataclass_fields__)


def test_status_labels_match_the_glossary() -> None:
    # CLAUDE.md section 13, UI status labels
    assert STATUS_LABELS["de"][Status.SHORTAGE_WARNING] == "Meldebestand unterschritten"
    assert STATUS_LABELS["de"][Status.DEAD_STOCK] == "Ladenhüter"
    assert STATUS_LABELS["en"][Status.SHORTAGE_WARNING] == "Below reorder point"
    assert STATUS_LABELS["en"][Status.INSUFFICIENT_DATA] == "Insufficient data"
