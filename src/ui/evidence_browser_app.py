"""Simple read-only Streamlit browser for authoritative LNP evidence."""

from __future__ import annotations

import streamlit as st

try:
    from src.ui.evidence_browser_service import (
        ARM_FIELD_COLUMNS,
        FORMULATION_COLUMNS,
        OUTCOME_FIELD_COLUMNS,
        BrowserEvidence,
        BrowserField,
        BrowserIssue,
        default_browser_paper_id,
        list_browser_papers,
        load_paper_browser,
    )
except ModuleNotFoundError:
    from evidence_browser_service import (  # type: ignore[no-redef]
        ARM_FIELD_COLUMNS,
        FORMULATION_COLUMNS,
        OUTCOME_FIELD_COLUMNS,
        BrowserEvidence,
        BrowserField,
        BrowserIssue,
        default_browser_paper_id,
        list_browser_papers,
        load_paper_browser,
    )


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

    st.caption("Read-only browser · no review decisions or database writes are available")


main()
