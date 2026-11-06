"""Cell encoding and cohort predicate matching (first match wins)."""
from __future__ import annotations

import json
from typing import Mapping, Sequence

FEATURES = ("lang", "city_tier", "age_band", "value_band")
DEFAULT_COHORT = "default"
VOCAB_META_KEY = "feature_vocab"


class FeatureVocab:
    """Interns feature values per feature; a cell is four 8-bit codes packed in an int."""

    def __init__(self, tables: Mapping[str, Sequence[str]] | None = None) -> None:
        self._values: dict[str, list[str]] = {f: [] for f in FEATURES}
        self._index: dict[str, dict[str, int]] = {f: {} for f in FEATURES}
        self.dirty = False
        for feature, values in (tables or {}).items():
            for value in values:
                self._code(feature, value)
        self.dirty = False

    def _code(self, feature: str, value: str) -> int:
        idx = self._index[feature]
        code = idx.get(value)
        if code is None:
            code = len(self._values[feature])
            if code > 255:
                raise ValueError(f"too many distinct values for feature {feature}")
            self._values[feature].append(value)
            idx[value] = code
            self.dirty = True
        return code

    def encode(self, features: Mapping[str, str]) -> int:
        cell = 0
        for feature in FEATURES:
            cell = (cell << 8) | self._code(feature, str(features[feature]))
        return cell

    def decode(self, cell: int) -> dict[str, str]:
        out: dict[str, str] = {}
        for feature in reversed(FEATURES):
            out[feature] = self._values[feature][cell & 0xFF]
            cell >>= 8
        return {f: out[f] for f in FEATURES}

    def dump(self) -> str:
        return json.dumps(self._values)

    @classmethod
    def load(cls, text: str | None) -> "FeatureVocab":
        return cls(json.loads(text)) if text else cls()


def matches(where: Mapping[str, Sequence[str]], features: Mapping[str, str]) -> bool:
    """AND across features, OR within a feature's list. Empty ``where`` matches all."""
    return all(features.get(feature) in allowed for feature, allowed in where.items())


def assign_cohort(cohorts: Sequence[Mapping], features: Mapping[str, str]) -> str:
    """First matching cohort in order, otherwise ``default``."""
    for cohort in cohorts:
        if matches(cohort.get("where", {}), features):
            return cohort["id"]
    return DEFAULT_COHORT


class CohortChecker:
    """Compares our cohort assignment with the event's ``cohort_id`` (CONTEXT C2 self-check)."""

    def __init__(self, vocab: FeatureVocab) -> None:
        self._vocab = vocab
        self._memo: dict[tuple[str, int, int], str] = {}

    def expected(self, workflow_id: str, version: int, cohorts: Sequence[Mapping],
                 cell: int) -> str:
        key = (workflow_id, version, cell)
        got = self._memo.get(key)
        if got is None:
            got = assign_cohort(cohorts, self._vocab.decode(cell))
            self._memo[key] = got
        return got
