# Shared-context projection invariants

These rules encode the recurring JSON-to-SQLite mistakes found during the
2026-08-07 corpus repair. They are implementation requirements, not optional
human-review guidance.

- A normalized fact must populate the canonical SQLite field used by the UI
  and readiness rules. Legacy `tissue_or_organ` and `cell_source` fields alone
  are not sufficient; populate `target_or_recipient_organ` and
  `observed_transfected_cell` when the evidence supports them.
- A paper-level or protocol-level fact may be copied to sibling arms only when
  the source explicitly gives it shared scope (for example, “identical dose
  and time frame,” one fabrication method for all study LNPs, or one route for
  all listed cohorts). Every copied value retains the source evidence link.
- In-vitro recipient cells populate `intended_target_cell`; in-vivo organ
  delivery populates `target_or_recipient_organ`. An observed transfected cell
  is recorded separately and is not automatically treated as intended target.
- Rich cell labels are normalized to the closest database category without
  quarantining the arm. A label outside the small category vocabulary is not a
  scientific conflict and must not create a human-review gate.
- Payloads are never chemical components. Payload ratios such as mRNA:siRNA
  are never stored as the lipid molar ratio.
- Group labels such as `LNP3-LNP7` must be expanded when a source table gives
  one row per formulation. Each resulting arm keeps its own payload,
  formulation identity, carrier composition, outcomes, and evidence links.
- A structured outcome already present in a validated artifact must be
  projected into `outcome`; it must not remain only as an evidence identifier
  or an unresolved graph fact.
- Evidence linked through `import_field_evidence` counts as arm evidence even
  when the immutable evidence row is intentionally paper-scoped. Outcome
  readiness still requires an outcome-specific field-evidence link.
- Automatic validation may make an arm generally usable and
  nearest-neighbor-ready. COMET remains a separate, stricter profile and may
  require manual verification and quantitative outcome metadata.
- Source-backed repairs address stable arm record IDs, never transient integer
  SQLite IDs.
- A rebuild must fail regression tests if sibling arms lose shared organ,
  route, timepoint, formulation chemistry, or already-structured outcomes.

