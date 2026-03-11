from __future__ import annotations

from collections.abc import Sequence

from ..configs.models import GroupingConfig
from ..contracts.records import GroupMembershipRecord, GroupRecord, UnitRecord
from ..enums import GroupingStrategy


def plan_fixed_size_groups(
    units: Sequence[UnitRecord],
    grouping: GroupingConfig,
    *,
    group_id_prefix: str = "group",
) -> list[GroupRecord]:
    if grouping.strategy is not GroupingStrategy.FIXED_SIZE:
        msg = "plan_fixed_size_groups requires a fixed-size grouping strategy"
        raise ValueError(msg)

    if not units:
        return []

    groups: list[GroupRecord] = []
    for group_index, start in enumerate(range(0, len(units), grouping.group_size)):
        group_units = units[start : start + grouping.group_size]
        groups.append(
            GroupRecord(
                group_id=f"{group_id_prefix}-{group_index:06d}",
                unit_ids=[unit.unit_id for unit in group_units],
                group_index=group_index,
                metadata={
                    "unit_count": len(group_units),
                    "group_size": grouping.group_size,
                    "start_index": start,
                },
            )
        )

    if grouping.max_groups is not None and len(groups) > grouping.max_groups:
        msg = (
            f"fixed-size grouping would create {len(groups)} groups, "
            f"which exceeds max_groups={grouping.max_groups}"
        )
        raise ValueError(msg)

    return groups


def build_group_memberships(groups: Sequence[GroupRecord]) -> list[GroupMembershipRecord]:
    memberships: list[GroupMembershipRecord] = []
    for group in groups:
        for member_index, unit_id in enumerate(group.unit_ids):
            memberships.append(
                GroupMembershipRecord(
                    group_id=group.group_id,
                    unit_id=unit_id,
                    member_index=member_index,
                    metadata={"group_index": group.group_index},
                )
            )
    return memberships


def membership_map(groups: Sequence[GroupRecord]) -> dict[str, tuple[str, ...]]:
    return {group.group_id: tuple(group.unit_ids) for group in groups}
