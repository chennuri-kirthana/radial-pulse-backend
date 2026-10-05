"""The contract between the platform and assessment ENGINES (owned by domain teams).

An engine is a plain Python object that turns clinic facts into ONE assessment component:

    class WebsiteEngine:
        name = "website-engine"; version = "1.0.0"
        component = AssessmentComponentKey.WEBSITE
        def assess(self, data: EngineInput) -> ComponentResult: ...

Rules for engines (enforced here, not trusted):
* Engines never touch the database, S3 or the platform API. They get `EngineInput`,
  return `ComponentResult`; the platform validates and stores it (as a service identity).
* Output is validated with the models below (bounded sizes, evidence required for
  high-priority findings) before anything is saved.
* Engines are discovered via the Python entry-point group ``radial_pulse.assessment_engines``
  in the worker image, so a domain team ships an engine as its own package.
* Crawling (httpx first, Playwright only for JS-heavy sites) and external providers
  (GBP/social/directory APIs behind their own Provider interfaces) live INSIDE engines.
"""

from __future__ import annotations

import logging
from datetime import datetime
from importlib.metadata import entry_points
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AssessmentComponentKey,
    ComponentStatus,
    FindingPriority,
    PresencePlatform,
)

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "radial_pulse.assessment_engines"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PresenceHint(_Strict):
    platform: PresencePlatform
    url: str
    verified: bool


class EngineInput(_Strict):
    """Business facts only — no personal data, no credentials."""

    clinic_id: UUID
    clinic_name: str
    city: str | None
    state: str | None
    country: str
    website_url: str | None
    services: list[str] = Field(default_factory=list)
    presence: list[PresenceHint] = Field(default_factory=list)


class Evidence(_Strict):
    source_url: str | None = Field(default=None, max_length=1000)
    #: Short quote/extract that shows the problem. Capped: never store whole pages.
    excerpt: str | None = Field(default=None, max_length=1000)
    provider: str = Field(max_length=64)
    observed_at: datetime


class FindingResult(_Strict):
    code: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$", max_length=96)
    title: str = Field(max_length=200)
    priority: FindingPriority
    description: str | None = Field(default=None, max_length=4000)
    recommendation: str | None = Field(default=None, max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _grounded(self) -> FindingResult:
        if self.priority in (FindingPriority.CRITICAL, FindingPriority.HIGH) and not self.evidence:
            raise ValueError("critical/high findings must include at least one evidence item")
        return self


class DiscoveredProfile(_Strict):
    """A finder engine found the clinic on a platform (stored as UNVERIFIED)."""

    platform: PresencePlatform
    url: str = Field(max_length=1000)
    external_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list, max_length=5)


class ComponentResult(_Strict):
    status: ComponentStatus
    score: float | None = Field(default=None, ge=0, le=100)
    summary: str | None = Field(default=None, max_length=2000)
    status_reason: str | None = Field(default=None, max_length=200)
    findings: list[FindingResult] = Field(default_factory=list, max_length=200)
    discovered_profiles: list[DiscoveredProfile] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _consistent(self) -> ComponentResult:
        if self.status is ComponentStatus.COMPLETED and self.score is None:
            raise ValueError("a completed component needs a score")
        if self.status is ComponentStatus.PENDING:
            raise ValueError("engines must return a final status")
        codes = [f.code for f in self.findings]
        if len(codes) != len(set(codes)):
            # Same problem = same code, once per section (the database has the same rule).
            raise ValueError("each finding code may appear only once per component")
        return self


class AssessmentEngine(Protocol):
    name: str
    version: str
    component: AssessmentComponentKey

    def assess(self, data: EngineInput) -> ComponentResult: ...


class EngineRegistry:
    """One engine per component key. Empty by default — no fake engines."""

    def __init__(self) -> None:
        self._engines: dict[AssessmentComponentKey, AssessmentEngine] = {}

    def register(self, engine: AssessmentEngine) -> None:
        if engine.component in self._engines:
            raise ValueError(f"an engine is already registered for {engine.component.value}")
        self._engines[engine.component] = engine

    def get(self, key: AssessmentComponentKey) -> AssessmentEngine | None:
        return self._engines.get(key)

    def keys(self) -> list[AssessmentComponentKey]:
        return list(self._engines)

    @classmethod
    def from_entry_points(cls) -> EngineRegistry:
        registry = cls()
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            factory = ep.load()
            registry.register(factory())
            logger.info("assessment engine loaded", extra={"engine_entry_point": ep.name})
        return registry
