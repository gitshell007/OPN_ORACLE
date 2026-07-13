from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from opn_oracle.integrations.service import canonical_source_url, signal_dedupe_key
from opn_oracle.integrations.signal_avanza import ProvenanceItem, SignalItem, SourceItem


def _item(item_id: str, *, url: str | None, title: str, source_name: str) -> SignalItem:
    return SignalItem(
        id=item_id,
        monitor_id="monitor",
        type="news",
        title=title,
        summary="",
        source=SourceItem(name=source_name, url=url, published_at=datetime.now(UTC)),
        language="es",
        tags=[],
        entities=[],
        categories=[],
        content_hash=hashlib.sha256(item_id.encode()).hexdigest(),
        observed_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        provenance=ProvenanceItem(connector="test", monitor_config_version=1),
    )


def test_canonical_source_url_removes_tracking_fragment_and_default_port() -> None:
    assert (
        canonical_source_url(
            "HTTPS://Example.TEST:443/noticia/?utm_source=feed&keep=1&gclid=x#fragment"
        )
        == "https://example.test/noticia?keep=1"
    )


def test_signal_dedupe_key_uses_url_then_title_source_fallback() -> None:
    with_url = _item(
        "a",
        url="https://example.test/path?utm_campaign=x",
        title="Título original",
        source_name="Medio",
    )
    assert (
        signal_dedupe_key(with_url, canonical_source_url(str(with_url.source.url)))
        == "url:https://example.test/path"
    )
    without_url = _item(
        "b",
        url=None,
        title="  Aviso   INDUSTRIAL relevante ",
        source_name="  BOE ",
    )
    assert signal_dedupe_key(without_url, None) == "title:boe:aviso industrial relevante"
