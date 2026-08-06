"""Fictional, immutable state for the human-review interface prototype."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Mapping


FieldStatus = Literal[
    "verified", "needs_confirmation", "missing", "conflict", "not_reported"
]
ReviewAction = Literal["accept", "correct", "not_reported", "unresolved"]


@dataclass(frozen=True)
class DemoEvidence:
    excerpt: str
    location: str
    modality: str
    confidence: str


@dataclass(frozen=True)
class DemoField:
    label: str
    value: str
    status: FieldStatus
    evidence: tuple[DemoEvidence, ...] = ()
    required_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemoArm:
    arm_id: str
    paper_id: str
    label: str
    primary_reason: str
    fields: Mapping[str, DemoField]


@dataclass(frozen=True)
class DemoPaper:
    paper_id: str
    title: str
    citation: str
    doi: str
    pmid: str
    pmcid: str
    doi_url: str
    pubmed_url: str
    pdf_url: str
    html_url: str
    library_url: str
    arms: tuple[DemoArm, ...]
    is_fictional: bool = True


@dataclass(frozen=True)
class EligibilityPreview:
    nearest_neighbor_eligible: bool
    comet_eligible: bool
    nearest_neighbor_reasons: tuple[str, ...] = field(default_factory=tuple)
    comet_reasons: tuple[str, ...] = field(default_factory=tuple)


def _evidence(excerpt: str, location: str) -> tuple[DemoEvidence, ...]:
    return (
        DemoEvidence(
            excerpt=excerpt,
            location=location,
            modality="Mock full-text HTML",
            confidence="Demo only",
        ),
    )


def _field(
    label: str,
    value: str,
    status: FieldStatus,
    excerpt: str = "",
    location: str = "No mock excerpt attached",
    required_for: tuple[str, ...] = (),
) -> DemoField:
    return DemoField(
        label=label,
        value=value,
        status=status,
        evidence=_evidence(excerpt, location) if excerpt else (),
        required_for=required_for,
    )


def _base_fields() -> dict[str, DemoField]:
    return {
        "formulation": _field("LNP formulation", "Demo-LNP-7", "verified", "Demo-LNP-7 contained four lipid components.", "Methods · paragraph 12", ("nearest_neighbor", "comet")),
        "lnp_ratio": _field("LNP formulation ratio", "50:10:38.5:1.5 mol%", "verified", "Lipids were mixed at 50:10:38.5:1.5 mol%.", "Methods · table 1", ("nearest_neighbor", "comet")),
        "target_cell": _field("Target cell", "Hepatocyte", "verified", "Reporter expression was quantified in hepatocytes.", "Results · paragraph 4", ("nearest_neighbor", "comet")),
        "delivery_cell": _field("Delivery cell", "Hepatocyte", "verified", "Reporter expression was quantified in hepatocytes.", "Results · paragraph 4", ("nearest_neighbor",)),
        "species": _field("Species", "Mus musculus", "verified", "Female mice were dosed intravenously.", "Methods · animal study", ("nearest_neighbor", "comet")),
        "model": _field("Biological model", "Healthy mouse", "verified", "Healthy animals were randomized across treatment groups.", "Methods · animal study", ("nearest_neighbor",)),
        "delivery_model": _field("Delivery model", "In vivo", "verified", "Animals received a single intravenous injection.", "Methods · dosing", ("nearest_neighbor", "comet")),
        "route": _field("Administration route", "Intravenous", "verified", "Animals received a single intravenous injection.", "Methods · dosing", ("comet",)),
        "payload": _field("Payload", "Mock reporter mRNA", "verified", "Particles encapsulated a reporter mRNA payload.", "Methods · formulation", ("nearest_neighbor", "comet")),
        "dose": _field("Dose", "0.5", "verified", "A dose of 0.5 mg/kg was administered.", "Methods · dosing", ("nearest_neighbor", "comet")),
        "dose_unit": _field("Dose unit", "mg/kg", "verified", "A dose of 0.5 mg/kg was administered.", "Methods · dosing", ("nearest_neighbor", "comet")),
        "assay": _field("Assay", "Flow cytometry", "verified", "Cell-associated fluorescence was measured by flow cytometry.", "Results · assay", ("comet",)),
        "timepoint": _field("Timepoint", "24 h", "verified", "Tissues were collected 24 h after dosing.", "Methods · tissue collection", ("comet",)),
        "outcome": _field("Outcome", "Reporter-positive cells", "verified", "Reporter-positive hepatocytes increased after treatment.", "Results · figure 3", ("nearest_neighbor", "comet")),
        "outcome_value": _field("Outcome value", "42", "verified", "Reporter-positive hepatocytes reached 42 percent.", "Results · figure 3", ("comet",)),
        "outcome_unit": _field("Outcome unit", "% positive cells", "verified", "Reporter-positive hepatocytes reached 42 percent.", "Results · figure 3", ("comet",)),
        "normalization": _field("Normalization", "Within viable hepatocytes", "verified", "Values were normalized to viable hepatocytes.", "Figure 3 caption", ("comet",)),
    }


def demo_papers() -> tuple[DemoPaper, ...]:
    """Return three independent fictional review scenarios."""

    confirmation = _base_fields()
    confirmation["target_cell"] = _field(
        "Target cell", "Liver parenchymal cells", "needs_confirmation",
        "Signal was strongest in liver parenchymal cells.", "Results · paragraph 8",
        ("nearest_neighbor", "comet"),
    )
    missing = _base_fields()
    missing["dose"] = _field(
        "Dose", "Not extracted", "missing", "", "No matching excerpt", ("nearest_neighbor", "comet")
    )
    missing["dose_unit"] = _field(
        "Dose unit", "mg/kg", "needs_confirmation", "Animals were dosed in mg/kg.", "Methods · dosing", ("nearest_neighbor", "comet")
    )
    conflict = _base_fields()
    conflict["outcome"] = DemoField(
        label="Outcome",
        value="Reporter expression / uptake",
        status="conflict",
        evidence=(
            DemoEvidence("Reporter expression increased in the treatment group.", "Results · paragraph 6", "Mock HTML", "Demo only"),
            DemoEvidence("Fluorescent particle uptake was quantified after 6 h.", "Figure 2 caption", "Mock figure caption", "Demo only"),
        ),
        required_for=("nearest_neighbor", "comet"),
    )

    scenarios = (
        ("DEMO-001", "A fictional LNP targeting study", "Target cell needs confirmation", confirmation),
        ("DEMO-002", "A fictional dose-response study", "Dose missing", missing),
        ("DEMO-003", "A fictional biodistribution study", "Outcome link conflict", conflict),
    )
    papers = []
    for index, (paper_id, title, reason, fields) in enumerate(scenarios, 1):
        arm = DemoArm(f"{paper_id}-A1", paper_id, f"Mock experimental arm {index}", reason, fields)
        papers.append(
            DemoPaper(
                paper_id=paper_id,
                title=title,
                citation=f"Example Author et al. Demo Journal (20{20 + index})",
                doi=f"10.0000/example.{index}",
                pmid=f"0000000{index}",
                pmcid=f"PMCDEMO{index}",
                doi_url=f"https://example.org/doi/demo-{index}",
                pubmed_url=f"https://example.org/pubmed/demo-{index}",
                pdf_url=f"https://example.org/pdf/demo-{index}",
                html_url=f"https://example.org/html/demo-{index}",
                library_url=f"https://example.org/library/demo-{index}",
                arms=(arm,),
            )
        )
    return tuple(papers)


def queue_items(
    papers: tuple[DemoPaper, ...],
    *,
    paper_ids: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    near_eligibility: bool = False,
) -> tuple[DemoArm, ...]:
    arms = tuple(arm for paper in papers for arm in paper.arms)
    if paper_ids:
        arms = tuple(arm for arm in arms if arm.paper_id in paper_ids)
    if reasons:
        arms = tuple(arm for arm in arms if arm.primary_reason in reasons)
    if near_eligibility:
        arms = tuple(
            arm for arm in arms
            if len(simulate_eligibility(arm).nearest_neighbor_reasons) <= 2
        )
    return arms


def apply_decision(
    arm: DemoArm,
    field_name: str,
    action: ReviewAction,
    corrected_value: str | None = None,
) -> DemoArm:
    if field_name not in arm.fields:
        raise KeyError(field_name)
    current = arm.fields[field_name]
    if action == "correct":
        if corrected_value is None or not corrected_value.strip():
            raise ValueError("A corrected value is required")
        updated = replace(current, value=corrected_value.strip(), status="verified")
    elif action == "accept":
        updated = replace(current, status="verified")
    elif action == "not_reported":
        updated = replace(current, value="Not reported", status="not_reported")
    elif action == "unresolved":
        updated = replace(current, status="needs_confirmation")
    else:
        raise ValueError(f"Unsupported review action: {action}")
    fields = dict(arm.fields)
    fields[field_name] = updated
    return replace(arm, fields=fields)


def simulate_eligibility(arm: DemoArm) -> EligibilityPreview:
    nn_reasons: set[str] = set()
    comet_reasons: set[str] = set()
    for name, value in arm.fields.items():
        unresolved = value.status in {"missing", "needs_confirmation", "conflict"}
        if not unresolved:
            continue
        if "nearest_neighbor" in value.required_for:
            nn_reasons.add(name)
        if "comet" in value.required_for:
            comet_reasons.add(name)
    if nn_reasons:
        comet_reasons.add("nearest_neighbor_requirements")
    return EligibilityPreview(
        nearest_neighbor_eligible=not nn_reasons,
        comet_eligible=not comet_reasons,
        nearest_neighbor_reasons=tuple(sorted(nn_reasons)),
        comet_reasons=tuple(sorted(comet_reasons)),
    )


__all__ = [
    "DemoArm", "DemoEvidence", "DemoField", "DemoPaper", "EligibilityPreview",
    "apply_decision", "demo_papers", "queue_items", "simulate_eligibility",
]
