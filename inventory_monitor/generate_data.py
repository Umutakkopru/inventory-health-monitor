"""Deterministic synthetic SAP-like inventory workbook with embedded scenarios and defects.

Run with ``python -m inventory_monitor.generate_data``. The same seed and date range always
produce the same data; the current date is never used.

The generator works in stages: build a plan per material and plant (master data and the
reorder-point policy), simulate stock day by day, apply the scenarios, then inject data
defects into the output frames only.
"""

import json
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from inventory_monitor.classify import assign_abc
from inventory_monitor.config import (
    DEFAULT_THRESHOLDS,
    MATERIAL_COLUMNS,
    MATERIAL_ID_LENGTH,
    RECEIPT_COLUMNS,
    SAMPLE_WORKBOOK,
    SCENARIO_MANIFEST,
    SHEET_MATERIALS,
    SHEET_RECEIPTS,
    SHEET_STOCK,
    STOCK_COLUMNS,
    Thresholds,
)
from inventory_monitor.models import Status

# --- Generator parameters --------------------------------------------------------------------
# These describe the synthetic world, not the analysis, so they are not part of Thresholds.

SEED = 42
START_DATE = pd.Timestamp("2025-11-01")
END_DATE = pd.Timestamp("2026-10-31")
PLANTS = ("1010", "1020")
N_SHARED_MATERIALS = 30  # stocked in both plants; the remaining materials in one plant only

PRICE_RANGE_EUR = (0.50, 2500.0)  # log-uniform, so ABC classes separate clearly
WEEKDAY_DEMAND_RANGE = (2.0, 200.0)  # mean units per weekday, log-uniform
PROFILE_SHARES = {"steady": 0.5, "variable": 0.3, "intermittent": 0.2}
SECOND_SLOC_SHARE = 0.3
MAIN_SLOC_SHARE_RANGE = (0.55, 0.80)
MIN_STOCK_SHARE = 0.7
MAX_STOCK_SHARE = 0.5
MAX_STOCK_FACTOR = 1.2  # max_stock = (reorder point + order quantity) * factor

# Demand model per profile (see _weekly_sigma for the resulting weekly variability).
STEADY_DAILY_CV = 0.15
VARIABLE_WEEK_SIGMA_LN = 0.6  # lognormal weekly level factor with mean 1
VARIABLE_DAILY_CV = 0.5
INTERMITTENT_PROBABILITY = 0.08  # chance of a demand event on a weekday
INTERMITTENT_SIZE_CV = 0.5

# Lead-time pools by estimated ABC class. Expensive A parts get short lead times so that one
# order (four to six lead times of demand) stays below the A overstock threshold.
LEAD_TIME_POOLS = {"A": (5, 7, 10, 14), "B": (7, 10, 14, 21), "C": (10, 14, 21, 28)}
ORDER_LEAD_TIMES_RANGE = (4.0, 6.0)  # one order covers k lead times of demand
MIN_ORDER_DAYS = 15.0
ORDER_CAP_SHARE_OF_OVERSTOCK = 0.75  # order quantity <= 75 % of the overstock coverage

LEAD_TIME_NOISE_DAYS = 2  # realised lead time = nominal +/- up to this many days
SPLIT_DELIVERY_SHARE = 0.1  # orders delivered as two receipts on the same day
SPLIT_FIRST_PART = 0.6
SUPPLIERS = tuple(f"Lieferant {i:02d}" for i in range(1, 13))
FIRST_PO_NUMBER = 4_500_000_001
SUPPLIER_STREAM = 1  # separate stream key so supplier choice does not shift demand draws

WEEKDAYS_PER_WEEK = 5
DAYS_PER_WEEK = 7

# Generic German industrial parts with their unit of measure. No real product names.
CATALOGUE: tuple[tuple[str, str], ...] = (
    ("Dichtungssatz NBR 40x52", "ST"),
    ("Hydraulikschlauch DN12", "ST"),
    ("Kugellager 6204", "ST"),
    ("Steuerblock Gehäuse", "ST"),
    ("O-Ring FKM 25x3", "ST"),
    ("Zylinderschraube M8x30", "ST"),
    ("Sechskantmutter M12", "ST"),
    ("Wegeventil 4/3 NG6", "ST"),
    ("Druckbegrenzungsventil NG10", "ST"),
    ("Zahnradpumpe 16 ccm", "ST"),
    ("Hydraulikzylinder 50/30-200", "ST"),
    ("Filterelement 10 µm", "ST"),
    ("Rückschlagventil R1/2", "ST"),
    ("Manometer 0-250 bar", "ST"),
    ("Kupplungsstecker DN10", "ST"),
    ("Schlauchschelle 20-32", "ST"),
    ("Passfeder 8x7x40", "ST"),
    ("Wellendichtring 35x52x7", "ST"),
    ("Rillenkugellager 6305", "ST"),
    ("Linearführung Wagen Gr. 25", "ST"),
    ("Kugelgewindetrieb 16x5", "ST"),
    ("Servomotor Flansch 80", "ST"),
    ("Drucksensor 0-400 bar", "ST"),
    ("Näherungsschalter M18", "ST"),
    ("Kabelverschraubung M20", "ST"),
    ("Steckverbinder M12 5-pol.", "ST"),
    ("Magnetspule 24V DC", "ST"),
    ("Ventilplatte NG6", "ST"),
    ("Druckfeder 2x20x60", "ST"),
    ("Scheibe DIN 125 M10", "ST"),
    ("Gewindestift M6x10", "ST"),
    ("Flanschlager UCF 205", "ST"),
    ("Zahnriemen AT10 1250", "ST"),
    ("Riemenscheibe AT10 Z30", "ST"),
    ("Kupplungsstern 24", "ST"),
    ("Hydrospeicher 1 l", "ST"),
    ("Ölkühler Platte 40 kW", "ST"),
    ("Steuerplatine Ventiltreiber", "ST"),
    ("Leistungsschütz 24V", "ST"),
    ("Endschalter Rollenhebel", "ST"),
    ("Gehäusedeckel Alu Guss", "ST"),
    ("Distanzhülse 10x20", "ST"),
    ("Granulat PA6 schwarz", "KG"),
    ("Schweißdraht SG2 1,0 mm", "KG"),
    ("Lagerfett Lithium EP2", "KG"),
    ("Messingstange CuZn39", "KG"),
    ("Rundstahl C45 Ø40", "KG"),
    ("Pulverlack RAL 7035", "KG"),
    ("Steuerleitung 7x0,75", "M"),
    ("Hydraulikrohr 12x1,5", "M"),
    ("Kupferkabel 3x1,5", "M"),
    ("Schutzschlauch PG16", "M"),
    ("Gummiprofil EPDM 10x8", "M"),
    ("Dichtungsband PTFE 20", "M"),
    ("Hydrauliköl HLP 46", "L"),
    ("Kühlschmierstoff Emulsion", "L"),
    ("Getriebeöl CLP 220", "L"),
    ("Reinigungsmittel alkalisch", "L"),
    ("Korrosionsschutzöl", "L"),
    ("Schneidöl wassermischbar", "L"),
)


@dataclass(frozen=True)
class MaterialPlan:
    """Master data and replenishment policy of one material in one plant."""

    material_id: str
    plant: str
    description: str
    unit: str
    unit_price_eur: float
    profile: str
    weekday_demand: float
    storage_locations: tuple[str, ...]
    sloc_shares: tuple[float, ...]
    abc_estimate: str
    lead_time_days: int
    weekly_sigma: float
    safety_stock: float
    reorder_point: float
    order_qty: float
    has_min_stock: bool
    has_max_stock: bool
    scenario: str = "normal"

    @property
    def daily_demand(self) -> float:
        """Mean demand per calendar day (weekends have none)."""
        return self.weekday_demand * WEEKDAYS_PER_WEEK / DAYS_PER_WEEK


def round_qty(qty: float, unit: str) -> float:
    """Round a planning quantity up: whole pieces for ST, one decimal for KG, M and L."""
    if unit == "ST":
        return float(math.ceil(qty))
    return math.ceil(qty * 10) / 10


def _log_uniform(rng: np.random.Generator, low: float, high: float, size: int) -> np.ndarray:
    return np.exp(rng.uniform(math.log(low), math.log(high), size))


def _material_ids(rng: np.random.Generator, n: int) -> list[str]:
    """Unique 8-digit material numbers; the first half starts with zeros, as in SAP."""
    with_zeros = rng.choice(np.arange(10_000, 1_000_000), n // 2, replace=False)
    # Upper bound below 99000000: the 99... range is reserved for the "unknown material" defect.
    without_zeros = rng.choice(np.arange(10_000_000, 99_000_000), n - n // 2, replace=False)
    numbers = np.concatenate([with_zeros, without_zeros])
    return [str(int(x)).zfill(MATERIAL_ID_LENGTH) for x in numbers]


def _weekly_sigma(profile: str, weekday_demand: float) -> float:
    """True standard deviation of weekly demand for a profile, derived analytically."""
    mu = weekday_demand
    if profile == "steady":
        # Five independent normal weekdays.
        return math.sqrt(WEEKDAYS_PER_WEEK) * STEADY_DAILY_CV * mu
    if profile == "variable":
        # W = F * sum(G_i), F lognormal with mean 1, G_i gamma with mean mu.
        # Var(W) = E[F^2] * 5 * (cv * mu)^2 + Var(F) * (5 * mu)^2
        e_f2 = math.exp(VARIABLE_WEEK_SIGMA_LN**2)
        var = (
            e_f2 * WEEKDAYS_PER_WEEK * (VARIABLE_DAILY_CV * mu) ** 2
            + (e_f2 - 1) * (WEEKDAYS_PER_WEEK * mu) ** 2
        )
        return math.sqrt(var)
    # Intermittent: event with probability p, size S with mean mu / p.
    # Var(day) = p * E[S^2] - mu^2, with E[S^2] = (mu / p)^2 * (1 + cv^2).
    p = INTERMITTENT_PROBABILITY
    size_mean = mu / p
    var_day = p * size_mean**2 * (1 + INTERMITTENT_SIZE_CV**2) - mu**2
    return math.sqrt(WEEKDAYS_PER_WEEK * var_day)


def _material_plant_frame(rng: np.random.Generator) -> pd.DataFrame:
    """One row per material and plant with catalogue data, price, profile and demand level."""
    n = len(CATALOGUE)
    catalogue = pd.DataFrame(
        {
            "material_id": _material_ids(rng, n),
            "description": [d for d, _ in CATALOGUE],
            "unit": [u for _, u in CATALOGUE],
            "unit_price_eur": np.round(_log_uniform(rng, *PRICE_RANGE_EUR, n), 2),
        }
    )
    order = rng.permutation(n)
    shared = order[:N_SHARED_MATERIALS]
    single = order[N_SHARED_MATERIALS:]
    half = len(single) // 2
    plant_rows = (
        [(i, PLANTS[0]) for i in shared]
        + [(i, PLANTS[1]) for i in shared]
        + [(i, PLANTS[0]) for i in single[:half]]
        + [(i, PLANTS[1]) for i in single[half:]]
    )
    frame = catalogue.iloc[[i for i, _ in plant_rows]].reset_index(drop=True)
    frame = frame.assign(plant=[p for _, p in plant_rows])
    frame = frame.sort_values(["plant", "material_id"], ignore_index=True)

    # Exact profile mix, shuffled, so the shares do not drift with the random draw.
    counts = {k: round(v * len(frame)) for k, v in PROFILE_SHARES.items()}
    counts["steady"] += len(frame) - sum(counts.values())
    profiles = np.concatenate([[k] * c for k, c in counts.items()])
    return frame.assign(
        profile=rng.permutation(profiles),
        weekday_demand=np.round(_log_uniform(rng, *WEEKDAY_DEMAND_RANGE, len(frame)), 2),
    )


def build_plans(
    rng: np.random.Generator, thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> list[MaterialPlan]:
    """Master data and reorder-point policy (s, Q) for every material and plant.

    Safety stock uses the service level of the estimated ABC class, so the simulated policy
    follows the same logic the analysis later applies to the data.
    """
    frame = _material_plant_frame(rng)
    # Expected annual consumption value, classified with the same rule the analysis uses.
    annual_value = frame["weekday_demand"] * WEEKDAYS_PER_WEEK * 52 * frame["unit_price_eur"]
    abc = assign_abc(frame.assign(annual_consumption_value=annual_value), thresholds)["abc"]

    plans = []
    for row, abc_class in zip(frame.itertuples(index=False), abc, strict=True):
        lead_time = int(rng.choice(LEAD_TIME_POOLS[abc_class]))
        sigma_w = _weekly_sigma(row.profile, row.weekday_demand)
        daily = row.weekday_demand * WEEKDAYS_PER_WEEK / DAYS_PER_WEEK
        z = NormalDist().inv_cdf(thresholds.service_level(abc_class))
        safety = round_qty(z * sigma_w * math.sqrt(lead_time / DAYS_PER_WEEK), row.unit)
        order_days = float(
            np.clip(
                rng.uniform(*ORDER_LEAD_TIMES_RANGE) * lead_time,
                MIN_ORDER_DAYS,
                ORDER_CAP_SHARE_OF_OVERSTOCK * thresholds.overstock_days(abc_class),
            )
        )
        if rng.random() < SECOND_SLOC_SHARE:
            main = rng.uniform(*MAIN_SLOC_SHARE_RANGE)
            slocs, shares = ("0001", "0002"), (main, 1 - main)
        else:
            slocs, shares = ("0001",), (1.0,)
        plans.append(
            MaterialPlan(
                material_id=row.material_id,
                plant=row.plant,
                description=row.description,
                unit=row.unit,
                unit_price_eur=float(row.unit_price_eur),
                profile=row.profile,
                weekday_demand=float(row.weekday_demand),
                storage_locations=slocs,
                sloc_shares=shares,
                abc_estimate=str(abc_class),
                lead_time_days=lead_time,
                weekly_sigma=sigma_w,
                safety_stock=safety,
                reorder_point=round_qty(daily * lead_time + safety, row.unit),
                order_qty=round_qty(daily * order_days, row.unit),
                has_min_stock=bool(rng.random() < MIN_STOCK_SHARE),
                has_max_stock=bool(rng.random() < MAX_STOCK_SHARE),
            )
        )
    return plans


# --- Daily simulation ------------------------------------------------------------------------

DATES = pd.date_range(START_DATE, END_DATE, freq="D")
N_DAYS = len(DATES)
SATURDAY = 5  # pandas day_of_week: Monday = 0


@dataclass(frozen=True, eq=False)
class Effects:
    """Scenario interventions for one material-plant. The default is no intervention.

    Arrays have one entry per day of `DATES`.
    """

    demand_factor: np.ndarray
    ordering_allowed: np.ndarray
    first_day: int = 0
    lost_order_from: int | None = None  # the first order placed on or after this day is lost
    fixed_rhythm: tuple[int, int] | None = None  # (start day, interval): order Q on a rhythm
    extra_receipts: tuple[tuple[int, float], ...] = ()  # (day index, quantity)
    consumption_stop: int | None = None  # no demand from this day on

    @classmethod
    def none(cls) -> "Effects":
        """No intervention: normal demand and the reorder-point policy all year."""
        return cls(demand_factor=np.ones(N_DAYS), ordering_allowed=np.ones(N_DAYS, dtype=bool))


@dataclass(frozen=True, eq=False)
class Simulation:
    """Ground truth of the simulation, before any data defect is injected.

    `daily` holds stock, receipts, consumption and demand per material, plant and date.
    `receipts` holds one row per goods receipt inside the date range and `orders` one row
    per purchase order. `arrival_day` is a day index into `DATES`; it is NA for a lost order
    and can lie beyond the last date for an order still in transit at the end.
    """

    daily: pd.DataFrame
    receipts: pd.DataFrame
    orders: pd.DataFrame


def _round_array(values: np.ndarray, unit: str) -> np.ndarray:
    return np.rint(values) if unit == "ST" else np.round(values, 1)


def draw_demand(plan: MaterialPlan, rng: np.random.Generator) -> np.ndarray:
    """Daily demand for the whole date range: profile-specific on weekdays, zero at weekends."""
    mu = plan.weekday_demand
    if plan.profile == "steady":
        raw = rng.normal(mu, STEADY_DAILY_CV * mu, N_DAYS)
    elif plan.profile == "variable":
        week = (DATES - DATES[0] + pd.Timedelta(days=DATES[0].day_of_week)).days // DAYS_PER_WEEK
        # Lognormal with mean 1: mu_ln = -sigma^2 / 2.
        sigma = VARIABLE_WEEK_SIGMA_LN
        level = rng.lognormal(-(sigma**2) / 2, sigma, week.max() + 1)[week]
        shape = 1 / VARIABLE_DAILY_CV**2
        raw = level * rng.gamma(shape, mu / shape, N_DAYS)
    else:
        p = INTERMITTENT_PROBABILITY
        sigma = math.sqrt(math.log(1 + INTERMITTENT_SIZE_CV**2))
        sizes = rng.lognormal(math.log(mu / p) - sigma**2 / 2, sigma, N_DAYS)
        raw = np.where(rng.random(N_DAYS) < p, sizes, 0.0)
    weekday = np.asarray(DATES.day_of_week < SATURDAY)
    return _round_array(np.clip(raw, 0, None) * weekday, plan.unit)


def _arrival_day(order_day: int, lead_time: int, rng: np.random.Generator) -> int:
    """Order day plus noisy lead time, moved to the following Monday if it hits a weekend."""
    noise = int(rng.integers(-LEAD_TIME_NOISE_DAYS, LEAD_TIME_NOISE_DAYS + 1))
    day = order_day + lead_time + noise
    weekday = (DATES[0].day_of_week + day) % DAYS_PER_WEEK
    return day + (DAYS_PER_WEEK - weekday if weekday >= SATURDAY else 0)


def simulate_one(
    plan: MaterialPlan, effects: Effects, rng: np.random.Generator
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """Simulate one material-plant day by day under the reorder-point policy.

    Order of events within a day: receipts arrive, demand is served up to the available
    stock, the end-of-day stock is recorded, then the planner may place an order. This is
    the timing assumption of the analysis: receipts of day t are in the stock of day t.

    Returns the daily frame, the receipts (day, quantity, index into the orders) and the
    orders. An order counts as open from its order day until it arrives; a lost order stays
    open forever, which is why the planner does not reorder after a lost delivery.
    """
    demand = draw_demand(plan, rng)
    demand = _round_array(demand * effects.demand_factor, plan.unit)
    if effects.consumption_stop is not None:
        demand[effects.consumption_stop :] = 0.0

    first = effects.first_day
    stock = round_qty(
        rng.uniform(plan.reorder_point, plan.reorder_point + plan.order_qty), plan.unit
    )
    orders: list[dict] = []
    receipts: list[dict] = []
    for day, qty in effects.extra_receipts:
        # A one-off order outside the policy, placed one lead time before it arrives.
        order_day = max(day - plan.lead_time_days, first)
        _add_order(orders, receipts, order_day, day, [qty], unplanned=True)

    stock_out = np.full(N_DAYS, np.nan)
    receipt_out = np.zeros(N_DAYS)
    consumption_out = np.full(N_DAYS, np.nan)
    for t in range(first, N_DAYS):
        received = round(sum(r["receipt_qty"] for r in receipts if r["day"] == t), 1)
        stock = round(stock + received, 1)
        consumed = min(demand[t], stock)
        stock = round(stock - consumed, 1)
        stock_out[t], receipt_out[t], consumption_out[t] = stock, received, consumed

        if not effects.ordering_allowed[t]:
            continue
        if effects.fixed_rhythm is not None and t >= effects.fixed_rhythm[0]:
            start, interval = effects.fixed_rhythm
            due = (t - start) % interval == 0
        else:
            open_qty = sum(
                o["qty"]
                for o in orders
                if o["order_day"] <= t and (o["arrival_day"] is None or o["arrival_day"] > t)
            )
            due = stock + open_qty < plan.reorder_point
        if not due:
            continue
        lost = (
            effects.lost_order_from is not None
            and t >= effects.lost_order_from
            and not any(o["arrival_day"] is None for o in orders)
        )
        arrival = None if lost else _arrival_day(t, plan.lead_time_days, rng)
        parts = [] if lost else _split_delivery(plan, rng)
        _add_order(orders, receipts, t, arrival, parts, unplanned=False, qty=plan.order_qty)

    daily = pd.DataFrame(
        {
            "date": DATES,
            "stock_qty": stock_out,
            "receipt_qty": receipt_out,
            "consumption": consumption_out,
            "demand": np.where(np.arange(N_DAYS) >= first, demand, np.nan),
        }
    ).iloc[first:]
    in_range = [r for r in receipts if first <= r["day"] < N_DAYS]
    return daily, sorted(in_range, key=lambda r: r["day"]), orders


def _add_order(
    orders: list[dict],
    receipts: list[dict],
    order_day: int,
    arrival_day: int | None,
    parts: list[float],
    *,
    unplanned: bool,
    qty: float | None = None,
) -> None:
    """Record an order and the receipts it will produce."""
    index = len(orders)
    orders.append(
        {
            "order_day": order_day,
            "arrival_day": arrival_day,
            "qty": qty if qty is not None else sum(parts),
            "unplanned": unplanned,
        }
    )
    receipts.extend({"day": arrival_day, "receipt_qty": p, "order": index} for p in parts)


def _split_delivery(plan: MaterialPlan, rng: np.random.Generator) -> list[float]:
    """One order as one receipt, or occasionally as two receipts on the same day."""
    if rng.random() >= SPLIT_DELIVERY_SHARE:
        return [plan.order_qty]
    first = round_qty(plan.order_qty * SPLIT_FIRST_PART, plan.unit)
    return [first, round(plan.order_qty - first, 1)]


def simulation_rng(index: int) -> np.random.Generator:
    """Random stream of the material-plant at position `index`; scenario trials reuse it."""
    return np.random.default_rng([SEED, index])


def simulate(plans: list[MaterialPlan], effects: dict[tuple[str, str], Effects]) -> Simulation:
    """Simulate every material-plant.

    Each material-plant gets its own random stream, keyed by its position in `plans`, so an
    intervention on one material never changes the random draws of another.
    """
    daily_parts, receipt_rows, order_rows = [], [], []
    po_number = FIRST_PO_NUMBER
    for index, plan in enumerate(plans):
        rng = simulation_rng(index)
        supplier_rng = np.random.default_rng([SEED, index, SUPPLIER_STREAM])
        supplier = SUPPLIERS[int(supplier_rng.integers(len(SUPPLIERS)))]
        key = {"material_id": plan.material_id, "plant": plan.plant}
        daily, receipts, orders = simulate_one(
            plan, effects.get((plan.material_id, plan.plant), Effects.none()), rng
        )
        daily_parts.append(daily.assign(**key))
        po_numbers = [str(po_number + i) for i in range(len(orders))]
        po_number += len(orders)
        order_rows.extend(
            key | o | {"po_number": po} for o, po in zip(orders, po_numbers, strict=True)
        )
        receipt_rows.extend(
            key
            | {
                "date": DATES[r["day"]],
                "receipt_qty": r["receipt_qty"],
                "supplier": supplier,
                "po_number": po_numbers[r["order"]],
            }
            for r in receipts
        )
    columns = ["material_id", "plant", "date"]
    daily = pd.concat(daily_parts, ignore_index=True)
    daily = daily[columns + [c for c in daily.columns if c not in columns]]
    orders_frame = pd.DataFrame(order_rows).astype({"arrival_day": "Int64"})
    return Simulation(daily=daily, receipts=pd.DataFrame(receipt_rows), orders=orders_frame)


# --- Scenarios -------------------------------------------------------------------------------
# Each builder returns the Effects for one candidate material-plant, or None when a trial
# simulation shows that the scenario would not be unambiguous for that material. Builders
# search only over timing; the scenario logic itself is fixed.

END = N_DAYS - 1
SCENARIOS_PER_TYPE = 3
SCENARIO_STREAM = 2  # stream key of the scenario assignment
SCENARIO_MARGIN = 1.5  # overstock scenarios end at >= 1.5x the overstock limit
RECENT_CONSUMPTION_DAYS = 60  # shortage scenarios must still have consumed within this window

DELAY_EXTRA_DAYS = (20, 80)  # lost order placed lead time + this many days before the end
SPIKE_FACTOR = 3.0
SPIKE_DAYS = (28, 42)
STOCKOUT_ZERO_DAYS_BEFORE_END = (14, 28)
OVER_ORDER_DAYS_BEFORE_END = (60, 80)
OVER_ORDER_COVERAGE_DAYS = 365
DROP_FACTOR = 0.2
DROP_DAYS = 120
DEAD_STOP_DAYS_BEFORE_END = (125, 160)
NEW_MATERIAL_DAYS_BEFORE_END = (20, 35)
PHASE_OUT_STOP_DAYS_BEFORE_END = 220
PHASE_OUT_ZERO_DAYS_BEFORE_END = 100
PHASE_OUT_STEP_DAYS = 10

SCENARIO_EXPECTED: dict[str, tuple[Status, ...]] = {
    "delayed_delivery": (Status.SHORTAGE_CRITICAL,),
    "demand_spike": (Status.SHORTAGE_CRITICAL, Status.SHORTAGE_WARNING),
    "stockout": (Status.SHORTAGE_CRITICAL,),
    "over_ordering": (Status.OVERSTOCK,),
    "demand_drop": (Status.OVERSTOCK,),
    "dead_stock": (Status.DEAD_STOCK,),
    "new_material": (Status.INSUFFICIENT_DATA,),
    "phased_out": (Status.INACTIVE,),
}


def planned_max_stock(plan: MaterialPlan) -> float:
    """Master-data maximum stock: one full order on top of the reorder point, plus a margin."""
    return round_qty((plan.reorder_point + plan.order_qty) * MAX_STOCK_FACTOR, plan.unit)


def _trial(plan: MaterialPlan, index: int, effects: Effects) -> tuple[pd.DataFrame, list, list]:
    """Simulate with the material's own random stream, exactly as `simulate` will."""
    return simulate_one(plan, effects, simulation_rng(index))


def _last_consumption_day(daily: pd.DataFrame) -> int:
    consumed = daily.index[daily["consumption"] > 0]
    return int(consumed.max()) if len(consumed) else -1


def _overstock_limit(plan: MaterialPlan, daily_demand: float, thresholds: Thresholds) -> float:
    """Stock the scenario must exceed so that OVERSTOCK is unambiguous."""
    limit = daily_demand * thresholds.overstock_days(plan.abc_estimate)
    if plan.has_max_stock:
        limit = max(limit, planned_max_stock(plan))
    return limit * SCENARIO_MARGIN


def _delayed_delivery(plan: MaterialPlan, index: int, **_: object) -> Effects | None:
    """An order late in the range never arrives; the planner waits for it and runs dry."""
    low, high = DELAY_EXTRA_DAYS
    for extra in range(low, high + 1):
        effects = replace(Effects.none(), lost_order_from=END - plan.lead_time_days - extra)
        daily, _, orders = _trial(plan, index, effects)
        lost = any(o["arrival_day"] is None for o in orders)
        if (
            lost
            and daily.loc[END, "stock_qty"] < plan.safety_stock
            and _last_consumption_day(daily) >= END - RECENT_CONSUMPTION_DAYS
        ):
            return effects
    return None


def _demand_spike(plan: MaterialPlan, index: int, **_: object) -> Effects | None:
    """Demand triples at the end; the shortest spike that ends below the reorder point wins."""
    low, high = SPIKE_DAYS
    for days in range(low, high + 1):
        factor = np.ones(N_DAYS)
        factor[N_DAYS - days :] = SPIKE_FACTOR
        effects = replace(Effects.none(), demand_factor=factor)
        daily, _, _ = _trial(plan, index, effects)
        if daily.loc[END, "stock_qty"] < plan.reorder_point:
            return effects
    return None


def _stockout(plan: MaterialPlan, index: int, **_: object) -> Effects | None:
    """Ordering stops; stock reaches zero two to four weeks before the end, demand goes on."""
    near, far = STOCKOUT_ZERO_DAYS_BEFORE_END
    for stop in range(END - near, 0, -1):
        allowed = np.ones(N_DAYS, dtype=bool)
        allowed[stop:] = False
        effects = replace(Effects.none(), ordering_allowed=allowed)
        daily, _, _ = _trial(plan, index, effects)
        stock = daily.loc[stop:, "stock_qty"]
        zero_days = stock.index[stock == 0]
        if len(zero_days) == 0:
            continue
        first_zero = int(zero_days[0])
        if first_zero < END - far:
            return None  # stopping earlier only moves the zero day further back
        if first_zero <= END - near and (stock.loc[first_zero:] == 0).all():
            return effects
    return None


def _over_ordering(
    plan: MaterialPlan, index: int, rng: np.random.Generator, thresholds: Thresholds
) -> Effects | None:
    """One very large unplanned receipt two to three months before the end."""
    low, high = OVER_ORDER_DAYS_BEFORE_END
    qty = round_qty(plan.daily_demand * OVER_ORDER_COVERAGE_DAYS, plan.unit)
    for back in rng.permutation(np.arange(low, high + 1)):
        day = END - int(back)
        if DATES[day].day_of_week >= SATURDAY:
            continue
        effects = replace(Effects.none(), extra_receipts=((day, qty),))
        daily, _, _ = _trial(plan, index, effects)
        limit = _overstock_limit(plan, plan.daily_demand, thresholds)
        return effects if daily.loc[END, "stock_qty"] >= limit else None
    return None


def _demand_drop(
    plan: MaterialPlan, index: int, thresholds: Thresholds, **_: object
) -> Effects | None:
    """Demand falls to a fifth; the planner keeps ordering Q on the old rhythm."""
    start = END - DROP_DAYS
    factor = np.ones(N_DAYS)
    factor[start:] = DROP_FACTOR
    interval = max(round(plan.order_qty / plan.daily_demand), 1)
    effects = replace(Effects.none(), demand_factor=factor, fixed_rhythm=(start, interval))
    daily, _, _ = _trial(plan, index, effects)
    limit = _overstock_limit(plan, DROP_FACTOR * plan.daily_demand, thresholds)
    recent = _last_consumption_day(daily) >= END - RECENT_CONSUMPTION_DAYS
    return effects if recent and daily.loc[END, "stock_qty"] >= limit else None


def _dead_stock(plan: MaterialPlan, index: int, **_: object) -> Effects | None:
    """Consumption stops for good on the day after a receipt, four to five months before end."""
    near, far = DEAD_STOP_DAYS_BEFORE_END
    _, receipts, _ = _trial(plan, index, Effects.none())
    days = [r["day"] for r in receipts if END - far <= r["day"] < END - near]
    if not days:
        return None
    effects = replace(Effects.none(), consumption_stop=max(days) + 1)
    daily, _, _ = _trial(plan, index, effects)
    # A full order above the safety stock keeps the status clear of the shortage rules.
    enough = daily.loc[END, "stock_qty"] >= plan.safety_stock + plan.order_qty
    return effects if enough else None


def _new_material(plan: MaterialPlan, index: int, rng: np.random.Generator, **_: object) -> Effects:
    """The first snapshot is only three to five weeks before the end."""
    low, high = NEW_MATERIAL_DAYS_BEFORE_END
    return replace(Effects.none(), first_day=END - int(rng.integers(low, high + 1)))


def _phased_out(plan: MaterialPlan, index: int, **_: object) -> Effects | None:
    """Ordering stops mid-year, the stock is used up, and demand ends with it."""
    for stop in range(END - PHASE_OUT_STOP_DAYS_BEFORE_END, 0, -PHASE_OUT_STEP_DAYS):
        allowed = np.ones(N_DAYS, dtype=bool)
        allowed[stop:] = False
        effects = replace(Effects.none(), ordering_allowed=allowed)
        daily, _, _ = _trial(plan, index, effects)
        stock = daily.loc[stop:, "stock_qty"]
        zero_days = stock.index[stock == 0]
        if len(zero_days) and zero_days[0] <= END - PHASE_OUT_ZERO_DAYS_BEFORE_END:
            # Demand is drawn up front, so stopping it at the zero day changes nothing before.
            return replace(effects, consumption_stop=int(zero_days[0]) + 1)
    return None


SCENARIO_BUILDERS = {
    "delayed_delivery": _delayed_delivery,
    "demand_spike": _demand_spike,
    "stockout": _stockout,
    "over_ordering": _over_ordering,
    "demand_drop": _demand_drop,
    "dead_stock": _dead_stock,
    "new_material": _new_material,
    "phased_out": _phased_out,
}


def build_scenarios(
    plans: list[MaterialPlan], thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> tuple[list[MaterialPlan], dict[tuple[str, str], Effects]]:
    """Assign each scenario to three material-plants and return their interventions.

    Candidates are non-intermittent materials in a seeded random order; a candidate on which
    the scenario would be ambiguous is skipped. Raises RuntimeError if a scenario cannot be
    placed three times, so a weak data set is never written silently.
    """
    rng = np.random.default_rng([SEED, SCENARIO_STREAM])
    pool = [int(i) for i in rng.permutation(len(plans)) if plans[i].profile != "intermittent"]
    assigned: dict[int, str] = {}
    effects: dict[tuple[str, str], Effects] = {}
    for name, builder in SCENARIO_BUILDERS.items():
        placed = 0
        for index in [i for i in pool if i not in assigned]:
            plan = plans[index]
            result = builder(plan, index, rng=rng, thresholds=thresholds)
            if result is None:
                continue
            assigned[index] = name
            effects[(plan.material_id, plan.plant)] = result
            placed += 1
            if placed == SCENARIOS_PER_TYPE:
                break
        if placed < SCENARIOS_PER_TYPE:
            raise RuntimeError(f"Scenario {name!r} placed only {placed} times")
    updated = [replace(p, scenario=assigned.get(i, "normal")) for i, p in enumerate(plans)]
    return updated, effects


# --- Output frames ---------------------------------------------------------------------------

MAIN_SLOC = "0001"


def build_master(plans: list[MaterialPlan], orders: pd.DataFrame) -> pd.DataFrame:
    """Material master per material and plant, in canonical column names.

    `lead_time_days` is the rounded mean realised lead time of the planned orders, so the
    master data agrees with what the deliveries show.
    """
    planned = orders[~orders["unplanned"] & orders["arrival_day"].notna()]
    realised = (
        (planned["arrival_day"] - planned["order_day"])
        .astype(float)
        .groupby([planned["material_id"], planned["plant"]])
        .mean()
    )
    rows = []
    for plan in plans:
        mean_lt = realised.get((plan.material_id, plan.plant), float(plan.lead_time_days))
        rows.append(
            {
                "material_id": plan.material_id,
                "plant": plan.plant,
                "description": plan.description,
                "unit_price_eur": plan.unit_price_eur,
                "lead_time_days": int(round(mean_lt)),
                "min_stock": plan.safety_stock if plan.has_min_stock else np.nan,
                "max_stock": planned_max_stock(plan) if plan.has_max_stock else np.nan,
                "unit": plan.unit,
            }
        )
    return pd.DataFrame(rows, columns=list(MATERIAL_COLUMNS.values()))


def split_stock(plans: list[MaterialPlan], daily: pd.DataFrame) -> pd.DataFrame:
    """Split the simulated stock across storage locations by each material's fixed shares.

    The main location gets the rounded-down share, the second the remainder, so the
    locations always add up to the simulated total.
    """
    parts = []
    for plan in plans:
        mine = daily[(daily["material_id"] == plan.material_id) & (daily["plant"] == plan.plant)]
        base = mine[["date", "material_id", "plant"]].assign(unit=plan.unit)
        total = mine["stock_qty"].to_numpy()
        if len(plan.storage_locations) == 1:
            parts.append(base.assign(storage_location=MAIN_SLOC, stock_qty=total))
            continue
        scale = 1 if plan.unit == "ST" else 10
        main = np.floor(total * plan.sloc_shares[0] * scale) / scale
        second = np.round(total - main, 1)
        for sloc, qty in zip(plan.storage_locations, (main, second), strict=True):
            parts.append(base.assign(storage_location=sloc, stock_qty=qty))
    stock = pd.concat(parts, ignore_index=True)
    stock = stock.sort_values(["date", "plant", "material_id", "storage_location"])
    return stock[list(STOCK_COLUMNS.values())].reset_index(drop=True)


def receipts_frame(sim: Simulation) -> pd.DataFrame:
    """Goods receipts in canonical columns, all booked to the main storage location."""
    receipts = sim.receipts.assign(storage_location=MAIN_SLOC)
    return receipts[list(RECEIPT_COLUMNS.values())].reset_index(drop=True)


# --- Data defects ----------------------------------------------------------------------------
# Applied to the output frames only, after the simulation. Every defect is logged so the
# tests can check that the data-quality layer finds each one.

DEFECT_STREAM = 3
PROTECTED_DAYS = 14  # no defect in the last days of a scenario material
N_CLEAN_MATERIAL_PLANTS = 5  # normal material-plants kept free of any defect
MISSING_DAY_SHARE = 0.01
# Fixed lengths so that every gap length from 2 to 4 days is present in the sample data.
MISSING_GAP_LENGTHS = (2, 3, 4, 3, 4)
N_PARTIAL_SNAPSHOTS = 10
N_NEGATIVE_STOCK = 6
NEGATIVE_STOCK_RANGE = (1, 5)
N_EXACT_DUPLICATES = 5
N_CONFLICTING_DUPLICATES = 5
CONFLICT_FACTOR = 1.1  # the wrong duplicate shows 10 % more stock
N_UNKNOWN_RECEIPTS = 4
UNKNOWN_MATERIAL_RANGE = (99_000_000, 100_000_000)
UNKNOWN_RECEIPT_QTY = (10, 500)
N_LOST_ZEROS_STOCK = 6
N_LOST_ZEROS_RECEIPTS = 4
N_UNRECORDED_RECEIPTS = 3


@dataclass(frozen=True, eq=False)
class Defects:
    """Output frames after defect injection, plus a log with one row per defect."""

    stock: pd.DataFrame
    receipts: pd.DataFrame
    log: pd.DataFrame
    clean_material_plants: list[tuple[str, str]]


def _protected(frame: pd.DataFrame, scenario_keys: set[tuple[str, str]]) -> pd.Series:
    """Rows in the last PROTECTED_DAYS of a scenario material, which must stay untouched."""
    keys = pd.Series(list(zip(frame["material_id"], frame["plant"], strict=True)), frame.index)
    late = frame["date"] > END_DATE - pd.Timedelta(days=PROTECTED_DAYS)
    return keys.isin(scenario_keys) & late


def _log(kind: str, sheet: str, row: pd.Series, detail: str) -> dict:
    return {
        "defect": kind,
        "sheet": sheet,
        "material_id": row["material_id"],
        "plant": row["plant"],
        "storage_location": row.get("storage_location", ""),
        "date": row["date"],
        "detail": detail,
    }


def inject_defects(
    stock: pd.DataFrame, receipts: pd.DataFrame, plans: list[MaterialPlan], orders: pd.DataFrame
) -> Defects:
    """Inject the defects from the specification into copies of the output frames."""
    rng = np.random.default_rng([SEED, DEFECT_STREAM])
    scenario_keys = {(p.material_id, p.plant) for p in plans if p.scenario != "normal"}
    normal = [(p.material_id, p.plant) for p in plans if p.scenario == "normal"]
    clean = sorted(normal[i] for i in rng.choice(len(normal), N_CLEAN_MATERIAL_PLANTS, False))
    excluded = scenario_keys | set(clean)
    log: list[dict] = []
    # Material-plant-days already touched by a defect; one defect per day keeps counts exact.
    used: set[tuple[str, str, pd.Timestamp]] = set()

    receipts, receipt_log = _receipt_defects(receipts, orders, excluded, clean, used, rng)
    log.extend(receipt_log)
    stock, stock_log = _stock_defects(stock, plans, scenario_keys, set(clean), used, rng)
    log.extend(stock_log)
    log_frame = pd.DataFrame(log).sort_values(["defect", "date", "material_id"], ignore_index=True)
    return Defects(stock=stock, receipts=receipts, log=log_frame, clean_material_plants=clean)


def _receipt_defects(
    receipts: pd.DataFrame,
    orders: pd.DataFrame,
    excluded: set[tuple[str, str]],
    clean: list[tuple[str, str]],
    used: set,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, list[dict]]:
    """Unrecorded receipts, lost leading zeros and receipts for unknown materials."""
    log: list[dict] = []
    unplanned = set(orders.loc[orders["unplanned"], "po_number"])
    single = receipts["po_number"].map(receipts["po_number"].value_counts()) == 1
    keys = pd.Series(list(zip(receipts["material_id"], receipts["plant"], strict=True)))
    late = receipts["date"] > END_DATE - pd.Timedelta(days=PROTECTED_DAYS)
    in_clean = keys.isin(set(clean))
    eligible = ~in_clean & ~(keys.isin(excluded) & late) & ~receipts["po_number"].isin(unplanned)

    # Unrecorded receipt: the stock still rises. Only single-part deliveries, so the stock
    # jump is unmistakable, and the day and the day before are kept free of other defects.
    candidates = receipts.index[eligible & single]
    removed = rng.choice(candidates, N_UNRECORDED_RECEIPTS, replace=False)
    for i in removed:
        row = receipts.loc[i]
        log.append(_log("unrecorded_receipt", SHEET_RECEIPTS, row, f"{row['receipt_qty']:g}"))
        for day in (row["date"], row["date"] - pd.Timedelta(days=1)):
            used.add((row["material_id"], row["plant"], day))
    out = receipts.drop(index=removed)

    # Lost leading zeros: the material number is written as a plain number.
    zeros = out.index[eligible.reindex(out.index) & out["material_id"].str.startswith("0")]
    lost = rng.choice(zeros, N_LOST_ZEROS_RECEIPTS, replace=False)
    out = out.astype({"material_id": object})
    for i in lost:
        log.append(_log("lost_leading_zeros", SHEET_RECEIPTS, out.loc[i], ""))
        out.loc[i, "material_id"] = int(out.loc[i, "material_id"])

    # Receipts for materials missing from the master data.
    low, high = UNKNOWN_MATERIAL_RANGE
    next_po = int(max(receipts["po_number"])) + 1
    weekdays = DATES[DATES.day_of_week < SATURDAY]
    unknown = pd.DataFrame(
        {
            "date": rng.choice(weekdays, N_UNKNOWN_RECEIPTS, replace=False),
            "material_id": [str(int(x)) for x in rng.integers(low, high, N_UNKNOWN_RECEIPTS)],
            "plant": rng.choice(PLANTS, N_UNKNOWN_RECEIPTS),
            "storage_location": MAIN_SLOC,
            "receipt_qty": rng.integers(*UNKNOWN_RECEIPT_QTY, N_UNKNOWN_RECEIPTS).astype(float),
            "supplier": rng.choice(SUPPLIERS, N_UNKNOWN_RECEIPTS),
            "po_number": [str(next_po + i) for i in range(N_UNKNOWN_RECEIPTS)],
        }
    )
    log.extend(
        _log("unknown_material", SHEET_RECEIPTS, row, "") for row in unknown.to_dict("records")
    )
    out = pd.concat([out, unknown], ignore_index=True).sort_values(
        ["date", "plant", "po_number"], ignore_index=True
    )
    return out, log


def _pick_days(
    days: pd.DataFrame, n: int, used: set, rng: np.random.Generator
) -> list[tuple[str, str, pd.Timestamp]]:
    """Draw n distinct, unused material-plant-days and mark them as used."""
    keys = [k for k in days.itertuples(index=False, name=None) if k not in used]
    chosen = [keys[i] for i in rng.choice(len(keys), n, replace=False)]
    used.update(chosen)
    return chosen


def _stock_defects(
    stock: pd.DataFrame,
    plans: list[MaterialPlan],
    scenario_keys: set[tuple[str, str]],
    clean: set[tuple[str, str]],
    used: set,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, list[dict]]:
    """Missing days and gaps, partial snapshots, negative stock, duplicates, lost zeros."""
    log: list[dict] = []
    mp_days = stock[["material_id", "plant", "date"]].drop_duplicates(ignore_index=True)
    keys = pd.Series(list(zip(mp_days["material_id"], mp_days["plant"], strict=True)))
    grouped = mp_days.groupby(["material_id", "plant"])["date"]
    # Never the first or last date of a material: that would shift its range, not leave a gap.
    inner = (mp_days["date"] > grouped.transform("min")) & (
        mp_days["date"] < grouped.transform("max")
    )
    eligible_days = mp_days[inner & ~keys.isin(clean) & ~_protected(mp_days, scenario_keys)]
    eligible_set = set(eligible_days.itertuples(index=False, name=None))

    # Gaps of two to four consecutive days, whole material-plant.
    remove_days: list[tuple[str, str, pd.Timestamp]] = []
    for length in MISSING_GAP_LENGTHS:
        while True:
            material, plant, start = eligible_days.iloc[int(rng.integers(len(eligible_days)))]
            span = [(material, plant, start + pd.Timedelta(days=k)) for k in range(-1, length + 1)]
            # The day before and after must stay observed so the gap has its exact length.
            if all(day in eligible_set and day not in used for day in span):
                used.update(span)
                remove_days.extend(span[1:-1])
                break
    gap_days = len(remove_days)

    # Partial snapshots: one of two storage locations missing on a day.
    two_slocs = {(p.material_id, p.plant) for p in plans if len(p.storage_locations) == 2}
    split_days = eligible_days[
        pd.Series(
            list(zip(eligible_days["material_id"], eligible_days["plant"], strict=True)),
            eligible_days.index,
        ).isin(two_slocs)
    ]
    partial = _pick_days(split_days, N_PARTIAL_SNAPSHOTS, used, rng)

    # Single missing days make up the rest of the target share.
    target = round(MISSING_DAY_SHARE * len(mp_days))
    singles = _pick_days(eligible_days, target - gap_days - len(partial), used, rng)
    remove_days.extend(singles)

    index = stock.set_index(["material_id", "plant", "date"]).index
    drop_whole = index.isin(remove_days)
    drop_partial = index.isin(partial) & (stock["storage_location"] != MAIN_SLOC).to_numpy()
    for key in remove_days:
        log.append(_log_key("missing_day", key, "gap" if key not in singles else "single"))
    for key in partial:
        log.append(_log_key("partial_snapshot", key, "0002 missing"))
    out = stock[~(drop_whole | drop_partial)]

    # Row-level defects on the main storage location of further unused days.
    main_index = out.set_index(["material_id", "plant", "date"]).index
    is_main = (out["storage_location"] == MAIN_SLOC).to_numpy()

    def rows_for(chosen: list) -> pd.Index:
        return out.index[main_index.isin(chosen) & is_main]

    negative = rows_for(_pick_days(eligible_days, N_NEGATIVE_STOCK, used, rng))
    values = -rng.integers(*NEGATIVE_STOCK_RANGE, len(negative), endpoint=True).astype(float)
    out = out.astype({"stock_qty": float})
    for i, value in zip(negative, values, strict=True):
        log.append(_log("negative_stock", SHEET_STOCK, out.loc[i], f"{value:g}"))
    out.loc[negative, "stock_qty"] = values

    exact = rows_for(_pick_days(eligible_days, N_EXACT_DUPLICATES, used, rng))
    conflicting = rows_for(_pick_days(eligible_days, N_CONFLICTING_DUPLICATES, used, rng))
    wrong = out.loc[conflicting].assign(
        stock_qty=lambda f: np.round(f["stock_qty"] * CONFLICT_FACTOR + 1)
    )
    log.extend(_log("exact_duplicate", SHEET_STOCK, out.loc[i], "") for i in exact)
    log.extend(
        _log("conflicting_duplicate", SHEET_STOCK, out.loc[i], f"{wrong.loc[i, 'stock_qty']:g}")
        for i in conflicting
    )

    zero_days = eligible_days[eligible_days["material_id"].str.startswith("0")]
    lost = rows_for(_pick_days(zero_days, N_LOST_ZEROS_STOCK, used, rng))
    log.extend(_log("lost_leading_zeros", SHEET_STOCK, out.loc[i], "") for i in lost)

    # The wrong duplicate is placed before the true row, so "keep the last row" restores
    # the truth; exact duplicates are identical either way.
    out = pd.concat([wrong, out, out.loc[exact]]).sort_index(kind="stable")
    out = out.astype({"material_id": object})
    is_lost = out.index.isin(lost)
    out.loc[is_lost, "material_id"] = out.loc[is_lost, "material_id"].map(int)
    out = out.sort_values(["date", "plant", "storage_location"], kind="stable")
    return out.reset_index(drop=True), log


def _log_key(kind: str, key: tuple[str, str, pd.Timestamp], detail: str) -> dict:
    material, plant, date = key
    row = pd.Series({"material_id": material, "plant": plant, "date": date})
    return _log(kind, SHEET_STOCK, row, detail)


# --- Assembly and output ---------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Generated:
    """Everything the generator produces. `simulation` is the defect-free ground truth."""

    plans: list[MaterialPlan]
    simulation: Simulation
    stock: pd.DataFrame
    receipts: pd.DataFrame
    materials: pd.DataFrame
    defects: pd.DataFrame
    manifest: dict


def generate(thresholds: Thresholds = DEFAULT_THRESHOLDS) -> Generated:
    """Run the whole generator in memory: plans, scenarios, simulation, defects, manifest."""
    plans, effects = build_scenarios(build_plans(np.random.default_rng(SEED), thresholds))
    sim = simulate(plans, effects)
    materials = build_master(plans, sim.orders)
    defects = inject_defects(split_stock(plans, sim.daily), receipts_frame(sim), plans, sim.orders)
    manifest = _manifest(plans, defects)
    return Generated(
        plans=plans,
        simulation=sim,
        stock=defects.stock,
        receipts=defects.receipts,
        materials=materials,
        defects=defects.log,
        manifest=manifest,
    )


def _manifest(plans: list[MaterialPlan], defects: Defects) -> dict:
    scenarios = [
        {
            "material_id": p.material_id,
            "plant": p.plant,
            "scenario": p.scenario,
            "expected_status": [s.value for s in SCENARIO_EXPECTED[p.scenario]],
        }
        for p in sorted(plans, key=lambda p: (p.scenario, p.plant, p.material_id))
        if p.scenario != "normal"
    ]
    log = defects.log
    return {
        "seed": SEED,
        "start_date": START_DATE.date().isoformat(),
        "end_date": END_DATE.date().isoformat(),
        "scenarios": scenarios,
        "normal_material_plants": [
            [p.material_id, p.plant] for p in plans if p.scenario == "normal"
        ],
        "clean_material_plants": [list(k) for k in defects.clean_material_plants],
        "defect_counts": {k: int(v) for k, v in log["defect"].value_counts().sort_index().items()},
        "defects": [
            r | {"date": r["date"].date().isoformat()} for r in log.to_dict(orient="records")
        ],
    }


EXCEL_DATE_FORMAT = "DD.MM.YYYY"
MAX_COLUMN_WIDTH = 40


def _to_excel_headers(frame: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    return frame.rename(columns={v: k for k, v in columns.items()})[list(columns)]


def write_workbook(generated: Generated, path: Path) -> None:
    """Write the three sheets with German headers, real dates and a frozen header row."""
    sheets = {
        SHEET_STOCK: _to_excel_headers(generated.stock, STOCK_COLUMNS),
        SHEET_RECEIPTS: _to_excel_headers(generated.receipts, RECEIPT_COLUMNS),
        SHEET_MATERIALS: _to_excel_headers(generated.materials, MATERIAL_COLUMNS),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes = "A2"
            for position, column in enumerate(frame.columns, start=1):
                letter = sheet.cell(row=1, column=position).column_letter
                if pd.api.types.is_datetime64_any_dtype(frame[column]):
                    # pandas' own date_format option is not applied by the openpyxl engine.
                    for (cell,) in sheet.iter_rows(min_row=2, min_col=position, max_col=position):
                        cell.number_format = EXCEL_DATE_FORMAT
                    width = len(EXCEL_DATE_FORMAT)
                else:
                    width = max(len(str(column)), frame[column].astype(str).str.len().max())
                sheet.column_dimensions[letter].width = min(width + 2, MAX_COLUMN_WIDTH)


def write_manifest(generated: Generated, path: Path) -> None:
    """Write the scenario manifest as stable, readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(generated.manifest, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def main() -> None:
    """Generate the sample workbook and the manifest at their paths from config."""
    generated = generate()
    write_workbook(generated, SAMPLE_WORKBOOK)
    write_manifest(generated, SCENARIO_MANIFEST)
    logging.getLogger(__name__).info(
        "Wrote %s (%d stock rows, %d receipts, %d materials) and %s",
        SAMPLE_WORKBOOK.name,
        len(generated.stock),
        len(generated.receipts),
        len(generated.materials),
        SCENARIO_MANIFEST.name,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
