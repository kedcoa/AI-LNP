from __future__ import annotations

import ast
from pathlib import Path
import re

from src.extraction.evaluate_application_requirements import (
    evaluate_application_requirements,
)


def _fact(
    field_name: str,
    value: object,
    *,
    experiment_id: str | None = None,
    provenance: str = "text",
) -> dict:
    row = {
        "field_name": field_name,
        "raw_values": [str(value)],
        "canonical_value": str(value),
        "evidence_ids": ["E-1"],
        "provenance": provenance,
    }
    if experiment_id is not None:
        row["experiment_id"] = experiment_id
    return row


def _reference_fact(
    reference_id: str,
    category: str,
    field_name: str,
    expected: object,
    *,
    aliases: list[object] | None = None,
    experiment_id: str | None = None,
    reported: bool = True,
) -> dict:
    row = {
        "reference_id": reference_id,
        "category": category,
        "field_name": field_name,
        "expected": expected,
        "aliases": aliases or [],
        "reported": reported,
    }
    if experiment_id is not None:
        row["experiment_id"] = experiment_id
    return row


def _documents(
    extraction_facts: list[dict],
    reference_facts: list[dict],
    *,
    paper_id: str = "PAPER-1",
) -> tuple[dict, dict]:
    shared = [row for row in extraction_facts if "experiment_id" not in row]
    experiment_rows: dict[str, list[dict]] = {}
    for row in extraction_facts:
        experiment_id = row.get("experiment_id")
        if experiment_id is not None:
            fact = {key: value for key, value in row.items() if key != "experiment_id"}
            experiment_rows.setdefault(experiment_id, []).append(fact)
    extraction = {
        "papers": [
            {
                "paper_id": paper_id,
                "shared_facts": shared,
                "experiments": [
                    {"experiment_id": experiment_id, "facts": facts}
                    for experiment_id, facts in experiment_rows.items()
                ],
                "quarantined_conflicts": [],
            }
        ]
    }
    reference = {
        "papers": [
            {
                "paper_id": paper_id,
                "reference_facts": reference_facts,
                "experiment_ids": sorted(experiment_rows),
                "evidence_ids": ["E-1"],
            }
        ]
    }
    return extraction, reference


def test_equivalent_ratio_format_matches_without_losing_raw_text() -> None:
    extraction, reference = _documents(
        [_fact("component_ratio", "50 : 38.5 : 1.5 : 10")],
        [
            _reference_fact(
                "APP-P1-FORM-1",
                "formulation",
                "component_ratio",
                "50:38.5:1.5:10",
            )
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["formulation"].recall == 1.0
    assert extraction["papers"][0]["shared_facts"][0]["raw_values"] == [
        "50 : 38.5 : 1.5 : 10"
    ]


def test_unreported_numeric_fact_is_not_in_denominator() -> None:
    extraction, reference = _documents(
        [],
        [
            _reference_fact(
                "APP-P1-NUM-1",
                "exact_numeric",
                "outcome_value",
                14.2,
                reported=False,
            )
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["exact_numeric"].denominator == 0


def test_specific_supported_comparison_matches_only_a_controlled_alias() -> None:
    extraction, reference = _documents(
        [
            _fact(
                "comparative_outcome",
                "higher liver expression than the matched untreated control",
                experiment_id="EXP-A",
            )
        ],
        [
            _reference_fact(
                "APP-P1-OUT-1",
                "qualitative_outcome",
                "comparative_outcome",
                "higher than control",
                aliases=[
                    "higher liver expression than the matched untreated control"
                ],
                experiment_id="EXP-A",
            )
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["qualitative_outcome"].numerator == 1


def test_contradictory_comparison_does_not_match() -> None:
    extraction, reference = _documents(
        [
            _fact(
                "comparative_outcome",
                "lower than control",
                experiment_id="EXP-A",
            )
        ],
        [
            _reference_fact(
                "APP-P1-OUT-2",
                "qualitative_outcome",
                "comparative_outcome",
                "higher than control",
                aliases=["greater than control"],
                experiment_id="EXP-A",
            )
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["qualitative_outcome"].numerator == 0
    assert score.missing_reference_ids == ["APP-P1-OUT-2"]


def test_graph_estimate_cannot_satisfy_exact_numeric_expectation() -> None:
    extraction, reference = _documents(
        [
            _fact(
                "outcome_value",
                14.2,
                experiment_id="EXP-A",
                provenance="graph_estimated",
            )
        ],
        [
            _reference_fact(
                "APP-P1-NUM-2",
                "exact_numeric",
                "outcome_value",
                14.2,
                experiment_id="EXP-A",
            )
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["exact_numeric"].numerator == 0
    assert score.unsupported_numeric_count == 1


def test_provenance_is_scored_from_the_support_attached_to_a_fact() -> None:
    extraction, reference = _documents(
        [_fact("assay", "ddPCR", experiment_id="EXP-A", provenance="figure_label")],
        [
            _reference_fact(
                "APP-P1-PROV-1",
                "provenance",
                "provenance",
                "figure_label",
                experiment_id="EXP-A",
            ),
            _reference_fact(
                "APP-P1-PROV-2",
                "provenance",
                "evidence_id",
                "E-1",
                experiment_id="EXP-A",
            ),
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["provenance"].numerator == 2
    assert score.categories["provenance"].denominator == 2


def test_typed_accepted_atomic_outcomes_are_scored() -> None:
    extraction = {
        "paper_id": "PAPER-1",
        "accepted_candidate_outcomes": {
            "CTX-A": {
                "candidate_id": "CTX-A",
                "experiment_id": "EXP-A",
                "foundational_outcomes": [],
                "comparative_outcomes": [
                    {
                        "assertion_type": "comparison",
                        "direction": "higher",
                        "subject": "liver expression",
                        "comparator": "untreated control",
                        "raw_text": "higher than the untreated control",
                        "value": None,
                        "unit": None,
                        "numeric_provenance": "not_reported",
                        "evidence_ids": ["E-1"],
                    }
                ],
                "exact_measurements": [
                    {
                        "assertion_type": "measurement",
                        "direction": "reported",
                        "subject": "liver expression",
                        "comparator": None,
                        "raw_text": "42% liver expression",
                        "value": 42.0,
                        "unit": "%",
                        "numeric_provenance": "exact_reported",
                        "evidence_ids": ["E-1"],
                    }
                ],
            }
        },
    }
    reference = {
        "paper_id": "PAPER-1",
        "experiment_ids": ["EXP-A"],
        "evidence_ids": ["E-1"],
        "reference_facts": [
            _reference_fact(
                "APP-P1-OUT-ATOMIC",
                "qualitative_outcome",
                "comparative_outcome",
                "higher than control",
                aliases=["higher than the untreated control"],
                experiment_id="EXP-A",
            ),
            _reference_fact(
                "APP-P1-NUM-ATOMIC",
                "exact_numeric",
                "outcome_value",
                42,
                experiment_id="EXP-A",
            ),
        ],
    }

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["qualitative_outcome"].numerator == 1
    assert score.categories["exact_numeric"].numerator == 1


def test_scores_aggregate_and_each_paper_category() -> None:
    first_extraction, first_reference = _documents(
        [_fact("assay", "ddPCR")],
        [
            _reference_fact(
                "APP-P1-ASSAY-1", "assay", "assay", "droplet digital PCR"
            )
        ],
        paper_id="PAPER-1",
    )
    second_extraction, second_reference = _documents(
        [],
        [
            _reference_fact(
                "APP-P2-MODEL-1",
                "biological_model",
                "species",
                "mouse",
            )
        ],
        paper_id="PAPER-2",
    )
    extraction = {"papers": first_extraction["papers"] + second_extraction["papers"]}
    reference = {"papers": first_reference["papers"] + second_reference["papers"]}

    score = evaluate_application_requirements(extraction, reference)

    assert score.overall_recall == 0.5
    assert score.per_paper_recall == {"PAPER-1": 1.0, "PAPER-2": 0.0}
    assert score.per_paper_categories["PAPER-1"]["assay"].recall == 1.0


def test_wrong_arm_invented_id_and_unsupported_numeric_counts_are_strict() -> None:
    extraction, reference = _documents(
        [
            _fact("species", "mouse", experiment_id="EXP-INVENTED"),
            _fact(
                "outcome_value",
                9.0,
                experiment_id="EXP-INVENTED",
                provenance="graph_estimated",
            ),
        ],
        [
            _reference_fact(
                "APP-P1-MODEL-2",
                "biological_model",
                "species",
                "mouse",
                experiment_id="EXP-A",
            )
        ],
    )
    extraction["papers"][0]["quarantined_conflicts"] = [
        {"code": "candidate_experiment_mismatch"},
        {"code": "unknown_experiment_id"},
    ]
    reference["papers"][0]["experiment_ids"] = ["EXP-A"]

    score = evaluate_application_requirements(extraction, reference)

    assert score.wrong_arm_link_count == 1
    assert score.invented_id_count == 2
    assert score.unsupported_numeric_count == 1
    assert score.precision == 0.0


def test_scientifically_matching_fact_on_another_valid_arm_is_wrong_link() -> None:
    extraction, reference = _documents(
        [
            _fact(
                "comparative_outcome",
                "higher than control",
                experiment_id="EXP-B",
            )
        ],
        [
            _reference_fact(
                "APP-P1-WRONG-ARM-1",
                "qualitative_outcome",
                "comparative_outcome",
                "higher than control",
                experiment_id="EXP-A",
            )
        ],
    )
    reference["papers"][0]["experiment_ids"] = ["EXP-A", "EXP-B"]

    score = evaluate_application_requirements(extraction, reference)

    assert score.wrong_arm_link_count == 1


def test_detected_wrong_arm_and_its_quarantine_are_counted_once() -> None:
    extraction, reference = _documents(
        [
            _fact(
                "comparative_outcome",
                "higher than control",
                experiment_id="EXP-B",
            )
        ],
        [
            _reference_fact(
                "APP-P1-WRONG-ARM-2",
                "qualitative_outcome",
                "comparative_outcome",
                "higher than control",
                experiment_id="EXP-A",
            )
        ],
    )
    reference["papers"][0]["experiment_ids"] = ["EXP-A", "EXP-B"]
    extraction["papers"][0]["quarantined_conflicts"] = [
        {
            "code": "candidate_experiment_mismatch",
            "experiment_id": "EXP-B",
            "field_name": "comparative_outcome",
        }
    ]

    score = evaluate_application_requirements(extraction, reference)

    assert score.wrong_arm_link_count == 1


def test_same_value_on_multiple_arms_is_not_wrong_when_own_arm_supports_it() -> None:
    extraction, reference = _documents(
        [_fact("species", "mouse", experiment_id="EXP-B")],
        [
            _reference_fact(
                "APP-P1-MODEL-ARM-A",
                "biological_model",
                "species",
                "mouse",
                experiment_id="EXP-A",
            ),
            _reference_fact(
                "APP-P1-MODEL-ARM-B",
                "biological_model",
                "species",
                "mouse",
                experiment_id="EXP-B",
            ),
        ],
    )
    reference["papers"][0]["experiment_ids"] = ["EXP-A", "EXP-B"]

    score = evaluate_application_requirements(extraction, reference)

    assert score.wrong_arm_link_count == 0


def test_only_unreferenced_exact_reported_number_is_unsupported() -> None:
    extraction, reference = _documents(
        [
            _fact(
                "outcome_value",
                42,
                experiment_id="EXP-A",
                provenance="exact_reported",
            ),
            _fact(
                "numeric_value",
                99,
                experiment_id="EXP-A",
                provenance="exact_reported",
            ),
        ],
        [
            _reference_fact(
                "APP-P1-NUM-SUPPORTED",
                "exact_numeric",
                "outcome_value",
                42,
                experiment_id="EXP-A",
            )
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["exact_numeric"].numerator == 1
    assert score.unsupported_numeric_count == 1


def test_unknown_experiment_ids_are_found_in_flat_facts_and_atomic_bundles() -> None:
    extraction = {
        "paper_id": "PAPER-1",
        "facts": [
            {
                **_fact("species", "mouse"),
                "experiment_id": "EXP-FLAT-INVENTED",
            }
        ],
        "accepted_candidate_outcomes": {
            "CTX-X": {
                "candidate_id": "CTX-X",
                "experiment_id": "EXP-BUNDLE-INVENTED",
                "foundational_outcomes": [
                    {
                        "raw_text": "expression was present",
                        "numeric_provenance": "not_reported",
                        "evidence_ids": ["E-1"],
                    }
                ],
                "comparative_outcomes": [],
                "exact_measurements": [],
            }
        },
    }
    reference = {
        "paper_id": "PAPER-1",
        "experiment_ids": ["EXP-A"],
        "evidence_ids": ["E-1"],
        "reference_facts": [],
    }

    score = evaluate_application_requirements(extraction, reference)

    assert score.invented_id_count == 2


def test_anonymous_invented_conflicts_are_added_after_id_deduplication() -> None:
    extraction, reference = _documents(
        [_fact("species", "mouse", experiment_id="EXP-INVENTED")],
        [],
    )
    reference["papers"][0]["experiment_ids"] = ["EXP-A"]
    extraction["papers"][0]["quarantined_conflicts"] = [
        {"code": "unknown_experiment_id", "experiment_id": "EXP-INVENTED"},
        {
            "code": "invented_candidate_ids",
            "candidate_id": None,
            "candidate_ids": [],
        },
        {
            "code": "unknown_evidence_id",
            "evidence_id": None,
            "evidence_ids": [],
        },
    ]

    score = evaluate_application_requirements(extraction, reference)

    assert score.invented_id_count == 3


def test_maximum_matching_is_independent_of_overlapping_alias_order() -> None:
    extraction, reference = _documents(
        [_fact("assay", "alpha"), _fact("assay", "beta")],
        [
            _reference_fact(
                "APP-P1-MATCH-FLEXIBLE",
                "assay",
                "assay",
                "alpha",
                aliases=["beta"],
            ),
            _reference_fact(
                "APP-P1-MATCH-ONLY-ALPHA",
                "assay",
                "assay",
                "alpha",
            ),
        ],
    )

    score = evaluate_application_requirements(extraction, reference)

    assert score.categories["assay"].numerator == 2
    assert score.precision == 1.0


def test_application_reference_does_not_leak_into_production_or_prompts() -> None:
    repository = Path(__file__).resolve().parents[1]
    production_files = list((repository / "src" / "extraction").rglob("*.py"))
    serialized_prompts = [
        path
        for root in (repository / "config", repository / "src" / "extraction")
        for suffix in ("*.json", "*.txt", "*.md")
        for path in root.rglob(suffix)
    ]

    path_leaks = {
        str(path.relative_to(repository))
        for path in [*production_files, *serialized_prompts]
        if "data/benchmarks/application_pilot"
        in path.read_text(encoding="utf-8")
    }
    reference_id_leaks = {
        str(path.relative_to(repository)): sorted(
            set(re.findall(r"\bAPP-[A-Z0-9]+(?:-[A-Z0-9]+)+\b", text))
        )
        for path in [*production_files, *serialized_prompts]
        if (
            text := path.read_text(encoding="utf-8")
        )
        and re.search(r"\bAPP-[A-Z0-9]+(?:-[A-Z0-9]+)+\b", text)
    }

    assert path_leaks == set()
    assert reference_id_leaks == {}


def test_production_extraction_modules_do_not_import_evaluator_or_keys() -> None:
    repository = Path(__file__).resolve().parents[1]
    extraction_root = repository / "src" / "extraction"
    forbidden_imports: dict[str, list[str]] = {}
    for path in extraction_root.glob("*.py"):
        if path.name.startswith(("evaluate_", "benchmark_")) or (
            "benchmark" in path.stem
        ):
            continue
        imported: list[str] = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.append(module)
                imported.extend(
                    ".".join(part for part in (module, alias.name) if part)
                    for alias in node.names
                )
        forbidden = sorted(
            module
            for module in imported
            if module.startswith("src.extraction.evaluate_")
            or ".benchmark" in module
            or module.endswith("reference_loader")
        )
        if forbidden:
            forbidden_imports[str(path.relative_to(repository))] = forbidden

    assert forbidden_imports == {}
