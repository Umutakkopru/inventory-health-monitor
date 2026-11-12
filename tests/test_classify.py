"""Tests for the ABC and XYZ classification (CLAUDE.md section 6.4)."""

import numpy as np
import pandas as pd
import pytest

from inventory_monitor.classify import assign_abc, assign_xyz
from inventory_monitor.config import DEFAULT_THRESHOLDS, Thresholds


def _abc(values: list[float], plant: str = "1010", ids: list[str] | None = None) -> list[str]:
    frame = pd.DataFrame(
        {
            "material_id": ids or [f"{i:08d}" for i in range(1, len(values) + 1)],
            "plant": plant,
            "annual_consumption_value": values,
        }
    )
    return assign_abc(frame, DEFAULT_THRESHOLDS)["abc"].tolist()


# --- ABC -----------------------------------------------------------------------------------


def test_abc_boundaries_belong_to_the_lower_class_when_reached_exactly() -> None:
    # Share before each item: 0.00, 0.50, 0.80, 0.95.
    # 0.80 is not below the A cutoff 0.80 -> B; 0.95 is not below the B cutoff 0.95 -> C.
    assert _abc([50, 30, 15, 5]) == ["A", "A", "B", "C"]


def test_abc_item_crossing_a_boundary_belongs_to_the_higher_class() -> None:
    # Share before: 0.00, 0.70, 0.90. The second item takes the total from 70 % to 90 %,
    # crossing 80 %, and is still A. The third crosses 95 % and is still B.
    assert _abc([70, 20, 10]) == ["A", "A", "B"]


def test_abc_result_follows_the_input_order() -> None:
    # Same values as above, shuffled: the classes stay with their items.
    assert _abc([10, 70, 20]) == ["B", "A", "A"]


def test_abc_ties_are_broken_by_material_number() -> None:
    # 70, then three items of 10. Shares before: 0.70, 0.80, 0.90 in material order,
    # so 00000002 is A and 00000003 and 00000004 are B.
    ids = ["00000004", "00000003", "00000002", "00000001"]
    assert _abc([10, 10, 10, 70], ids=ids) == ["B", "B", "A", "A"]


def test_abc_zero_value_is_c() -> None:
    assert _abc([100, 0]) == ["A", "C"]
    assert _abc([0, 0]) == ["C", "C"]  # a plant without any consumption


def test_abc_missing_value_counts_as_zero() -> None:
    assert _abc([100, np.nan]) == ["A", "C"]


def test_abc_single_material_in_a_plant_is_a() -> None:
    assert _abc([5]) == ["A"]


def test_abc_is_ranked_within_each_plant() -> None:
    frame = pd.DataFrame(
        {
            "material_id": ["00000001", "00000002", "00000001", "00000002"],
            "plant": ["1010", "1010", "1020", "1020"],
            "annual_consumption_value": [1000.0, 1.0, 2.0, 1.0],
        }
    )
    # In 1020 the value 2 is small next to 1000 in 1010, but it is A within its own plant:
    # 1020 shares before: 0.00 (A), 0.67 (A).
    assert assign_abc(frame, DEFAULT_THRESHOLDS)["abc"].tolist() == ["A", "C", "A", "A"]


def test_abc_float_sums_do_not_shift_a_boundary() -> None:
    # Share before the third item: (0.9 + 0.3) / 1.5 = 0.8 exactly, but in floating point
    # it comes out as 0.7999999999999999. It must count as 0.8 (B), not as below 0.8 (A).
    assert (0.9 + 0.3) / (0.9 + 0.3 + 0.3) < 0.8
    assert _abc([0.9, 0.3, 0.3]) == ["A", "A", "B"]


def test_abc_uses_the_cutoffs_from_thresholds() -> None:
    frame = pd.DataFrame(
        {"material_id": ["1", "2"], "plant": "1010", "annual_consumption_value": [60.0, 40.0]}
    )
    strict = Thresholds(abc_cutoff_a=0.5, abc_cutoff_b=0.55)
    # Shares before: 0.0 (A), 0.6 (not below 0.55 -> C)
    assert assign_abc(frame, strict)["abc"].tolist() == ["A", "C"]


def test_abc_does_not_mutate_the_input() -> None:
    frame = pd.DataFrame(
        {"material_id": ["1", "2"], "plant": "1010", "annual_consumption_value": [1.0, 2.0]}
    )
    before = frame.copy()
    assign_abc(frame, DEFAULT_THRESHOLDS)
    pd.testing.assert_frame_equal(frame, before)


# --- XYZ -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cv", "expected"),
    [
        (0.0, "X"),
        (0.49, "X"),
        (0.5, "Y"),  # "Y from 0.5 to 1.0": the lower boundary is Y
        (1.0, "Y"),  # and so is the upper one
        (1.01, "Z"),
        (np.nan, "Z"),  # no usable demand history
    ],
)
def test_xyz_boundaries(cv: float, expected: str) -> None:
    frame = pd.DataFrame({"cv_weekly": [cv]})
    assert assign_xyz(frame, DEFAULT_THRESHOLDS)["xyz"].tolist() == [expected]
