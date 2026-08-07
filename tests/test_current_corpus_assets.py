from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.rag.current_corpus_assets import (
    classify_link,
    discover_declared_assets,
    ingest_current_corpus_assets,
    resolve_declared_supplements,
    inventory_local_assets,
)


ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = Path("/Users/renemilywei/Desktop/AI-LNP")


def _gp8_entry() -> dict:
    manifest = json.loads(
        (ROOT / "config/database/current_corpus_v1.json").read_text()
    )
    return next(row for row in manifest["entries"] if row["paper_id"] == "GP-008")


def test_gp008_uses_existing_supplement_without_network(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("network must not be used for a registered local asset")

    monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
    assets = resolve_declared_supplements(
        _gp8_entry(), root=ROOT, allow_network=False
    )

    supplement = next(
        path for path in assets.local_files
        if path.name == "pnas.2534673123.sapp.pdf"
    )
    assert hashlib.sha256(supplement.read_bytes()).hexdigest() == (
        "6e4700f3b72972a63f77903a32cae1a85b100b4d1f1cf40fbfdbc2b5d0f555d6"
    )
    assert not assets.access_blockers


def test_asset_classifier_ignores_navigation_links() -> None:
    assert classify_link("About this journal", "/about") is None
    assert classify_link("Supplementary Table S1", "mmc1.xlsx") == "supplement"
    assert classify_link("Supplementary data", "asset?id=8921") == "supplement"


def test_asset_classifier_recognizes_scientific_link_kinds() -> None:
    assert classify_link(
        "Lipids and lipid nanoparticle formulations",
        "https://patents.google.com/patent/US10221127B2/en",
        element_name="ext-link",
        citation_context="US patent US10,221,127",
    ) == "patent"
    assert classify_link("Study protocol", "protocol.pdf") == "protocol"
    assert classify_link("Source data", "dataset.xlsx") == "dataset"


def test_declared_asset_discovery_is_selective_and_local_first() -> None:
    assets = discover_declared_assets(
        (ROOT / "tests/fixtures/assets/paper_with_scientific_links.nxml",)
    )

    assert {(row.kind, row.filename) for row in assets} == {
        ("supplement", "mmc1.xlsx"),
        ("patent", "US10221127"),
    }
    supplement = next(row for row in assets if row.kind == "supplement")
    patent = next(row for row in assets if row.kind == "patent")
    assert supplement.provenance_scope == "direct_source_asset"
    assert patent.provenance_scope == "indirect_reference"


def test_jats_keyword_discovers_opaque_local_supplement(tmp_path: Path) -> None:
    source = tmp_path / "paper.nxml"
    supplement = tmp_path / "asset8921.pdf"
    supplement.write_bytes(b"supplement")
    source.write_text(
        '<article xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<supplementary-material xlink:href="asset8921.pdf">'
        'Supplementary methods</supplementary-material></article>'
    )
    entry = {
        "paper_id": "P1",
        "contributing_artifacts": [
            {"role": "source_document", "path": "paper.nxml"}
        ],
    }

    inventory = inventory_local_assets(entry, tmp_path)

    assert supplement.resolve() in inventory.local_files


def test_gp008_local_supplement_yields_page_four_ratio() -> None:
    assets = resolve_declared_supplements(
        _gp8_entry(), root=MAIN_ROOT, allow_network=False
    )
    blocks = ingest_current_corpus_assets(_gp8_entry(), assets)
    page = next(
        block for block in blocks
        if block.source_path.endswith("pnas.2534673123.sapp.pdf")
        and block.page_number == 4
    )
    assert "45:30:23.5:1.5" in page.text
