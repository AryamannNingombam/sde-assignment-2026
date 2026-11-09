"""The one shared cohort object (C2).

A segment is the full feature tuple 'lang|tier|age|value'. Every cohort is a union of segments, so detection,
experiments, impact counts and the supervisor view all compute from the same `agg` rows with the same rule.
Matching mirrors the simulator: ordered list, first match wins, otherwise 'default'.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FEATURE_ORDER = ("lang", "city_tier", "age_band", "value_band")
DEFAULT = "default"


def segment_of(features: dict) -> str:
    return "|".join(str(features[f]) for f in FEATURE_ORDER)


def features_of(segment: str) -> dict[str, str]:
    return dict(zip(FEATURE_ORDER, segment.split("|")))


@dataclass(frozen=True)
class Cohort:
    id: str
    where: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def matches(self, features: dict) -> bool:
        """AND across features, OR within one feature's list."""
        return all(str(features.get(f)) in vals for f, vals in self.where.items())

    def to_config(self) -> dict:
        return {"id": self.id, "where": {f: list(v) for f, v in self.where.items()}}


def from_config(cfg: dict) -> list[Cohort]:
    return [Cohort(c["id"], {f: tuple(v) for f, v in (c.get("where") or {}).items()}) for c in cfg.get("cohorts", [])]


def assign(cohorts: list[Cohort], features: dict) -> str:
    for c in cohorts:
        if c.matches(features):
            return c.id
    return DEFAULT


def segments_in(cohorts: list[Cohort], cohort_id: str, segments: list[str]) -> list[str]:
    """Segments whose leads land in `cohort_id` under this ordered cohort list."""
    return [s for s in segments if assign(cohorts, features_of(s)) == cohort_id]
