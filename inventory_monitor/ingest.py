"""Read the Excel workbook into canonical DataFrames.

This is the only module that raises for bad input, and only for structural problems: an
unreadable file, a missing sheet or column, or a column whose values have the wrong type.
Problems in individual rows are left to `quality.run_checks`.
"""

import zipfile
from pathlib import Path
from typing import BinaryIO

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from inventory_monitor.config import (
    MATERIAL_ID_LENGTH,
    SHEET_COLUMNS,
    SHEET_MATERIALS,
    SHEET_RECEIPTS,
    SHEET_STOCK,
    STRING_HEADERS,
)
from inventory_monitor.models import RawData, WorkbookFormatError

DATE_COLUMNS = ("date",)
NUMERIC_COLUMNS = (
    "stock_qty",
    "receipt_qty",
    "unit_price_eur",
    "lead_time_days",
    "min_stock",
    "max_stock",
)
TEXT_COLUMNS = (
    "material_id",
    "plant",
    "storage_location",
    "unit",
    "supplier",
    "po_number",
    "description",
)
REPAIRED_FLAG = "material_id_repaired"
EXAMPLE_VALUES = 3  # bad values quoted in an error message


def load_workbook(source: str | Path | BinaryIO) -> RawData:
    """Read the three sheets from a path or a binary file-like object.

    Identifier columns are read as text so that leading zeros survive. Material numbers
    are stripped and left-padded to eight digits; each frame gets a boolean column
    `material_id_repaired` so the quality layer can report the repairs (check DQ07).

    Raises WorkbookFormatError when the file is not an Excel workbook, a sheet or a
    required column is missing, or a date or number column holds values of another type.
    """
    sheets = _read_sheets(source)
    frames = {name: _canonical(name, sheets, columns) for name, columns in SHEET_COLUMNS.items()}
    return RawData(
        stock=frames[SHEET_STOCK],
        receipts=frames[SHEET_RECEIPTS],
        materials=frames[SHEET_MATERIALS],
    )


def _read_sheets(source: str | Path | BinaryIO) -> dict[str, pd.DataFrame]:
    try:
        return pd.read_excel(
            source,
            sheet_name=None,
            dtype={header: str for header in STRING_HEADERS},
            engine="openpyxl",
        )
    except (ValueError, zipfile.BadZipFile, InvalidFileException) as error:
        raise WorkbookFormatError(f"The file is not a readable Excel workbook: {error}") from error


def _canonical(name: str, sheets: dict[str, pd.DataFrame], columns: dict[str, str]) -> pd.DataFrame:
    """Check one sheet's structure, rename its headers and convert the column types."""
    if name not in sheets:
        raise WorkbookFormatError(
            f"Sheet '{name}' is missing. Sheets found: {', '.join(map(repr, sheets)) or 'none'}."
        )
    frame = sheets[name].rename(columns=lambda header: str(header).strip())
    missing = [header for header in columns if header not in frame.columns]
    if missing:
        raise WorkbookFormatError(
            f"Sheet '{name}' is missing column(s) {', '.join(map(repr, missing))}. "
            f"Columns found: {', '.join(map(repr, frame.columns))}."
        )
    frame = frame[list(columns)].rename(columns=columns)
    converted = {}
    for column in frame.columns:
        header = next(h for h, c in columns.items() if c == column)
        converted[column] = _convert(frame[column], column, name, header)
    return _repair_material_id(pd.DataFrame(converted), raw_material=frame["material_id"])


def _convert(values: pd.Series, column: str, sheet: str, header: str) -> pd.Series:
    """Convert one column to its canonical type; empty cells stay missing."""
    if column in DATE_COLUMNS:
        try:
            if not pd.api.types.is_datetime64_any_dtype(values):
                values = pd.to_datetime(values, format="mixed", dayfirst=True)
        except (ValueError, TypeError) as error:
            raise _type_error(sheet, header, "dates", values) from error
        return values.dt.normalize().astype("datetime64[ns]")
    if column in NUMERIC_COLUMNS:
        numbers = pd.to_numeric(values, errors="coerce")
        if (numbers.isna() & values.notna()).any():
            raise _type_error(sheet, header, "numbers", values[numbers.isna() & values.notna()])
        return numbers.astype(float)
    return values.astype("string").str.strip().astype(object).where(values.notna())


def _type_error(sheet: str, header: str, kind: str, values: pd.Series) -> WorkbookFormatError:
    examples = ", ".join(repr(v) for v in values.dropna().astype(str).unique()[:EXAMPLE_VALUES])
    return WorkbookFormatError(
        f"Sheet '{sheet}', column '{header}' must contain {kind}. Examples found: {examples}."
    )


def _repair_material_id(frame: pd.DataFrame, raw_material: pd.Series) -> pd.DataFrame:
    """Left-pad material numbers to eight digits and flag every row whose raw value changed.

    The flag compares with the value as read, so stripped whitespace counts as a repair too.
    """
    stripped = frame["material_id"]
    padded = stripped.str.zfill(MATERIAL_ID_LENGTH).where(stripped.notna())
    changed = (padded != raw_material.astype(object)) & raw_material.notna()
    return frame.assign(material_id=padded, **{REPAIRED_FLAG: changed})
