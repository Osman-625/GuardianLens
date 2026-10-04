from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ComponentPrediction:
    probability: float | None
    available: bool
    feature_values: dict[str, float]
    metadata: dict[str, str]


class VisualPipeline(Protocol):
    version: str

    def predict(self, images: list[bytes], text: str) -> ComponentPrediction: ...


class TextualPipeline(Protocol):
    version: str

    def predict(self, text: str) -> ComponentPrediction: ...


class BehaviouralPipeline(Protocol):
    version: str

    def predict(self, features: dict[str, float | None]) -> ComponentPrediction: ...


class FusionPipeline(Protocol):
    version: str

    def predict(
        self,
        component_probabilities: dict[str, float | None],
        availability: dict[str, bool],
    ) -> float: ...
