from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
PACKETS = ROOT / "data" / "staging" / "rag" / "retrieval_packets"
DECISIONS = ROOT / "data" / "review" / "fulltext_rag_decisions.jsonl"


st.set_page_config(page_title="AI-LNP full-text evidence review", layout="wide")
st.title("AI-LNP full-text evidence review")
st.caption("Review retrieval evidence only. This screen does not treat a RAG answer as ground truth.")

paths = sorted(PACKETS.glob("GP-*.json"))
if not paths:
    st.warning("No retrieval packets exist. Run `python -m src.rag.run_pipeline` first.")
    st.stop()

selected = st.selectbox("Paper", [path.stem for path in paths])
payload = json.loads((PACKETS / f"{selected}.json").read_text())
field = st.selectbox("Field group", list(payload["packets"]))
packet = payload["packets"][field]

st.subheader(packet["query"]["question"])
if field in payload["blocked_fields"]:
    st.error("Automatic evidence gate blocked extraction for this field.")
    for reason in payload["blocked_fields"][field]:
        st.write(f"- {reason}")

for rank, hit in enumerate(packet["hits"], 1):
    with st.expander(f"{rank}. {hit['section_path']} · {hit['block_id']}", expanded=rank <= 2):
        st.write(hit["text"])
        st.caption(
            f"Source: {hit['source_path']} · page: {hit['page_number'] or 'n/a'} "
            f"· XML ID: {hit.get('xml_element_id') or 'n/a'}"
        )

decision = st.radio(
    "Does this evidence packet contain sufficient, experiment-matched evidence?",
    ["unreviewed", "sufficient", "insufficient", "ambiguous"],
    horizontal=True,
)
reason = st.text_area("Scientific reason (required for every final decision)")
if st.button("Save decision", type="primary"):
    if decision == "unreviewed" or not reason.strip():
        st.error("Choose a final decision and provide a reason.")
    else:
        DECISIONS.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "paper_id": selected,
            "field": field,
            "query_id": packet["query"]["query_id"],
            "decision": decision,
            "reason": reason.strip(),
            "reviewed_block_ids": [hit["block_id"] for hit in packet["hits"]],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with DECISIONS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        st.success("Decision and reason saved.")
