"""Strict request and response schemas for anomaly inference."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from anomaly_config import FEATURE_NAMES


class FeatureVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_mean: float
    current_std: float
    current_imbalance: float
    voltage_mean: float
    voltage_imbalance: float
    vibration_rms: float
    vibration_magnitude_std: float
    temperature_delta: float
    temperature_rate: float

    @model_validator(mode="before")
    @classmethod
    def require_finite_json_numbers(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for name in FEATURE_NAMES:
                if name in value:
                    item = value[name]
                    try:
                        finite = math.isfinite(float(item))
                    except (OverflowError, TypeError, ValueError):
                        finite = False
                    if isinstance(item, bool) or not isinstance(item, (int, float)) or not finite:
                        raise ValueError("Every approved feature must be a finite JSON number.")
        return value

    def as_feature_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in FEATURE_NAMES}


class AnomalyScoreData(BaseModel):
    anomaly_score: float
    anomaly_status: str
    model_name: str
    model_version: str
    features_used: list[str]


class AnomalyScoreResponse(BaseModel):
    success: bool
    data: AnomalyScoreData
