#!/usr/bin/env python3
"""Refresh the packaged Spanish CPV taxonomy from the EU Publications Office."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
DATASET_URI = "http://publications.europa.eu/resource/dataset/cpv"
CONCEPT_SCHEME_URI = "http://data.europa.eu/cpv/cpv"
QUERY = f"""
SELECT ?notation ?label WHERE {{
  ?concept <http://www.w3.org/2004/02/skos/core#inScheme> <{CONCEPT_SCHEME_URI}> ;
           <http://www.w3.org/2004/02/skos/core#notation> ?notation ;
           <http://www.w3.org/2004/02/skos/core#prefLabel> ?label .
  FILTER(lang(?label) = "es")
}}
ORDER BY ?notation
""".strip()


def _default_output() -> Path:
    return (
        Path(__file__).resolve().parents[1] / "apps/api/src/opn_oracle/oracle/data/cpv_2008_es.json"
    )


def _download() -> dict[str, object]:
    query_url = f"{SPARQL_ENDPOINT}?{urlencode({'query': QUERY, 'format': 'json'})}"
    request = Request(
        query_url,
        headers={"Accept": "application/sparql-results+json", "User-Agent": "OPN-Oracle/1.0"},
    )
    with urlopen(request, timeout=60) as response:
        payload = json.load(response)
    bindings = payload["results"]["bindings"]
    codes = {
        row["notation"]["value"]: row["label"]["value"]
        for row in bindings
        if row["notation"]["value"] and row["label"]["value"]
    }
    return {
        "metadata": {
            "dataset": "Common Procurement Vocabulary",
            "version": "2008",
            "language": "es",
            "source_uri": DATASET_URI,
            "concept_scheme_uri": CONCEPT_SCHEME_URI,
            "sparql_endpoint": SPARQL_ENDPOINT,
            "downloaded_at": datetime.now(UTC).date().isoformat(),
            "code_count": len(codes),
        },
        "codes": dict(sorted(codes.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=_default_output())
    parser.add_argument("--expected-count", type=int, default=9_454)
    args = parser.parse_args()

    payload = _download()
    count = payload["metadata"]["code_count"]  # type: ignore[index]
    if count != args.expected_count:
        print(
            f"Se esperaban {args.expected_count} códigos CPV y la fuente devolvió {count}.",
            file=sys.stderr,
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Taxonomía CPV escrita en {args.output} ({count} códigos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
