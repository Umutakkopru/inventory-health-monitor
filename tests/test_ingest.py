"""Tests for reading the workbook (CLAUDE.md section 4)."""

import io

import pandas as pd
import pytest

from inventory_monitor.config import SAMPLE_WORKBOOK
from inventory_monitor.ingest import load_workbook
from inventory_monitor.models import WorkbookFormatError


def _sheets() -> dict[str, pd.DataFrame]:
    """A minimal valid workbook with German headers, as the users would export it."""
    return {
        "Bestand": pd.DataFrame(
            {
                "Datum": [pd.Timestamp("2026-01-05 13:45"), pd.Timestamp("2026-01-06")],
                "Material": ["00012345", "  12345 "],
                "Werk": ["1010", "1010"],
                "Lagerort": ["0001", "0001"],
                "Bestand": [10.0, 8.0],
                "Mengeneinheit": ["ST", "ST"],
            }
        ),
        "Wareneingang": pd.DataFrame(
            {
                "Buchungsdatum": pd.to_datetime(["2026-01-06"]),
                "Material": ["00012345"],
                "Werk": ["1010"],
                "Lagerort": ["0001"],
                "Menge": [5.0],
                "Lieferant": ["Lieferant 01"],
                "Bestellnummer": ["0450000001"],
            }
        ),
        "Materialstamm": pd.DataFrame(
            {
                "Material": ["00012345"],
                "Werk": ["1010"],
                "Materialkurztext": ["Kugellager 6204"],
                "Preis": [2.5],
                "Wiederbeschaffungszeit": [7],
                "Mindestbestand": [None],
                "Maximalbestand": [None],
                "Mengeneinheit": ["ST"],
            }
        ),
    }


def _workbook(sheets: dict[str, pd.DataFrame]) -> io.BytesIO:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    buffer.seek(0)
    return buffer


@pytest.fixture(scope="module")
def sample():
    return load_workbook(SAMPLE_WORKBOOK)


def test_sample_workbook_has_canonical_columns(sample) -> None:
    assert list(sample.stock.columns) == [
        "date",
        "material_id",
        "plant",
        "storage_location",
        "stock_qty",
        "unit",
        "material_id_repaired",
    ]
    assert sample.stock["date"].dtype == "datetime64[ns]"
    assert sample.stock["stock_qty"].dtype == "float64"


def test_leading_zeros_survive(sample) -> None:
    assert sample.materials["material_id"].str.fullmatch(r"\d{8}").all()
    assert sample.materials["material_id"].str.startswith("00").any()
    assert sample.receipts["po_number"].str.fullmatch(r"\d{10}").all()
    assert sample.stock["plant"].isin(["1010", "1020"]).all()


def test_lost_zeros_in_sample_are_repaired_and_flagged(sample) -> None:
    # The generator wrote 6 stock rows and 4 receipts without their leading zeros.
    assert sample.stock["material_id_repaired"].sum() == 6
    assert sample.receipts["material_id_repaired"].sum() == 4
    assert sample.materials["material_id_repaired"].sum() == 0
    assert sample.stock["material_id"].str.len().eq(8).all()


def test_file_like_object_gives_the_same_result(sample) -> None:
    from_bytes = load_workbook(io.BytesIO(SAMPLE_WORKBOOK.read_bytes()))
    pd.testing.assert_frame_equal(from_bytes.stock, sample.stock)
    pd.testing.assert_frame_equal(from_bytes.materials, sample.materials)


def test_padding_and_whitespace_both_count_as_repairs() -> None:
    raw = load_workbook(_workbook(_sheets()))
    assert raw.stock["material_id"].tolist() == ["00012345", "00012345"]
    assert raw.stock["material_id_repaired"].tolist() == [False, True]


def test_dates_are_normalised_to_midnight() -> None:
    raw = load_workbook(_workbook(_sheets()))
    assert raw.stock["date"].tolist() == [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")]


def test_empty_min_and_max_stock_are_allowed() -> None:
    raw = load_workbook(_workbook(_sheets()))
    assert raw.materials["min_stock"].isna().all()
    assert raw.materials["max_stock"].isna().all()


def test_text_dates_in_german_format_are_parsed() -> None:
    sheets = _sheets()
    sheets["Bestand"] = sheets["Bestand"].assign(Datum=["05.01.2026", "06.01.2026"])
    raw = load_workbook(_workbook(sheets))
    assert raw.stock["date"].tolist() == [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")]


def test_missing_sheet_names_sheet_and_found_sheets() -> None:
    sheets = _sheets()
    del sheets["Wareneingang"]
    with pytest.raises(WorkbookFormatError) as error:
        load_workbook(_workbook(sheets))
    message = str(error.value)
    assert "'Wareneingang'" in message
    assert "'Bestand'" in message and "'Materialstamm'" in message


def test_missing_column_names_sheet_column_and_found_columns() -> None:
    sheets = _sheets()
    sheets["Materialstamm"] = sheets["Materialstamm"].drop(columns="Preis")
    with pytest.raises(WorkbookFormatError) as error:
        load_workbook(_workbook(sheets))
    message = str(error.value)
    assert "'Materialstamm'" in message
    assert "'Preis'" in message
    assert "'Wiederbeschaffungszeit'" in message  # listed among the columns found


def test_headers_with_surrounding_spaces_are_accepted() -> None:
    sheets = _sheets()
    sheets["Bestand"] = sheets["Bestand"].rename(columns={"Bestand": " Bestand "})
    assert load_workbook(_workbook(sheets)).stock["stock_qty"].tolist() == [10.0, 8.0]


def test_text_in_a_number_column_is_a_format_error() -> None:
    sheets = _sheets()
    sheets["Bestand"] = sheets["Bestand"].assign(Bestand=[10.0, "viel"])
    with pytest.raises(WorkbookFormatError, match=r"'Bestand'.*numbers.*'viel'"):
        load_workbook(_workbook(sheets))


def test_text_in_a_date_column_is_a_format_error() -> None:
    sheets = _sheets()
    sheets["Bestand"] = sheets["Bestand"].assign(Datum=["05.01.2026", "gestern"])
    with pytest.raises(WorkbookFormatError, match=r"'Datum'.*dates"):
        load_workbook(_workbook(sheets))


def test_a_file_that_is_not_excel_is_a_format_error() -> None:
    with pytest.raises(WorkbookFormatError, match="not a readable Excel workbook"):
        load_workbook(io.BytesIO(b"Datum;Material\n01.01.2026;123\n"))
