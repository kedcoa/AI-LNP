from __future__ import annotations

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


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_PATH = (
    PROJECT_ROOT
    / "docs"
    / "search"
    / "query_manifest_v1.yaml"
)

RAW_SEARCH_ROOT = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "searches"
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

EUROPE_PMC_SEARCH_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)

TOOL_NAME = "lnp_liver_evidence_tool"

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


def now_local() -> datetime:
    """Return the current time with the local timezone included."""
    return datetime.now().astimezone()


def iso_now() -> str:
    """Return an ISO 8601 timestamp containing the timezone."""
    return now_local().isoformat(timespec="seconds")


def sha256_bytes(content: bytes) -> str:
    """Calculate a SHA-256 checksum for raw response bytes."""
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, value: object) -> None:
    """Write derived metadata as readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def load_manifest() -> dict:
    """Read and validate the YAML query manifest."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest not found: {MANIFEST_PATH}"
        )

    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
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

    actual_cells = set(manifest["cell_types"])

    if actual_cells != EXPECTED_CELLS:
        raise ValueError(
            "cell_types must contain exactly "
            "hepatocyte, kupffer, lsec, and hsc. "
            f"Found: {sorted(actual_cells)}"
        )

    actual_sources = set(manifest["queries"])

    if actual_sources != EXPECTED_SOURCES:
        raise ValueError(
            "queries must contain exactly pubmed and "
            f"europe_pmc. Found: {sorted(actual_sources)}"
        )

    for source in EXPECTED_SOURCES:
        source_cells = set(
            manifest["queries"][source]
        )

        if source_cells != EXPECTED_CELLS:
            raise ValueError(
                f"{source} queries must contain exactly "
                "hepatocyte, kupffer, lsec, and hsc. "
                f"Found: {sorted(source_cells)}"
            )

        for cell in EXPECTED_CELLS:
            query = manifest["queries"][source][cell]

            if not isinstance(query, str):
                raise ValueError(
                    f"Query {source}/{cell} is not text."
                )

            if not query.strip():
                raise ValueError(
                    f"Query {source}/{cell} is empty."
                )

    cap = int(
        manifest["retrieval_policy"][
            "retrieval_cap_per_cell_per_source"
        ]
    )

    if cap <= 0:
        raise ValueError(
            "The retrieval cap must be greater than zero."
        )

    return manifest


def sanitized_url(url: str, params: dict) -> str:
    """Create a saved URL with any API key removed."""
    safe_params = {
        key: value
        for key, value in params.items()
        if key != "api_key"
    }
    return f"{url}?{urlencode(safe_params)}"


def save_raw_response(
    path: Path,
    response: requests.Response,
) -> str:
    """
    Save the exact bytes returned by the server.

    Do not parse and reserialize the response before this step.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return sha256_bytes(response.content)


def make_request(
    session: requests.Session,
    url: str,
    params: dict,
) -> requests.Response:
    """
    Make one API request.

    Robust retry and exponential backoff are intentionally left
    for the Day 3 afternoon implementation.
    """
    response = session.get(
        url,
        params=params,
        timeout=60,
    )
    response.raise_for_status()
    return response


def run_pubmed_query(
    session: requests.Session,
    run_dir: Path,
    manifest_version: str,
    cell: str,
    query: str,
    cap: int,
    ncbi_email: str | None,
    ncbi_api_key: str | None,
) -> dict:
    """Run PubMed ESearch followed by PubMed EFetch."""
    output_dir = run_dir / "pubmed" / cell
    output_dir.mkdir(parents=True, exist_ok=True)

    esearch_params = {
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
        esearch_params["email"] = ncbi_email

    if ncbi_api_key:
        esearch_params["api_key"] = ncbi_api_key

    esearch_requested_at = iso_now()

    esearch_response = make_request(
        session,
        PUBMED_ESEARCH_URL,
        esearch_params,
    )

    esearch_completed_at = iso_now()

    esearch_raw_path = (
        output_dir / "esearch_response.json"
    )

    esearch_checksum = save_raw_response(
        esearch_raw_path,
        esearch_response,
    )

    esearch_data = json.loads(
        esearch_response.content
    )

    esearch_result = esearch_data["esearchresult"]
    pmids = esearch_result.get("idlist", [])
    total_matches = int(
        esearch_result.get("count", 0)
    )
    records_returned = len(pmids)

    esearch_metadata = {
        "manifest_version": manifest_version,
        "query_id": (
            f"pubmed_{cell}_v{manifest_version}"
        ),
        "source": "pubmed",
        "cell_type": cell,
        "endpoint": PUBMED_ESEARCH_URL,
        "request_url_without_api_key": sanitized_url(
            PUBMED_ESEARCH_URL,
            esearch_params,
        ),
        "query_text": query,
        "parameters_without_api_key": {
            key: value
            for key, value in esearch_params.items()
            if key != "api_key"
        },
        "api_key_used": bool(ncbi_api_key),
        "requested_at": esearch_requested_at,
        "completed_at": esearch_completed_at,
        "http_status": esearch_response.status_code,
        "content_type": esearch_response.headers.get(
            "Content-Type"
        ),
        "total_matches": total_matches,
        "records_returned": records_returned,
        "retrieval_cap": cap,
        "pagination": {
            "method": "offset",
            "retstart": 0,
            "retmax": cap,
            "next_retstart": records_returned,
            "more_results_available": (
                total_matches > records_returned
            ),
        },
        "raw_file": esearch_raw_path.name,
        "sha256": esearch_checksum,
    }

    write_json(
        output_dir / "esearch_response.meta.json",
        esearch_metadata,
    )

    efetch_completed = False

    if pmids:
        efetch_params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "tool": TOOL_NAME,
        }

        if ncbi_email:
            efetch_params["email"] = ncbi_email

        if ncbi_api_key:
            efetch_params["api_key"] = ncbi_api_key

        efetch_requested_at = iso_now()

        efetch_response = make_request(
            session,
            PUBMED_EFETCH_URL,
            efetch_params,
        )

        efetch_completed_at = iso_now()

        efetch_raw_path = (
            output_dir / "efetch_response.xml"
        )

        efetch_checksum = save_raw_response(
            efetch_raw_path,
            efetch_response,
        )

        efetch_metadata = {
            "manifest_version": manifest_version,
            "query_id": (
                f"pubmed_{cell}_v{manifest_version}"
            ),
            "source": "pubmed",
            "cell_type": cell,
            "endpoint": PUBMED_EFETCH_URL,
            "request_url_without_api_key": sanitized_url(
                PUBMED_EFETCH_URL,
                efetch_params,
            ),
            "pmids": pmids,
            "pmid_count_requested": len(pmids),
            "api_key_used": bool(ncbi_api_key),
            "requested_at": efetch_requested_at,
            "completed_at": efetch_completed_at,
            "http_status": efetch_response.status_code,
            "content_type": efetch_response.headers.get(
                "Content-Type"
            ),
            "raw_file": efetch_raw_path.name,
            "sha256": efetch_checksum,
        }

        write_json(
            output_dir / "efetch_response.meta.json",
            efetch_metadata,
        )

        efetch_completed = True

    return {
        "source": "pubmed",
        "cell_type": cell,
        "total_matches": total_matches,
        "retrieval_cap": cap,
        "records_retrieved": records_returned,
        "status": (
            "cap_reached"
            if records_returned == cap
            and total_matches >= cap
            else "all_available_retrieved"
        ),
        "efetch_completed": efetch_completed,
    }


def run_europe_pmc_query(
    session: requests.Session,
    run_dir: Path,
    manifest_version: str,
    cell: str,
    query: str,
    cap: int,
) -> dict:
    """Run one capped Europe PMC discovery request."""
    output_dir = run_dir / "europe_pmc" / cell
    output_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": cap,
        "cursorMark": "*",
    }

    requested_at = iso_now()

    response = make_request(
        session,
        EUROPE_PMC_SEARCH_URL,
        params,
    )

    completed_at = iso_now()

    raw_path = output_dir / "search_response.json"

    checksum = save_raw_response(
        raw_path,
        response,
    )

    data = json.loads(response.content)

    results = (
        data.get("resultList", {})
        .get("result", [])
    )

    total_matches = int(
        data.get("hitCount", 0)
    )

    records_returned = len(results)
    next_cursor = data.get("nextCursorMark")

    metadata = {
        "manifest_version": manifest_version,
        "query_id": (
            f"europe_pmc_{cell}_v{manifest_version}"
        ),
        "source": "europe_pmc",
        "cell_type": cell,
        "endpoint": EUROPE_PMC_SEARCH_URL,
        "request_url": sanitized_url(
            EUROPE_PMC_SEARCH_URL,
            params,
        ),
        "query_text": query,
        "parameters": params,
        "requested_at": requested_at,
        "completed_at": completed_at,
        "http_status": response.status_code,
        "content_type": response.headers.get(
            "Content-Type"
        ),
        "total_matches": total_matches,
        "records_returned": records_returned,
        "retrieval_cap": cap,
        "pagination": {
            "method": "cursor",
            "request_cursor": "*",
            "next_cursor": next_cursor,
            "more_results_available": (
                total_matches > records_returned
            ),
        },
        "raw_file": raw_path.name,
        "sha256": checksum,
    }

    write_json(
        output_dir / "search_response.meta.json",
        metadata,
    )

    return {
        "source": "europe_pmc",
        "cell_type": cell,
        "total_matches": total_matches,
        "retrieval_cap": cap,
        "records_retrieved": records_returned,
        "status": (
            "cap_reached"
            if records_returned == cap
            and total_matches >= cap
            else "all_available_retrieved"
        ),
    }


def main() -> int:
    """Run all eight Day 3 morning discovery searches."""
    load_dotenv(PROJECT_ROOT / ".env")

    manifest = load_manifest()

    manifest_version = str(
        manifest["manifest_version"]
    )

    cap = int(
        manifest["retrieval_policy"][
            "retrieval_cap_per_cell_per_source"
        ]
    )

    started = now_local()
    date_directory = started.strftime("%Y-%m-%d")
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

    shutil.copy2(
        MANIFEST_PATH,
        run_dir / "manifest_snapshot.yaml",
    )

    run_metadata_path = (
        run_dir / "run_metadata.json"
    )

    run_metadata = {
        "run_id": run_id,
        "manifest_version": manifest_version,
        "manifest_snapshot": (
            "manifest_snapshot.yaml"
        ),
        "started_at": started.isoformat(
            timespec="seconds"
        ),
        "completed_at": None,
        "status": "in_progress",
        "retrieval_cap_per_cell_per_source": cap,
        "results": [],
        "errors": [],
    }

    write_json(
        run_metadata_path,
        run_metadata,
    )

    ncbi_email = os.environ.get("NCBI_EMAIL")
    ncbi_api_key = os.environ.get(
        "NCBI_API_KEY"
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

    jobs = []

    for cell in manifest["cell_types"]:
        jobs.append(("pubmed", cell))

    for cell in manifest["cell_types"]:
        jobs.append(("europe_pmc", cell))

    for source, cell in jobs:
        print(f"Running {source}/{cell}...")

        try:
            query = manifest["queries"][source][cell]

            if source == "pubmed":
                result = run_pubmed_query(
                    session=session,
                    run_dir=run_dir,
                    manifest_version=manifest_version,
                    cell=cell,
                    query=query,
                    cap=cap,
                    ncbi_email=ncbi_email,
                    ncbi_api_key=ncbi_api_key,
                )
            else:
                result = run_europe_pmc_query(
                    session=session,
                    run_dir=run_dir,
                    manifest_version=manifest_version,
                    cell=cell,
                    query=query,
                    cap=cap,
                )

            run_metadata["results"].append(result)

            print(
                f"  matches={result['total_matches']}, "
                f"retrieved={result['records_retrieved']}"
            )

        except Exception as error:
            error_record = {
                "source": source,
                "cell_type": cell,
                "error_type": type(error).__name__,
                "error": str(error),
                "time": iso_now(),
            }

            run_metadata["errors"].append(
                error_record
            )

            print(
                f"  FAILED: "
                f"{type(error).__name__}: {error}"
            )

        write_json(
            run_metadata_path,
            run_metadata,
        )

        # Courtesy delay for this initial morning run.
        # Automatic retry/backoff belongs to the afternoon.
        time.sleep(0.5)

    run_metadata["completed_at"] = iso_now()

    if run_metadata["errors"]:
        run_metadata["status"] = "partial"
    else:
        run_metadata["status"] = "completed"

    write_json(
        run_metadata_path,
        run_metadata,
    )

    print()
    print(f"Run directory: {run_dir}")
    print(f"Status: {run_metadata['status']}")
    print(
        "Successful searches: "
        f"{len(run_metadata['results'])}"
    )
    print(
        "Failed searches: "
        f"{len(run_metadata['errors'])}"
    )

    return (
        0
        if not run_metadata["errors"]
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())