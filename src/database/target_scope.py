"""Conservative target-scope semantics for delivery experiments.

The legacy ``cell_type`` field mixed three different scientific claims:
intentional targeting, organ-level delivery, and cells observed after delivery.
This module keeps those claims separate and abstains when the wording does not
support one of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetScope:
    intended_target_cell: str | None = None
    target_or_recipient_organ: str | None = None
    observed_transfected_cell: str | None = None


@dataclass(frozen=True)
class TargetStatementCandidate(TargetScope):
    ambiguous: bool = False


_CELLS = {
    "hepatocyte": re.compile(r"\bhepatocytes?\b", re.IGNORECASE),
    "kupffer_cell": re.compile(r"\bkupffer cells?\b", re.IGNORECASE),
    "lsec": re.compile(
        r"\b(?:lsecs?|liver sinusoidal endothelial cells?)\b", re.IGNORECASE
    ),
    "hsc": re.compile(
        r"\b(?:hscs?|hepatic stellate cells?)\b", re.IGNORECASE
    ),
}
_ORGANS = {
    "liver": re.compile(r"\blivers?\b|\bhepatic\b", re.IGNORECASE),
    "lung": re.compile(r"\blungs?\b|\bpulmonary\b", re.IGNORECASE),
    "spleen": re.compile(r"\bspleens?\b|\bsplenic\b", re.IGNORECASE),
    "kidney": re.compile(r"\bkidneys?\b|\brenal\b", re.IGNORECASE),
    "uterus": re.compile(r"\buterus\b|\buterine\b", re.IGNORECASE),
}
_INTENT_PATTERN = re.compile(
    r"\b(?:target(?:ed|ing)?|designed|directed|selective(?:ly)?|"
    r"ligand[- ]directed|intended)\b",
    re.IGNORECASE,
)
_OBSERVED_PATTERN = re.compile(
    r"\b(?:transfection|transfected|expression|expressed|uptake|staining|"
    r"immunostaining|colocalization|positive cells?|fluorescen(?:ce|t))\b",
    re.IGNORECASE,
)
_DESTINATION_PATTERN = re.compile(
    r"\b(?:deliver(?:ed|y|ing)?|target(?:ed|ing)?|recipient|accumulat(?:e|ed|ion)|"
    r"biodistribution|restrict(?:ed|ion)|scan(?:ned|ning)?|imaging|microscopy|"
    r"transfection|transfected|expression|expressed|uptake|staining|"
    r"immunostaining|colocalization)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_COMPARISON = re.compile(
    r"\bpreviously demonstrated\b.*\bhydrody(?:namic|.{0,160}?namic) injection\b",
    re.IGNORECASE | re.DOTALL,
)


def _first_match(patterns: dict[str, re.Pattern[str]], text: str) -> str | None:
    return next((name for name, pattern in patterns.items() if pattern.search(text)), None)


def classify_target_statement(text: str) -> TargetStatementCandidate:
    """Classify only claims directly supported by one target statement."""

    if _OUT_OF_SCOPE_COMPARISON.search(text):
        return TargetStatementCandidate(ambiguous=True)

    cell = _first_match(_CELLS, text)
    organ = (
        _first_match(_ORGANS, text)
        if _DESTINATION_PATTERN.search(text)
        else None
    )
    intended = cell if cell and _INTENT_PATTERN.search(text) else None
    observed = (
        cell
        if cell and intended is None and _OBSERVED_PATTERN.search(text)
        else None
    )
    return TargetStatementCandidate(
        intended_target_cell=intended,
        target_or_recipient_organ=organ,
        observed_transfected_cell=observed,
        ambiguous=not any((intended, organ, observed)),
    )


def has_supported_delivery_destination(
    connection, experiment_id: int
) -> bool:
    """Return whether an arm records an intended cell or recipient organ.

    Legacy columns remain stored for display and provenance, but they are not
    readiness inputs. An observed cell is deliberately excluded because
    observation does not prove intent or scope.
    """

    row = connection.execute(
        """SELECT intended_target_cell,target_or_recipient_organ
           FROM experiment WHERE experiment_id=?""",
        (experiment_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown experiment_id: {experiment_id}")
    placeholders = {"", "na", "n/a", "none", "not_reported", "unknown"}
    return any(
        str(value or "").strip().casefold().replace(" ", "_") not in placeholders
        for value in row
    )
