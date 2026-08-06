import json
from pathlib import Path

import pytest

from src.database.adapters.np_results import build_np_bundle, write_bundle
from src.database.import_contracts import ImportBundle
from src.database.reconcile_np002 import reconcile_slices


ROOT = Path(__file__).resolve().parents[1]


def _field(value, *evidence_ids):
    return {
        "value": value,
        "status": "reported" if value is not None else "missing",
        "evidence_ids": list(evidence_ids),
        "missing_reason": None if value is not None else "not reported",
    }


def _slice(cell: str, dose: float = 1.0):
    return {
        "paper_id": "NP-002",
        "formulations": [{
            "formulation_id": "F1",
            "formulation_name": _field("MC3", "E-FORM"),
            "composition": _field("MC3/DSPC/cholesterol/PEG", "E-FORM"),
            "composition_basis": _field(None),
            "np_ratio": _field(6.0, "E-FORM"),
        }],
        "components": [],
        "experiments": [{
            "experiment_id": "X1",
            "formulation_id": "F1",
            "payload_type": _field("mRNA", "E-ARM"),
            "payload_name": _field("Cre mRNA", "E-ARM"),
            "encoded_product": _field("Cre", "E-ARM"),
            "molecular_target": _field(None),
            "delivery_recipient_cell": _field(cell, "E-ARM"),
            "therapeutic_target_cell": _field(cell, "E-ARM"),
            "tissue_or_organ": _field("liver", "E-ARM"),
            "species": _field("mouse", "E-ARM"),
            "disease_model": _field(None),
            "experimental_context": _field("in_vivo", "E-ARM"),
            "dose": _field(dose, "E-ARM"),
            "dose_unit": _field("mg/kg", "E-ARM"),
            "route": _field("intravenous", "E-ARM"),
            "timepoint": _field(None),
            "timepoint_unit": _field(None),
        }],
        "outcomes": [{
            "outcome_id": "O1",
            "experiment_id": "X1",
            "assay": _field("flow cytometry", "E-OUT"),
            "endpoint": _field("positive cells", "E-OUT"),
            "comparator": _field(None),
            "outcome_value": _field(None),
            "outcome_unit": _field(None),
            "qualitative_outcome": _field("higher expression", "E-OUT"),
        }],
        "unresolved_items": [],
    }


def _packet():
    return {
        "evidence": [
            {"evidence_id": "E-FORM", "text": "MC3 ratio 6:1", "source_ids": ["S1"]},
            {"evidence_id": "E-ARM", "text": "Cre mRNA was injected", "source_ids": ["S1"]},
            {"evidence_id": "E-OUT", "text": "Flow cytometry showed higher expression", "source_ids": ["S2"]},
        ],
        "sources": [
            {"source_id": "S1", "section": "Methods", "page_number": 2},
            {"source_id": "S2", "section": "Results", "page_number": 4},
        ],
    }


def test_reconciliation_namespaces_overlapping_ids_and_preserves_slice_provenance():
    reconciled = reconcile_slices([
        ("hepatocytes", _slice("hepatocytes")),
        ("kupffer", _slice("Kupffer cells")),
    ])

    assert [row["experiment_id"] for row in reconciled["experiments"]] == [
        "hepatocytes::X1", "kupffer::X1"
    ]
    assert {row["source_slice"] for row in reconciled["experiments"]} == {
        "hepatocytes", "kupffer"
    }
    assert len(reconciled["formulations"]) == 1
    assert reconciled["formulations"][0]["source_slices"] == ["hepatocytes", "kupffer"]


def test_reconciliation_retains_conflicting_formulations():
    second = _slice("Kupffer cells")
    second["formulations"][0]["np_ratio"] = _field(8.0, "E-FORM")

    reconciled = reconcile_slices([("a", _slice("hepatocytes")), ("b", second)])

    assert len(reconciled["formulations"]) == 2
    assert reconciled["conflicts"][0]["entity_type"] == "formulation"
    assert reconciled["conflicts"][0]["field_name"] == "np_ratio"


def test_reconciliation_unions_supported_scientific_formulation_identity():
    first = _slice("hepatocytes")
    first["formulations"][0]["formulation_id"] = "F1"
    first["formulations"][0]["composition"] = _field(
        "MC3, cholesterol, C14 PEG 2000, and DSPC at a 50:38.5:1.5:10 molar ratio",
        "E-FORM",
    )
    second = _slice("Kupffer cells")
    second["formulations"][0]["formulation_id"] = "F-MC3"
    second["experiments"][0]["formulation_id"] = "F-MC3"
    second["formulations"][0]["composition"] = _field(
        "MC3, cholesterol, C14 PEG 2000, DSPC; lipids formulated at 50:38.5:1.5:10",
        "E-FORM",
    )

    reconciled = reconcile_slices([("a", first), ("b", second)])

    assert len(reconciled["formulations"]) == 1
    assert {row["formulation_id"] for row in reconciled["experiments"]} == {"F1"}
    assert reconciled["formulations"][0]["source_slices"] == ["a", "b"]


def test_adapter_builds_valid_quarantined_bundle_without_synthesizing_links(tmp_path):
    result_path = tmp_path / "result.json"
    packet_path = tmp_path / "packet.json"
    result_path.write_text(json.dumps(_slice("hepatocytes")))
    packet_path.write_text(json.dumps(_packet()))

    bundle = build_np_bundle(
        result_paths=[result_path],
        packet_path=packet_path,
        paper_metadata={"title": "Example", "doi": "10.1/example"},
    )

    assert isinstance(bundle, ImportBundle)
    assert len(bundle.arms) == 1
    assert bundle.arms[0].completeness_status == "quarantined"
    assert not bundle.arms[0].nearest_neighbor_eligible
    assert not bundle.arms[0].comet_eligible
    assert {review.reason_code for review in bundle.reviews} >= {
        "missing_timepoint", "missing_comparator"
    }
    assert all("::" in row.record_id for row in bundle.evidence)
    assert all(row.verification_status == "unreviewed" for row in bundle.evidence)
    evidence = {row.record_id: row for row in bundle.evidence}
    for field_link in bundle.field_evidence_links:
        for evidence_id in field_link.evidence_ids:
            assert evidence[evidence_id].field_name == field_link.field_name
    assert all(not Path(row.path).is_absolute() for row in bundle.artifacts)
    assert any(row.path == "packet.json" for row in bundle.artifacts)
    packet_artifact = next(row for row in bundle.artifacts if row.path == "packet.json")
    assert all(row.artifact_id == packet_artifact.artifact_id for row in bundle.evidence)


def test_adapter_preserves_every_packet_source_locator(tmp_path):
    result_path = tmp_path / "result.json"
    packet_path = tmp_path / "packet.json"
    result_path.write_text(json.dumps(_slice("hepatocytes")))
    packet = _packet()
    packet["evidence"][1]["source_ids"] = ["S1", "S2"]
    packet_path.write_text(json.dumps(packet))

    bundle = build_np_bundle(
        result_paths=[result_path], packet_path=packet_path,
        paper_metadata={"title": "Example"},
    )

    rows = [row for row in bundle.evidence if row.field_name == "payload_type"]
    assert rows[0].structured_evidence["source_locators"] == [
        {"source_id": "S1", "section": "Methods", "page_number": 2},
        {"source_id": "S2", "section": "Results", "page_number": 4},
    ]


def test_generated_bundle_is_checkout_root_independent(tmp_path):
    payload = _slice("hepatocytes")
    packet = _packet()
    bundles = []
    for root in (tmp_path / "one", tmp_path / "two"):
        root.mkdir()
        (root / "result.json").write_text(json.dumps(payload))
        (root / "packet.json").write_text(json.dumps(packet))
        bundles.append(build_np_bundle(
            result_paths=[root / "result.json"], packet_path=root / "packet.json",
            paper_metadata={"title": "Example"},
        ))
    assert json.dumps(bundles[0].to_dict(), sort_keys=True) == json.dumps(
        bundles[1].to_dict(), sort_keys=True
    )


def test_adapter_rejects_evidence_missing_from_packet(tmp_path):
    result = _slice("hepatocytes")
    result["experiments"][0]["dose"]["evidence_ids"] = ["DOES-NOT-EXIST"]
    result_path = tmp_path / "result.json"
    packet_path = tmp_path / "packet.json"
    result_path.write_text(json.dumps(result))
    packet_path.write_text(json.dumps(_packet()))

    with pytest.raises(ValueError, match="unknown packet evidence"):
        build_np_bundle(
            result_paths=[result_path],
            packet_path=packet_path,
            paper_metadata={"title": "Example"},
        )


def test_real_np_artifacts_generate_deterministic_valid_bundles(tmp_path):
    np1 = build_np_bundle(
        result_paths=[ROOT / "data/staging/extraction/np001_primary_paid_v1/NP-001/result.json"],
        packet_path=ROOT / "data/staging/rag/compact_api_packets_v1/NP-001.json",
        paper_metadata={
            "title": "Encapsulation of Dexamethasone into mRNA-Lipid Nanoparticles",
            "doi": "10.3390/ijms252011254",
            "pmcid": "PMC11508592",
        },
    )
    np2_paths = sorted((ROOT / "data/staging/extraction/np002_isolated_liver_cell_run").glob("*/result.json"))
    np2 = build_np_bundle(
        result_paths=np2_paths,
        packet_path=ROOT / "data/staging/rag/compact_api_packets_v1/NP-002.json",
        paper_metadata={
            "title": "Cell Subtypes Within the Liver Microenvironment Differentially Interact with Lipid Nanoparticles",
            "doi": "10.1007/s12195-019-00573-4",
            "pmid": "31719922",
            "pmcid": "PMC6816632",
        },
    )

    assert (len(np1.formulations), len(np1.arms), len(np1.outcomes)) == (1, 1, 1)
    assert (len(np2.arms), len(np2.outcomes)) == (13, 13)
    assert len(np2.formulations) == 2
    first = write_bundle(np2, tmp_path / "np2.json")
    second = write_bundle(np2, tmp_path / "np2.json")
    assert first == second
    assert ImportBundle.from_dict(json.loads(first.read_text())).paper.source_paper_id == "NP-002"
