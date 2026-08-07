"""Shared result contracts for lossless source-format adapters."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.import_contracts import ImportBundle
from src.database.source_fact_import import SourceArtifactRecord, SourceFactRecord


@dataclass(frozen=True)
class AdapterCoverage:
    source_entities: int = 0
    source_claims: int = 0
    source_experiments: int = 0
    source_fields: int = 0
    unresolved_items: int = 0
    silent_omissions: int = 0


@dataclass(frozen=True)
class LosslessAdapterResult:
    bundle: ImportBundle
    artifact: SourceArtifactRecord
    source_facts: tuple[SourceFactRecord, ...]
    coverage: AdapterCoverage
    contributing_artifacts: tuple[SourceArtifactRecord, ...] = field(
        default_factory=tuple
    )

    @property
    def source_fact_count(self) -> int:
        return len(self.source_facts)
