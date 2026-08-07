"""Minimal, no-retry client for the documented ChatPDF backend API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx


BASE_URL = "https://api.chatpdf.com/v1"


class ChatPdfError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatPdfResponse:
    content: str
    references: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


class Transport(Protocol):
    def post_file(self, **kwargs) -> dict[str, Any]: ...
    def post_json(self, **kwargs) -> dict[str, Any]: ...


class HttpxTransport:
    def post_file(
        self, *, url: str, headers: dict[str, str], path: Path, timeout: float
    ) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                response = httpx.post(
                    url,
                    headers=headers,
                    files={"file": (path.name, handle, "application/pdf")},
                    timeout=timeout,
                )
        except (OSError, httpx.HTTPError) as error:
            raise ChatPdfError(f"ChatPDF upload failed: {error}") from error
        return _response_json(response)

    def post_json(
        self, *, url: str, headers: dict[str, str], payload: dict[str, Any],
        timeout: float
    ) -> dict[str, Any]:
        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=timeout
            )
        except httpx.HTTPError as error:
            raise ChatPdfError(f"ChatPDF message failed: {error}") from error
        return _response_json(response)


def _response_json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        body = response.text[:500]
        raise ChatPdfError(
            f"ChatPDF HTTP {response.status_code}: {body}"
        )
    try:
        payload = response.json()
    except ValueError as error:
        raise ChatPdfError("ChatPDF returned non-JSON response") from error
    if not isinstance(payload, dict):
        raise ChatPdfError("ChatPDF returned a non-object response")
    return payload


class ChatPdfClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: Transport | None = None,
        timeout: float = 180.0,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("CHATPDF_API_KEY")
        if not (self._api_key or "").strip():
            raise ChatPdfError("CHATPDF_API_KEY is not set")
        self._transport = transport or HttpxTransport()
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": str(self._api_key)}

    def add_file(self, path: Path) -> str:
        pdf = Path(path)
        if not pdf.is_file() or pdf.suffix.casefold() != ".pdf":
            raise ChatPdfError(f"PDF does not exist: {pdf}")
        payload = self._transport.post_file(
            url=f"{BASE_URL}/sources/add-file",
            headers=self._headers,
            path=pdf,
            timeout=self._timeout,
        )
        source_id = payload.get("sourceId")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ChatPdfError("ChatPDF upload response lacks sourceId")
        return source_id

    def ask(
        self, source_id: str, prompt: str, reference_sources: bool = True
    ) -> ChatPdfResponse:
        payload = self._transport.post_json(
            url=f"{BASE_URL}/chats/message",
            headers={**self._headers, "Content-Type": "application/json"},
            payload={
                "sourceId": source_id,
                "messages": [{"role": "user", "content": prompt}],
                "referenceSources": reference_sources,
            },
            timeout=self._timeout,
        )
        content = payload.get("content")
        if not isinstance(content, str):
            raise ChatPdfError("ChatPDF message response lacks content")
        references = payload.get("references") or []
        if not isinstance(references, list):
            raise ChatPdfError("ChatPDF references are malformed")
        return ChatPdfResponse(content, tuple(references), payload)


__all__ = ["ChatPdfClient", "ChatPdfError", "ChatPdfResponse"]
