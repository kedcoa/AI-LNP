from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
import yaml
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Project paths and API endpoints
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_PATH = (
    PROJECT_ROOT
    / "docs"
    / "search"
    / "query_manifest_v2_1.yaml"
)

RAW_SEARCH_ROOT = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "searches"
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/"
    "entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/"
    "entrez/eutils/efetch.fcgi"
)

EUROPE_PMC_SEARCH_URL = (
    "https://www.ebi.ac.uk/"
    "europepmc/webservices/rest/search"
)

TOOL_NAME = "lnp_liver_evidence_tool"


# ---------------------------------------------------------------------------
# Retrieval and retry settings
# ---------------------------------------------------------------------------

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

MAX_REQUEST_ATTEMPTS = 5
INITIAL_BACKOFF_SECONDS = 1.0
COURTESY_DELAY_SECONDS = 0.5

EXPECTED_CELLS = {
    "hepatocyte",
    "kupffer",
    "lsec",
    "hsc",
}

EXPECTED_SOURCES = {
    "pubmed",
    "europe_pmc",
}


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def now_local() -> datetime:
    """Return the current local time with its timezone."""
    return datetime.now().astimezone()


def iso_now() -> str:
    """Return a timezone-aware ISO 8601 timestamp."""
    return now_local().isoformat(timespec="seconds")


def sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 checksum of a byte sequence."""
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a file."""
    return sha256_bytes(path.read_bytes())


def write_json(
    path: Path,
    value: object,
) -> None:
    """
    Write JSON through a temporary file.

    Replacing the destination only after the temporary file is complete
    prevents a process interruption from leaving truncated JSON.
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_name(
        f"{path.name}.tmp"
    )

    temporary_path.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(path)


def read_json(path: Path) -> dict:
    """Read a JSON object from a file."""
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise ValueError(
            f"Expected a JSON object in {path}"
        )

    return value


# ---------------------------------------------------------------------------
# Manifest loading and validation
# ---------------------------------------------------------------------------

def load_manifest(
    manifest_path: Path,
) -> dict:
    """Read and validate a versioned YAML query manifest."""
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {manifest_path}"
        )

    if not manifest_path.is_file():
        raise ValueError(
            f"Manifest path is not a file: {manifest_path}"
        )

    with manifest_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        manifest = yaml.safe_load(file)

    if not isinstance(manifest, dict):
        raise ValueError(
            "The manifest must contain a YAML mapping."
        )

    required_top_level = {
        "manifest_version",
        "retrieval_policy",
        "cell_types",
        "queries",
    }

    missing_top_level = (
        required_top_level - set(manifest)
    )

    if missing_top_level:
        raise ValueError(
            "Manifest is missing these top-level fields: "
            f"{sorted(missing_top_level)}"
        )

    manifest_version = manifest[
        "manifest_version"
    ]

    if manifest_version is None:
        raise ValueError(
            "manifest_version cannot be empty."
        )

    if not isinstance(
        manifest["retrieval_policy"],
        dict,
    ):
        raise ValueError(
            "retrieval_policy must be a YAML mapping."
        )

    if not isinstance(
        manifest["cell_types"],
        dict,
    ):
        raise ValueError(
            "cell_types must be a YAML mapping."
        )

    if not isinstance(
        manifest["queries"],
        dict,
    ):
        raise ValueError(
            "queries must be a YAML mapping."
        )

    actual_cells = set(
        manifest["cell_types"]
    )

    if actual_cells != EXPECTED_CELLS:
        raise ValueError(
            "cell_types must contain exactly "
            "hepatocyte, kupffer, lsec, and hsc. "
            f"Found: {sorted(actual_cells)}"
        )

    actual_sources = set(
        manifest["queries"]
    )

    if actual_sources != EXPECTED_SOURCES:
        raise ValueError(
            "queries must contain exactly pubmed and "
            f"europe_pmc. Found: {sorted(actual_sources)}"
        )

    for source in EXPECTED_SOURCES:
        source_queries = manifest[
            "queries"
        ][source]

        if not isinstance(
            source_queries,
            dict,
        ):
            raise ValueError(
                f"queries/{source} must be a mapping."
            )

        source_cells = set(source_queries)

        if source_cells != EXPECTED_CELLS:
            raise ValueError(
                f"{source} queries must contain exactly "
                "hepatocyte, kupffer, lsec, and hsc. "
                f"Found: {sorted(source_cells)}"
            )

        for cell in EXPECTED_CELLS:
            query = source_queries[cell]

            if not isinstance(query, str):
                raise ValueError(
                    f"Query {source}/{cell} is not text."
                )

            if not query.strip():
                raise ValueError(
                    f"Query {source}/{cell} is empty."
                )

    policy = manifest["retrieval_policy"]

    required_policy_fields = {
        "retrieval_cap_per_cell_per_source",
        "pubmed_page_size",
        "europe_pmc_page_size",
    }

    missing_policy_fields = (
        required_policy_fields - set(policy)
    )

    if missing_policy_fields:
        raise ValueError(
            "retrieval_policy is missing: "
            f"{sorted(missing_policy_fields)}"
        )

    try:
        cap = int(
            policy[
                "retrieval_cap_per_cell_per_source"
            ]
        )
        pubmed_page_size = int(
            policy["pubmed_page_size"]
        )
        europe_pmc_page_size = int(
            policy["europe_pmc_page_size"]
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Retrieval cap and page sizes must be integers."
        ) from error

    if cap <= 0:
        raise ValueError(
            "The retrieval cap must be greater than zero."
        )

    # PubMed ESearch can return at most the first 10,000 IDs.
    if cap > 10_000:
        raise ValueError(
            "The retrieval cap cannot exceed 10,000 "
            "for this PubMed implementation."
        )

    if pubmed_page_size <= 0:
        raise ValueError(
            "pubmed_page_size must be greater than zero."
        )

    if europe_pmc_page_size <= 0:
        raise ValueError(
            "europe_pmc_page_size must be greater than zero."
        )

    if pubmed_page_size > 1_000:
        raise ValueError(
            "pubmed_page_size should not exceed 1,000."
        )

    if europe_pmc_page_size > 1_000:
        raise ValueError(
            "europe_pmc_page_size should not exceed 1,000."
        )

    return manifest


# ---------------------------------------------------------------------------
# URL and response-storage helpers
# ---------------------------------------------------------------------------

def sanitized_url(
    url: str,
    params: dict,
) -> str:
    """Construct a saved request URL without an API key."""
    safe_params = {
        key: value
        for key, value in params.items()
        if key != "api_key"
    }

    return f"{url}?{urlencode(safe_params)}"


def parameters_without_api_key(
    params: dict,
) -> dict:
    """Return request parameters without the API key."""
    return {
        key: value
        for key, value in params.items()
        if key != "api_key"
    }


def save_raw_response(
    path: Path,
    response: requests.Response,
) -> str:
    """
    Save the exact response bytes atomically.

    The raw response is written to a temporary .part file and moved to
    its final name only after the write succeeds.
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_name(
        f"{path.name}.part"
    )

    temporary_path.write_bytes(
        response.content
    )

    temporary_path.replace(path)

    return sha256_bytes(
        response.content
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def page_is_complete(
    raw_path: Path,
    metadata_path: Path,
) -> bool:
    """
    Return True only when a page has valid raw data and completed metadata.
    """
    if not raw_path.is_file():
        return False

    if not metadata_path.is_file():
        return False

    try:
        metadata = read_json(metadata_path)
    except (
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return False

    if metadata.get("status") != "completed":
        return False

    expected_checksum = metadata.get("sha256")

    if not expected_checksum:
        return False

    try:
        actual_checksum = sha256_file(raw_path)
    except OSError:
        return False

    return actual_checksum == expected_checksum


def load_cached_json(
    raw_path: Path,
    metadata_path: Path,
) -> dict | None:
    """
    Read a completed cached JSON page.

    Return None if the cache is missing, incomplete, damaged, or invalid.
    """
    if not page_is_complete(
        raw_path,
        metadata_path,
    ):
        return None

    try:
        value = json.loads(
            raw_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        OSError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def write_page_metadata(
    metadata_path: Path,
    metadata: dict,
) -> None:
    """
    Mark a page completed only after its raw response has been stored.
    """
    completed_metadata = dict(metadata)
    completed_metadata["status"] = "completed"

    write_json(
        metadata_path,
        completed_metadata,
    )


# ---------------------------------------------------------------------------
# HTTP request and retry helper
# ---------------------------------------------------------------------------

def retry_delay_for_response(
    response: requests.Response,
    fallback_delay: float,
) -> float:
    """
    Honor a numeric Retry-After header when present.

    Otherwise return the exponential-backoff delay.
    """
    retry_after = response.headers.get(
        "Retry-After"
    )

    if retry_after is None:
        return fallback_delay

    try:
        retry_after_seconds = float(
            retry_after
        )
    except ValueError:
        return fallback_delay

    return max(
        fallback_delay,
        retry_after_seconds,
    )


def make_request(
    session: requests.Session,
    url: str,
    params: dict,
    max_attempts: int = MAX_REQUEST_ATTEMPTS,
) -> tuple[requests.Response, list[dict]]:
    """
    Send one request with bounded exponential backoff.

    Retry:
    - rate limiting;
    - selected temporary server errors;
    - connection and timeout errors.

    Do not retry permanent HTTP errors such as malformed queries.
    """
    if max_attempts <= 0:
        raise ValueError(
            "max_attempts must be greater than zero."
        )

    attempts: list[dict] = []
    delay = INITIAL_BACKOFF_SECONDS

    for attempt_number in range(
        1,
        max_attempts + 1,
    ):
        attempted_at = iso_now()

        try:
            response = session.get(
                url,
                params=params,
                timeout=60,
            )
        except requests.RequestException as error:
            attempts.append(
                {
                    "attempt": attempt_number,
                    "attempted_at": attempted_at,
                    "http_status": None,
                    "error": (
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                }
            )

            if attempt_number >= max_attempts:
                raise

            print(
                "Temporary network failure; "
                f"waiting {delay:.1f} seconds "
                "before retry."
            )

            time.sleep(delay)
            delay *= 2
            continue

        status_code = response.status_code

        if status_code in RETRYABLE_STATUS_CODES:
            attempts.append(
                {
                    "attempt": attempt_number,
                    "attempted_at": attempted_at,
                    "http_status": status_code,
                    "error": (
                        "Retryable HTTP status "
                        f"{status_code}"
                    ),
                }
            )

            if attempt_number >= max_attempts:
                response.raise_for_status()

            sleep_seconds = (
                retry_delay_for_response(
                    response,
                    delay,
                )
            )

            print(
                "Temporary HTTP failure "
                f"{status_code}; waiting "
                f"{sleep_seconds:.1f} seconds "
                "before retry."
            )

            time.sleep(sleep_seconds)
            delay *= 2
            continue

        attempts.append(
            {
                "attempt": attempt_number,
                "attempted_at": attempted_at,
                "http_status": status_code,
                "error": None,
            }
        )

        # This raises immediately for permanent 4xx/5xx errors.
        response.raise_for_status()

        return response, attempts

    raise RuntimeError(
        "Request attempts ended without a response."
    )


# ---------------------------------------------------------------------------
# PubMed retrieval
# ---------------------------------------------------------------------------

def run_pubmed_query(
    session: requests.Session,
    run_dir: Path,
    manifest_version: str,
    cell: str,
    query: str,
    cap: int,
    page_size: int,
    ncbi_email: str | None,
    ncbi_api_key: str | None,
) -> dict:
    """
    Run PubMed ESearch and retrieve the resulting records in EFetch pages.
    """
    output_dir = (
        run_dir / "pubmed" / cell
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    search_raw_path = (
        output_dir / "esearch_response.json"
    )

    search_metadata_path = (
        output_dir / "esearch_response.meta.json"
    )

    search_data = load_cached_json(
        search_raw_path,
        search_metadata_path,
    )

    if search_data is not None:
        print(
            f"  Cache hit: pubmed/{cell} ESearch"
        )

    else:
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retstart": 0,
            "retmax": cap,
            "sort": "pub date",
            "usehistory": "y",
            "tool": TOOL_NAME,
        }

        if ncbi_email:
            search_params["email"] = ncbi_email

        if ncbi_api_key:
            search_params["api_key"] = (
                ncbi_api_key
            )

        requested_at = iso_now()

        response, request_attempts = (
            make_request(
                session,
                PUBMED_ESEARCH_URL,
                search_params,
            )
        )

        completed_at = iso_now()

        checksum = save_raw_response(
            search_raw_path,
            response,
        )

        search_data = json.loads(
            response.content
        )

        if not isinstance(
            search_data,
            dict,
        ):
            raise ValueError(
                "PubMed ESearch did not return "
                "a JSON object."
            )

        search_result = search_data.get(
            "esearchresult"
        )

        if not isinstance(
            search_result,
            dict,
        ):
            raise ValueError(
                "PubMed ESearch response has no "
                "esearchresult object."
            )

        pmids = search_result.get(
            "idlist",
            [],
        )

        if not isinstance(pmids, list):
            raise ValueError(
                "PubMed ESearch idlist is not a list."
            )

        total_matches = int(
            search_result.get("count", 0)
        )

        metadata = {
            "status": "in_progress",
            "manifest_version": manifest_version,
            "query_id": (
                f"pubmed_{cell}_v"
                f"{manifest_version}"
            ),
            "source": "pubmed",
            "cell_type": cell,
            "endpoint": PUBMED_ESEARCH_URL,
            "request_url_without_api_key": (
                sanitized_url(
                    PUBMED_ESEARCH_URL,
                    search_params,
                )
            ),
            "query_text": query,
            "parameters_without_api_key": (
                parameters_without_api_key(
                    search_params
                )
            ),
            "api_key_used": bool(
                ncbi_api_key
            ),
            "requested_at": requested_at,
            "completed_at": completed_at,
            "http_status": response.status_code,
            "content_type": (
                response.headers.get(
                    "Content-Type"
                )
            ),
            "total_matches": total_matches,
            "records_returned": len(pmids),
            "retrieval_cap": cap,
            "pagination": {
                "method": "saved_pmid_list",
                "page_size": page_size,
                "next_start_index": 0,
            },
            "request_attempts": (
                request_attempts
            ),
            "raw_file": search_raw_path.name,
            "sha256": checksum,
        }

        write_page_metadata(
            search_metadata_path,
            metadata,
        )

    search_result = search_data.get(
        "esearchresult"
    )

    if not isinstance(
        search_result,
        dict,
    ):
        raise ValueError(
            "Cached PubMed ESearch response has "
            "no esearchresult object."
        )

    pmids = search_result.get(
        "idlist",
        [],
    )

    if not isinstance(pmids, list):
        raise ValueError(
            "Cached PubMed ESearch idlist is not a list."
        )

    pmids = [
        str(pmid)
        for pmid in pmids
        if str(pmid).strip()
    ]

    total_matches = int(
        search_result.get("count", 0)
    )

    expected_retrieval_count = min(
        total_matches,
        cap,
    )

    if len(pmids) != expected_retrieval_count:
        raise RuntimeError(
            "PubMed ESearch returned an unexpected "
            "number of PMIDs: "
            f"expected {expected_retrieval_count}, "
            f"received {len(pmids)}."
        )

    completed_pages = 0

    for start in range(
        0,
        len(pmids),
        page_size,
    ):
        page_pmids = pmids[
            start : start + page_size
        ]

        page_number = (
            start // page_size
        )

        raw_path = output_dir / (
            f"efetch_page_{page_number:04d}.xml"
        )

        metadata_path = output_dir / (
            f"efetch_page_{page_number:04d}"
            ".meta.json"
        )

        if page_is_complete(
            raw_path,
            metadata_path,
        ):
            print(
                f"  Cache hit: pubmed/{cell} "
                f"EFetch page {page_number}"
            )

            completed_pages += 1
            continue

        params = {
            "db": "pubmed",
            "id": ",".join(page_pmids),
            "retmode": "xml",
            "tool": TOOL_NAME,
        }

        if ncbi_email:
            params["email"] = ncbi_email

        if ncbi_api_key:
            params["api_key"] = ncbi_api_key

        requested_at = iso_now()

        response, request_attempts = (
            make_request(
                session,
                PUBMED_EFETCH_URL,
                params,
            )
        )

        completed_at = iso_now()

        checksum = save_raw_response(
            raw_path,
            response,
        )

        metadata = {
            "status": "in_progress",
            "manifest_version": manifest_version,
            "query_id": (
                f"pubmed_{cell}_v"
                f"{manifest_version}"
            ),
            "source": "pubmed",
            "cell_type": cell,
            "endpoint": PUBMED_EFETCH_URL,
            "page_number": page_number,
            "request_url_without_api_key": (
                sanitized_url(
                    PUBMED_EFETCH_URL,
                    params,
                )
            ),
            "parameters_without_api_key": (
                parameters_without_api_key(
                    params
                )
            ),
            "api_key_used": bool(
                ncbi_api_key
            ),
            "requested_at": requested_at,
            "completed_at": completed_at,
            "http_status": response.status_code,
            "content_type": (
                response.headers.get(
                    "Content-Type"
                )
            ),
            "pmids": page_pmids,
            "records_requested": len(
                page_pmids
            ),
            "pagination": {
                "method": "saved_pmid_list",
                "start_index": start,
                "end_index_exclusive": (
                    start + len(page_pmids)
                ),
                "page_size": page_size,
                "next_start_index": (
                    start + len(page_pmids)
                ),
            },
            "request_attempts": (
                request_attempts
            ),
            "raw_file": raw_path.name,
            "sha256": checksum,
        }

        write_page_metadata(
            metadata_path,
            metadata,
        )

        completed_pages += 1

        time.sleep(
            COURTESY_DELAY_SECONDS
        )

    if len(pmids) >= cap:
        status = "cap_reached"
    else:
        status = "all_available_retrieved"

    return {
        "source": "pubmed",
        "cell_type": cell,
        "total_matches": total_matches,
        "retrieval_cap": cap,
        "records_retrieved": len(pmids),
        "pages_completed": completed_pages,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Europe PMC retrieval
# ---------------------------------------------------------------------------

def run_europe_pmc_query(
    session: requests.Session,
    run_dir: Path,
    manifest_version: str,
    cell: str,
    query: str,
    cap: int,
    page_size: int,
) -> dict:
    """
    Retrieve Europe PMC results using cursor-based pagination.
    """
    output_dir = (
        run_dir / "europe_pmc" / cell
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    cursor = "*"
    records_retrieved = 0
    total_matches: int | None = None
    page_number = 0
    completed_pages = 0

    while records_retrieved < cap:
        raw_path = output_dir / (
            f"search_page_{page_number:04d}.json"
        )

        metadata_path = output_dir / (
            f"search_page_{page_number:04d}"
            ".meta.json"
        )

        data = load_cached_json(
            raw_path,
            metadata_path,
        )

        if data is not None:
            cached_metadata = read_json(
                metadata_path
            )

            cached_cursor = (
                cached_metadata
                .get("pagination", {})
                .get("request_cursor")
            )

            if cached_cursor != cursor:
                raise ValueError(
                    "Cached Europe PMC page cursor "
                    "does not match the expected cursor. "
                    f"Page: {page_number}; "
                    f"expected: {cursor}; "
                    f"cached: {cached_cursor}"
                )

            print(
                f"  Cache hit: europe_pmc/"
                f"{cell} page {page_number}"
            )

        else:
            remaining = (
                cap - records_retrieved
            )

            current_page_size = min(
                page_size,
                remaining,
            )

            params = {
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": (
                    current_page_size
                ),
                "cursorMark": cursor,
            }

            requested_at = iso_now()

            response, request_attempts = (
                make_request(
                    session,
                    EUROPE_PMC_SEARCH_URL,
                    params,
                )
            )

            completed_at = iso_now()

            checksum = save_raw_response(
                raw_path,
                response,
            )

            data = json.loads(
                response.content
            )

            if not isinstance(data, dict):
                raise ValueError(
                    "Europe PMC did not return "
                    "a JSON object."
                )

            results = (
                data.get("resultList", {})
                .get("result", [])
            )

            if not isinstance(results, list):
                raise ValueError(
                    "Europe PMC resultList/result "
                    "is not a list."
                )

            page_total_matches = int(
                data.get("hitCount", 0)
            )

            metadata = {
                "status": "in_progress",
                "manifest_version": (
                    manifest_version
                ),
                "query_id": (
                    f"europe_pmc_{cell}_v"
                    f"{manifest_version}"
                ),
                "source": "europe_pmc",
                "cell_type": cell,
                "page_number": page_number,
                "endpoint": (
                    EUROPE_PMC_SEARCH_URL
                ),
                "request_url": sanitized_url(
                    EUROPE_PMC_SEARCH_URL,
                    params,
                ),
                "query_text": query,
                "parameters": params,
                "requested_at": requested_at,
                "completed_at": completed_at,
                "http_status": (
                    response.status_code
                ),
                "content_type": (
                    response.headers.get(
                        "Content-Type"
                    )
                ),
                "total_matches": (
                    page_total_matches
                ),
                "records_returned": len(
                    results
                ),
                "pagination": {
                    "method": "cursor",
                    "request_cursor": cursor,
                    "next_cursor": (
                        data.get(
                            "nextCursorMark"
                        )
                    ),
                    "page_size": (
                        current_page_size
                    ),
                },
                "request_attempts": (
                    request_attempts
                ),
                "raw_file": raw_path.name,
                "sha256": checksum,
            }

            write_page_metadata(
                metadata_path,
                metadata,
            )

            time.sleep(
                COURTESY_DELAY_SECONDS
            )

        result_list = data.get(
            "resultList",
            {},
        )

        if not isinstance(
            result_list,
            dict,
        ):
            raise ValueError(
                "Europe PMC resultList is not an object."
            )

        results = result_list.get(
            "result",
            [],
        )

        if not isinstance(results, list):
            raise ValueError(
                "Europe PMC resultList/result "
                "is not a list."
            )

        page_total_matches = int(
            data.get("hitCount", 0)
        )

        if total_matches is None:
            total_matches = (
                page_total_matches
            )
        elif total_matches != page_total_matches:
            raise RuntimeError(
                "Europe PMC hitCount changed during "
                "the same paginated run."
            )

        records_retrieved += len(
            results
        )

        if results:
            completed_pages += 1

        # We have reached the balanced retrieval cap.
        if records_retrieved >= cap:
            break

        # We have retrieved all results reported by Europe PMC.
        if (
            total_matches is not None
            and records_retrieved
            >= total_matches
        ):
            break

        # An empty page before reaching the expected total is incomplete.
        if not results:
            raise RuntimeError(
                "Europe PMC returned an empty page "
                "before the expected results were retrieved."
            )

        next_cursor = data.get(
            "nextCursorMark"
        )

        if not next_cursor:
            raise RuntimeError(
                "Europe PMC did not return a next cursor "
                "before retrieval was complete."
            )

        if next_cursor == cursor:
            raise RuntimeError(
                "Europe PMC returned the same cursor "
                "before retrieval was complete."
            )

        cursor = str(next_cursor)
        page_number += 1

    final_total_matches = (
        total_matches
        if total_matches is not None
        else 0
    )

    if records_retrieved >= cap:
        status = "cap_reached"
    else:
        status = "all_available_retrieved"

    return {
        "source": "europe_pmc",
        "cell_type": cell,
        "total_matches": (
            final_total_matches
        ),
        "retrieval_cap": cap,
        "records_retrieved": min(
            records_retrieved,
            cap,
        ),
        "pages_completed": (
            completed_pages
        ),
        "status": status,
    }


# ---------------------------------------------------------------------------
# Run metadata helpers
# ---------------------------------------------------------------------------

def replace_result(
    run_metadata: dict,
    new_result: dict,
) -> None:
    """Replace the result summary for the same source and cell."""
    source = new_result["source"]
    cell = new_result["cell_type"]

    existing_results = (
        run_metadata.setdefault(
            "results",
            [],
        )
    )

    existing_results[:] = [
        result
        for result in existing_results
        if not (
            result.get("source") == source
            and result.get("cell_type") == cell
        )
    ]

    existing_results.append(
        new_result
    )


def remove_result(
    run_metadata: dict,
    source: str,
    cell: str,
) -> None:
    """Remove a stale result for a failed source/cell job."""
    results = run_metadata.setdefault(
        "results",
        [],
    )

    results[:] = [
        result
        for result in results
        if not (
            result.get("source") == source
            and result.get("cell_type") == cell
        )
    ]


def remove_error(
    run_metadata: dict,
    source: str,
    cell: str,
) -> None:
    """Remove an older error for a source/cell job."""
    errors = run_metadata.setdefault(
        "errors",
        [],
    )

    errors[:] = [
        error
        for error in errors
        if not (
            error.get("source") == source
            and error.get("cell_type") == cell
        )
    ]


# ---------------------------------------------------------------------------
# Command-line arguments
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse new-run and resume options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run or resume balanced PubMed and "
            "Europe PMC discovery."
        )
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help=(
            "Path to the versioned YAML manifest. "
            f"Default: {MANIFEST_PATH}"
        ),
    )

    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help=(
            "Exact existing run directory to resume. "
            "Omit this argument to create a new run."
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> int:
    """Start or resume all eight balanced discovery jobs."""
    args = parse_args()

    load_dotenv(
        PROJECT_ROOT / ".env"
    )

    manifest_path = (
        args.manifest.resolve()
    )

    manifest = load_manifest(
        manifest_path
    )

    manifest_version = str(
        manifest["manifest_version"]
    )

    policy = manifest[
        "retrieval_policy"
    ]

    cap = int(
        policy[
            "retrieval_cap_per_cell_per_source"
        ]
    )

    pubmed_page_size = int(
        policy["pubmed_page_size"]
    )

    europe_pmc_page_size = int(
        policy["europe_pmc_page_size"]
    )

    if args.resume is None:
        started = now_local()

        date_directory = (
            started.strftime("%Y-%m-%d")
        )

        run_id = started.strftime(
            "run_%Y%m%dT%H%M%S%z"
        )

        run_dir = (
            RAW_SEARCH_ROOT
            / date_directory
            / run_id
        )

        run_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        snapshot_path = (
            run_dir
            / "manifest_snapshot.yaml"
        )

        shutil.copy2(
            manifest_path,
            snapshot_path,
        )

        run_metadata = {
            "run_id": run_id,
            "manifest_version": (
                manifest_version
            ),
            "manifest_snapshot": (
                snapshot_path.name
            ),
            "manifest_sha256": (
                sha256_file(snapshot_path)
            ),
            "started_at": (
                started.isoformat(
                    timespec="seconds"
                )
            ),
            "completed_at": None,
            "status": "in_progress",
            "retrieval_cap_per_cell_per_source": (
                cap
            ),
            "pubmed_page_size": (
                pubmed_page_size
            ),
            "europe_pmc_page_size": (
                europe_pmc_page_size
            ),
            "results": [],
            "errors": [],
            "resume_events": [],
        }

    else:
        run_dir = (
            args.resume.resolve()
        )

        if not run_dir.is_dir():
            raise FileNotFoundError(
                "Resume directory not found: "
                f"{run_dir}"
            )

        run_metadata_path = (
            run_dir / "run_metadata.json"
        )

        if not run_metadata_path.is_file():
            raise FileNotFoundError(
                "The resume directory has no "
                "run_metadata.json file."
            )

        run_metadata = read_json(
            run_metadata_path
        )

        run_metadata.setdefault(
            "results",
            [],
        )

        run_metadata.setdefault(
            "errors",
            [],
        )

        run_metadata.setdefault(
            "resume_events",
            [],
        )

        recorded_version = str(
            run_metadata.get(
                "manifest_version"
            )
        )

        if recorded_version != manifest_version:
            raise ValueError(
                "The requested manifest version "
                "does not match the resumed run. "
                f"Run version: {recorded_version}; "
                f"requested version: "
                f"{manifest_version}"
            )

        snapshot_name = run_metadata.get(
            "manifest_snapshot"
        )

        if not snapshot_name:
            raise ValueError(
                "The resumed run metadata has no "
                "manifest_snapshot value."
            )

        snapshot_path = (
            run_dir / snapshot_name
        )

        if not snapshot_path.is_file():
            raise FileNotFoundError(
                "The resumed run has no manifest "
                f"snapshot: {snapshot_path}"
            )

        snapshot_checksum = (
            sha256_file(snapshot_path)
        )

        selected_manifest_checksum = (
            sha256_file(manifest_path)
        )

        if (
            snapshot_checksum
            != selected_manifest_checksum
        ):
            raise ValueError(
                "The selected manifest differs from "
                "the manifest snapshot used to start "
                "this run."
            )

        recorded_checksum = (
            run_metadata.get(
                "manifest_sha256"
            )
        )

        if (
            recorded_checksum is not None
            and recorded_checksum
            != snapshot_checksum
        ):
            raise ValueError(
                "The run's manifest snapshot checksum "
                "does not match its recorded checksum."
            )

        run_metadata[
            "manifest_sha256"
        ] = snapshot_checksum

        run_metadata["status"] = (
            "in_progress"
        )

        run_metadata["completed_at"] = None

        run_metadata[
            "resume_events"
        ].append(
            {
                "resumed_at": iso_now(),
                "manifest_path": (
                    str(manifest_path)
                ),
            }
        )

    run_metadata_path = (
        run_dir / "run_metadata.json"
    )

    write_json(
        run_metadata_path,
        run_metadata,
    )

    ncbi_email = os.environ.get(
        "NCBI_EMAIL"
    )

    ncbi_api_key = os.environ.get(
        "NCBI_API_KEY"
    )

    jobs: list[tuple[str, str]] = []

    for cell in manifest["cell_types"]:
        jobs.append(
            ("pubmed", cell)
        )

    for cell in manifest["cell_types"]:
        jobs.append(
            ("europe_pmc", cell)
        )

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "lnp-liver-evidence-tool/1.0 "
                f"({ncbi_email or 'email-not-configured'})"
            )
        }
    )

    try:
        for source, cell in jobs:
            print(
                f"Running {source}/{cell}..."
            )

            try:
                query = manifest[
                    "queries"
                ][source][cell]

                if source == "pubmed":
                    result = (
                        run_pubmed_query(
                            session=session,
                            run_dir=run_dir,
                            manifest_version=(
                                manifest_version
                            ),
                            cell=cell,
                            query=query,
                            cap=cap,
                            page_size=(
                                pubmed_page_size
                            ),
                            ncbi_email=(
                                ncbi_email
                            ),
                            ncbi_api_key=(
                                ncbi_api_key
                            ),
                        )
                    )

                else:
                    result = (
                        run_europe_pmc_query(
                            session=session,
                            run_dir=run_dir,
                            manifest_version=(
                                manifest_version
                            ),
                            cell=cell,
                            query=query,
                            cap=cap,
                            page_size=(
                                europe_pmc_page_size
                            ),
                        )
                    )

                replace_result(
                    run_metadata,
                    result,
                )

                # A successful resumed job clears its old error.
                remove_error(
                    run_metadata,
                    source,
                    cell,
                )

                print(
                    "  matches="
                    f"{result['total_matches']}, "
                    "retrieved="
                    f"{result['records_retrieved']}, "
                    "pages="
                    f"{result['pages_completed']}"
                )

            except Exception as error:
                # A failed attempt must not retain a stale success.
                remove_result(
                    run_metadata,
                    source,
                    cell,
                )

                # Keep only the newest error for this job.
                remove_error(
                    run_metadata,
                    source,
                    cell,
                )

                error_record = {
                    "source": source,
                    "cell_type": cell,
                    "error_type": (
                        type(error).__name__
                    ),
                    "error": str(error),
                    "time": iso_now(),
                }

                run_metadata[
                    "errors"
                ].append(
                    error_record
                )

                print(
                    "  FAILED: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )

            write_json(
                run_metadata_path,
                run_metadata,
            )

            # Courtesy delay between source/cell jobs.
            time.sleep(
                COURTESY_DELAY_SECONDS
            )

    finally:
        session.close()

    expected_job_keys = set(jobs)

    completed_job_keys = {
        (
            result.get("source"),
            result.get("cell_type"),
        )
        for result in run_metadata[
            "results"
        ]
    }

    missing_job_keys = (
        expected_job_keys
        - completed_job_keys
    )

    run_metadata["completed_at"] = (
        iso_now()
    )

    if (
        run_metadata["errors"]
        or missing_job_keys
    ):
        run_metadata["status"] = "partial"
    else:
        run_metadata["status"] = "completed"

    run_metadata["missing_jobs"] = [
        {
            "source": source,
            "cell_type": cell,
        }
        for source, cell
        in sorted(missing_job_keys)
    ]

    write_json(
        run_metadata_path,
        run_metadata,
    )

    print()
    print(f"Run directory: {run_dir}")
    print(
        f"Status: "
        f"{run_metadata['status']}"
    )
    print(
        "Successful searches: "
        f"{len(run_metadata['results'])}"
    )
    print(
        "Failed searches: "
        f"{len(run_metadata['errors'])}"
    )
    print(
        "Missing searches: "
        f"{len(missing_job_keys)}"
    )

    if (
        run_metadata["errors"]
        or missing_job_keys
    ):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())