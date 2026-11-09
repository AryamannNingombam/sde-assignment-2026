"""The one cohort definition used by detection, experiments and the supervisor view (memo 05).

A cohort's id is derived from its predicate, so the same people always get the same id whichever
part of the system names them. Cohorts a supervisor creates keep the id the supervisor gave them.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

DEFAULT = "default"
FEATURES = ("lang", "city_tier", "age_band", "value_band")


@dataclass(frozen=True)
class Cohort:
    id: str
    where: tuple[tuple[str, tuple[str, ...]], ...]

    @classmethod
    def build(cls, where: dict, cohort_id: str | None = None) -> "Cohort":
        norm = tuple(sorted((k, tuple(sorted(str(x) for x in v))) for k, v in where.items()))
        return cls(cohort_id or cls.slug(norm), norm)

    @staticmethod
    def slug(norm) -> str:
        parts = []
        for key, vals in norm:
            parts.append(key + "_" + "_".join(re.sub(r"[^0-9a-zA-Z]+", "p", v) for v in vals))
        return "c_" + "__".join(parts)

    def matches(self, features: dict) -> bool:
        return all(features.get(k) in vals for k, vals in self.where)

    def where_dict(self) -> dict:
        return {k: list(vals) for k, vals in self.where}

    def describe(self) -> str:
        return " and ".join(f"{k} in {'/'.join(vals)}" for k, vals in self.where) or "everyone"

    @property
    def specificity(self) -> int:
        return len(self.where)


def from_config(config: dict) -> list[Cohort]:
    return [Cohort.build(c["where"], c["id"]) for c in config.get("cohorts", [])]


def assign(cohorts: list[Cohort], features: dict) -> str:
    """Same rule as the dialler: first match wins, otherwise default."""
    for c in cohorts:
        if c.matches(features):
            return c.id
    return DEFAULT


def candidate_slices(segments: dict[int, dict]) -> list[Cohort]:
    """Every one- and two-feature predicate seen in the data.

    Stops at two features: three-way slices fragment traffic below the minimum cohort size on
    everything except the largest workflows.
    """
    values: dict[str, set] = {f: set() for f in FEATURES}
    for feats in segments.values():
        for f in FEATURES:
            if f in feats:
                values[f].add(feats[f])
    out = [Cohort.build({f: [v]}) for f in FEATURES for v in sorted(values[f])]
    for a, b in itertools.combinations(FEATURES, 2):
        for va, vb in itertools.product(sorted(values[a]), sorted(values[b])):
            out.append(Cohort.build({a: [va], b: [vb]}))
    return out
