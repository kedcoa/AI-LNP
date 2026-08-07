"""Simple read-only Streamlit browser for authoritative LNP evidence."""

from __future__ import annotations

import streamlit as st

try:
    from src.ui.evidence_browser_service import (
        ARM_FIELD_COLUMNS,
        FORMULATION_COLUMNS,
        OUTCOME_FIELD_COLUMNS,
        BrowserEvidence,
        BrowserFilters,
        BrowserField,
        BrowserIssue,
        default_browser_paper_id,
        list_browser_papers,
        list_combined_arm_rows,
        load_paper_browser,
    )
except ModuleNotFoundError:
    from evidence_browser_service import (  # type: ignore[no-redef]
        ARM_FIELD_COLUMNS,
        FORMULATION_COLUMNS,
        OUTCOME_FIELD_COLUMNS,
        BrowserEvidence,
        BrowserFilters,
        BrowserField,
        BrowserIssue,
        default_browser_paper_id,
        list_browser_papers,
        list_combined_arm_rows,
        load_paper_browser,
    )

try:
    from src.ui import review_service
except ModuleNotFoundError:
    import review_service  # type: ignore[no-redef]


COLUMN_LABELS = {
    "lnp_name": "LNP name",
    "chemical_formulation_total": "Chemical formulation (total)",
    "lnp_molar_ratio": "LNP molar ratio",
    "ionizable_lipid": "Ionizable lipid",
    "helper_lipid": "Helper lipid",
    "cholesterol": "Cholesterol",
    "peg_lipid": "PEG lipid",
    "others": "Others",
}

FIELD_LABELS = {
    "cell_type": "Target cell",
    "cell_source": "Cell source",
    "tissue_or_organ": "Tissue or organ",
    "species": "Species",
    "disease_model": "Biological model",
    "in_vitro_in_vivo": "Delivery setting",
    "route": "Route",
    "payload_type": "Payload type",
    "payload_name": "Payload name",
    "payload_encoded_product": "Encoded product",
    "payload_molecular_target": "Molecular target",
    "dose": "Dose",
    "assay": "Assay",
    "timepoint": "Timepoint",
    "comparator_type": "Comparator type",
    "comparator_description": "Comparator",
    "protocol_reference": "Protocol reference",
    "endpoint_family": "Endpoint family",
    "endpoint_name": "Endpoint name",
    "outcome_value": "Outcome value",
    "outcome_unit": "Outcome unit",
    "normalization_basis": "Normalization basis",
    "uncertainty_value": "Uncertainty",
    "uncertainty_type": "Uncertainty type",
    "qualitative_outcome": "Qualitative outcome",
    "value_status": "Value status",
}


def _plain_label(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _validation_label(value: str) -> str:
    if value == "manually_verified":
        return "COMET reviewed"
    if value == "automatically_validated":
        return "Automatically validated"
    if value == "rejected":
        return "Excluded from automatic use"
    return _plain_label(value)


def _reason_label(value: str) -> str:
    if value in {"manually_verified", "manually_verified_evidence"}:
        return "COMET evidence requirement"
    return _plain_label(value)


def _evidence_text(evidence: tuple[BrowserEvidence, ...]) -> str:
    if not evidence:
        return "NA"
    return "\n\n".join(
        f"#{item.evidence_id}: {item.text}" for item in evidence
    )


def _evidence_locations(evidence: tuple[BrowserEvidence, ...]) -> str:
    if not evidence:
        return "NA"
    return "; ".join(
        f"#{item.evidence_id} {item.location}" for item in evidence
    )


def _evidence_methods(evidence: tuple[BrowserEvidence, ...]) -> str:
    if not evidence:
        return "NA"
    return "; ".join(
        f"#{item.evidence_id} {_plain_label(item.modality)} · {item.confidence} · "
        f"{_validation_label(item.verification_status)}"
        for item in evidence
    )


def _field_rows(
    fields: dict[str, BrowserField] | object,
    names: tuple[str, ...],
    labels: dict[str, str],
) -> list[dict[str, str]]:
    return [
        {
            "Field": labels.get(name, _plain_label(name)),
            "Value": fields[name].display_value,  # type: ignore[index]
            "Evidence": _evidence_text(fields[name].evidence),  # type: ignore[index]
            "Location": _evidence_locations(fields[name].evidence),  # type: ignore[index]
            "Method / validation": _evidence_methods(fields[name].evidence),  # type: ignore[index]
        }
        for name in names
    ]


def _issue_rows(issues: tuple[BrowserIssue, ...]) -> list[dict[str, str]]:
    return [
        {
            "Reason": _reason_label(issue.reason_code),
            "Field": issue.field_name or "NA",
            "Status": _plain_label(issue.status),
            "Explanation": issue.notes or "NA",
        }
        for issue in issues
    ]


def _combined_rows(rows: tuple[object, ...]) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    for row in rows:
        values = {
            "Paper": row.paper.source_paper_id,  # type: ignore[attr-defined]
            "Paper title": row.paper.title,  # type: ignore[attr-defined]
            "DOI / paper link": next(iter(row.paper.links.values()), "NA"),  # type: ignore[attr-defined]
            "Arm ID": str(row.experiment_id),  # type: ignore[attr-defined]
        }
        values.update({
            COLUMN_LABELS[column]: row.formulation[column].display_value  # type: ignore[attr-defined]
            for column in FORMULATION_COLUMNS
        })
        values.update({
            "Target cell": row.arm_fields["cell_type"].display_value,  # type: ignore[attr-defined]
            "Species": row.arm_fields["species"].display_value,  # type: ignore[attr-defined]
            "Biological model": row.arm_fields["disease_model"].display_value,  # type: ignore[attr-defined]
            "Payload": row.arm_fields["payload_name"].display_value,  # type: ignore[attr-defined]
            "Encoded product": row.arm_fields["payload_encoded_product"].display_value,  # type: ignore[attr-defined]
            "Molecular target": row.arm_fields["payload_molecular_target"].display_value,  # type: ignore[attr-defined]
            "Dose": row.arm_fields["dose"].display_value,  # type: ignore[attr-defined]
            "Route": row.arm_fields["route"].display_value,  # type: ignore[attr-defined]
            "Timepoint": row.arm_fields["timepoint"].display_value,  # type: ignore[attr-defined]
            "Assay": row.arm_fields["assay"].display_value,  # type: ignore[attr-defined]
            "Outcomes": row.outcomes_display,  # type: ignore[attr-defined]
            "General use": "Ready" if row.general_usable else "Not ready",  # type: ignore[attr-defined]
            "Nearest neighbor": "Ready" if row.nearest_neighbor_ready else "Not ready",  # type: ignore[attr-defined]
            "COMET": "Ready" if row.comet_ready else "Not ready",  # type: ignore[attr-defined]
            "COMET blockers": ", ".join(row.comet_blockers) or "None",  # type: ignore[attr-defined]
            "Missing fields": ", ".join(row.missing_fields) or "None",  # type: ignore[attr-defined]
            "Automatic-resolution issues": ", ".join(
                issue.reason_code for issue in row.issues  # type: ignore[attr-defined]
            ) or "None",
        })
        rendered.append(values)
    return rendered


def _render_eligibility(
    nearest: bool,
    comet: bool,
    nearest_blockers: tuple[str, ...],
    comet_blockers: tuple[str, ...],
) -> None:
    nearest_column, comet_column = st.columns(2)
    with nearest_column:
        st.markdown(
            f"**Nearest neighbor:** {'Ready' if nearest else 'Not ready'}"
        )
        st.caption(
            "No blockers" if not nearest_blockers else
            "Blockers: " + ", ".join(_reason_label(item) for item in nearest_blockers)
        )
    with comet_column:
        st.markdown(f"**COMET:** {'Ready' if comet else 'Not ready'}")
        st.caption(
            "No blockers" if not comet_blockers else
            "Blockers: " + ", ".join(_reason_label(item) for item in comet_blockers)
        )


def _render_comet_gap_correction() -> None:
    st.subheader("Almost COMET-ready corrections")
    st.caption(
        "Only small COMET gaps appear here. General application rows do not require human approval."
    )
    try:
        arms = review_service.list_comet_gap_arms()
    except Exception as error:
        st.error(f"Could not load the COMET correction queue: {error}")
        return
    if not arms:
        st.success("No almost-COMET-ready arms currently need a correction.")
        return
    arm_ids = [arm.experiment_id for arm in arms]
    experiment_id = st.selectbox(
        "COMET arm",
        arm_ids,
        format_func=lambda value: next(
            f"{arm.source_paper_id} · arm #{arm.experiment_id} · "
            f"{len(arm.comet_blockers)} missing"
            for arm in arms if arm.experiment_id == value
        ),
    )
    workspace = review_service.load_arm_workspace(int(experiment_id))
    links = review_service.paper_access_links(workspace.paper)
    st.markdown(f"**{workspace.paper.source_paper_id} · {workspace.paper.title}**")
    link_values = [
        ("PMC", links.pmc_url), ("PubMed", links.pubmed_url),
        ("DOI / publisher", links.doi_url), ("Source", links.source_url),
        ("Local full text", links.local_full_text_url),
    ]
    available_links = [(label, url) for label, url in link_values if url]
    if available_links:
        columns = st.columns(len(available_links))
        for column, (label, url) in zip(columns, available_links):
            column.link_button(label, url, width="stretch")

    arm = next(item for item in arms if item.experiment_id == experiment_id)
    aliases = {
        "formulation_identity": "formulation",
        "formulation_composition": "chemical_formulation_total",
        "payload_identity": "payload_name",
        "encoded_product": "payload_encoded_product",
        "molecular_target": "payload_molecular_target",
    }
    by_name = {field.name: field for field in workspace.fields}
    candidates = []
    for blocker in arm.comet_blockers:
        name = aliases.get(blocker, blocker)
        field = by_name.get(name) or next(
            (item for item in workspace.fields if item.field_name == name), None
        )
        if field is not None and field not in candidates:
            candidates.append(field)
    if not candidates:
        st.info("These blockers need automatic relationship repair, not a typed value.")
        return
    selected_name = st.selectbox(
        "Missing field", [field.name for field in candidates],
        format_func=lambda value: next(
            field.label for field in candidates if field.name == value
        ),
    )
    selected = next(field for field in candidates if field.name == selected_name)
    st.caption(
        "Current value: " + (selected.value or "NA")
        + " · COMET blockers: " + ", ".join(arm.comet_blockers)
    )
    updated_value = st.text_input("Updated value")
    evidence_excerpt = st.text_area("Evidence excerpt")
    evidence_location = st.text_input(
        "Evidence location", placeholder="Methods, page 4; Table S2; patent example 12"
    )
    reviewer = st.text_input("Reviewer", value="researcher")
    if st.button("Save correction", type="primary"):
        if not all((updated_value.strip(), evidence_excerpt.strip(), evidence_location.strip(), reviewer.strip())):
            st.error("Updated value, evidence excerpt, evidence location, and reviewer are required.")
        else:
            try:
                readiness = review_service.prepare_writes(
                    review_service.review_backup_directory()
                )
                if not readiness.ready:
                    raise RuntimeError(readiness.failure_reason or "Could not prepare a safe write")
                result = review_service.apply_review_decision(review_service.ReviewDecision(
                    experiment_id=workspace.arm.experiment_id,
                    entity_type=selected.entity_type,
                    entity_id=selected.entity_id,
                    field_name=selected.field_name,
                    decision="correct",
                    corrected_value=updated_value,
                    evidence_excerpt=evidence_excerpt,
                    evidence_location=evidence_location,
                    reviewer=reviewer,
                    reviewer_notes="COMET gap correction entered in compact browser form.",
                    expected_review_revision_id=max(
                        (item.review_revision_id for item in workspace.history), default=0
                    ),
                    expected_state_token=workspace.state_token,
                    write_readiness=readiness,
                ))
            except (KeyError, ValueError, RuntimeError) as error:
                st.error(str(error))
            else:
                st.success(
                    "Correction saved. COMET was recalculated under "
                    f"{result.comet.rules_version}."
                )
                st.rerun()
    with st.expander("Evidence history and current arm details"):
        st.dataframe(
            [{"Field": field.label, "Value": field.value or "NA"}
             for field in workspace.fields],
            hide_index=True, width="stretch",
        )
        for excerpt in workspace.evidence:
            st.write(excerpt.text)
            st.caption(f"#{excerpt.evidence_id} · {excerpt.location or excerpt.location_type}")


def _render_formulation(formulation: object) -> None:
    cells = formulation.cells  # type: ignore[attr-defined]
    name = cells["lnp_name"].display_value
    with st.expander(f"{name} · formulation #{formulation.formulation_id}"):  # type: ignore[attr-defined]
        st.subheader("Formulation evidence")
        st.dataframe(
            _field_rows(cells, FORMULATION_COLUMNS, COLUMN_LABELS),
            hide_index=True,
            width="stretch",
        )

        st.subheader("Experimental arms")
        arms = formulation.arms  # type: ignore[attr-defined]
        if not arms:
            st.info("No experimental arms are linked to this formulation.")
            return
        for arm in arms:
            with st.container(border=True):
                st.markdown(f"#### Experimental arm #{arm.experiment_id}")
                st.caption(
                    f"Completeness: {_plain_label(arm.completeness_status)} · "
                    f"Validation: {_validation_label(arm.verification_status)}"
                )
                _render_eligibility(
                    arm.nearest_neighbor_eligible,
                    arm.comet_eligible,
                    arm.nearest_neighbor_blockers,
                    arm.comet_blockers,
                )
                st.dataframe(
                    _field_rows(arm.fields, ARM_FIELD_COLUMNS, FIELD_LABELS),
                    hide_index=True,
                    width="stretch",
                )

                st.markdown("##### Outcomes")
                if not arm.outcomes:
                    st.info("No normalized outcomes are linked to this arm.")
                for outcome in arm.outcomes:
                    st.markdown(f"**Outcome #{outcome.outcome_id}**")
                    st.dataframe(
                        _field_rows(
                            outcome.fields,
                            OUTCOME_FIELD_COLUMNS,
                            FIELD_LABELS,
                        ),
                        hide_index=True,
                        width="stretch",
                    )

                st.markdown("##### Automatic-resolution issues")
                if arm.issues:
                    st.dataframe(
                        _issue_rows(arm.issues),
                        hide_index=True,
                        width="stretch",
                    )
                else:
                    st.caption("None recorded for this arm.")


def main() -> None:
    st.set_page_config(
        page_title="AI-LNP evidence browser",
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
          .stApp { background: #f5f7f6; color: #17211d; }
          [data-testid="stSidebar"] { background: #edf2ef; border-right: 1px solid #d8e1dc; }
          .paper-card { background: white; border: 1px solid #dbe3df; border-radius: 12px;
            padding: 1rem 1.1rem; margin-bottom: .7rem; box-shadow: 0 1px 3px rgba(20,40,30,.04); }
          .eyebrow { color: #567065; font-size: .74rem; font-weight: 750; letter-spacing: .08em;
            text-transform: uppercase; }
          div[data-testid="stMetric"] { background: white; border: 1px solid #dbe3df;
            border-radius: 11px; padding: .65rem .8rem; }
          div[data-testid="stDataFrame"] { border: 1px solid #dbe3df; border-radius: 9px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("LNP evidence browser")
    st.caption(
        "Authoritative SQLite evidence · read-only · missing values and missing evidence display as NA"
    )
    try:
        papers = list_browser_papers()
        all_arm_rows = list_combined_arm_rows()
    except Exception as error:
        st.error(f"Could not open the authoritative evidence database: {error}")
        return
    if not papers:
        st.warning("The evidence database contains no papers.")
        return

    with st.sidebar:
        st.header("Papers")
        search = st.text_input("Search", placeholder="Paper ID or title").casefold().strip()
        visible = tuple(
            paper for paper in papers
            if not search
            or search in paper.source_paper_id.casefold()
            or search in paper.title.casefold()
        )
        if not visible:
            st.warning("No papers match this search.")
            return
        visible_ids = [paper.paper_id for paper in visible]
        selected_id = st.selectbox(
            "Paper",
            options=visible_ids,
            index=visible_ids.index(default_browser_paper_id(visible)),
            format_func=lambda paper_id: next(
                f"{paper.source_paper_id} · {paper.title}"
                for paper in visible if paper.paper_id == paper_id
            ),
        )
        st.divider()
        st.header("Combined table filters")
        combined_papers = st.multiselect(
            "Combined table papers",
            options=[paper.source_paper_id for paper in papers if paper.counts.arms],
        )
        cell_types = sorted({
            row.arm_fields["cell_type"].value
            for row in all_arm_rows if row.arm_fields["cell_type"].value
        })
        combined_cells = st.multiselect("Cell type", options=cell_types)
        general_choice = st.selectbox("General use", ("All", "Ready", "Not ready"))
        nearest_choice = st.selectbox("Nearest-neighbor readiness", ("All", "Ready", "Not ready"))
        comet_choice = st.selectbox("COMET readiness", ("All", "Ready", "Not ready"))
        blockers = sorted({
            blocker for row in all_arm_rows
            for blocker in (*row.nearest_neighbor_blockers, *row.comet_blockers)
        })
        blocker_choice = st.selectbox("Required blocker", ("All", *blockers))

    def ready_filter(value: str) -> bool | None:
        return None if value == "All" else value == "Ready"

    combined = list_combined_arm_rows(BrowserFilters(
        paper_ids=tuple(combined_papers),
        cell_types=tuple(combined_cells),
        general_usable=ready_filter(general_choice),
        nearest_neighbor_ready=ready_filter(nearest_choice),
        comet_ready=ready_filter(comet_choice),
        blocker=None if blocker_choice == "All" else blocker_choice,
    ))
    st.subheader("Combined experimental arms")
    st.caption(
        "One row is one experimental arm. Multiple outcomes stay separate in SQLite and are stacked inside the Outcomes cell. NA means the value is absent."
    )
    st.dataframe(_combined_rows(combined), hide_index=True, width="stretch")
    st.caption(f"Showing {len(combined)} of {len(all_arm_rows)} canonical arms.")
    st.divider()
    _render_comet_gap_correction()
    st.divider()

    try:
        view = load_paper_browser(int(selected_id))
    except Exception as error:
        st.error(f"Could not load the selected paper: {error}")
        return
    paper = view.paper

    st.subheader("Paper access")
    st.markdown(
        f'<div class="paper-card"><div class="eyebrow">{paper.source_paper_id}</div>'
        f'<h3 style="margin:.25rem 0 .35rem">{paper.title}</h3>'
        f'<div>Full text: {_plain_label(paper.full_text_status)} · '
        f'Import: {_plain_label(paper.import_status)}</div></div>',
        unsafe_allow_html=True,
    )
    if paper.links:
        columns = st.columns(len(paper.links))
        for column, (label, url) in zip(columns, paper.links.items()):
            column.link_button(label, url, width="stretch")
    else:
        st.caption("No paper links are available in the database.")

    for column, label, value in zip(
        st.columns(6),
        ("Formulations", "Components", "Experimental arms", "Outcomes", "Evidence", "Resolution issues"),
        (
            view.counts.formulations,
            view.counts.components,
            view.counts.arms,
            view.counts.outcomes,
            view.counts.evidence_records,
            view.counts.automatic_resolution_issues,
        ),
    ):
        column.metric(label, value)

    st.subheader("LNP formulations")
    if not view.formulations:
        if paper.import_status == "screening_only":
            st.info("This paper is screening-only, so it has no scientific database rows.")
        else:
            st.info("No canonical LNP formulations are available for this paper.")
        return

    table_rows = [
        {
            column: formulation.cells[column].display_value
            for column in FORMULATION_COLUMNS
        }
        for formulation in view.formulations
    ]
    st.dataframe(table_rows, hide_index=True, width="stretch")
    st.caption(
        "One row represents one canonical formulation. Expand a formulation below to see its evidence and separate experimental arms."
    )

    for formulation in view.formulations:
        _render_formulation(formulation)

    if view.issues:
        st.subheader("Paper-level automatic-resolution issues")
        st.dataframe(_issue_rows(view.issues), hide_index=True, width="stretch")

    st.caption(
        "Combined evidence tables are read-only · COMET corrections are append-only and backed up before saving"
    )


main()
