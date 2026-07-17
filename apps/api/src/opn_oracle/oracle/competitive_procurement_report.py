"""Durable report workflow for competitive public-procurement intelligence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from opn_oracle.extensions import db
from opn_oracle.integrations.procurement import procurement_client_from_config
from opn_oracle.oracle.competitive_procurement import (
    COMPETITIVE_PROCUREMENT_AGENT,
    analysis_evidence_extract,
    build_competitive_procurement_analysis,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import Evidence, Report
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.reporting.service import (
    ReportLeaseLost,
    ReportWorkflowError,
    freeze_report_enrichment,
    process_report,
)

COMPETITIVE_ANALYSIS_SNAPSHOT_KEY = "competitive_procurement_analysis"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _prepare_analysis(report: Report, job: BackgroundJob) -> dict[str, Any]:
    existing = report.source_snapshot.get(COMPETITIVE_ANALYSIS_SNAPSHOT_KEY)
    if isinstance(existing, dict):
        return existing
    company_name = str(report.options.get("company_name", "")).strip()
    if not company_name:
        raise ReportWorkflowError("El informe no conserva el adjudicatario solicitado.")

    client = procurement_client_from_config()
    try:
        analysis = build_competitive_procurement_analysis(
            client,
            company_name=company_name,
        )
    finally:
        client.close()
    if not analysis["corpus"]["unique_contracts"]:
        raise ReportWorkflowError(
            "Signal no devolvió adjudicaciones analizables para esa denominación."
        )

    db.session.rollback()
    locked_report = db.session.scalar(
        select(Report)
        .where(
            Report.id == report.id,
            Report.tenant_id == job.tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        locked_report is None
        or locked_report.background_job_id != job.id
        or job.execution_lease_id is None
    ):
        raise ReportLeaseLost("El job perdió la propiedad del informe.")
    existing = locked_report.source_snapshot.get(COMPETITIVE_ANALYSIS_SNAPSHOT_KEY)
    if isinstance(existing, dict):
        return existing

    extract = analysis_evidence_extract(analysis)
    captured_at = datetime.now(UTC).isoformat()
    analysis_hash = hashlib.sha256(_canonical(analysis)).hexdigest()
    evidence = Evidence(
        tenant_id=locked_report.tenant_id,
        source_kind="procurement",
        source_url=None,
        extract=extract[:20_000],
        locator={
            "kind": "competitive_procurement_corpus",
            "report_id": str(locked_report.id),
            "company_name": company_name,
            "captured_at": captured_at,
        },
        checksum=hashlib.sha256(extract.encode("utf-8")).digest(),
        classification="internal",
        provenance={
            "source_kind": "procurement",
            "procurement_kind": "competitive_analysis",
            "derived": True,
            "schema": analysis["schema"],
            "company_name": company_name,
            "captured_at": captured_at,
            "analysis_sha256": analysis_hash,
            "provider_total_rows": analysis["corpus"]["provider_total_rows"],
            "analyzed_rows": analysis["corpus"]["analyzed_rows"],
            "unique_contracts": analysis["corpus"]["unique_contracts"],
        },
    )
    db.session.add(evidence)
    db.session.flush()
    db.session.add(
        EvidenceDossier(
            tenant_id=locked_report.tenant_id,
            evidence_id=evidence.id,
            dossier_id=locked_report.dossier_id,
        )
    )
    db.session.flush()
    freeze_report_enrichment(
        locked_report,
        key=COMPETITIVE_ANALYSIS_SNAPSHOT_KEY,
        payload=analysis,
        evidence=evidence,
        source_label=f"Histórico PLACSP calculado · {company_name}",
    )
    append_audit_event(
        db.session,
        action="competitive_procurement.analysis_frozen",
        resource_type="report",
        resource_id=locked_report.id,
        dossier_id=locked_report.dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "job_id": str(job.id),
            "analysis_sha256": analysis_hash,
            "analyzed_rows": analysis["corpus"]["analyzed_rows"],
            "provider_total_rows": analysis["corpus"]["provider_total_rows"],
            "unique_contracts": analysis["corpus"]["unique_contracts"],
            "discount_computable": analysis["discount_coverage"]["computable"],
            "discount_coverage_percent": analysis["discount_coverage"]["coverage_percent"],
        },
    )
    job.progress = 65
    job.stage = "analysis_ready"
    job.heartbeat_at = datetime.now(UTC)
    job.version += 1
    db.session.commit()
    return analysis


def process_competitive_procurement_report(
    report_id: uuid.UUID,
    job: BackgroundJob,
) -> dict[str, Any]:
    report = db.session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == job.tenant_id,
        )
    )
    if report is None or report.background_job_id != job.id:
        raise ReportWorkflowError("Informe competitivo no disponible para este job.")
    analysis = _prepare_analysis(report, job)
    return process_report(
        report_id,
        job,
        agent=COMPETITIVE_PROCUREMENT_AGENT,
        requested_scope={
            "computed_analysis": analysis,
            "arithmetic_policy": (
                "Todos los agregados proceden de Python. El modelo no debe recalcular, "
                "estimar ni completar valores ausentes."
            ),
        },
    )
