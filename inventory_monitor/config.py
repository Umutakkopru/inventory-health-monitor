"""Project-wide constants: paths, workbook layout, column mappings and analysis thresholds.

The German-to-canonical column mapping lives here and nowhere else. Every threshold used by
the analytics is a field of `Thresholds`; no threshold appears as a literal elsewhere.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

# --- Paths -----------------------------------------------------------------------------------

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DATA_DIR: Final[Path] = REPO_ROOT / "data"
SAMPLE_WORKBOOK: Final[Path] = DATA_DIR / "sample_inventory.xlsx"
SCENARIO_MANIFEST: Final[Path] = DATA_DIR / "scenario_manifest.json"
SQL_DIR: Final[Path] = Path(__file__).resolve().parent / "sql"

# --- Workbook layout (German headers, as an SAP export would deliver them) -------------------

SHEET_STOCK: Final[str] = "Bestand"
SHEET_RECEIPTS: Final[str] = "Wareneingang"
SHEET_MATERIALS: Final[str] = "Materialstamm"

# Excel header -> canonical column name. Dict order is the column order in the workbook.
STOCK_COLUMNS: Final[dict[str, str]] = {
    "Datum": "date",
    "Material": "material_id",
    "Werk": "plant",
    "Lagerort": "storage_location",
    "Bestand": "stock_qty",
    "Mengeneinheit": "unit",
}

RECEIPT_COLUMNS: Final[dict[str, str]] = {
    "Buchungsdatum": "date",
    "Material": "material_id",
    "Werk": "plant",
    "Lagerort": "storage_location",
    "Menge": "receipt_qty",
    "Lieferant": "supplier",
    "Bestellnummer": "po_number",
}

MATERIAL_COLUMNS: Final[dict[str, str]] = {
    "Material": "material_id",
    "Werk": "plant",
    "Materialkurztext": "description",
    "Preis": "unit_price_eur",
    "Wiederbeschaffungszeit": "lead_time_days",
    "Mindestbestand": "min_stock",
    "Maximalbestand": "max_stock",
    "Mengeneinheit": "unit",
}

SHEET_COLUMNS: Final[dict[str, dict[str, str]]] = {
    SHEET_STOCK: STOCK_COLUMNS,
    SHEET_RECEIPTS: RECEIPT_COLUMNS,
    SHEET_MATERIALS: MATERIAL_COLUMNS,
}

# Identifier columns are read as text so that leading zeros survive (00012345 != 12345).
STRING_HEADERS: Final[tuple[str, ...]] = ("Material", "Werk", "Lagerort", "Bestellnummer")

MATERIAL_ID_LENGTH: Final[int] = 8
UNITS: Final[tuple[str, ...]] = ("ST", "KG", "M", "L")

# --- Classification labels -------------------------------------------------------------------

ABC_CLASSES: Final[tuple[str, ...]] = ("A", "B", "C")
XYZ_CLASSES: Final[tuple[str, ...]] = ("X", "Y", "Z")

# --- Fixed analysis constants (part of the method, not tunable in the dashboard) -------------

DAYS_PER_WEEK: Final[int] = 7
MIN_COMPLETE_WEEKS: Final[int] = 4  # fewer complete weeks: sigma_weekly is not estimated
ANNUAL_WINDOW_DAYS: Final[int] = 365  # window of the annual consumption value (ABC)
RECEIPT_ANOMALY_WINDOW_DAYS: Final[int] = 30  # receipts this recent are checked for anomalies
MIN_RECEIPT_HISTORY: Final[int] = 5  # earlier receipts needed before a receipt can be unusual
# Master-data safety stock deviating this much from the calculated value is listed for review.
MASTER_DEVIATION_ALERT: Final[float] = 0.5


# --- Thresholds ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """Tunable parameters of the analysis, with the defaults from the Methodology page.

    Frozen and built from plain scalars so that it is hashable and can serve as a
    `st.cache_data` key. Per-class values are separate fields for the same reason; use
    `service_level()` and `overstock_days()` to look them up by ABC class.
    """

    demand_window_days: int = 90
    variability_window_weeks: int = 26
    min_history_days: int = 56
    service_level_a: float = 0.98
    service_level_b: float = 0.95
    service_level_c: float = 0.90
    abc_cutoff_a: float = 0.80
    abc_cutoff_b: float = 0.95
    xyz_cutoff_x: float = 0.5
    xyz_cutoff_y: float = 1.0
    overstock_days_a: int = 60
    overstock_days_b: int = 90
    overstock_days_c: int = 180
    dead_stock_days: int = 90
    anomaly_iqr_factor: float = 3.0
    ewma_alpha: float = 0.3
    projection_horizon_days: int = 60

    def service_level(self, abc_class: str) -> float:
        """Target cycle service level for an ABC class ('A', 'B' or 'C')."""
        return {
            "A": self.service_level_a,
            "B": self.service_level_b,
            "C": self.service_level_c,
        }[abc_class]

    def overstock_days(self, abc_class: str) -> int:
        """Days of coverage above which stock counts as overstock, for an ABC class."""
        return {
            "A": self.overstock_days_a,
            "B": self.overstock_days_b,
            "C": self.overstock_days_c,
        }[abc_class]


DEFAULT_THRESHOLDS: Final[Thresholds] = Thresholds()
