#!/usr/bin/env python3
"""Build the local ORACLE-EXP-INV-02 frames from official read-only sources."""

from __future__ import annotations

import argparse
import heapq
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from investigation_harness import sha256_bytes, sha256_json
from investigation_sampling import (
    BOE_HOSTS,
    PLACSP_HOSTS,
    SignalReadOnlyClient,
    compare_signal_units,
    detect_borme_challenge_candidates,
    iter_placsp_zip_entries,
    load_ephemeral_signal_key,
    parse_borme_articles,
    placsp_units,
    redacted_borme_manifest,
    redacted_placsp_manifest,
    select_borme_article_frame,
    select_placsp_challenge,
    source_snapshot,
)

JsonObject = dict[str, Any]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_DIR = REPO_ROOT / "docs/implementation/spikes/.work/77/default"
SEED = "ORACLE-EXP-INV-02|frame-v1.1|2026-07-23"
USER_AGENT = "OPN-Oracle-read-only-investigation-spike/2.0"


@dataclass(frozen=True, slots=True)
class PlacspSource:
    source_family: Literal["hosted", "aggregated"]
    period: Literal["recent", "historical"]
    collection: str
    url: str
    filename: str


PLACSP_SOURCES = (
    PlacspSource(
        source_family="hosted",
        period="historical",
        collection="sindicacion_643",
        url=(
            "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
            "licitacionesPerfilesContratanteCompleto3_202201.zip"
        ),
        filename="hosted_202201.zip",
    ),
    PlacspSource(
        source_family="hosted",
        period="recent",
        collection="sindicacion_643",
        url=(
            "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
            "licitacionesPerfilesContratanteCompleto3_202501.zip"
        ),
        filename="hosted_202501.zip",
    ),
    PlacspSource(
        source_family="aggregated",
        period="historical",
        collection="sindicacion_1044",
        url=(
            "https://contrataciondelestado.es/sindicacion/sindicacion_1044/"
            "PlataformasAgregadasSinMenores_202201.zip"
        ),
        filename="aggregated_202201.zip",
    ),
    PlacspSource(
        source_family="aggregated",
        period="recent",
        collection="sindicacion_1044",
        url=(
            "https://contrataciondelestado.es/sindicacion/sindicacion_1044/"
            "PlataformasAgregadasSinMenores_202501.zip"
        ),
        filename="aggregated_202501.zip",
    ),
)


def _write_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.chmod(mode)
    temporary.replace(path)


def _download(
    url: str,
    path: Path,
    *,
    allowed_hosts: frozenset[str],
    max_bytes: int,
    accept: str,
    attempts: int = 4,
) -> JsonObject:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError("Official source URL is outside its HTTPS allowlist")
    metadata_path = path.with_name(f"{path.name}.source.json")
    if path.exists():
        observed = source_snapshot(path, url=url)
        if metadata_path.exists():
            stored = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                isinstance(stored, dict)
                and stored.get("url") == observed["url"]
                and stored.get("sha256") == observed["sha256"]
                and stored.get("bytes") == observed["bytes"]
            ):
                return stored | {"reused": True}
        _write_json(metadata_path, observed)
        return observed | {"reused": True}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    digest = __import__("hashlib").sha256()
    size = 0
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"Accept": accept, "User-Agent": USER_AGENT},
        )
        digest = __import__("hashlib").sha256()
        size = 0
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in allowed_hosts:
                    raise ValueError("Official source redirected outside its allowlist")
                with temporary.open("wb") as target:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("Official source exceeds byte budget")
                        digest.update(chunk)
                        target.write(chunk)
            break
        except urllib.error.HTTPError as error:
            temporary.unlink(missing_ok=True)
            if error.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
            time.sleep(2**attempt)
        except urllib.error.URLError:
            temporary.unlink(missing_ok=True)
            if attempt + 1 >= attempts:
                raise
            time.sleep(2**attempt)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    else:  # pragma: no cover - the loop either succeeds or raises
        raise RuntimeError("Official source retry loop ended unexpectedly")
    temporary.chmod(0o600)
    temporary.replace(path)
    result = {
        "url": url,
        "sha256": digest.hexdigest(),
        "bytes": size,
        "acquired_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json(metadata_path, result)
    return result | {"reused": False}


def _date_range(start: date, end: date) -> list[date]:
    current = start
    dates = []
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _borme_summary_items(payload: JsonObject) -> list[JsonObject]:
    try:
        diaries = payload["data"]["sumario"]["diario"]
    except (KeyError, TypeError) as error:
        raise ValueError("BORME summary schema drifted") from error
    diaries = diaries if isinstance(diaries, list) else [diaries]
    items: list[JsonObject] = []
    for diary in diaries:
        if not isinstance(diary, dict):
            continue
        sections = diary.get("seccion", [])
        sections = sections if isinstance(sections, list) else [sections]
        for section in sections:
            if not isinstance(section, dict) or section.get("codigo") != "A":
                continue
            section_items = section.get("item", [])
            section_items = (
                section_items if isinstance(section_items, list) else [section_items]
            )
            items.extend(item for item in section_items if isinstance(item, dict))
    return items


def _load_borme_period(
    *,
    work_dir: Path,
    year: int,
    period: Literal["recent", "historical"],
    workers: int,
) -> tuple[list[JsonObject], JsonObject]:
    source_dir = work_dir / "sources" / "borme" / str(year)
    summary_status: Counter[str] = Counter()
    document_specs: list[tuple[str, str, Path]] = []
    source_records: list[JsonObject] = []
    for day in _date_range(date(year, 1, 1), date(year, 1, 31)):
        day_text = day.strftime("%Y%m%d")
        url = f"https://www.boe.es/datosabiertos/api/borme/sumario/{day_text}"
        path = source_dir / f"summary_{day_text}.json"
        missing_path = source_dir / f"summary_{day_text}.404.json"
        if missing_path.exists():
            summary_status["not_published_404"] += 1
            continue
        try:
            record = _download(
                url,
                path,
                allowed_hosts=BOE_HOSTS,
                max_bytes=2_000_000,
                accept="application/json",
            )
        except urllib.error.HTTPError as error:
            if error.code == 404:
                summary_status["not_published_404"] += 1
                _write_json(
                    missing_path,
                    {
                        "url": url,
                        "status": 404,
                        "observed_at_utc": datetime.now(UTC).isoformat(),
                    },
                )
                continue
            raise
        summary_status["published_200"] += 1
        source_records.append(record)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("BORME summary is not an object")
        for item in _borme_summary_items(payload):
            document_id = item.get("identificador")
            xml_url_value = item.get("url_xml")
            xml_url = (
                xml_url_value.get("texto")
                if isinstance(xml_url_value, dict)
                else xml_url_value
            )
            if not isinstance(document_id, str) or not isinstance(xml_url, str):
                continue
            document_specs.append(
                (document_id, xml_url, source_dir / "xml" / f"{document_id}.xml")
            )

    def acquire(
        spec: tuple[str, str, Path],
    ) -> tuple[tuple[str, str, Path], JsonObject]:
        _, url, path = spec
        return spec, _download(
            url,
            path,
            allowed_hosts=BOE_HOSTS,
            max_bytes=5_000_000,
            accept="application/xml,text/xml;q=0.9",
        )

    document_records: dict[str, JsonObject] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(acquire, spec) for spec in document_specs]
        for future in as_completed(futures):
            (document_id, _, _), record = future.result()
            document_records[document_id] = record

    articles: list[JsonObject] = []
    for document_id, xml_url, path in sorted(document_specs):
        for article in parse_borme_articles(path.read_bytes(), source_url=xml_url):
            article["period"] = period
            articles.append(article)
    return articles, {
        "year": year,
        "period": period,
        "summary_status": dict(summary_status),
        "summaries": len(source_records),
        "documents": len(document_records),
        "articles": len(articles),
        "summary_manifest_hash": sha256_json(
            [
                {key: value for key, value in record.items() if key != "reused"}
                for record in source_records
            ]
        ),
        "document_manifest_hash": sha256_json(
            [
                {
                    key: value
                    for key, value in document_records[document_id].items()
                    if key != "reused"
                }
                for document_id in sorted(document_records)
            ]
        ),
    }


def _candidate_pool(
    articles: list[JsonObject], *, seed: str, per_family_period: int = 24
) -> JsonObject:
    heaps: dict[tuple[str, str], list[tuple[int, str, JsonObject]]] = {}
    inventory: Counter[tuple[str, str]] = Counter()
    for article in articles:
        period = str(article["period"])
        for candidate in detect_borme_challenge_candidates(article):
            family = str(candidate["family"])
            key = period, family
            inventory[key] += 1
            rank = int(
                sha256_bytes(f"{seed}\0{candidate['candidate_id']}".encode()),
                16,
            )
            heap = heaps.setdefault(key, [])
            local_row = {
                **candidate,
                "period": period,
                "publication_date": article["publication_date"],
                "document_id": article["document_id"],
                "article_number": article["article_number"],
                "province": article["province"],
                "source_url": article["source_url"],
                "source_text": article["source_text"],
                "company_literal": article["company_literal"],
            }
            item = (-rank, str(candidate["candidate_id"]), local_row)
            if len(heap) < per_family_period:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    selected: list[JsonObject] = []
    for key in sorted(heaps):
        selected.extend(
            row
            for _, _, row in sorted(
                heaps[key],
                key=lambda item: (-item[0], item[1]),
            )
        )
    return {
        "status": "candidate_pool_only_human_strata_pending",
        "per_family_period": per_family_period,
        "inventory": [
            {"period": key[0], "family": key[1], "candidates": inventory[key]}
            for key in sorted(inventory)
        ],
        "selected": selected,
    }


def _run_signal(
    *,
    units: list[JsonObject],
    key_file: Path | None,
    base_url: str | None,
    expected_slug: str | None,
) -> JsonObject:
    if key_file is None:
        return {
            "status": "not_run_missing_ephemeral_credential",
            "measured_denominator": 0,
        }
    if not all((base_url, expected_slug)):
        raise ValueError("Signal comparison requires base URL and expected slug")
    key = load_ephemeral_signal_key(key_file)
    client = SignalReadOnlyClient(
        base_url=str(base_url),
        allowed_host="signal.opnconsultoria.com",
        api_key=key,
    )
    preflight = client.preflight(expected_slug=str(expected_slug))
    comparison = compare_signal_units(units, fetch_awards=client.awards_by_folder)
    return {
        **comparison,
        "preflight": preflight,
        "cleanup_verified": False,
        "cleanup_gate": "external_consumer_pause_and_401_check_required",
    }


def run(args: argparse.Namespace) -> JsonObject:
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(work_dir, 0o700)
    placsp_entries: list[JsonObject] = []
    placsp_sources = []
    for source in PLACSP_SOURCES:
        path = work_dir / "sources" / "placsp" / source.filename
        source_record = _download(
            source.url,
            path,
            allowed_hosts=PLACSP_HOSTS,
            max_bytes=args.placsp_max_bytes,
            accept="application/zip",
        )
        placsp_sources.append(
            source_record
            | {
                "source_family": source.source_family,
                "period": source.period,
                "collection": source.collection,
            }
        )
        placsp_entries.extend(
            iter_placsp_zip_entries(
                path,
                source_family=source.source_family,
                collection=source.collection,
                period=source.period,
            )
        )
    units = placsp_units(placsp_entries, seed=SEED)
    placsp_selection = select_placsp_challenge(units, seed=SEED)
    _write_json(work_dir / "placsp_annotation_ledger.json", placsp_selection)

    borme_articles: list[JsonObject] = []
    borme_sources = []
    for year, period in ((2022, "historical"), (2025, "recent")):
        articles, source_record = _load_borme_period(
            work_dir=work_dir,
            year=year,
            period=period,
            workers=args.borme_workers,
        )
        borme_articles.extend(articles)
        borme_sources.append(source_record)
    article_frame = select_borme_article_frame(
        borme_articles,
        seed=SEED,
        per_period=args.borme_articles_per_period,
    )
    candidate_pool = _candidate_pool(borme_articles, seed=SEED)
    _write_json(work_dir / "borme_article_gold_ledger.json", article_frame)
    _write_json(work_dir / "borme_challenge_candidate_ledger.json", candidate_pool)

    selected = placsp_selection.get("selected")
    selected_units = [row for row in selected if isinstance(row, dict)]
    signal = _run_signal(
        units=selected_units,
        key_file=args.signal_key_file,
        base_url=args.signal_base_url,
        expected_slug=args.signal_expected_slug,
    )
    redacted_candidates = {
        "status": candidate_pool["status"],
        "inventory": candidate_pool["inventory"],
        "selected_candidate_count": len(candidate_pool["selected"]),
        "human_challenge_labels_completed": 0,
        "target": 72,
    }
    result = {
        "protocol_version": "1.1",
        "seed_hash": sha256_bytes(SEED.encode()),
        "placsp": {
            "sources": placsp_sources,
            "raw_parsed_entry_revisions": len(placsp_entries),
            "core_units_after_dedup_and_folder_cap": len(units),
            "challenge": redacted_placsp_manifest(placsp_selection),
        },
        "borme": {
            "sources": borme_sources,
            "article_frame": redacted_borme_manifest(article_frame),
            "challenge": redacted_candidates,
        },
        "signal": signal,
        "runtime_mutations": False,
        "domain_rows_written": 0,
        "limitations": [
            "PLACSP 96 is a challenge set, not a weighted national estimate.",
            "BORME article gold requires exhaustive blind human annotation.",
            "BORME 72 challenge labels cannot be promoted by name/suffix heuristics.",
            "Signal v1 lacks revision and does not index the aggregated family.",
        ],
    }
    _write_json(work_dir / "result_redacted.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--placsp-max-bytes", type=int, default=300_000_000)
    parser.add_argument("--borme-workers", type=int, default=4)
    parser.add_argument("--borme-articles-per-period", type=int, default=36)
    parser.add_argument("--signal-key-file", type=Path)
    parser.add_argument("--signal-base-url")
    parser.add_argument("--signal-expected-slug")
    return parser


def main() -> int:
    result = run(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
