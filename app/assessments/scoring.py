"""Overall score for the Digital Presence Assessment.

PLACEHOLDER METHODOLOGY (needs product-owner approval, see docs/architecture/decisions.md):
equal-weight mean of the component scores that COMPLETED. Components that failed or were
not available do not count; if none completed there is no overall score.
Change the rules → bump `Settings.assessment_methodology_version`.
"""

from __future__ import annotations

from collections.abc import Iterable


def overall_score(component_scores: Iterable[float | None]) -> float | None:
    scores = [float(s) for s in component_scores if s is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)
