from openai.lib._pydantic import to_strict_json_schema

from src.extraction.missing_record_contracts import MissingRecordFragment
from src.extraction.preflight_missing_record_repairs import strict_schema_issues


def test_missing_record_response_schema_is_strict_at_every_object():
    assert strict_schema_issues(
        to_strict_json_schema(MissingRecordFragment)
    ) == []


def test_schema_audit_rejects_optional_or_open_object_properties():
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": [],
    }
    assert strict_schema_issues(schema) == [
        "$:additionalProperties_must_be_false",
        "$:all_properties_must_be_required",
    ]
