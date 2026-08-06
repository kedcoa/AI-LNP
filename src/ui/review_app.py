"""Streamlit workspace for safely reviewing authoritative extraction evidence."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

try:
    from src.ui.review_service import (
        ArmWorkspace,
        ReviewDecision,
        ReviewResult,
        WriteReadiness,
        apply_review_decision,
        list_paper_summaries,
        list_review_arms,
        load_arm_workspace,
        load_dashboard,
        prepare_writes,
    )
except ModuleNotFoundError:
    from review_service import (  # type: ignore[no-redef]
        ArmWorkspace,
        ReviewDecision,
        ReviewResult,
        WriteReadiness,
        apply_review_decision,
        list_paper_summaries,
        list_review_arms,
        load_arm_workspace,
        load_dashboard,
        prepare_writes,
    )


st.set_page_config(page_title="AI-LNP evidence review", page_icon="🧪", layout="wide")
st.markdown(
    """
    <style>
      .stApp { background: #f5f7f6; color: #17211d; }
      [data-testid="stSidebar"] { background: #edf2ef; border-right: 1px solid #d8e1dc; }
      .paper-card { background: white; border: 1px solid #dbe3df; border-radius: 12px;
        padding: 1rem 1.1rem; margin-bottom: .65rem; }
      .eyebrow { color: #567065; font-size: .74rem; font-weight: 750; letter-spacing: .08em;
        text-transform: uppercase; }
      div[data-testid="stMetric"] { background: white; border: 1px solid #dbe3df;
        border-radius: 11px; padding: .65rem .8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


DECISIONS = {
    "Accept extracted value": "accept",
    "Correct value": "correct",
    "Mark not reported": "not_reported",
    "Reject evidence": "reject",
    "Evidence belongs to another arm": "wrong_arm",
    "Leave unresolved": "unresolved",
}


def _label(value: str | None) -> str:
    return (value or "not recorded").replace("_", " ").title()


def _source_links(workspace: ArmWorkspace) -> tuple[tuple[str, str], ...]:
    paper = workspace.paper
    links: list[tuple[str, str]] = []
    if paper.doi:
        links.append(("DOI / publisher", f"https://doi.org/{paper.doi}"))
    if paper.pmid:
        links.append(("PubMed", f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/"))
    if paper.pmcid:
        links.append(("PMC", f"https://pmc.ncbi.nlm.nih.gov/articles/{paper.pmcid}/"))
    if paper.source_url:
        links.append(("Source record", paper.source_url))
    return tuple(links)


def _show_eligibility(result: ReviewResult | None, workspace: ArmWorkspace) -> None:
    st.subheader("Eligibility after save")
    if result is None:
        nearest = workspace.arm.nearest_neighbor_eligible
        comet = workspace.arm.comet_eligible
        st.caption("Current saved eligibility; a successful review refreshes this immediately.")
        st.write(f"Nearest neighbor: {'Eligible' if nearest else 'Not yet eligible'}")
        st.write(f"COMET: {'Eligible' if comet else 'Not yet eligible'}")
        return
    st.success("Review saved. Eligibility was recalculated in the same transaction.")
    st.write(f"Nearest neighbor: {'Eligible' if result.nearest_neighbor.eligible else 'Not yet eligible'}")
    st.write(f"COMET: {'Eligible' if result.comet.eligible else 'Not yet eligible'}")
    if result.comet.reasons:
        st.caption("COMET blockers: " + ", ".join(result.comet.reasons))


def _readiness_message(readiness: WriteReadiness | None) -> None:
    if readiness is None:
        st.info("Read-only mode. Prepare a verified external backup before enabling decisions.")
    elif readiness.ready:
        st.success(f"Writes ready: verified backup at {readiness.backup_path}")
    else:
        st.error(f"Writes disabled: {readiness.failure_reason or 'backup verification failed'}")


def main() -> None:
    st.title("Evidence review workspace")
    st.caption("Authoritative SQLite evidence only · review revisions are additive and auditable")
    try:
        dashboard = load_dashboard()
        papers = list_paper_summaries()
        arms = list_review_arms()
    except Exception as error:
        st.error(f"Could not load the authoritative review workspace: {error}")
        return

    for column, label, value in zip(
        st.columns(5),
        ("Nearest-neighbor ready", "COMET ready", "Automatically validated facts",
         "Manually verified facts", "Usable field facts"),
        (dashboard.nearest_neighbor_ready_arms, dashboard.comet_ready_arms,
         dashboard.automatically_validated_usable_facts,
         dashboard.manually_verified_usable_facts, dashboard.usable_field_facts),
    ):
        column.metric(label, value)

    st.subheader("Paper inventory")
    st.dataframe([
        {"Paper": paper.source_paper_id or paper.paper_id, "Title": paper.title,
         "Formulations": paper.row_counts.formulations,
         "Chemical components": paper.row_counts.chemical_components,
         "Experimental arms": paper.row_counts.experimental_arms,
         "Outcomes": paper.row_counts.outcomes,
         "Evidence excerpts": paper.row_counts.evidence_excerpts,
         "Usable field facts": paper.row_counts.usable_field_facts,
         "Open review items": paper.row_counts.open_review_items,
         "History revisions": paper.row_counts.review_history_revisions}
        for paper in papers
    ], hide_index=True, width="stretch")

    with st.sidebar:
        st.header("Review queue")
        paper_options = sorted({arm.source_paper_id or str(arm.paper_id) for arm in arms})
        status_options = sorted({arm.review_status or "not_recorded" for arm in arms})
        reason_options = sorted({arm.review_reason_code or arm.review_reason or "not_recorded" for arm in arms})
        paper_filter = st.multiselect("Paper", paper_options)
        status_filter = st.multiselect("Review status", status_options)
        reason_filter = st.multiselect("Review reason", reason_options)
        near_filter = st.checkbox("Only show nearly eligible arms")
        visible = [
            arm for arm in arms
            if (not paper_filter or (arm.source_paper_id or str(arm.paper_id)) in paper_filter)
            and (not status_filter or (arm.review_status or "not_recorded") in status_filter)
            and (not reason_filter or (arm.review_reason_code or arm.review_reason or "not_recorded") in reason_filter)
            and (not near_filter or (not arm.comet_eligible and len(arm.comet_blockers) <= 2))
        ]
        if not visible:
            st.warning("No authoritative arms match these filters.")
            return
        identifiers = [arm.experiment_id for arm in visible]
        current = st.session_state.get("selected_experiment_id", identifiers[0])
        if current not in identifiers:
            current = identifiers[0]
        selected = st.radio(
            "Select an arm", identifiers, index=identifiers.index(current),
            format_func=lambda experiment_id: next(
                f"{arm.source_paper_id or arm.paper_id} · {arm.formulation or 'unnamed formulation'} · "
                f"{_label(arm.review_reason_code or arm.review_reason)}"
                for arm in visible if arm.experiment_id == experiment_id
            ), label_visibility="collapsed",
        )
        st.session_state.selected_experiment_id = selected

    try:
        workspace = load_arm_workspace(selected)
    except Exception as error:
        st.error(f"Could not load the selected arm: {error}")
        return

    paper = workspace.paper
    st.subheader("Paper access")
    st.markdown(
        f'<div class="paper-card"><div class="eyebrow">{paper.source_paper_id or paper.paper_id}</div>'
        f"<h3>{paper.title}</h3><div>Full text: {_label(paper.full_text_status)}</div></div>",
        unsafe_allow_html=True,
    )
    for column, (label, url) in zip(st.columns(4), _source_links(workspace)):
        column.link_button(label, url, width="stretch")

    details, inspector = st.columns([1.55, 1], gap="large")
    with details:
        st.subheader("Experimental arm")
        st.caption(f"Review status: {_label(workspace.arm.review_status)} · "
                   f"Reason: {_label(workspace.arm.review_reason_code or workspace.arm.review_reason)}")
        st.dataframe([
            {"Field": field.label, "Extracted value": field.value or "—",
             "Missing": "Yes" if field.is_blank else "No"}
            for field in workspace.fields
        ], hide_index=True, width="stretch", height=390)
    with inspector:
        st.subheader("Evidence inspector")
        field_names = [field.name for field in workspace.fields]
        field_by_name = {field.name: field for field in workspace.fields}
        selected_field = st.selectbox(
            "Choose a field", field_names,
            format_func=lambda name: field_by_name[name].label,
        )
        matching_evidence = [item for item in workspace.evidence if item.field_name == selected_field]
        shown_evidence = matching_evidence or list(workspace.evidence)
        evidence_id = st.selectbox(
            "Supporting evidence", [None] + [item.evidence_id for item in shown_evidence],
            format_func=lambda item: "Choose evidence" if item is None else next(
                f"#{excerpt.evidence_id} · {excerpt.location or excerpt.location_type}"
                for excerpt in shown_evidence if excerpt.evidence_id == item
            ),
        )
        for excerpt in shown_evidence:
            with st.container(border=True):
                st.write(f"{excerpt.text}")
                st.caption(f"#{excerpt.evidence_id} · {excerpt.location or excerpt.location_type} · "
                           f"{excerpt.modality} · {excerpt.confidence} · {_label(excerpt.verification_status)}")

    st.subheader("Review history")
    st.dataframe([
        {"When": item.reviewed_at, "Field": item.field_name, "Decision": item.review_action,
         "Previous value": item.previous_value or "—", "Reviewed value": item.corrected_value,
         "Reviewer": item.reviewer, "Note": item.reviewer_notes or "—"}
        for item in workspace.history
    ], hide_index=True, width="stretch")

    st.divider()
    decision_column, eligibility_column = st.columns(2, gap="large")
    with decision_column:
        st.subheader("Review decision")
        decision_label = st.radio("Decision", tuple(DECISIONS), horizontal=True)
        decision = DECISIONS[decision_label]
        corrected_value = st.text_input(
            "Corrected value", disabled=decision != "correct",
            placeholder="Value confirmed during human review",
        )
        reviewer = st.text_input("Reviewer")
        reviewer_notes = st.text_area("Reviewer note")
        readiness = st.session_state.get("write_readiness")
        _readiness_message(readiness)
        if st.button("Prepare writing session"):
            readiness = prepare_writes(Path("data/review_backups"))
            st.session_state.write_readiness = readiness
            st.rerun()
        needs_evidence = decision in {"accept", "correct", "reject", "wrong_arm"}
        can_submit = bool(
            isinstance(readiness, WriteReadiness) and readiness.ready and reviewer.strip()
            and reviewer_notes.strip() and (not needs_evidence or evidence_id is not None)
            and (decision != "correct" or corrected_value.strip())
        )
        if st.button("Submit review decision", type="primary", disabled=not can_submit):
            request = ReviewDecision(
                experiment_id=workspace.arm.experiment_id, field_name=selected_field,
                decision=decision, reviewer=reviewer, reviewer_notes=reviewer_notes,
                expected_review_revision_id=max(
                    (item.review_revision_id for item in workspace.history), default=0
                ), expected_state_token=workspace.state_token, write_readiness=readiness,
                corrected_value=corrected_value or None, evidence_id=evidence_id,
            )
            try:
                result = apply_review_decision(request)
            except (KeyError, ValueError, RuntimeError) as error:
                st.error(str(error))
            else:
                st.session_state.last_review_result = result
                st.rerun()
    with eligibility_column:
        _show_eligibility(st.session_state.pop("last_review_result", None), workspace)


if __name__ == "__main__":
    main()
