"""
generator/strategy_spec.py — Pydantic model for LLM-generated strategy specs.

The LLM outputs a JSON object conforming to this schema. The deterministic
generator then compiles it into a Hypothesis SearchStrategy.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class StrategyConstraint(BaseModel):
    """A constraint on generated input."""

    type: Literal[
        "max_depth",
        "max_size",
        "max_nesting",
        "entity_whitelist",
        "forbid_control_chars",
        "valid_utf8",
    ]
    value: int | str | list[str] | bool


class StrategyObjective(BaseModel):
    """What the fuzzer should aim to cover in this iteration."""

    name: str  # e.g. "CDATA", "entity_references", "deep_nesting"
    priority: int = Field(default=1, ge=1, le=5)


class StrategyMutation(BaseModel):
    """Structural mutations to apply when generating inputs."""

    name: str  # e.g. "increase_nesting", "inject_entities"
    probability: float = Field(default=0.2, ge=0.0, le=1.0)


class StrategySpec(BaseModel):
    """
    Structured strategy specification produced by the LLM.
    The deterministic generator compiles this into a Hypothesis strategy.
    """

    target: str = "mxmlLoadString"
    objectives: list[StrategyObjective] = Field(default_factory=list)
    constraints: list[StrategyConstraint] = Field(default_factory=list)
    mutations: list[StrategyMutation] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "target": "mxmlLoadString",
                "objectives": [
                    {"name": "CDATA", "priority": 3},
                    {"name": "deep_nesting", "priority": 4},
                    {"name": "entity_references", "priority": 2},
                ],
                "constraints": [
                    {"type": "max_depth", "value": 40},
                    {"type": "max_size", "value": 65536},
                    {"type": "entity_whitelist", "value": ["amp", "lt", "gt", "quot", "apos"]},
                    {"type": "forbid_control_chars", "value": True},
                ],
                "mutations": [
                    {"name": "increase_nesting", "probability": 0.3},
                    {"name": "inject_entities", "probability": 0.2},
                    {"name": "duplicate_attributes", "probability": 0.15},
                ],
            }
        }
