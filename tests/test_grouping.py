from __future__ import annotations

import pytest

from llm_batch_annotate import (
    GroupMembershipRecord,
    GroupingConfig,
    materialize_units,
    membership_map,
    plan_fixed_size_groups,
    build_group_memberships,
)


def make_units(count: int) -> list:
    rows = [{"query_id": f"unit-{index:02d}", "text": f"row-{index}"} for index in range(count)]
    return materialize_units(rows, row_id_column="query_id")


def test_plan_fixed_size_groups_preserves_order_and_stable_ids() -> None:
    groups = plan_fixed_size_groups(make_units(5), GroupingConfig(group_size=2))

    assert [group.group_id for group in groups] == ["group-000000", "group-000001", "group-000002"]
    assert [group.unit_ids for group in groups] == [
        ["unit-00", "unit-01"],
        ["unit-02", "unit-03"],
        ["unit-04"],
    ]
    assert groups[0].metadata["unit_count"] == 2


def test_plan_fixed_size_groups_honors_max_groups() -> None:
    with pytest.raises(ValueError, match="exceeds max_groups"):
        plan_fixed_size_groups(make_units(5), GroupingConfig(group_size=2, max_groups=2))


def test_build_group_memberships_creates_explicit_membership_rows() -> None:
    groups = plan_fixed_size_groups(make_units(3), GroupingConfig(group_size=2))

    memberships = build_group_memberships(groups)

    assert memberships == [
        GroupMembershipRecord(group_id="group-000000", unit_id="unit-00", member_index=0, metadata={"group_index": 0}),
        GroupMembershipRecord(group_id="group-000000", unit_id="unit-01", member_index=1, metadata={"group_index": 0}),
        GroupMembershipRecord(group_id="group-000001", unit_id="unit-02", member_index=0, metadata={"group_index": 1}),
    ]


def test_membership_map_returns_ordered_membership_by_group() -> None:
    groups = plan_fixed_size_groups(make_units(4), GroupingConfig(group_size=3))

    assert membership_map(groups) == {
        "group-000000": ("unit-00", "unit-01", "unit-02"),
        "group-000001": ("unit-03",),
    }
