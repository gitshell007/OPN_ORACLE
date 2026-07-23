#!/usr/bin/env python3
"""Pure sampling and safety primitives for ORACLE-EXP-INV-02.

Real source material belongs under the ignored ``.work/77`` directory.  Functions in this module
return either local annotation rows or redacted aggregates; they never write Oracle domain data.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

from investigation_harness import (
    canonical_json,
    sha256_bytes,
    sha256_json,
    wilson_interval,
)

JsonObject = dict[str, Any]
SourceFamily = Literal["hosted", "aggregated"]
Period = Literal["recent", "historical"]
Complexity = Literal["simple", "complex"]

ATOM = "{http://www.w3.org/2005/Atom}"
CBC = "{urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2}"
CAC = "{urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2}"
PLACE_CAC = (
    "{urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2}"
)
PLACE_CBC = "{urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2}"
PLACSP_HOSTS = frozenset(
    {"contrataciondelsectorpublico.gob.es", "contrataciondelestado.es"}
)
BOE_HOSTS = frozenset({"www.boe.es", "boe.es"})
SIGNAL_INVESTIGATION_HOSTS = frozenset({"signal.opnconsultoria.com"})

CONTRACT_TYPE_MAP = {
    "1": "supplies",
    "2": "services",
    "3": "works",
    "21": "works_concession",
    "22": "services_concession",
    "31": "public_private_partnership",
    "40": "mixed",
    "50": "private",
    "7": "administrative_special",
    "8": "patrimonial",
    "other": "other",
}

BORME_ACTION_MARKERS = (
    "Ceses/Dimisiones.",
    "Nombramientos.",
    "Revocaciones.",
    "Reelecciones.",
)
BORME_ROLE_PATTERN = re.compile(
    r"(?:Adm\.\s*(?:Unico|Único|Solid\.|Mancom\.)|Administrador(?:a)?|Consejero|"
    r"Presidente|Vicepresid\.|Secretario|Con\.Delegado|Cons\.Del\.Sol|Liquidador):\s*"
    r"(?P<literal>[^.]+)",
    re.IGNORECASE,
)
BORME_SOLE_PATTERN = re.compile(r"Socio único:\s*(?P<literal>[^.]+)", re.IGNORECASE)
BORME_REPRESENTATIVE_PATTERN = re.compile(
    r"(?:Representan|Representante|REPR\.143 RRM):\s*(?P<literal>[^.]+)",
    re.IGNORECASE,
)
BORME_DIFFICULT_PATTERN = re.compile(
    r"Fe de erratas|Correcci[oó]n|sociedad profesional|\bSLP\b",
    re.IGNORECASE,
)


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = " ".join(value.split())
    return clean or None


def _element_text(element: ET.Element | None) -> str | None:
    return _text(element.text) if element is not None else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _stable_rank(seed: str, *parts: object) -> str:
    return hashlib.sha256(
        canonical_json({"seed": seed, "parts": [str(part) for part in parts]}).encode()
    ).hexdigest()


def _entry_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("collection") or ""), str(row.get("entry_id") or "")


def deduplicate_latest_entries(rows: Iterable[JsonObject]) -> list[JsonObject]:
    """Keep the latest Atom revision per collection and entry id."""

    latest: dict[tuple[str, str], JsonObject] = {}
    for row in rows:
        key = _entry_identity(row)
        if not all(key):
            raise ValueError("Every PLACSP entry needs collection and entry_id")
        current = latest.get(key)
        if current is None or str(row.get("updated") or "") > str(
            current.get("updated") or ""
        ):
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def _party_name(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    return _element_text(node.find(f"{CAC}PartyName/{CBC}Name")) or _element_text(
        node.find(f"{CAC}Party/{CAC}PartyName/{CBC}Name")
    )


def _winner_identifier_present(node: ET.Element | None) -> bool:
    return bool(
        node is not None
        and _element_text(node.find(f"{CAC}PartyIdentification/{CBC}ID")) is not None
    )


def _document_references(entry: ET.Element) -> list[JsonObject]:
    references: list[JsonObject] = []
    for node in entry.iter():
        if not _local_name(node.tag).endswith("DocumentReference"):
            continue
        uri = next(
            (
                _text(child.text)
                for child in node.iter()
                if _local_name(child.tag) == "URI" and _text(child.text)
            ),
            None,
        )
        document_id = next(
            (
                _text(child.text)
                for child in node.iter()
                if _local_name(child.tag) == "ID" and _text(child.text)
            ),
            None,
        )
        if uri:
            references.append({"document_id": document_id, "url": uri})
    return references


def _contracting_party(entry: ET.Element) -> ET.Element | None:
    status = entry.find(f"{PLACE_CAC}ContractFolderStatus")
    return (
        status.find(f"{PLACE_CAC}LocatedContractingParty")
        if status is not None
        else None
    )


def _contract_type(entry: ET.Element) -> str:
    status = entry.find(f"{PLACE_CAC}ContractFolderStatus")
    project = status.find(f"{CAC}ProcurementProject") if status is not None else None
    code = (
        _element_text(project.find(f"{CBC}TypeCode")) if project is not None else None
    )
    return CONTRACT_TYPE_MAP.get(code or "", CONTRACT_TYPE_MAP["other"])


def parse_placsp_entries(
    xml_bytes: bytes,
    *,
    source_family: SourceFamily,
    collection: str,
    period: Period,
    member_name: str,
) -> list[JsonObject]:
    """Parse source rows needed to create a local annotation frame."""

    root = ET.fromstring(xml_bytes)
    parsed: list[JsonObject] = []
    for entry in root.findall(f"{ATOM}entry"):
        entry_id = _element_text(entry.find(f"{ATOM}id"))
        updated = _element_text(entry.find(f"{ATOM}updated"))
        if not entry_id or not updated:
            continue
        status = entry.find(f"{PLACE_CAC}ContractFolderStatus")
        folder_id = (
            _element_text(status.find(f"{CBC}ContractFolderID"))
            if status is not None
            else None
        )
        if not folder_id:
            continue
        links = [
            str(link.attrib["href"])
            for link in entry.findall(f"{ATOM}link")
            if link.attrib.get("href")
        ]
        source_url = links[0] if links else None
        producer = urlparse(source_url).hostname if source_url else collection
        party = _contracting_party(entry)
        buyer_name = _party_name(party)
        buyer_identifiers = []
        if party is not None:
            buyer_party = party.find(f"{CAC}Party")
            buyer_identifiers = [
                {
                    "scheme": identifier.attrib.get("schemeName"),
                    "value": _text(identifier.text),
                }
                for identifier in (
                    buyer_party.findall(f"{CAC}PartyIdentification/{CBC}ID")
                    if buyer_party is not None
                    else []
                )
                if _text(identifier.text)
            ]
        result_groups: dict[str, list[JsonObject]] = defaultdict(list)
        results = entry.findall(f".//{CAC}TenderResult")
        for result in results:
            lot_id = _element_text(
                result.find(f"{CAC}AwardedTenderedProject/{CBC}ProcurementProjectLotID")
            )
            scope = lot_id or "__procedure__"
            received_raw = _element_text(result.find(f"{CBC}ReceivedTenderQuantity"))
            received = (
                int(received_raw) if received_raw and received_raw.isdigit() else None
            )
            winner = result.find(f"{CAC}WinningParty")
            winner_name = _party_name(winner)
            result_groups[scope].append(
                {
                    "lot_id": lot_id,
                    "received_tender_quantity": received,
                    "result_code": _element_text(result.find(f"{CBC}ResultCode")),
                    "award_date": _element_text(result.find(f"{CBC}AwardDate")),
                    "winner_name": winner_name,
                    "winner_identifier_present": _winner_identifier_present(winner),
                    "is_ute": bool(
                        winner_name
                        and (
                            winner_name.casefold().startswith("ute ")
                            or "unión temporal" in winner_name.casefold()
                        )
                    ),
                }
            )
        lot_count = len(result_groups)
        all_results = [result for group in result_groups.values() for result in group]
        complex_entry = (
            lot_count > 1
            or any(len(group) > 1 for group in result_groups.values())
            or any(result["is_ute"] for result in all_results)
        )
        parsed.append(
            {
                "source_family": source_family,
                "period": period,
                "collection": collection,
                "producer": producer,
                "member_name": member_name,
                "entry_id": entry_id,
                "updated": updated,
                "folder_id": folder_id,
                "source_url": source_url,
                "contract_type": _contract_type(entry),
                "buyer_name": buyer_name,
                "buyer_identifiers": buyer_identifiers,
                "status_code": (
                    _element_text(status.find(f"{PLACE_CBC}ContractFolderStatusCode"))
                    if status is not None
                    else None
                ),
                "documents": _document_references(entry),
                "complexity": "complex" if complex_entry else "simple",
                "flags": {
                    "multilot": lot_count > 1,
                    "multiwinner": any(
                        len(group) > 1 for group in result_groups.values()
                    ),
                    "ute": any(result["is_ute"] for result in all_results),
                    "deserted_or_cancelled": any(
                        result["winner_name"] is None for result in all_results
                    ),
                    "received_tender_quantity_ge_5": any(
                        isinstance(result["received_tender_quantity"], int)
                        and result["received_tender_quantity"] >= 5
                        for result in all_results
                    ),
                },
                "result_groups": dict(result_groups),
            }
        )
    return parsed


def iter_placsp_zip_entries(
    path: Path,
    *,
    source_family: SourceFamily,
    collection: str,
    period: Period,
) -> Iterator[JsonObject]:
    with zipfile.ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            if not member.casefold().endswith(".atom"):
                continue
            for entry in parse_placsp_entries(
                archive.read(member),
                source_family=source_family,
                collection=collection,
                period=period,
                member_name=member,
            ):
                yield entry


def _unit_id(entry: Mapping[str, Any], lot_id: str) -> str:
    return sha256_json(
        {
            "source_family": entry["source_family"],
            "collection": entry["collection"],
            "producer": entry["producer"],
            "entry_id": entry["entry_id"],
            "folder_id": entry["folder_id"],
            "lot_id": lot_id,
            "updated": entry["updated"],
        }
    )


def placsp_units(entries: Iterable[JsonObject], *, seed: str) -> list[JsonObject]:
    """Choose one deterministic lot per latest entry and cap one unit per source/folder."""

    latest = deduplicate_latest_entries(entries)
    by_folder: dict[tuple[str, str, str], list[JsonObject]] = defaultdict(list)
    for entry in latest:
        key = (
            str(entry["source_family"]),
            str(entry["producer"]),
            str(entry["folder_id"]),
        )
        by_folder[key].append(entry)
    units: list[JsonObject] = []
    for folder_key in sorted(by_folder):
        latest_updated = max(str(row["updated"]) for row in by_folder[folder_key])
        latest_folder_entries = [
            row
            for row in by_folder[folder_key]
            if str(row["updated"]) == latest_updated
        ]
        chosen_entry = min(
            latest_folder_entries,
            key=lambda row: _stable_rank(
                seed,
                "entry-tie",
                row["collection"],
                row["producer"],
                row["entry_id"],
            ),
        )
        groups = chosen_entry.get("result_groups")
        if not isinstance(groups, dict) or not groups:
            continue
        lot_id = min(
            (str(value) for value in groups),
            key=lambda value: _stable_rank(
                seed, "lot", chosen_entry["entry_id"], value
            ),
        )
        results = groups[lot_id]
        winners = [
            result.get("winner_name")
            for result in results
            if isinstance(result, dict) and result.get("winner_name")
        ]
        received_values = {
            result.get("received_tender_quantity")
            for result in results
            if isinstance(result, dict)
            and isinstance(result.get("received_tender_quantity"), int)
        }
        winner_rows = [
            result
            for result in results
            if isinstance(result, dict) and result.get("winner_name")
        ]
        units.append(
            {
                "sample_id": _unit_id(chosen_entry, lot_id),
                "source_family": chosen_entry["source_family"],
                "period": chosen_entry["period"],
                "complexity": chosen_entry["complexity"],
                "collection": chosen_entry["collection"],
                "producer": chosen_entry["producer"],
                "entry_id": chosen_entry["entry_id"],
                "folder_id": chosen_entry["folder_id"],
                "lot_id": None if lot_id == "__procedure__" else lot_id,
                "updated": chosen_entry["updated"],
                "source_url": chosen_entry.get("source_url"),
                "contract_type": chosen_entry["contract_type"],
                "status_code": chosen_entry["status_code"],
                "winner_names": winners,
                "received_tender_quantity": (
                    next(iter(received_values)) if len(received_values) == 1 else None
                ),
                "received_tender_quantity_conflict": len(received_values) > 1,
                "winner_identifier_present": bool(winner_rows)
                and all(
                    bool(result.get("winner_identifier_present"))
                    for result in winner_rows
                ),
                "documents": chosen_entry["documents"],
                "flags": chosen_entry["flags"],
                "annotation": {
                    "document_download": None,
                    "document_relevant": None,
                    "nominal_content": None,
                    "role_complete": None,
                    "list_reconciled": None,
                    "labeler_1": None,
                    "labeler_2": None,
                    "adjudicated": False,
                },
            }
        )
    return units


def select_placsp_challenge(
    units: Iterable[JsonObject], *, seed: str, per_cell: int = 12
) -> JsonObject:
    cells: dict[tuple[str, str, str], list[JsonObject]] = defaultdict(list)
    for unit in units:
        key = (
            str(unit["source_family"]),
            str(unit["period"]),
            str(unit["complexity"]),
        )
        cells[key].append(unit)
    selected: list[JsonObject] = []
    inventory: list[JsonObject] = []
    expected = [
        (family, period, complexity)
        for family in ("hosted", "aggregated")
        for period in ("recent", "historical")
        for complexity in ("simple", "complex")
    ]
    for key in expected:
        ranked = sorted(
            cells.get(key, []),
            key=lambda row: _stable_rank(seed, "sample", row["sample_id"]),
        )
        chosen = ranked[:per_cell]
        selected.extend(chosen)
        inventory.append(
            {
                "source_family": key[0],
                "period": key[1],
                "complexity": key[2],
                "candidates": len(ranked),
                "selected": len(chosen),
                "required": per_cell,
                "feasible": len(ranked) >= per_cell,
            }
        )
    return {
        "algorithm": "sha256_rank_v1",
        "seed_hash": sha256_bytes(seed.encode()),
        "per_cell": per_cell,
        "inventory": inventory,
        "complete": all(row["feasible"] for row in inventory),
        "selected": selected,
    }


def redacted_placsp_manifest(selection: Mapping[str, Any]) -> JsonObject:
    selected = selection.get("selected")
    rows = selected if isinstance(selected, list) else []
    redacted = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
        redacted.append(
            {
                "sample_id": row.get("sample_id"),
                "source_family": row.get("source_family"),
                "period": row.get("period"),
                "complexity": row.get("complexity"),
                "contract_type": row.get("contract_type"),
                "status_code": row.get("status_code"),
                "document_reference_count": len(row.get("documents") or []),
                "winner_present": bool(row.get("winner_names")),
                "winner_identifier_present": row.get("winner_identifier_present"),
                "received_tender_quantity_present": isinstance(
                    row.get("received_tender_quantity"), int
                ),
                "flags": flags,
            }
        )
    return {
        "algorithm": selection.get("algorithm"),
        "seed_hash": selection.get("seed_hash"),
        "per_cell": selection.get("per_cell"),
        "inventory": selection.get("inventory"),
        "complete": selection.get("complete"),
        "selected_count": len(redacted),
        "selected": redacted,
    }


def parse_borme_articles(xml_bytes: bytes, *, source_url: str) -> list[JsonObject]:
    root = ET.fromstring(xml_bytes)
    metadata = root.find("./metadatos")
    document_id = (
        _element_text(metadata.find("identificador")) if metadata is not None else None
    )
    publication_date = (
        _element_text(metadata.find("fecha_publicacion"))
        if metadata is not None
        else None
    )
    province = _element_text(metadata.find("titulo")) if metadata is not None else None
    source_updated = root.attrib.get("fecha_actualizacion")
    if not document_id or not publication_date:
        raise ValueError("BORME XML lacks publication identity")
    children = list(root.findall("./texto/*"))
    articles: list[JsonObject] = []
    pending_number: str | None = None
    pending_company: str | None = None
    for child in children:
        class_name = child.attrib.get("class")
        content = _text("".join(child.itertext()))
        if not content:
            continue
        if class_name == "articulo":
            match = re.match(r"(?P<number>\d+)\s*-\s*(?P<company>.+)", content)
            pending_number = match.group("number") if match else None
            pending_company = match.group("company") if match else content
            continue
        if class_name != "parrafo" or not pending_number:
            continue
        registry_match = re.search(r"Datos registrales\.\s*(?P<registry>.+)$", content)
        identity = {
            "publication_date": publication_date,
            "document_id": document_id,
            "article_number": pending_number,
            "source_content_hash": sha256_bytes(content.encode()),
        }
        articles.append(
            {
                "article_id": sha256_json(identity),
                **identity,
                "province": province,
                "source_updated": source_updated,
                "source_url": source_url,
                "company_literal": pending_company,
                "source_text": content,
                "registry_locator": registry_match.group("registry")
                if registry_match
                else None,
                "annotation": {
                    "assertions": [],
                    "labeler_1_complete": False,
                    "labeler_2_complete": False,
                    "adjudicated": False,
                },
            }
        )
        pending_number = None
        pending_company = None
    return articles


def select_borme_article_frame(
    articles: Iterable[JsonObject], *, seed: str, per_period: int
) -> JsonObject:
    by_period: dict[str, list[JsonObject]] = defaultdict(list)
    for article in articles:
        by_period[str(article["period"])].append(article)
    selected: list[JsonObject] = []
    inventory: list[JsonObject] = []
    for period in ("recent", "historical"):
        ranked = sorted(
            by_period.get(period, []),
            key=lambda row: _stable_rank(seed, "borme-article", row["article_id"]),
        )
        chosen = ranked[:per_period]
        selected.extend(chosen)
        inventory.append(
            {
                "period": period,
                "candidates": len(ranked),
                "selected": len(chosen),
                "required": per_period,
                "feasible": len(ranked) >= per_period,
            }
        )
    return {
        "algorithm": "sha256_rank_v1_before_detector",
        "seed_hash": sha256_bytes(seed.encode()),
        "inventory": inventory,
        "complete": all(item["feasible"] for item in inventory),
        "selected": selected,
    }


def detect_borme_challenge_candidates(article: Mapping[str, Any]) -> list[JsonObject]:
    """Propose review candidates without asserting a person/company type."""

    text = str(article.get("source_text") or "")
    candidates: list[JsonObject] = []
    for family, pattern in (
        ("governance", BORME_ROLE_PATTERN),
        ("sole_shareholder", BORME_SOLE_PATTERN),
        ("representative", BORME_REPRESENTATIVE_PATTERN),
        ("difficult", BORME_DIFFICULT_PATTERN),
    ):
        for ordinal, match in enumerate(pattern.finditer(text), start=1):
            literal = match.groupdict().get("literal")
            candidates.append(
                {
                    "candidate_id": sha256_json(
                        {
                            "article_id": article["article_id"],
                            "family": family,
                            "ordinal": ordinal,
                            "match_hash": sha256_bytes(match.group(0).encode()),
                        }
                    ),
                    "article_id": article["article_id"],
                    "family": family,
                    "literal": _text(literal),
                    "counterpart_kind": "unknown",
                    "source_match": match.group(0),
                    "human_stratum": None,
                    "accepted": None,
                }
            )
    return candidates


def redacted_borme_manifest(frame: Mapping[str, Any]) -> JsonObject:
    selected = frame.get("selected")
    rows = selected if isinstance(selected, list) else []
    return {
        "algorithm": frame.get("algorithm"),
        "seed_hash": frame.get("seed_hash"),
        "inventory": frame.get("inventory"),
        "complete": frame.get("complete"),
        "selected_count": len(rows),
        "selected": [
            {
                "article_id": row.get("article_id"),
                "period": row.get("period"),
                "publication_date": row.get("publication_date"),
                "document_id": row.get("document_id"),
                "article_number_hash": sha256_bytes(
                    str(row.get("article_number")).encode()
                ),
                "source_content_hash": row.get("source_content_hash"),
            }
            for row in rows
            if isinstance(row, dict)
        ],
    }


def load_ephemeral_signal_key(path: Path) -> str:
    """Load a single-use key without accepting symlinks or group/world access."""

    if not path.is_absolute():
        raise ValueError("Signal key file must be absolute")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError("Signal key file is not readable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Signal key file must be a regular non-symlink file")
    if metadata.st_uid != os.getuid():
        raise ValueError("Signal key file must belong to the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(
            "Signal key file permissions must not grant group/other access"
        )
    if metadata.st_size <= 0 or metadata.st_size > 4096:
        raise ValueError("Signal key file has an invalid size")
    raw = path.read_bytes()
    if b"\x00" in raw or b"\n" in raw.rstrip(b"\n"):
        raise ValueError("Signal key file must contain exactly one text line")
    try:
        key = raw.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValueError("Signal key file is not UTF-8") from error
    if not key:
        raise ValueError("Signal key file is empty")
    return key


def normalize_signal_base_url(base_url: str, *, allowed_host: str) -> str:
    parsed = urlparse(base_url)
    if (
        allowed_host not in SIGNAL_INVESTIGATION_HOSTS
        or parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "Signal endpoint must be root HTTPS on the exact allowlisted host"
        )
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Signal endpoint has an invalid port") from error
    suffix = f":{port}" if port is not None else ""
    return f"https://{allowed_host}{suffix}"


class SignalReadOnlyError(RuntimeError):
    """The ephemeral comparison run is not valid."""


class SignalReadOnlyClient:
    ALLOWED_PATH = re.compile(
        r"^/api/v1/(?:consumers/me|registry/awards/[A-Za-z0-9%._~!$&'()*+,;=:@/-]+)$"
    )

    def __init__(
        self,
        *,
        base_url: str,
        allowed_host: str,
        api_key: str,
        timeout_seconds: float = 20,
        max_bytes: int = 2_000_000,
    ) -> None:
        self.base_url = normalize_signal_base_url(base_url, allowed_host=allowed_host)
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def get_json(self, path: str) -> JsonObject:
        if not self.ALLOWED_PATH.fullmatch(path):
            raise ValueError("Path is outside the INV-02 GET-only allowlist")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json", "X-API-Key": self.api_key},
            method="GET",
        )
        opener = urllib.request.build_opener(_RejectRedirects())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise SignalReadOnlyError(f"Signal returned HTTP {response.status}")
                if "json" not in response.headers.get("Content-Type", ""):
                    raise SignalReadOnlyError("Signal returned a non-JSON content type")
                body = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as error:
            raise SignalReadOnlyError(f"Signal returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise SignalReadOnlyError("Signal is unavailable") from error
        if len(body) > self.max_bytes:
            raise SignalReadOnlyError("Signal response exceeds byte budget")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise SignalReadOnlyError("Signal returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise SignalReadOnlyError("Signal returned a non-object payload")
        return payload

    def preflight(self, *, expected_slug: str) -> JsonObject:
        if not re.fullmatch(
            r"opn-oracle-exp-inv-02-[a-z0-9][a-z0-9-]{2,63}",
            expected_slug,
        ):
            raise ValueError("Signal consumer slug is not an INV-02 ephemeral slug")
        payload = self.get_json("/api/v1/consumers/me")
        if payload.get("slug") != expected_slug or payload.get("is_active") is not True:
            raise SignalReadOnlyError(
                "Signal ephemeral consumer identity does not match"
            )
        return {
            "slug_match": True,
            "active": True,
            "rate_limit": payload.get("rate_limit"),
        }

    def awards_by_folder(self, folder_id: str) -> JsonObject:
        encoded = quote(folder_id, safe="")
        payload = self.get_json(f"/api/v1/registry/awards/{encoded}")
        if payload.get("folder_id") != folder_id:
            raise SignalReadOnlyError("Signal folder_id drifted")
        total = payload.get("total")
        items = payload.get("items")
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or not isinstance(items, list)
        ):
            raise SignalReadOnlyError("Signal award schema drifted")
        if total != len(items):
            raise SignalReadOnlyError("Signal award payload is partial")
        return payload


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        raise SignalReadOnlyError("Signal redirect rejected")


def compare_signal_units(
    units: Iterable[Mapping[str, Any]],
    *,
    fetch_awards: Callable[[str], Mapping[str, Any]],
) -> JsonObject:
    """Compare 643 only, one GET per unique folder, without inventing revision coverage."""

    rows = list(units)
    hosted = [row for row in rows if row.get("source_family") == "hosted"]
    aggregated = [row for row in rows if row.get("source_family") == "aggregated"]
    by_folder: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in hosted:
        by_folder[str(row["folder_id"])].append(row)
    fetched = {folder_id: fetch_awards(folder_id) for folder_id in sorted(by_folder)}
    classifications: Counter[str] = Counter()
    secondary_winner_matches = 0
    for folder_id, folder_units in by_folder.items():
        payload = fetched[folder_id]
        items = payload.get("items")
        if not isinstance(items, list):
            raise SignalReadOnlyError("Signal comparator received invalid items")
        if not items:
            classifications["folder_missing"] += len(folder_units)
            continue
        for unit in folder_units:
            lot_id = unit.get("lot_id")
            lot_rows = [
                item
                for item in items
                if isinstance(item, dict)
                and (
                    item.get("lot_id") == lot_id
                    or (lot_id is None and item.get("lot_id") in {None, ""})
                )
            ]
            if not lot_rows:
                classifications["lot_missing"] += 1
                continue
            classifications["revision_contract_missing"] += 1
            official = {
                str(name).casefold()
                for name in unit.get("winner_names", [])
                if isinstance(name, str)
            }
            signal = {
                str(item.get("winner")).casefold()
                for item in lot_rows
                if isinstance(item.get("winner"), str)
            }
            if official and official == signal:
                secondary_winner_matches += 1
    classifications["source_not_indexed_v1"] = len(aggregated)
    comparable = len(hosted)
    return {
        "status": "completed",
        "requests": len(fetched),
        "hosted_denominator": comparable,
        "aggregated_denominator": len(aggregated),
        "classifications": dict(classifications),
        "revision_exact_comparison_available": False,
        "winner_secondary_match": {
            "numerator": secondary_winner_matches,
            "denominator": comparable,
            "wilson_95": wilson_interval(secondary_winner_matches, comparable),
        },
    }


def source_snapshot(path: Path, *, url: str) -> JsonObject:
    metadata = path.stat()
    return {
        "url": url,
        "sha256": sha256_bytes(path.read_bytes()),
        "bytes": metadata.st_size,
        "acquired_at_utc": datetime.now(UTC).isoformat(),
    }
