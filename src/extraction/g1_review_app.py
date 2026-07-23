"""Interactive local reviewer for the Day 5 G1 decision packet."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIEW_FILE = Path(os.getenv("G1_REVIEW_FILE", ROOT / "data" / "review" / "day5_g1_human_review.jsonl"))
DECISIONS = ("pending", "correct", "incorrect", "ambiguous_or_absent")


def load_records(path: Path = DEFAULT_REVIEW_FILE) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_records(records: list[dict[str, Any]], path: Path = DEFAULT_REVIEW_FILE) -> None:
    """Atomically replace the review file so interrupted saves cannot corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def apply_decision(
    records: list[dict[str, Any]],
    *,
    review_id: str,
    decision: str,
    reason: str,
    reviewer: str,
) -> None:
    if decision not in DECISIONS or decision == "pending":
        raise ValueError("A final decision is required")
    if not reason.strip():
        raise ValueError("A reviewer reason is required")
    if not reviewer.strip():
        raise ValueError("A reviewer name is required")
    record = next(item for item in records if item["review_id"] == review_id)
    record["human_decision"] = decision
    record["reviewer_reason"] = reason.strip()
    record["reviewer"] = reviewer.strip()
    record["reviewed_at"] = datetime.now(timezone.utc).isoformat()


def record_summary(record: dict[str, Any]) -> str:
    return " · ".join(
        part
        for part in (
            record.get("paper_id"),
            record.get("entity_type"),
            record.get("field_name"),
        )
        if part
    )


def structured_value_rows(record: dict[str, Any]) -> list[dict[str, str]]:
    """Turn one extracted entity into compact human-readable reported fields."""
    rows: list[dict[str, str]] = []
    for field_name, field in record.items():
        if field_name.endswith("_id") and not isinstance(field, dict):
            rows.append({"Field": field_name, "Extracted value": str(field), "Evidence": "Record/link identifier"})
            continue
        if isinstance(field, dict) and field.get("status") == "reported":
            rows.append(
                {
                    "Field": field_name,
                    "Extracted value": str(field.get("value", "")),
                    "Evidence": str(field.get("evidence_quote", "")),
                }
            )
        elif not isinstance(field, dict):
            rows.append({"Field": field_name, "Extracted value": str(field), "Evidence": ""})
    return rows


def render_extracted_value(value: Any) -> None:
    if isinstance(value, list):
        if not value:
            st.caption("No records extracted.")
            return
        for number, item in enumerate(value, 1):
            if not isinstance(item, dict):
                st.write(item)
                continue
            identifiers = [str(v) for k, v in item.items() if k.endswith("_id") and not isinstance(v, dict)]
            title = f"Record {number}" + (f" · {' · '.join(identifiers)}" if identifiers else "")
            with st.expander(title, expanded=number == 1):
                rows = structured_value_rows(item)
                if rows:
                    st.dataframe(rows, hide_index=True, use_container_width=True)
                missing = [name for name, field in item.items() if isinstance(field, dict) and field.get("status") == "missing"]
                if missing:
                    st.caption("Missing in abstract: " + ", ".join(missing))
        return
    if isinstance(value, dict):
        rows = structured_value_rows(value)
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
        else:
            st.json(value)
        return
    st.code(str(value), language=None)


def evidence_sentence(quote: str, abstract: str) -> str:
    """Expand a short evidence fragment to its complete abstract sentence."""
    if not quote or not abstract:
        return quote
    normalized_quote = " ".join(quote.split()).lower()
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(abstract.split()))
    matching = [sentence for sentence in sentences if normalized_quote in sentence.lower()]
    return " ".join(matching) if matching else quote


def main() -> None:
    st.set_page_config(page_title="Day 5 · G1 Review", page_icon="✓", layout="wide")
    st.title("Day 5 · G1 extraction review")
    st.caption("Decide whether each extracted value is scientifically and evidentially correct. Every decision requires a reason.")

    records = load_records()
    completed = sum(item.get("human_decision") in DECISIONS[1:] for item in records)
    st.progress(completed / len(records), text=f"{completed} of {len(records)} decisions saved")

    reviewer = st.text_input("Reviewer name", value=st.session_state.get("reviewer", "renemilywei"))
    st.session_state["reviewer"] = reviewer

    labels = [
        f"{item['review_id']} — {record_summary(item)}"
        + (" ✓" if item.get("human_decision") in DECISIONS[1:] else "")
        for item in records
    ]
    if "record_index" not in st.session_state:
        st.session_state.record_index = next(
            (index for index, item in enumerate(records) if item.get("human_decision") not in DECISIONS[1:]),
            0,
        )
    selected_label = st.selectbox("Review item", labels, index=st.session_state.record_index)
    index = labels.index(selected_label)
    st.session_state.record_index = index
    record = records[index]

    left, right = st.columns([1, 1.35], gap="large")
    with left:
        st.subheader(record["review_id"])
        st.write(f"**Paper:** {record.get('paper_id', '—')}")
        st.write(f"**Entity:** {record.get('entity_type', '—')}")
        st.write(f"**Field:** `{record.get('field_name', '—')}`")
        value = record.get("value", record.get("gold_value", "No model value returned"))
        st.write("**Extracted/expected value**")
        render_extracted_value(value)
        if record.get("entity_context") and not isinstance(value, list):
            with st.expander("Show complete parent record", expanded=False):
                context_rows = structured_value_rows(record["entity_context"])
                if context_rows:
                    st.dataframe(context_rows, hide_index=True, use_container_width=True)
                missing_context = [name for name, field in record["entity_context"].items() if isinstance(field, dict) and field.get("status") == "missing"]
                if missing_context:
                    st.caption("Missing in abstract: " + ", ".join(missing_context))
        st.write(f"**Preliminary classification:** `{record.get('preliminary_classification', '—')}`")
        if record.get("verifier_explanation"):
            st.write("**Second-read finding**")
            st.warning(record["verifier_explanation"])
        if record.get("confidence"):
            st.write(f"**Model confidence:** `{record['confidence']}`")

    with right:
        st.subheader("Evidence supplied for this decision")
        quotes = record.get("evidence_quotes") or []
        if isinstance(value, list) and record.get("abstract"):
            st.text_area("Full abstract context", record["abstract"], height=320, disabled=True)
        elif quotes:
            for quote in quotes:
                st.info(evidence_sentence(quote, record.get("abstract", "")))
            if record.get("abstract"):
                st.text_area(
                    "Complete approved source sentence(s)",
                    record["abstract"],
                    height=220,
                    disabled=True,
                )
        elif record.get("abstract"):
            st.text_area("Abstract", record["abstract"], height=260, disabled=True)
        else:
            st.warning("No valid model response or evidence quote was available.")

    existing = record.get("human_decision", "pending")
    decision_options = list(DECISIONS[1:])
    decision_index = decision_options.index(existing) if existing in decision_options else None
    with st.form(f"decision-{record['review_id']}"):
        decision = st.radio(
            "Decision",
            decision_options,
            index=decision_index,
            format_func=lambda value: {
                "correct": "Correct",
                "incorrect": "Incorrect",
                "ambiguous_or_absent": "Ambiguous / absent / no valid response",
            }[value],
        )
        reason = st.text_area(
            "Reason (required)",
            value=record.get("reviewer_reason", ""),
            placeholder="Explain what the evidence supports, what is wrong, or why the information is unresolved.",
            height=110,
        )
        save_next = st.form_submit_button("Save decision and go to next", type="primary", use_container_width=True)

    if save_next:
        if decision is None:
            st.error("Choose a decision before saving.")
        else:
            try:
                apply_decision(records, review_id=record["review_id"], decision=decision, reason=reason, reviewer=reviewer)
                save_records(records)
            except ValueError as error:
                st.error(str(error))
            else:
                next_pending = next(
                    (offset for offset in range(1, len(records) + 1) if records[(index + offset) % len(records)].get("human_decision") not in DECISIONS[1:]),
                    0,
                )
                st.session_state.record_index = (index + next_pending) % len(records)
                st.rerun()

    if completed == len(records):
        st.success("All decisions are saved. Return to Codex so final G1 metrics can be calculated.")


if __name__ == "__main__":
    main()
