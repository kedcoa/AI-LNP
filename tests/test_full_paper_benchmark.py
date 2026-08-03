from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.extraction.evaluate_full_paper_benchmark import evaluate


ROOT = Path(__file__).resolve().parents[1]


def _arm(
    arm_id: str,
    *,
    formulation: str,
    payload: str,
    dose: float,
    recipient_context: str,
    experimental_model: str = "mouse model",
    route: str = "intravenous",
    species: str = "mouse",
    tissue: str = "liver",
    timepoint: float = 6,
    timepoint_unit: str = "hour",
) -> dict:
    return {
        "arm_id": arm_id,
        "formulation": formulation,
        "payload": payload,
        "dose": dose,
        "dose_unit": "mg/kg",
        "recipient_context": recipient_context,
        "experimental_model": experimental_model,
        "route": route,
        "species": species,
        "tissue": tissue,
        "timepoint": timepoint,
        "timepoint_unit": timepoint_unit,
    }


def _gold_fact(
    gold_id: str,
    namespace: str,
    field: str,
    expected,
    *,
    aliases: list | None = None,
    arm: dict | None = None,
    entity: dict | None = None,
) -> dict:
    return {
        "gold_id": gold_id,
        "namespace": namespace,
        "entity": entity or {
            "entity_type": "arm",
            "identity": arm["arm_id"],
            "aliases": [],
        },
        "arm": arm,
        "field": field,
        "expected": expected,
        "aliases": aliases or [],
        "source_quote": "A synthetic source sentence directly supports this fact.",
        "source_locator": {
            "html_section": "Synthetic Results",
            "html_id": "Par-SYNTH",
            "pdf_page": 1,
        },
        "criticality": "critical",
    }


def _actual_fact(
    namespace: str,
    field: str,
    value,
    *,
    arm: dict | None = None,
    entity: dict | None = None,
) -> dict:
    return {
        "namespace": namespace,
        "entity": entity or {
            "entity_type": "arm",
            "identity": arm["arm_id"],
        },
        "arm": arm,
        "field": field,
        "value": value,
    }


def _synthetic_gold() -> dict:
    arm_a = _arm(
        "ARM-A",
        formulation="Zephyr-9",
        payload="cobalt RNA",
        dose=0.4,
        recipient_context="stellate cells",
    )
    arm_b = _arm(
        "ARM-B",
        formulation="Nimbus-4",
        payload="amber RNA",
        dose=0.8,
        recipient_context="endothelial cells",
    )
    paper = {
        "entity_type": "paper",
        "identity": "SYNTH-77",
        "aliases": [],
    }
    return {
        "benchmark_version": "full-paper-gold-1.0.0",
        "paper_id": "SYNTH-77",
        "sources": [],
        "context_inventory": [
            {**arm_a, "supported": True},
            {**arm_b, "supported": True},
        ],
        "excluded_contexts": [],
        "shared_facts": [
            _gold_fact(
                "G-S-ROUTE",
                "shared",
                "route",
                "intravenous",
                aliases=["IV"],
                entity=paper,
            ),
            _gold_fact(
                "G-S-SPECIES",
                "shared",
                "species",
                "mouse",
                aliases=["mice"],
                entity=paper,
            ),
        ],
        "experiment_facts": [
            _gold_fact(
                "G-A-PAYLOAD",
                "experiment",
                "payload",
                "cobalt RNA",
                arm=arm_a,
            ),
            _gold_fact(
                "G-A-ENDPOINT",
                "experiment",
                "endpoint",
                "cobalt signal",
                aliases=["blue signal"],
                arm=arm_a,
            ),
            _gold_fact(
                "G-B-PAYLOAD",
                "experiment",
                "payload",
                "amber RNA",
                arm=arm_b,
            ),
            _gold_fact(
                "G-B-ENDPOINT",
                "experiment",
                "endpoint",
                "amber signal",
                arm=arm_b,
            ),
        ],
    }


def _perfect_artifact(gold: dict) -> dict:
    return {
        "artifact_version": "full-paper-merged-1.0.0",
        "paper_id": gold["paper_id"],
        "shared_facts": [
            _actual_fact(
                "shared",
                row["field"],
                row["expected"],
                entity=row["entity"],
            )
            for row in gold["shared_facts"]
        ],
        "experiment_facts": [
            _actual_fact(
                "experiment",
                row["field"],
                row["expected"],
                arm=row["arm"],
            )
            for row in gold["experiment_facts"]
        ],
    }


def _write_case(tmp_path: Path, gold: dict, artifact: dict) -> tuple[Path, Path]:
    extraction_dir = tmp_path / "extraction"
    extraction_dir.mkdir()
    (extraction_dir / "merged_extraction.json").write_text(
        json.dumps(artifact),
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")
    return extraction_dir, gold_path


def test_perfect_extraction_scores_every_metric_at_one(tmp_path: Path) -> None:
    """A dropped match or arm denominator must make a perfect score fail."""
    gold = _synthetic_gold()
    extraction_dir, gold_path = _write_case(
        tmp_path,
        gold,
        _perfect_artifact(gold),
    )

    score = evaluate(extraction_dir, gold_path)

    assert score.overall_micro_recall == 1.0
    assert score.shared_paper_recall == 1.0
    assert score.experiment_fact_recall == 1.0
    assert score.complete_arm_recall == 1.0
    assert score.precision == 1.0
    assert score.unsupported_invention_count == 0
    assert score.wrong_arm_link_count == 0
    assert score.missing_gold_ids == []
    assert score.per_recipient_context_recall == {
        "endothelial cells": 1.0,
        "stellate cells": 1.0,
    }
    assert score.matched_gold_fact_count == 6
    assert score.total_gold_fact_count == 6


def test_partial_extraction_reports_fact_and_complete_arm_recall(
    tmp_path: Path,
) -> None:
    """Missing facts must lower their namespace and complete-arm denominators."""
    gold = _synthetic_gold()
    artifact = _perfect_artifact(gold)
    artifact["shared_facts"].pop()
    artifact["experiment_facts"] = [
        row
        for row in artifact["experiment_facts"]
        if not (
            row["arm"]["arm_id"] == "ARM-B"
            and row["field"] == "endpoint"
        )
    ]
    extraction_dir, gold_path = _write_case(tmp_path, gold, artifact)

    score = evaluate(extraction_dir, gold_path)

    assert score.overall_micro_recall == pytest.approx(4 / 6)
    assert score.shared_paper_recall == 0.5
    assert score.experiment_fact_recall == 0.75
    assert score.complete_arm_recall == 0.5
    assert score.precision == 1.0
    assert score.missing_gold_ids == ["G-S-SPECIES", "G-B-ENDPOINT"]
    assert score.per_recipient_context_recall == {
        "endothelial cells": 0.5,
        "stellate cells": 1.0,
    }


def test_wrong_arm_link_is_not_recalled_or_labeled_as_an_invention(
    tmp_path: Path,
) -> None:
    """Moving a supported endpoint to another arm must be a wrong link."""
    gold = _synthetic_gold()
    artifact = _perfect_artifact(gold)
    wrong = next(
        row
        for row in artifact["experiment_facts"]
        if row["arm"]["arm_id"] == "ARM-A" and row["field"] == "endpoint"
    )
    wrong["arm"] = deepcopy(gold["context_inventory"][1])
    wrong["arm"].pop("supported")
    extraction_dir, gold_path = _write_case(tmp_path, gold, artifact)

    score = evaluate(extraction_dir, gold_path)

    assert score.wrong_arm_link_count == 1
    assert score.unsupported_invention_count == 0
    assert "G-A-ENDPOINT" in score.missing_gold_ids
    assert score.precision == pytest.approx(5 / 6)


def test_arm_link_requires_model_route_tissue_and_timepoint_identity(
    tmp_path: Path,
) -> None:
    """An endpoint moved between otherwise identical contexts is a wrong link."""
    early = _arm(
        "ARM-EARLY",
        formulation="Zephyr-9",
        payload="cobalt RNA",
        dose=0.4,
        recipient_context="stellate cells",
        experimental_model="healthy mouse",
        route="intravenous",
        tissue="liver",
        timepoint=6,
    )
    late = _arm(
        "ARM-LATE",
        formulation="Zephyr-9",
        payload="cobalt RNA",
        dose=0.4,
        recipient_context="stellate cells",
        experimental_model="fibrotic mouse",
        route="portal-vein infusion",
        tissue="fibrotic liver",
        timepoint=24,
    )
    gold = _synthetic_gold()
    gold["context_inventory"] = [
        {**early, "supported": True},
        {**late, "supported": True},
    ]
    gold["experiment_facts"] = [
        _gold_fact(
            "G-EARLY-ENDPOINT",
            "experiment",
            "endpoint",
            "early cobalt signal",
            arm=early,
        ),
        _gold_fact(
            "G-LATE-ENDPOINT",
            "experiment",
            "endpoint",
            "late cobalt signal",
            arm=late,
        ),
    ]
    artifact = _perfect_artifact(gold)
    artifact["experiment_facts"][0]["arm"] = deepcopy(late)
    extraction_dir, gold_path = _write_case(tmp_path, gold, artifact)

    score = evaluate(extraction_dir, gold_path)

    assert score.wrong_arm_link_count == 1
    assert score.unsupported_invention_count == 0
    assert "G-EARLY-ENDPOINT" in score.missing_gold_ids
    assert score.experiment_fact_recall == 0.5
    assert score.complete_arm_recall == 0.5
    assert score.precision == 0.75


def test_unsupported_benchmark_fact_lowers_precision(tmp_path: Path) -> None:
    """A novel value in a benchmark field must count as an invention."""
    gold = _synthetic_gold()
    artifact = _perfect_artifact(gold)
    artifact["experiment_facts"].append(
        _actual_fact(
            "experiment",
            "endpoint",
            "hallucinated necrosis",
            arm=gold["context_inventory"][0],
        )
    )
    artifact["experiment_facts"][-1]["arm"].pop("supported")
    extraction_dir, gold_path = _write_case(tmp_path, gold, artifact)

    score = evaluate(extraction_dir, gold_path)

    assert score.overall_micro_recall == 1.0
    assert score.unsupported_invention_count == 1
    assert score.wrong_arm_link_count == 0
    assert score.precision == pytest.approx(6 / 7)


def test_declared_aliases_match_without_fuzzy_scientific_matching(
    tmp_path: Path,
) -> None:
    """Only normalized exact values and explicit aliases may match."""
    gold = _synthetic_gold()
    artifact = _perfect_artifact(gold)
    artifact["shared_facts"][0]["value"] = "  iv "
    artifact["shared_facts"][1]["value"] = "MICE"
    endpoint = next(
        row
        for row in artifact["experiment_facts"]
        if row["arm"]["arm_id"] == "ARM-A" and row["field"] == "endpoint"
    )
    endpoint["value"] = "Blue signal"
    extraction_dir, gold_path = _write_case(tmp_path, gold, artifact)

    score = evaluate(extraction_dir, gold_path)

    assert score.overall_micro_recall == 1.0
    assert score.precision == 1.0


def test_perfect_compact_artifact_and_paper_map_deduplicate_shared_facts(
    tmp_path: Path,
) -> None:
    """Two production projections of one fact must not lower precision."""
    arm = _arm(
        "ARM-PRODUCTION",
        formulation="Zephyr-9",
        payload="cobalt RNA",
        dose=0.4,
        recipient_context="stellate cells",
        experimental_model="healthy mouse",
        route="intravenous",
        tissue="liver",
        timepoint=6,
    )
    paper = {
        "entity_type": "paper",
        "identity": "SYNTH-77",
        "aliases": [],
    }
    formulation = {
        "entity_type": "formulation",
        "identity": "Zephyr-9",
        "aliases": [],
    }
    payload = {
        "entity_type": "payload",
        "identity": "cobalt RNA",
        "aliases": [],
    }
    shared_facts = [
        _gold_fact(
            "G-PROD-FORM",
            "shared",
            "formulation",
            "Zephyr-9",
            entity=formulation,
        ),
        _gold_fact(
            "G-PROD-COMP",
            "shared",
            "component",
            "amphiphile A",
            entity=formulation,
        ),
        _gold_fact(
            "G-PROD-PAYLOAD",
            "shared",
            "payload",
            "cobalt RNA",
            entity=payload,
        ),
        _gold_fact(
            "G-PROD-ROLE",
            "shared",
            "payload_role",
            "reporter",
            entity=payload,
        ),
    ]
    shared_facts.extend(
        _gold_fact(
            f"G-PROD-{field.upper()}",
            "shared",
            field,
            value,
            entity=paper,
        )
        for field, value in (
            ("route", "intravenous"),
            ("species", "mouse"),
            ("experimental_model", "healthy mouse"),
            ("tissue", "liver"),
        )
    )
    gold = {
        "benchmark_version": "full-paper-gold-1.0.0",
        "paper_id": "SYNTH-77",
        "sources": [],
        "context_inventory": [{**arm, "supported": True}],
        "excluded_contexts": [],
        "shared_facts": shared_facts,
        "experiment_facts": [
            _gold_fact(
                "G-PROD-ENDPOINT",
                "experiment",
                "endpoint",
                "cobalt signal",
                arm=arm,
            )
        ],
    }
    artifact = {
        "paper_id": "SYNTH-77",
        "formulations": [
            {
                "formulation_id": "FORM-Z9",
                "formulation_name": {"value": "Zephyr-9", "status": "reported"},
                "composition": {"value": "amphiphile A", "status": "reported"},
                "composition_basis": {"value": "molar", "status": "reported"},
                "np_ratio": {"value": 8, "status": "reported"},
            }
        ],
        "components": [
            {
                "component_id": "COMP-A",
                "formulation_id": "FORM-Z9",
                "identity": {"value": "amphiphile A", "status": "reported"},
                "role": {"value": "ionizable_lipid", "status": "reported"},
            }
        ],
        "experiments": [
            {
                "experiment_id": "EXP-Z9",
                "formulation_id": "FORM-Z9",
                "payload_name": {"value": "cobalt RNA", "status": "reported"},
                "payload_role": {"value": "reporter", "status": "reported"},
                "dose": {"value": 0.4, "status": "reported"},
                "dose_unit": {"value": "mg/kg", "status": "reported"},
                "delivery_recipient_cell": {
                    "value": "stellate cells",
                    "status": "reported",
                },
                "route": {"value": "intravenous", "status": "reported"},
                "species": {"value": "mouse", "status": "reported"},
                "experimental_model": {
                    "value": "healthy mouse",
                    "status": "reported",
                },
                "tissue_or_organ": {"value": "liver", "status": "reported"},
                "timepoint": {"value": 6, "status": "reported"},
                "timepoint_unit": {"value": "hour", "status": "reported"},
            }
        ],
        "outcomes": [
            {
                "outcome_id": "OUT-Z9",
                "experiment_id": "EXP-Z9",
                "endpoint": {"value": "cobalt signal", "status": "reported"},
            }
        ],
    }
    paper_map = {
        "paper_id": "SYNTH-77",
        "formulations": [
            {
                "formulation_id": "FORM-Z9",
                "name": {"value": "Zephyr-9"},
                "components": [
                    {
                        "component_id": "COMP-A",
                        "identity": {"value": "amphiphile A"},
                        "role": {"value": "ionizable_lipid"},
                    }
                ],
                "ratios": [],
                "ratio_bases": [],
            }
        ],
        "payloads": [
            {
                "payload_id": "PAY-COBALT",
                "identity": {"value": "cobalt RNA"},
                "role": {"value": "reporter"},
            }
        ],
        "common_routes": [{"value": "intravenous"}],
        "common_species": [{"value": "mouse"}],
        "common_models": [{"value": "healthy mouse"}],
    }
    extraction_dir, gold_path = _write_case(tmp_path, gold, artifact)
    (extraction_dir / "paper_map.json").write_text(
        json.dumps(paper_map),
        encoding="utf-8",
    )

    score = evaluate(extraction_dir, gold_path)

    assert score.overall_micro_recall == 1.0
    assert score.shared_paper_recall == 1.0
    assert score.experiment_fact_recall == 1.0
    assert score.complete_arm_recall == 1.0
    assert score.precision == 1.0
    assert score.per_recipient_context_recall == {"stellate cells": 1.0}
    assert score.unsupported_invention_count == 0
    assert score.wrong_arm_link_count == 0
    assert score.missing_gold_ids == []


def test_missing_gold_id_is_rejected_before_scoring(tmp_path: Path) -> None:
    """An unidentifiable answer-key item must not silently enter a denominator."""
    gold = _synthetic_gold()
    del gold["shared_facts"][0]["gold_id"]
    extraction_dir, gold_path = _write_case(
        tmp_path,
        gold,
        _perfect_artifact(_synthetic_gold()),
    )

    with pytest.raises(ValueError, match="gold_id"):
        evaluate(extraction_dir, gold_path)


def test_np002_key_audits_all_eighteen_supported_contexts() -> None:
    """Dropping a formulation/payload/dose/cell combination must fail."""
    gold_path = ROOT / "data/benchmarks/full_paper/NP-002.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    contexts = gold["context_inventory"]

    assert gold["paper_id"] == "NP-002"
    assert len(contexts) == 18
    assert all(row["supported"] is True for row in contexts)
    assert gold["excluded_contexts"] == []
    assert {
        (
            row["formulation"],
            row["payload"],
            row["dose"],
            row["recipient_context"],
        )
        for row in contexts
    } == {
        (formulation, payload, dose, recipient)
        for formulation in ("MC3", "cKK-E12")
        for payload, dose in (
            ("QUANT DNA", 0.3),
            ("Cre mRNA", 0.3),
            ("Cre mRNA", 1.0),
        )
        for recipient in (
            "Kupffer cells",
            "liver endothelial cells",
            "hepatocytes",
        )
    }

    facts = [*gold["shared_facts"], *gold["experiment_facts"]]
    assert facts
    assert len({row["gold_id"] for row in facts}) == len(facts)
    for row in facts:
        assert row["namespace"] in {"shared", "experiment"}
        assert row["entity"]["entity_type"]
        assert row["entity"]["identity"]
        assert row["field"]
        assert row["expected"] is not None
        assert isinstance(row["aliases"], list)
        assert row["source_quote"].strip()
        assert row["source_locator"]["html_section"].strip()
        assert row["source_locator"]["html_id"].strip()
        assert row["source_locator"]["pdf_page"] >= 1
        assert row["criticality"] in {"critical", "important", "context"}

    shared_expected = {
        json.dumps(row["expected"], sort_keys=True)
        for row in gold["shared_facts"]
    }
    for expected in (
        "MC3",
        "cKK-E12",
        "cholesterol",
        "C14PEG2000",
        "DSPC",
        "50:38.5:1.5:10",
        "10:1",
        "QUANT DNA",
        "Cre mRNA",
        "intravenous via the lateral tail vein",
        "mouse",
        "liver",
        "6 hours",
        "3 days",
    ):
        assert json.dumps(expected) in shared_expected

    arm_ids = {row["arm_id"] for row in contexts}
    facts_by_arm = {
        arm_id: [
            fact
            for fact in gold["experiment_facts"]
            if fact["arm"]["arm_id"] == arm_id
        ]
        for arm_id in arm_ids
    }
    assert all(facts_by_arm.values())
    required_arm_identity = {
        "arm_id",
        "formulation",
        "payload",
        "dose",
        "dose_unit",
        "route",
        "species",
        "experimental_model",
        "recipient_context",
        "tissue",
        "timepoint",
        "timepoint_unit",
    }
    assert all(
        required_arm_identity <= set(fact["arm"])
        for fact in gold["experiment_facts"]
    )
    assert all(
        {
            "formulation",
            "payload",
            "dose",
            "dose_unit",
            "recipient_context",
            "timepoint",
            "timepoint_unit",
            "assay",
            "endpoint",
            "qualitative_outcome",
        }
        <= {fact["field"] for fact in arm_facts}
        for arm_facts in facts_by_arm.values()
    )


def test_np002_aliases_do_not_merge_distinct_conditions_or_components() -> None:
    """Scientific aliases must not collapse controls or specific PEG lipids."""
    gold = json.loads(
        (
            ROOT / "data/benchmarks/full_paper/NP-002.json"
        ).read_text(encoding="utf-8")
    )
    component_facts = [
        row
        for row in gold["shared_facts"]
        if row["field"] == "component" and row["expected"] == "C14PEG2000"
    ]
    assert component_facts
    assert all("PEG-lipid" not in row["aliases"] for row in component_facts)

    comparator_facts = [
        row
        for row in gold["experiment_facts"]
        if row["field"] == "comparator"
    ]
    assert comparator_facts
    for row in comparator_facts:
        if row["arm"]["dose"] == 0.3:
            assert row["expected"] == "untreated Ai14 control"
            assert "PBS-treated Ai14 control" not in row["aliases"]
        else:
            assert row["expected"] == "PBS-treated Ai14 control"
            assert not any(
                "untreated" in alias.casefold() for alias in row["aliases"]
            )


def test_production_full_paper_modules_do_not_reference_hidden_gold() -> None:
    """A request/preparation module referencing the key is a gold leak."""
    production_paths = [
        ROOT / "src/extraction/full_paper_inventory.py",
        ROOT / "src/extraction/full_paper_contracts.py",
        ROOT / "src/extraction/full_paper_tasks.py",
        ROOT / "src/extraction/prepare_full_paper_extraction.py",
    ]
    banned = ("data/benchmarks/full_paper", "NP-002.json")

    for path in production_paths:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in banned), path
