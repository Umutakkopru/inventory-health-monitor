"""Data-quality checks DQ01 to DQ11 and the cleaned frames the rest of the pipeline uses.

`run_checks` never raises for bad rows. Each check repairs, drops or flags rows and records
one issue per finding. Codes (check IDs, severities, actions) are stored untranslated; the
dashboard translates them for display. DQ08 needs the derived consumption from the SQL step,
so it lives in `pipeline.py`; its definition is listed here so all checks share one table.

The checks run in a fixed order because later checks rely on earlier repairs: material
numbers are repaired (DQ07) before any join on them, and duplicates are removed (DQ03)
before missing days (DQ01) and negative stock (DQ02) are counted.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from inventory_monitor.config import SHEET_MATERIALS, SHEET_RECEIPTS, SHEET_STOCK
from inventory_monitor.ingest import REPAIRED_FLAG
from inventory_monitor.models import CleanData, RawData

KEY = ["material_id", "plant"]
SNAPSHOT_KEY = ["date", "material_id", "plant", "storage_location"]
ISSUE_COLUMNS = [
    "check_id",
    "severity",
    "sheet",
    "material_id",
    "plant",
    "date",
    "detail",
    "action_taken",
]


@dataclass(frozen=True)
class Check:
    """Severity, the sheet the finding refers to, and what the pipeline does about it."""

    severity: str
    sheet: str
    action: str


CHECKS: dict[str, Check] = {
    "DQ01": Check("warning", SHEET_STOCK, "gap_imputed"),
    "DQ02": Check("error", SHEET_STOCK, "treated_as_missing"),
    "DQ03": Check("warning", SHEET_STOCK, "kept_last"),
    "DQ04": Check("error", SHEET_RECEIPTS, "receipt_dropped"),
    "DQ05": Check("error", SHEET_STOCK, "rows_dropped"),
    "DQ06": Check("error", SHEET_RECEIPTS, "receipt_dropped"),
    "DQ07": Check("info", SHEET_STOCK, "repaired"),  # sheet set per finding
    "DQ08": Check("warning", SHEET_STOCK, "clipped_to_zero"),
    "DQ09": Check("warning", SHEET_STOCK, "master_unit_kept"),
    "DQ10": Check("error", SHEET_MATERIALS, "material_excluded"),
    "DQ11": Check("info", SHEET_RECEIPTS, "ignored"),
}


def make_issues(check_id: str, findings: pd.DataFrame, sheet: str | None = None) -> pd.DataFrame:
    """Turn findings into rows of the issues table.

    `findings` needs `material_id` and `plant`; `date` and `detail` are optional and
    default to empty. `sheet` overrides the check's default sheet (used by DQ07).
    """
    check = CHECKS[check_id]
    n = len(findings)
    date = findings["date"] if "date" in findings else pd.Series(pd.NaT, index=findings.index)
    detail = findings["detail"] if "detail" in findings else pd.Series("", index=findings.index)
    out = pd.DataFrame(
        {
            "check_id": [check_id] * n,
            "severity": [check.severity] * n,
            "sheet": [sheet or check.sheet] * n,
            "material_id": findings["material_id"].to_numpy(),
            "plant": findings["plant"].to_numpy(),
            "date": pd.to_datetime(date).to_numpy(),
            "detail": detail.astype(str).to_numpy(),
            "action_taken": [check.action] * n,
        }
    )
    types = {c: object for c in ISSUE_COLUMNS} | {"date": "datetime64[ns]"}
    return out.astype(types)[ISSUE_COLUMNS]


def empty_issues() -> pd.DataFrame:
    """An issues table without rows but with the right columns and types."""
    return make_issues("DQ01", pd.DataFrame(columns=[*KEY, "date", "detail"]))


def run_checks(raw: RawData) -> tuple[CleanData, pd.DataFrame]:
    """Run DQ01 to DQ11 (except DQ08) and return the cleaned frames and the issues table.

    The cleaned stock still has gaps; the SQL step decides how a gap day is treated.
    Materials excluded by DQ10 are removed from all three frames.
    """
    found: list[pd.DataFrame] = []
    stock, receipts, materials = raw.stock, raw.receipts, raw.materials

    found.append(_dq07_repaired(stock, receipts, materials))
    stock, receipts, materials = (
        f.drop(columns=REPAIRED_FLAG) for f in (stock, receipts, materials)
    )

    known = materials[KEY].drop_duplicates()
    materials, issues = _dq10_invalid_master(materials)
    found.append(issues)
    excluded = known.merge(materials[KEY], how="left", indicator=True)
    excluded = excluded.loc[excluded["_merge"] == "left_only", KEY]

    stock, issues = _dq05_unknown_stock(stock, known)
    found.append(issues)
    receipts, issues = _dq04_unknown_receipts(receipts, known)
    found.append(issues)
    stock, receipts = _drop_keys(stock, excluded), _drop_keys(receipts, excluded)

    receipts, issues = _dq06_bad_receipt_qty(receipts)
    found.append(issues)
    stock, issues = _dq09_units(stock, materials)
    found.append(issues)
    stock, issues = _dq03_duplicates(stock)
    found.append(issues)
    # Empty quantity cells are missing snapshots; DQ01 reports their days below.
    stock = stock[stock["date"].notna() & stock["stock_qty"].notna()]
    found.append(_dq01_missing_days(stock))
    stock, issues = _dq02_negative_stock(stock)
    found.append(issues)
    receipts, issues = _dq11_receipts_outside_range(receipts, stock)
    found.append(issues)

    issues = pd.concat([f for f in found if len(f)] or [empty_issues()], ignore_index=True)
    issues = issues.sort_values(["check_id", "material_id", "plant", "date"], ignore_index=True)
    clean = CleanData(
        stock=stock.sort_values(SNAPSHOT_KEY, ignore_index=True),
        receipts=receipts.sort_values(["date", *KEY], ignore_index=True),
        materials=materials.sort_values(KEY, ignore_index=True),
    )
    return clean, issues


def _numbers(values: pd.Series) -> pd.Series:
    """Quantities as short text for the detail column, e.g. 5.0 -> "5", -2.5 -> "-2.5"."""
    return pd.Series([f"{v:g}" for v in values], index=values.index, dtype=object)


def _join(left: pd.Series, separator: str, right: pd.Series) -> pd.Series:
    """Element-wise text join that also works on empty frames of any dtype."""
    text = [f"{a}{separator}{b}" for a, b in zip(left, right, strict=True)]
    return pd.Series(text, index=left.index, dtype=object)


def _drop_keys(frame: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """Rows of `frame` whose material-plant is not in `keys`."""
    merged = frame.merge(keys, on=KEY, how="left", indicator=True)
    return frame[(merged["_merge"] == "left_only").to_numpy()]


def _not_in(frame: pd.DataFrame, keys: pd.DataFrame) -> np.ndarray:
    """Boolean mask: the row's material-plant does not appear in `keys`."""
    merged = frame[KEY].merge(keys, on=KEY, how="left", indicator=True)
    return (merged["_merge"] == "left_only").to_numpy()


def _dq07_repaired(
    stock: pd.DataFrame, receipts: pd.DataFrame, materials: pd.DataFrame
) -> pd.DataFrame:
    """DQ07: material numbers that ingest had to pad or strip, one issue per row."""
    parts = []
    for sheet, frame in ((SHEET_STOCK, stock), (SHEET_RECEIPTS, receipts)):
        parts.append(make_issues("DQ07", frame[frame[REPAIRED_FLAG]], sheet))
    master = materials[materials[REPAIRED_FLAG]]
    parts.append(make_issues("DQ07", master, SHEET_MATERIALS))
    return pd.concat(parts, ignore_index=True)


def _dq10_invalid_master(materials: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ10: a missing or non-positive price or lead time excludes the material."""
    bad_price = ~(materials["unit_price_eur"] > 0)  # also true for NaN
    bad_lead = ~(materials["lead_time_days"] > 0)
    bad = bad_price | bad_lead
    detail = np.where(
        bad_price & bad_lead,
        "unit_price_eur,lead_time_days",
        np.where(bad_price, "unit_price_eur", "lead_time_days"),
    )
    findings = materials[bad].assign(date=pd.NaT, detail=detail[bad.to_numpy()])
    valid = materials[~bad]
    valid = valid.assign(lead_time_days=valid["lead_time_days"].round().astype(int))
    return valid, make_issues("DQ10", findings)


def _dq05_unknown_stock(
    stock: pd.DataFrame, known: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ05: stock of a material-plant missing from the master; one issue per material-plant."""
    unknown = _not_in(stock, known)
    findings = (
        stock[unknown]
        .groupby(KEY, dropna=False)
        .agg(date=("date", "min"), rows=("date", "size"))
        .reset_index()
    )
    findings = findings.assign(detail=findings["rows"].astype(str))
    return stock[~unknown], make_issues("DQ05", findings)


def _dq04_unknown_receipts(
    receipts: pd.DataFrame, known: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ04: receipts for a material-plant missing from the master are dropped."""
    unknown = _not_in(receipts, known)
    findings = receipts[unknown].assign(detail=_numbers(receipts.loc[unknown, "receipt_qty"]))
    return receipts[~unknown], make_issues("DQ04", findings)


def _dq06_bad_receipt_qty(receipts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ06: receipts with a missing, zero or negative quantity are dropped."""
    bad = ~(receipts["receipt_qty"] > 0)
    findings = receipts[bad].assign(detail=_numbers(receipts.loc[bad, "receipt_qty"]))
    return receipts[~bad], make_issues("DQ06", findings)


def _dq09_units(stock: pd.DataFrame, materials: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ09: stock rows in another unit than the master; the master unit is kept."""
    master_unit = (
        stock[KEY]
        .merge(
            materials[[*KEY, "unit"]].rename(columns={"unit": "master_unit"}), on=KEY, how="left"
        )["master_unit"]
        .to_numpy()
    )
    differs = (stock["unit"].to_numpy() != master_unit) & pd.notna(master_unit)
    rows = stock[differs].assign(master_unit=master_unit[differs])
    findings = (
        rows.groupby(KEY)
        .agg(
            date=("date", "min"),
            units=("unit", lambda u: "/".join(sorted(u.dropna().unique()))),
            master=("master_unit", "first"),
        )
        .reset_index()
    )
    findings = findings.assign(detail=_join(findings["units"], " -> ", findings["master"]))
    return stock.assign(unit=master_unit), make_issues("DQ09", findings)


def _dq03_duplicates(stock: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ03: several rows for one snapshot key; the last row in file order is kept.

    The detail lists the quantities in file order, so an exact duplicate shows the same
    number twice and a conflicting one shows which value was kept (the last).
    """
    duplicated = stock.duplicated(SNAPSHOT_KEY, keep=False)
    findings = (
        stock[duplicated]
        .groupby(SNAPSHOT_KEY)["stock_qty"]
        .agg(lambda q: " | ".join(f"{v:g}" for v in q))
        .rename("detail")
        .reset_index()
    )
    return stock.drop_duplicates(SNAPSHOT_KEY, keep="last"), make_issues("DQ03", findings)


def _dq01_missing_days(stock: pd.DataFrame) -> pd.DataFrame:
    """DQ01: material-plant days inside the range on which a storage location has no row.

    A storage location's range runs from its first to its last snapshot. One issue per
    material-plant and day; the detail is empty when every location is missing and lists
    the missing locations otherwise (a partial snapshot, also a missing day per 6.2).
    """
    sloc_key = [*KEY, "storage_location"]
    ranges = stock.groupby(sloc_key)["date"].agg(["min", "max"]).reset_index()
    days = (ranges["max"] - ranges["min"]).dt.days + 1
    expanded = ranges.loc[ranges.index.repeat(days)]
    offset = pd.to_timedelta(expanded.groupby(level=0).cumcount(), unit="D")
    expected = expanded.assign(date=expanded["min"] + offset)[[*sloc_key, "date"]]

    present = stock[[*sloc_key, "date"]].drop_duplicates()
    merged = expected.merge(present, how="left", indicator=True)
    missing = merged[merged["_merge"] == "left_only"].sort_values("storage_location")
    day_key = [*KEY, "date"]
    covering = expected.groupby(day_key).size().rename("covering")
    per_day = (
        missing.groupby(day_key)["storage_location"]
        .agg(lambda s: ",".join(s))
        .rename("slocs")
        .to_frame()
        .join(missing.groupby(day_key).size().rename("missing"))
        .join(covering)
        .reset_index()
    )
    detail = np.where(per_day["missing"] == per_day["covering"], "", per_day["slocs"])
    return make_issues("DQ01", per_day.assign(detail=detail))


def _dq02_negative_stock(stock: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ02: a negative stock row is removed, so its day becomes a missing snapshot."""
    negative = stock["stock_qty"] < 0
    rows = stock[negative]
    findings = rows.assign(
        detail=_join(rows["storage_location"], ": ", _numbers(rows["stock_qty"]))
    )
    return stock[~negative], make_issues("DQ02", findings)


def _dq11_receipts_outside_range(
    receipts: pd.DataFrame, stock: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DQ11: receipts dated before the first or after the last snapshot are ignored."""
    ranges = stock.groupby(KEY)["date"].agg(first="min", last="max").reset_index()
    bounds = receipts[KEY].merge(ranges, on=KEY, how="left")
    date = receipts["date"].to_numpy()
    inside = (date >= bounds["first"].to_numpy()) & (date <= bounds["last"].to_numpy())
    outside = ~inside  # also true when the material-plant has no snapshot at all
    findings = receipts[outside].assign(detail=_numbers(receipts.loc[outside, "receipt_qty"]))
    return receipts[inside], make_issues("DQ11", findings)
