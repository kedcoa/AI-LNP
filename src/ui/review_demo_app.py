"""Interactive Streamlit prototype for reviewing fictional extraction data."""

from __future__ import annotations

import streamlit as st

try:
    from src.ui.review_demo_state import (
        DemoArm,
        DemoPaper,
        apply_decision,
        demo_papers,
        queue_items,
        simulate_eligibility,
    )
except ModuleNotFoundError:
    from review_demo_state import (  # type: ignore[no-redef]
        DemoArm,
        DemoPaper,
        apply_decision,
        demo_papers,
        queue_items,
        simulate_eligibility,
    )


st.set_page_config(
    page_title="AI-LNP review workspace demo",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .stApp { background: #f5f7f6; color: #17211d; }
      [data-testid="stSidebar"] { background: #edf2ef; border-right: 1px solid #d8e1dc; }
      .demo-banner { background: #fff3cd; border: 1px solid #ecd37a; border-radius: 10px;
        padding: .75rem 1rem; margin-bottom: 1rem; color: #574711; font-weight: 650; }
      .paper-card { background: white; border: 1px solid #dbe3df; border-radius: 12px;
        padding: 1rem 1.1rem; margin-bottom: .65rem; box-shadow: 0 1px 3px rgba(20,40,30,.04); }
      .eyebrow { color: #567065; font-size: .74rem; font-weight: 750; letter-spacing: .08em;
        text-transform: uppercase; }
      .status-verified { color: #17633a; font-weight: 700; }
      .status-needs_confirmation { color: #8a5d00; font-weight: 700; }
      .status-missing, .status-conflict { color: #a43b34; font-weight: 700; }
      .status-not_reported { color: #52615a; font-weight: 700; }
      div[data-testid="stMetric"] { background: white; border: 1px solid #dbe3df;
        border-radius: 11px; padding: .65rem .8rem; }
      .mock-note { color: #66746e; font-size: .82rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _initialize() -> tuple[tuple[DemoPaper, ...], dict[str, DemoArm]]:
    papers = demo_papers()
    if "demo_arms" not in st.session_state:
        st.session_state.demo_arms = {
            arm.arm_id: arm for paper in papers for arm in paper.arms
        }
    if "selected_arm" not in st.session_state:
        st.session_state.selected_arm = papers[0].arms[0].arm_id
    return papers, st.session_state.demo_arms


def _paper_for(papers: tuple[DemoPaper, ...], paper_id: str) -> DemoPaper:
    return next(paper for paper in papers if paper.paper_id == paper_id)


def _status_label(status: str) -> str:
    return status.replace("_", " ").title()


papers, arm_state = _initialize()

st.markdown(
    '<div class="demo-banner">DEMO DATA ONLY · Fictional papers, arms, links, and evidence. '
    "This prototype is not connected to the real database and saves nothing permanently.</div>",
    unsafe_allow_html=True,
)

title_col, reset_col = st.columns([8, 1])
with title_col:
    st.title("Evidence review workspace")
    st.caption("Queue-first prototype for reviewing extracted experimental arms")
with reset_col:
    if st.button("Reset demo", width="stretch"):
        for key in ("demo_arms", "selected_arm", "selected_field"):
            st.session_state.pop(key, None)
        st.rerun()

all_arms = tuple(arm_state.values())
pending = sum(
    any(value.status in {"missing", "needs_confirmation", "conflict"} for value in arm.fields.values())
    for arm in all_arms
)
near = sum(len(simulate_eligibility(arm).nearest_neighbor_reasons) <= 2 for arm in all_arms)
conflicts = sum(any(value.status == "conflict" for value in arm.fields.values()) for arm in all_arms)
nn_ready = sum(simulate_eligibility(arm).nearest_neighbor_eligible for arm in all_arms)
comet_ready = sum(simulate_eligibility(arm).comet_eligible for arm in all_arms)
metrics = st.columns(5)
for column, label, value in zip(
    metrics,
    ("Awaiting review", "Nearly eligible", "Conflicts", "NN eligible", "COMET eligible"),
    (pending, near, conflicts, nn_ready, comet_ready),
):
    column.metric(label, value)

with st.sidebar:
    st.header("Review queue")
    st.caption("Fictional arms ordered by what needs attention")
    paper_filter = st.multiselect(
        "Paper",
        options=[paper.paper_id for paper in papers],
        default=[],
    )
    reason_options = sorted({arm.primary_reason for arm in all_arms})
    reason_filter = st.multiselect("Review reason", options=reason_options, default=[])
    near_filter = st.checkbox("Only show nearly eligible arms", value=False)
    visible = queue_items(
        papers,
        paper_ids=tuple(paper_filter),
        reasons=tuple(reason_filter),
        near_eligibility=near_filter,
    )
    visible_ids = [arm.arm_id for arm in visible]
    if not visible_ids:
        st.warning("No mock arms match these filters.")
    else:
        if st.session_state.selected_arm not in visible_ids:
            st.session_state.selected_arm = visible_ids[0]
        selected = st.radio(
            "Select an arm",
            visible_ids,
            index=visible_ids.index(st.session_state.selected_arm),
            format_func=lambda arm_id: (
                f"{arm_state[arm_id].paper_id} · {arm_state[arm_id].primary_reason}"
            ),
            label_visibility="collapsed",
        )
        st.session_state.selected_arm = selected
        selected_preview = simulate_eligibility(arm_state[selected])
        st.divider()
        st.caption(
            f"Nearest-neighbor blockers: {len(selected_preview.nearest_neighbor_reasons)}  ·  "
            f"COMET blockers: {len(selected_preview.comet_reasons)}"
        )

arm = arm_state[st.session_state.selected_arm]
paper = _paper_for(papers, arm.paper_id)

st.subheader("Paper access")
st.markdown(
    f"""
    <div class="paper-card">
      <div class="eyebrow">{paper.paper_id} · fictional citation</div>
      <h3 style="margin:.25rem 0 .35rem">{paper.title}</h3>
      <div>{paper.citation}</div>
      <div class="mock-note">DOI {paper.doi} · PMID {paper.pmid} · {paper.pmcid}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
links = st.columns(5)
for column, label, url in zip(
    links,
    ("DOI / publisher", "PubMed", "PDF", "HTML full text", "Institutional access"),
    (paper.doi_url, paper.pubmed_url, paper.pdf_url, paper.html_url, paper.library_url),
):
    column.link_button(label, url, width="stretch")
st.caption("All access buttons lead to harmless example.org demo destinations.")

workspace, inspector = st.columns([1.55, 1], gap="large")
with workspace:
    st.subheader("Experimental arm")
    st.caption(f"{arm.label} · Primary review reason: {arm.primary_reason}")
    field_rows = [
        {
            "Field": value.label,
            "Extracted value": value.value,
            "Status": _status_label(value.status),
        }
        for value in arm.fields.values()
    ]
    st.dataframe(field_rows, hide_index=True, width="stretch", height=390)

with inspector:
    st.subheader("Evidence inspector")
    selected_field = st.selectbox(
        "Choose a field",
        options=list(arm.fields),
        format_func=lambda name: arm.fields[name].label,
        key="selected_field",
    )
    field_value = arm.fields[selected_field]
    st.markdown(
        f'<div class="status-{field_value.status}">{_status_label(field_value.status)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f"**Current value:** {field_value.value}")
    if not field_value.evidence:
        st.warning("No matching mock evidence excerpt was extracted for this field.")
    for index, evidence in enumerate(field_value.evidence, 1):
        with st.container(border=True):
            st.markdown(f"**Excerpt {index}**")
            st.write(f'“{evidence.excerpt}”')
            st.caption(
                f"{evidence.location} · {evidence.modality} · {evidence.confidence}"
            )

st.divider()
decision_col, eligibility_col = st.columns([1, 1], gap="large")
with decision_col:
    st.subheader("Review decision")
    action_label = st.radio(
        "What should happen to the selected field?",
        ("Accept extracted value", "Correct value", "Mark not reported", "Leave unresolved"),
        horizontal=True,
    )
    action_map = {
        "Accept extracted value": "accept",
        "Correct value": "correct",
        "Mark not reported": "not_reported",
        "Leave unresolved": "unresolved",
    }
    corrected = st.text_input(
        "Corrected value",
        value=field_value.value if action_label == "Correct value" else "",
        disabled=action_label != "Correct value",
        placeholder="Enter the value found during human review",
    )
    st.checkbox("Evidence belongs to another arm", value=False, help="Visual demo only; no reassignment is saved.")
    if st.button("Apply mock decision", type="primary"):
        try:
            updated_arm = apply_decision(
                arm,
                selected_field,
                action_map[action_label],  # type: ignore[arg-type]
                corrected_value=corrected,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.demo_arms[arm.arm_id] = updated_arm
            st.success("Mock decision applied in this browser session only.")
            st.rerun()

with eligibility_col:
    st.subheader("Eligibility preview")
    st.caption("Illustrative interface simulation—not the production eligibility engine.")
    preview = simulate_eligibility(arm)
    nn_color = "green" if preview.nearest_neighbor_eligible else "orange"
    comet_color = "green" if preview.comet_eligible else "orange"
    st.markdown(
        f":{nn_color}[**Nearest neighbor:** {'Eligible' if preview.nearest_neighbor_eligible else 'Not yet eligible'}]"
    )
    if preview.nearest_neighbor_reasons:
        st.write("Remaining: " + ", ".join(preview.nearest_neighbor_reasons))
    st.markdown(
        f":{comet_color}[**COMET:** {'Eligible' if preview.comet_eligible else 'Not yet eligible'}]"
    )
    if preview.comet_reasons:
        st.write("Remaining: " + ", ".join(preview.comet_reasons))

st.caption("Prototype scope: reviewer experience only · fictional state resets on refresh · no production data is loaded")
