"""Interactive side-by-side experiment-boundary review."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "data" / "review" / "day5_g1_v3_boundary_review.jsonl"


def load():
    return [json.loads(line) for line in REVIEW.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(rows):
    with NamedTemporaryFile("w", encoding="utf-8", dir=REVIEW.parent, delete=False) as handle:
        temporary = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temporary, REVIEW)


def render_reader(experiments, sentence_lookup):
    for index, experiment in enumerate(experiments, 1):
        with st.expander(f"Experiment {index}: {experiment['experiment_label']}", expanded=True):
            st.write(f"**Scope:** {', '.join(experiment['evidence_sentence_ids'])}")
            st.write(f"**Why distinct:** {experiment['distinctness_reason']}")
            for sentence_id in experiment["evidence_sentence_ids"]:
                st.info(f"{sentence_id}: {sentence_lookup[sentence_id]}")


def main():
    st.set_page_config(page_title="G1 v3 experiment boundaries", layout="wide")
    rows = load()
    complete = sum(row.get("boundary_decision") in {"reader_a", "reader_b", "custom_required"} for row in rows)
    st.title("G1 v3 · Freeze experiment boundaries")
    st.caption("Choose the map that correctly separates experimental events. Detailed fields will be extracted only after these boundaries are frozen.")
    st.progress(complete / len(rows), text=f"{complete} of {len(rows)} papers reviewed")
    labels = [f"{row['review_id']} · {row['paper_id']} · A={row['reader_a_count']} / B={row['reader_b_count']}" for row in rows]
    selected = st.selectbox("Paper", labels)
    index = labels.index(selected)
    row = rows[index]
    st.subheader(row["title"])
    sentence_lookup = {sentence["sentence_id"]: sentence["text"] for sentence in row["sentences"]}
    with st.expander("Numbered abstract", expanded=False):
        for sentence in row["sentences"]:
            st.write(f"**{sentence['sentence_id']}** {sentence['text']}")
    left, right = st.columns(2)
    with left:
        st.header(f"Reader A · {row['reader_a_count']} experiments")
        render_reader(row["reader_a"], sentence_lookup)
    with right:
        st.header(f"Reader B · {row['reader_b_count']} experiments")
        render_reader(row["reader_b"], sentence_lookup)
    with st.form(f"boundary-{row['paper_id']}"):
        options = ["reader_a", "reader_b", "custom_required"]
        existing = row.get("boundary_decision")
        choice = st.radio("Boundary decision", options, index=options.index(existing) if existing in options else None, format_func=lambda x: {"reader_a": "Use Reader A", "reader_b": "Use Reader B", "custom_required": "Neither — custom map required"}[x])
        reason = st.text_area("Reason or custom-map instructions (required)", value=row.get("reviewer_reason", ""))
        reviewer = st.text_input("Reviewer", value=row.get("reviewer", "renemilywei"))
        submitted = st.form_submit_button("Save boundary decision", type="primary")
    if submitted:
        if choice is None or not reason.strip() or not reviewer.strip():
            st.error("Decision, reason, and reviewer are required.")
        else:
            row["boundary_decision"] = choice
            row["reviewer_reason"] = reason.strip()
            row["reviewer"] = reviewer.strip()
            row["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            save(rows)
            st.rerun()
    if complete == len(rows):
        st.success("All boundary decisions are saved. Return to Codex to freeze the selected maps.")


if __name__ == "__main__":
    main()
