from __future__ import annotations

import pytest

from src.extraction.chatpdf_client import ChatPdfClient, ChatPdfError
from src.extraction.chatpdf_contracts import parse_extraction_response


class FakeTransport:
    def __init__(self, file_response=None, chat_response=None, error=None):
        self.file_response = file_response or {"sourceId": "src-1"}
        self.chat_response = chat_response or {
            "content": '{"paper_id":"GP-002","arms":[]}',
            "references": [{"pageNumber": 1}],
        }
        self.error = error
        self.file_calls = 0
        self.chat_calls = 0

    def post_file(self, **kwargs):
        self.file_calls += 1
        if self.error:
            raise self.error
        return self.file_response

    def post_json(self, **kwargs):
        self.chat_calls += 1
        if self.error:
            raise self.error
        return self.chat_response


def test_client_uploads_once_and_sends_one_message(tmp_path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF fixture")
    transport = FakeTransport()
    client = ChatPdfClient(api_key="secret", transport=transport)

    source_id = client.add_file(pdf)
    response = client.ask(source_id, "JSON only", reference_sources=True)

    assert source_id == "src-1"
    assert response.content == '{"paper_id":"GP-002","arms":[]}'
    assert transport.file_calls == 1
    assert transport.chat_calls == 1


def test_client_does_not_retry_failed_message() -> None:
    transport = FakeTransport(error=ChatPdfError("quota"))
    client = ChatPdfClient(api_key="secret", transport=transport)

    with pytest.raises(ChatPdfError, match="quota"):
        client.ask("src-1", "prompt")

    assert transport.chat_calls == 1


def test_client_rejects_missing_key() -> None:
    with pytest.raises(ChatPdfError, match="CHATPDF_API_KEY"):
        ChatPdfClient(api_key="")


def test_response_contract_rejects_prose_wrapped_json() -> None:
    with pytest.raises(ValueError, match="JSON object only"):
        parse_extraction_response(
            "Here is the result: {\"paper_id\":\"GP-002\",\"arms\":[]}"
        )


def test_response_contract_requires_evidence_for_populated_fields() -> None:
    payload = (
        '{"paper_id":"GP-002","arms":[{"arm_id":"A1",'
        '"lnp_name":"LNP","evidence":{},"outcomes":[]}]}'
    )

    with pytest.raises(ValueError, match="lnp_name"):
        parse_extraction_response(payload)
