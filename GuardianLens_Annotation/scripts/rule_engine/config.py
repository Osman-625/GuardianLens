from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_SEVERITIES = {"critical", "strong", "medium", "weak", "trust"}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    description: str
    category: str
    severity: str
    weight: float
    required_fields: list[str] = field(default_factory=list)
    matching_method: str = "keyword_group"
    evidence_to_record: str = "matched_phrase"
    source_reference: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"{self.rule_id}: invalid severity {self.severity!r}, "
                f"must be one of {sorted(VALID_SEVERITIES)}"
            )
        if not self.rule_id:
            raise ValueError("rule_id must not be empty")


@dataclass(frozen=True)
class ThresholdConfig:
    critical_rule_min: int
    strong_risk_score_min: float
    strong_rule_count_min: int
    suspicious_risk_score_min: float
    legitimate_risk_score_max: float
    legitimate_trust_score_min: float


def load_rules(path: str | Path) -> list[Rule]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for entry in raw:
        rule = Rule(**entry)
        if rule.rule_id in seen_ids:
            raise ValueError(f"duplicate rule_id: {rule.rule_id}")
        seen_ids.add(rule.rule_id)
        rules.append(rule)
    return rules


def load_thresholds(path: str | Path) -> ThresholdConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ThresholdConfig(**raw)
