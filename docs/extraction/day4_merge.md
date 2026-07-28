# Day 4 deterministic result merge

The merge stage combines the first compact extraction candidate with validated
field-level repair and selective-vision results. It makes no OpenAI request.

For every supplied correction, the merger verifies that:

- the task belongs to the same paper and validation finding;
- a repair task was built from the exact candidate checksum;
- the route-specific response validator accepts the result;
- only the requested collection, record index, and field are replaced;
- a visual correction is exact or derived and does not require human review;
- no two results attempt to replace the same finding; and
- the complete merged candidate passes the compact schema, relationship, and
  evidence-ID validation again.

The command writes `merge_report.json` for every completed attempt. It writes
`final_result.json` only when every original finding is resolved and the merged
record passes final validation. Missing, ambiguous, visually estimated, or
human-review results remain explicit unresolved findings.

Example:

```bash
python -m src.extraction.merge_compact_results \
  --candidate data/staging/extraction/compact_one_call_v1/GP-001/candidate.json \
  --validation-report data/staging/extraction/compact_one_call_v1/GP-001/validation_report.json \
  --packet data/staging/rag/compact_api_packets_v1/GP-001.json \
  --repair path/to/repair/task.json path/to/repair/result.json \
  --vision path/to/vision/task.json path/to/vision/result.json
```
