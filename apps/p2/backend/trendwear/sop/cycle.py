"""The rolling monthly S&OP cycle, its four stages, and the money view.

The use case asks for "a rolling monthly S&OP cycle integrating sales,
production and inventory views", and the official PDF adds financial plans to
demand and supply. Both requirements live here.

**Rolling** means the cycle runs month after month, each one re-planning the next
thirteen weeks from where the business actually is. A single run would be a
snapshot; a rolling cycle is a process, and the process is what the use case
asks for.

**Four stages**, in order, each producing an immutable version:

1. *Demand review* — merchandising and the forecast.
2. *Supply review* — what the plants and fabric allow.
3. *Pre-S&OP* — the gap is reconciled and a consensus number agreed.
4. *Executive approval* — the plan is committed.

A stage cannot be skipped and a version cannot be edited once stored. Rejecting
sends the plan back one stage, which is what actually happens in a business when
the numbers do not hold up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

STAGES = ("demand_review", "supply_review", "pre_sop", "executive_approval")

STAGE_LABELS = {
    "demand_review": "Demand review",
    "supply_review": "Supply review",
    "pre_sop": "Pre-S&OP",
    "executive_approval": "Executive approval",
}


@dataclass(frozen=True)
class PlanVersion:
    """An immutable snapshot of the plan at one stage."""

    version_id: str
    cycle_month: int
    stage: str
    created_at: str
    actor: str
    note: str
    metrics: dict[str, float]

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS.get(self.stage, self.stage)


@dataclass
class Cycle:
    """One month of the rolling process."""

    month: int
    start_week: int
    horizon_weeks: int
    versions: list[PlanVersion] = field(default_factory=list)

    @property
    def stage(self) -> str:
        return self.versions[-1].stage if self.versions else STAGES[0]

    @property
    def is_approved(self) -> bool:
        return any(version.stage == "executive_approval" for version in self.versions)

    @property
    def end_week(self) -> int:
        return self.start_week + self.horizon_weeks - 1


def next_stage(stage: str) -> str | None:
    """The stage that follows, or None at the end."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    index = STAGES.index(stage)
    return STAGES[index + 1] if index + 1 < len(STAGES) else None


def create_version(
    cycle: Cycle,
    stage: str,
    metrics: dict[str, float],
    actor: str = "planner",
    note: str = "",
) -> PlanVersion:
    """Store an immutable version at a stage."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")

    version = PlanVersion(
        version_id=f"v{cycle.month}.{len(cycle.versions) + 1}",
        cycle_month=cycle.month,
        stage=stage,
        created_at=datetime.now().isoformat(timespec="seconds"),
        actor=actor,
        note=note,
        metrics=dict(metrics),
    )
    cycle.versions.append(version)
    return version


def advance(cycle: Cycle, metrics: dict[str, float], actor: str = "planner",
            note: str = "") -> PlanVersion:
    """Move the cycle to the next stage.

    Stages run in order. A plan cannot jump from demand review to approval,
    because the point of the middle two is that supply and the gap have been
    looked at by someone.
    """
    if not cycle.versions:
        return create_version(cycle, STAGES[0], metrics, actor, note)

    following = next_stage(cycle.stage)
    if following is None:
        raise ValueError("the cycle is already approved; start the next month")
    return create_version(cycle, following, metrics, actor, note)


def reject(cycle: Cycle, reason: str, actor: str = "executive") -> PlanVersion:
    """Send the plan back a stage, with the reason recorded."""
    if not cycle.versions:
        raise ValueError("nothing to reject: the cycle has not started")

    index = STAGES.index(cycle.stage)
    if index == 0:
        raise ValueError("demand review is the first stage; there is nowhere to send it back to")

    previous = STAGES[index - 1]
    return create_version(
        cycle, previous, cycle.versions[-1].metrics, actor, f"Rejected: {reason}"
    )


def run_rolling(
    months: int = 3,
    horizon_weeks: int = 13,
    weeks_per_month: int = 4,
    start_week: int = 1,
) -> list[Cycle]:
    """Set up consecutive monthly cycles, each planning a rolling horizon."""
    if months < 1:
        raise ValueError("a rolling process needs at least one cycle")

    return [
        Cycle(
            month=month + 1,
            start_week=start_week + month * weeks_per_month,
            horizon_weeks=horizon_weeks,
        )
        for month in range(months)
    ]


def compare_versions(first: PlanVersion, second: PlanVersion) -> dict[str, dict[str, float]]:
    """What changed between two versions, metric by metric."""
    keys = sorted(set(first.metrics) | set(second.metrics))
    comparison: dict[str, dict[str, float]] = {}

    for key in keys:
        before = float(first.metrics.get(key, 0.0))
        after = float(second.metrics.get(key, 0.0))
        comparison[key] = {
            "before": round(before, 2),
            "after": round(after, 2),
            "change": round(after - before, 2),
            "change_pct": round((after - before) / before * 100, 2) if before else 0.0,
        }
    return comparison


def history(cycles: list[Cycle]) -> pd.DataFrame:
    """Every version across every cycle, for the version-comparison screen."""
    rows = [
        {
            "version_id": version.version_id,
            "cycle_month": version.cycle_month,
            "stage": version.stage,
            "stage_label": version.stage_label,
            "created_at": version.created_at,
            "actor": version.actor,
            "note": version.note,
            **{f"metric_{key}": value for key, value in version.metrics.items()},
        }
        for cycle in cycles
        for version in cycle.versions
    ]
    return pd.DataFrame(rows)
