"""Tenant-scoped REST API for the Oracle core domain."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from apiflask import APIBlueprint
from flask import g, request
from flask_login import current_user
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from opn_oracle.auth.permissions import current_permissions, require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.documents.models import Document
from opn_oracle.extensions import db
from opn_oracle.oracle.links import (
    DecisionEvidence,
    DossierActorEvidence,
    DossierCollaborator,
    EvidenceDossier,
    HypothesisEvidence,
    InsightEvidence,
    MeetingActor,
    MeetingEvidence,
    OpportunityActor,
    OpportunityEvidence,
    OpportunitySignal,
    RelationshipEvidence,
    ReportEvidence,
    RiskActor,
    RiskEvidence,
    RiskSignal,
)
from opn_oracle.oracle.models import (
    Actor,
    Briefing,
    Decision,
    DossierActor,
    DossierObjective,
    DossierSignal,
    Evidence,
    Feedback,
    Hypothesis,
    Insight,
    LivingSummary,
    Meeting,
    Opportunity,
    Relationship,
    Report,
    RiskItem,
    Signal,
    SignalMonitor,
    StatusHistory,
    StrategicDossier,
    Task,
    Watchlist,
)
from opn_oracle.oracle.policy import (
    active_membership_exists,
    dossier_access_clause,
    dossier_accessible,
    dossier_manageable,
    is_tenant_admin,
)
from opn_oracle.oracle.service import (
    DomainValidationError,
    ResourceNotFound,
    VersionConflict,
    archive_dossier,
    create_dossier,
    create_dossier_actor,
    create_scored_resource,
    list_page,
    merge_actors,
    promote_signal_link,
    record_status_change,
    review_signal_link,
    update_dossier,
    update_dossier_actor,
    update_scored_resource,
)
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.reporting.service import (
    ReportConflictError,
    ReportWorkflowError,
    create_report_request,
    serialize_report,
)

bp = APIBlueprint("oracle", __name__, url_prefix="/api/v1", tag="Oracle")


def _payload() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _serialize(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attribute in row.__mapper__.column_attrs:
        value = getattr(row, attribute.key)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, bytes):
            continue
        result[attribute.key] = value
    return result


def _domain_error(error: Exception) -> Any:
    if isinstance(error, ResourceNotFound):
        return problem_response(404, detail=str(error), code="not_found")
    if isinstance(error, VersionConflict):
        return problem_response(409, detail=str(error), code="version_conflict")
    return problem_response(422, detail=str(error), code="domain_validation")


def _page_args() -> tuple[int, int, str, bool]:
    try:
        page = int(request.args.get("page[number]", "1"))
        size = int(request.args.get("page[size]", "25"))
    except ValueError as error:
        raise DomainValidationError("Paginación no válida.") from error
    raw_sort = request.args.get("sort", "-updated_at")
    return page, size, raw_sort.removeprefix("-"), raw_sort.startswith("-")


def _typed_list_criteria(model: type[Any]) -> tuple[Any, ...]:
    criteria: list[Any] = []
    selected = request.args.get("filter[selected_ids]")
    if selected:
        raw_ids = [value for value in selected.split(",") if value]
        if len(raw_ids) > 100:
            raise DomainValidationError("selected_ids admite como máximo 100 UUID.")
        try:
            selected_ids = [uuid.UUID(value) for value in raw_ids]
        except ValueError as error:
            raise DomainValidationError("selected_ids contiene un UUID no válido.") from error
        criteria.append(model.id.in_(selected_ids))
    type_value = request.args.get("filter[type]")
    if type_value:
        type_field = next(
            (
                field
                for field in (
                    "dossier_type",
                    "opportunity_type",
                    "actor_type",
                    "report_type",
                    "insight_type",
                    "source_type",
                    "relationship_type",
                    "target_type",
                )
                if hasattr(model, field)
            ),
            None,
        )
        if type_field is None:
            raise DomainValidationError("Este listado no admite filter[type].")
        criteria.append(getattr(model, type_field) == type_value)
    owner = request.args.get("filter[owner]")
    if owner:
        if not hasattr(model, "owner_user_id"):
            raise DomainValidationError("Este listado no admite filter[owner].")
        try:
            criteria.append(model.owner_user_id == uuid.UUID(owner))
        except ValueError as error:
            raise DomainValidationError("filter[owner] debe ser UUID.") from error
    for argument, operator in (("filter[date_from]", "from"), ("filter[date_to]", "to")):
        value = request.args.get(argument)
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise DomainValidationError(f"{argument} no es una fecha ISO válida.") from error
            criteria.append(
                model.created_at >= parsed if operator == "from" else model.created_at <= parsed
            )
    if hasattr(model, "overall_score"):
        for argument, operator in (("filter[score_min]", "min"), ("filter[score_max]", "max")):
            value = request.args.get(argument)
            if value is not None:
                try:
                    score = int(value)
                except ValueError as error:
                    raise DomainValidationError(f"{argument} debe ser entero.") from error
                if not 0 <= score <= 100:
                    raise DomainValidationError(f"{argument} debe estar entre 0 y 100.")
                criteria.append(
                    model.overall_score >= score
                    if operator == "min"
                    else model.overall_score <= score
                )
    elif request.args.get("filter[score_min]") or request.args.get("filter[score_max]"):
        raise DomainValidationError("Este listado no admite filtros de score.")
    return tuple(criteria)


def _requested_dossier_id() -> uuid.UUID | None:
    value = request.args.get("filter[dossier_id]")
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise DomainValidationError("filter[dossier_id] debe ser UUID.") from error


def _dossier_reference(dossier: StrategicDossier) -> dict[str, Any]:
    return {
        "id": str(dossier.id),
        "title": dossier.title,
        "status": dossier.status,
    }


def _actor_access_clause() -> Any:
    if is_tenant_admin(db.session(), g.active_tenant_id, current_user.id):
        return Actor.tenant_id == g.active_tenant_id
    accessible_dossiers = select(StrategicDossier.id).where(
        dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
    )
    contextual = select(DossierActor.actor_id).where(
        DossierActor.dossier_id.in_(accessible_dossiers)
    )
    relationships_from = select(Relationship.from_actor_id).where(
        Relationship.dossier_id.in_(accessible_dossiers)
    )
    relationships_to = select(Relationship.to_actor_id).where(
        Relationship.dossier_id.in_(accessible_dossiers)
    )
    opportunities = (
        select(OpportunityActor.actor_id)
        .join(Opportunity, Opportunity.id == OpportunityActor.opportunity_id)
        .where(Opportunity.dossier_id.in_(accessible_dossiers))
    )
    risks = (
        select(RiskActor.actor_id)
        .join(RiskItem, RiskItem.id == RiskActor.risk_id)
        .where(RiskItem.dossier_id.in_(accessible_dossiers))
    )
    meetings = (
        select(MeetingActor.actor_id)
        .join(Meeting, Meeting.id == MeetingActor.meeting_id)
        .where(Meeting.dossier_id.in_(accessible_dossiers))
    )
    return or_(
        Actor.id.in_(contextual),
        Actor.id.in_(relationships_from),
        Actor.id.in_(relationships_to),
        Actor.id.in_(opportunities),
        Actor.id.in_(risks),
        Actor.id.in_(meetings),
    )


def _global_dossier_resource_page(model: type[Any]) -> dict[str, Any]:
    """List a dossier-owned resource without client fan-out or authorization leaks."""

    page, size, sort, desc = _page_args()
    sortable = {
        key: getattr(model, key)
        for key in (
            "updated_at",
            "created_at",
            "title",
            "status",
            "overall_score",
            "due_date",
            "deadline",
            "scheduled_at",
            "priority",
        )
        if hasattr(model, key)
    }
    if "sort" not in request.args and sort not in sortable:
        sort = "updated_at"
    if page < 1 or size < 1 or size > 100 or sort not in sortable:
        raise DomainValidationError("Paginación u ordenación no válida.")

    criteria: list[Any] = [
        dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id),
        *_typed_list_criteria(model),
    ]
    status = request.args.get("filter[status]")
    if status:
        criteria.append(model.status == status)
    dossier_id = _requested_dossier_id()
    if dossier_id is not None:
        criteria.append(model.dossier_id == dossier_id)
    search = request.args.get("filter[search]", "")[:100]
    if search:
        search_columns = tuple(
            getattr(model, key)
            for key in ("title", "description", "objective", "notes")
            if hasattr(model, key)
        )
        if not search_columns:
            raise DomainValidationError("Este listado no admite búsqueda.")
        criteria.append(or_(*(column.ilike(f"%{search}%") for column in search_columns)))

    query = (
        select(model, StrategicDossier)
        .join(StrategicDossier, StrategicDossier.id == model.dossier_id)
        .where(*criteria)
    )
    count_query = (
        select(func.count(model.id))
        .select_from(model)
        .join(StrategicDossier, StrategicDossier.id == model.dossier_id)
        .where(*criteria)
    )
    order = sortable[sort].desc() if desc else sortable[sort].asc()
    rows = list(
        db.session.execute(
            query.order_by(order, model.id.asc()).offset((page - 1) * size).limit(size)
        ).all()
    )
    dossiers = {dossier.id: dossier for _, dossier in rows}
    return {
        "data": [_serialize(row) for row, _ in rows],
        "included": {
            "dossiers": [
                _dossier_reference(dossier)
                for dossier in sorted(dossiers.values(), key=lambda value: value.title.casefold())
            ]
        },
        "meta": {
            "page": page,
            "size": size,
            "total": int(db.session.scalar(count_query) or 0),
        },
    }


def _home_attention_item(
    *,
    kind: str,
    resource_id: uuid.UUID,
    title: str,
    status: str,
    updated_at: datetime,
    dossier: StrategicDossier,
    score: int | None,
    due_at: date | datetime | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": str(resource_id),
        "dossier_id": str(dossier.id),
        "dossier_title": dossier.title,
        "title": title,
        "status": status,
        "score": score,
        "due_at": due_at.isoformat() if due_at is not None else None,
        "updated_at": updated_at.isoformat(),
        "href": f"/app/dossiers/{dossier.id}/{kind}",
    }


@bp.get("/home")
@require_permission("dossier.read")
def home_read_model() -> Any:
    """Bounded command-center projection over only authorized dossiers."""

    permissions = current_permissions(current_user.id, g.active_tenant_id)
    access = dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
    total_dossiers = int(
        db.session.scalar(select(func.count(StrategicDossier.id)).where(access)) or 0
    )
    active_dossiers = int(
        db.session.scalar(
            select(func.count(StrategicDossier.id)).where(
                access, StrategicDossier.status == "active"
            )
        )
        or 0
    )
    metrics: list[dict[str, Any]] = [
        {
            "key": "dossiers",
            "label": "Expedientes activos",
            "count": active_dossiers,
            "href": "/app/dossiers?filter%5Bstatus%5D=active",
            "available": True,
        }
    ]
    attention: list[dict[str, Any]] = []

    def dossier_resource_count(model: type[Any], *criteria: Any) -> int:
        return int(
            db.session.scalar(
                select(func.count(model.id))
                .select_from(model)
                .join(StrategicDossier, StrategicDossier.id == model.dossier_id)
                .where(access, *criteria)
            )
            or 0
        )

    module_specs: tuple[tuple[str, str, str, type[Any], tuple[Any, ...]], ...] = (
        (
            "opportunities",
            "Oportunidades abiertas",
            "opportunity.read",
            Opportunity,
            (Opportunity.status.in_(("identified", "qualified", "pursuing")),),
        ),
        (
            "risks",
            "Riesgos abiertos",
            "risk.read",
            RiskItem,
            (RiskItem.status.in_(("open", "monitoring")),),
        ),
        (
            "meetings",
            "Reuniones próximas",
            "meeting.read",
            Meeting,
            (Meeting.status == "planned",),
        ),
        (
            "tasks",
            "Tareas pendientes",
            "task.read",
            Task,
            (Task.status.in_(("open", "in_progress", "blocked")),),
        ),
    )
    for key, label, permission, model, criteria in module_specs:
        available = permission in permissions
        metrics.append(
            {
                "key": key,
                "label": label,
                "count": dossier_resource_count(model, *criteria) if available else None,
                "href": f"/app/{key}",
                "available": available,
            }
        )

    signal_available = "signal.read" in permissions
    signal_count = None
    if signal_available:
        signal_count = int(
            db.session.scalar(
                select(func.count(DossierSignal.id))
                .select_from(DossierSignal)
                .join(StrategicDossier, StrategicDossier.id == DossierSignal.dossier_id)
                .where(access, DossierSignal.status == "new")
            )
            or 0
        )
        signal_rows = db.session.execute(
            select(DossierSignal, Signal, StrategicDossier)
            .join(Signal, Signal.id == DossierSignal.signal_id)
            .join(StrategicDossier, StrategicDossier.id == DossierSignal.dossier_id)
            .where(access, DossierSignal.status == "new")
            .order_by(DossierSignal.overall_score.desc(), DossierSignal.id.asc())
            .limit(2)
        ).all()
        attention.extend(
            _home_attention_item(
                kind="signals",
                resource_id=link.id,
                title=signal.title,
                status=link.status,
                updated_at=link.updated_at,
                dossier=dossier,
                score=link.overall_score,
                due_at=signal.published_at,
            )
            for link, signal, dossier in signal_rows
        )
    metrics.insert(
        1,
        {
            "key": "signals",
            "label": "Señales nuevas",
            "count": signal_count,
            "href": "/app/signals?filter%5Bstatus%5D=new",
            "available": signal_available,
        },
    )

    if "opportunity.read" in permissions:
        opportunity_rows = db.session.execute(
            select(Opportunity, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == Opportunity.dossier_id)
            .where(
                access,
                Opportunity.status.in_(("identified", "qualified", "pursuing")),
            )
            .order_by(Opportunity.overall_score.desc(), Opportunity.id.asc())
            .limit(2)
        ).all()
        attention.extend(
            _home_attention_item(
                kind="opportunities",
                resource_id=row.id,
                title=row.title,
                status=row.status,
                updated_at=row.updated_at,
                dossier=dossier,
                score=row.overall_score,
                due_at=row.deadline,
            )
            for row, dossier in opportunity_rows
        )
    if "risk.read" in permissions:
        risk_rows = db.session.execute(
            select(RiskItem, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == RiskItem.dossier_id)
            .where(access, RiskItem.status.in_(("open", "monitoring")))
            .order_by(RiskItem.overall_score.desc(), RiskItem.id.asc())
            .limit(2)
        ).all()
        attention.extend(
            _home_attention_item(
                kind="risks",
                resource_id=row.id,
                title=row.title,
                status=row.status,
                updated_at=row.updated_at,
                dossier=dossier,
                score=row.overall_score,
                due_at=row.due_date,
            )
            for row, dossier in risk_rows
        )
    if "meeting.read" in permissions:
        meeting_rows = db.session.execute(
            select(Meeting, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == Meeting.dossier_id)
            .where(access, Meeting.status == "planned")
            .order_by(Meeting.scheduled_at.asc().nulls_last(), Meeting.id.asc())
            .limit(2)
        ).all()
        attention.extend(
            _home_attention_item(
                kind="meetings",
                resource_id=row.id,
                title=row.title,
                status=row.status,
                updated_at=row.updated_at,
                dossier=dossier,
                score=None,
                due_at=row.scheduled_at,
            )
            for row, dossier in meeting_rows
        )
    if "task.read" in permissions:
        task_rows = db.session.execute(
            select(Task, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == Task.dossier_id)
            .where(access, Task.status.in_(("open", "in_progress", "blocked")))
            .order_by(Task.due_date.asc().nulls_last(), Task.id.asc())
            .limit(2)
        ).all()
        attention.extend(
            _home_attention_item(
                kind="tasks",
                resource_id=row.id,
                title=row.title,
                status=row.status,
                updated_at=row.updated_at,
                dossier=dossier,
                score=None,
                due_at=row.due_date,
            )
            for row, dossier in task_rows
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dossier_total": total_dossiers,
        "metrics": metrics,
        "attention": attention[:10],
    }


@bp.get("/changes")
@require_permission("dossier.read")
def changes_read_model() -> Any:
    """Read-only, bounded projection of durable semantic status transitions."""

    try:
        page, size, sort, desc = _page_args()
        if "page[size]" not in request.args:
            size = 10
        if "sort" not in request.args:
            sort, desc = "created_at", True
        if size > 50 or sort != "created_at":
            raise DomainValidationError("Paginación u ordenación no válida.")
        criteria: list[Any] = [
            dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
        ]
        dossier_id = _requested_dossier_id()
        if dossier_id is not None:
            criteria.append(StatusHistory.dossier_id == dossier_id)
        resource_type = request.args.get("filter[type]")
        if resource_type:
            criteria.append(StatusHistory.resource_type == resource_type)
        since = request.args.get("filter[since]") or request.args.get("filter[date_from]")
        if since:
            try:
                parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError as error:
                raise DomainValidationError("filter[since] no es una fecha ISO válida.") from error
            criteria.append(StatusHistory.created_at >= parsed)
        search = request.args.get("filter[search]", "")[:100]
        if search:
            term = f"%{search}%"
            criteria.append(
                or_(StatusHistory.reason.ilike(term), StrategicDossier.title.ilike(term))
            )
        query = (
            select(StatusHistory, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == StatusHistory.dossier_id)
            .where(*criteria)
        )
        count_query = (
            select(func.count(StatusHistory.id))
            .select_from(StatusHistory)
            .join(StrategicDossier, StrategicDossier.id == StatusHistory.dossier_id)
            .where(*criteria)
        )
        order = StatusHistory.created_at.desc() if desc else StatusHistory.created_at.asc()
        rows = db.session.execute(
            query.order_by(order, StatusHistory.id.asc()).offset((page - 1) * size).limit(size)
        ).all()
        return {
            "data": [
                {
                    "id": str(row.id),
                    "dossier_id": str(dossier.id),
                    "dossier_title": dossier.title,
                    "resource_type": row.resource_type,
                    "resource_id": str(row.resource_id),
                    "from_status": row.from_status,
                    "to_status": row.to_status,
                    "reason": row.reason,
                    "actor_user_id": str(row.actor_user_id),
                    "occurred_at": row.created_at.isoformat(),
                    "href": f"/app/dossiers/{dossier.id}",
                }
                for row, dossier in rows
            ],
            "meta": {
                "page": page,
                "size": size,
                "total": int(db.session.scalar(count_query) or 0),
                "review_supported": False,
            },
        }
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/search")
@require_permission("dossier.read")
def global_search() -> Any:
    """Permission-aware command-palette search with bounded groups and no content snippets."""

    query_text = request.args.get("q", "").strip()
    if not 2 <= len(query_text) <= 100:
        return _domain_error(DomainValidationError("q debe tener entre 2 y 100 caracteres."))
    try:
        limit = int(request.args.get("limit", "5"))
    except ValueError:
        return _domain_error(DomainValidationError("limit debe ser entero."))
    if not 1 <= limit <= 10:
        return _domain_error(DomainValidationError("limit debe estar entre 1 y 10."))
    allowed_groups = {"dossiers", "actors", "signals", "opportunities", "documents"}
    requested_groups = {
        value.strip()
        for value in request.args.get("types", ",".join(sorted(allowed_groups))).split(",")
        if value.strip()
    }
    if not requested_groups or not requested_groups.issubset(allowed_groups):
        return _domain_error(DomainValidationError("types contiene un grupo no permitido."))

    permissions = current_permissions(current_user.id, g.active_tenant_id)
    access = dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
    term = f"%{query_text}%"
    groups: dict[str, list[dict[str, Any]]] = {group: [] for group in sorted(requested_groups)}

    def result(
        *,
        kind: str,
        resource_id: uuid.UUID,
        title: str,
        subtitle: str,
        href: str,
        dossier: StrategicDossier | None = None,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "id": str(resource_id),
            "title": title,
            "subtitle": subtitle,
            "href": href,
            "dossier_id": str(dossier.id) if dossier is not None else None,
            "dossier_title": dossier.title if dossier is not None else None,
        }

    if "dossiers" in requested_groups:
        dossier_rows = db.session.scalars(
            select(StrategicDossier)
            .where(
                access,
                or_(
                    StrategicDossier.title.ilike(term),
                    StrategicDossier.description.ilike(term),
                ),
            )
            .order_by(StrategicDossier.title.asc(), StrategicDossier.id.asc())
            .limit(limit)
        )
        groups["dossiers"] = [
            result(
                kind="dossier",
                resource_id=row.id,
                title=row.title,
                subtitle=row.status,
                href=f"/app/dossiers/{row.id}",
                dossier=row,
            )
            for row in dossier_rows
        ]
    if "actors" in requested_groups and "actor.read" in permissions:
        actor_rows = db.session.scalars(
            select(Actor)
            .where(_actor_access_clause(), Actor.canonical_name.ilike(term))
            .order_by(Actor.canonical_name.asc(), Actor.id.asc())
            .limit(limit)
        )
        groups["actors"] = [
            result(
                kind="actor",
                resource_id=row.id,
                title=row.canonical_name,
                subtitle=row.actor_type,
                href=f"/app/actors?selected={row.id}",
            )
            for row in actor_rows
        ]
    if "signals" in requested_groups and "signal.read" in permissions:
        signal_rows = db.session.execute(
            select(DossierSignal, Signal, StrategicDossier)
            .join(Signal, Signal.id == DossierSignal.signal_id)
            .join(StrategicDossier, StrategicDossier.id == DossierSignal.dossier_id)
            .where(
                access,
                or_(
                    Signal.title.ilike(term),
                    Signal.summary.ilike(term),
                    Signal.source_name.ilike(term),
                ),
            )
            .order_by(Signal.title.asc(), DossierSignal.id.asc())
            .limit(limit)
        ).all()
        groups["signals"] = [
            result(
                kind="signal",
                resource_id=link.id,
                title=signal.title,
                subtitle=signal.source_name,
                href=f"/app/dossiers/{dossier.id}/signals?selected={link.id}",
                dossier=dossier,
            )
            for link, signal, dossier in signal_rows
        ]
    if "opportunities" in requested_groups and "opportunity.read" in permissions:
        search_opportunity_rows = db.session.execute(
            select(Opportunity, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == Opportunity.dossier_id)
            .where(
                access,
                or_(Opportunity.title.ilike(term), Opportunity.description.ilike(term)),
            )
            .order_by(Opportunity.title.asc(), Opportunity.id.asc())
            .limit(limit)
        ).all()
        groups["opportunities"] = [
            result(
                kind="opportunity",
                resource_id=row.id,
                title=row.title,
                subtitle=row.status,
                href=f"/app/dossiers/{dossier.id}/opportunities?selected={row.id}",
                dossier=dossier,
            )
            for row, dossier in search_opportunity_rows
        ]
    if "documents" in requested_groups and "documents.read" in permissions:
        document_rows = db.session.execute(
            select(Document, StrategicDossier)
            .join(StrategicDossier, StrategicDossier.id == Document.dossier_id)
            .where(
                access,
                Document.original_filename.ilike(term),
                Document.status == "ready",
                Document.scan_status == "clean",
                Document.deleted_at.is_(None),
            )
            .order_by(Document.original_filename.asc(), Document.id.asc())
            .limit(limit)
        ).all()
        groups["documents"] = [
            result(
                kind="document",
                resource_id=row.id,
                title=row.original_filename,
                subtitle=row.classification,
                href=f"/app/dossiers/{dossier.id}/documents?selected={row.id}",
                dossier=dossier,
            )
            for row, dossier in document_rows
        ]
    return {
        "query": query_text,
        "limit_per_group": limit,
        "groups": groups,
        "items": [item for group in sorted(groups) for item in groups[group]],
    }


@bp.get("/dossiers")
@require_permission("dossier.read")
def dossiers_list() -> Any:
    try:
        page, size, sort, desc = _page_args()
        rows, total = list_page(
            db.session(),
            StrategicDossier,
            page=page,
            size=size,
            sort_key=sort,
            descending=desc,
            filters={
                "status": request.args.get("filter[status]"),
                "dossier_type": request.args.get("filter[type]"),
                "owner_user_id": request.args.get("filter[owner]"),
            },
            allow_sort={
                "updated_at": StrategicDossier.updated_at,
                "title": StrategicDossier.title,
                "status": StrategicDossier.status,
                "health_score": StrategicDossier.health_score,
                "opportunity_score": StrategicDossier.opportunity_score,
                "risk_score": StrategicDossier.risk_score,
            },
            search_columns=(StrategicDossier.title, StrategicDossier.description),
            search=request.args.get("filter[search]", ""),
            extra_criteria=(
                dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id),
                *_typed_list_criteria(StrategicDossier),
            ),
        )
        return {
            "data": [_serialize(row) for row in rows],
            "meta": {"page": page, "size": size, "total": total},
        }
    except DomainValidationError as error:
        return _domain_error(error)


@bp.post("/dossiers")
@require_permission("dossier.write")
def dossiers_create() -> Any:
    try:
        dossier = create_dossier(db.session(), _payload(), actor_id=current_user.id)
        return _serialize(dossier), 201, {"ETag": f'W/"{dossier.version}"'}
    except (DomainValidationError, ResourceNotFound) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.get("/signals")
@require_permission("signal.read")
def signals_list() -> Any:
    """Return contextual signal links across every dossier the caller may read."""

    try:
        page, size, sort, desc = _page_args()
        sortable = {
            "updated_at": DossierSignal.updated_at,
            "published_at": Signal.published_at,
            "title": Signal.title,
            "status": DossierSignal.status,
            "overall_score": DossierSignal.overall_score,
            "source_type": Signal.source_type,
        }
        if page < 1 or size < 1 or size > 100 or sort not in sortable:
            raise DomainValidationError("Paginación u ordenación no válida.")
        criteria: list[Any] = [
            dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
        ]
        dossier_id = _requested_dossier_id()
        if dossier_id is not None:
            criteria.append(DossierSignal.dossier_id == dossier_id)
        status = request.args.get("filter[status]")
        if status:
            criteria.append(DossierSignal.status == status)
        source_type = request.args.get("filter[type]")
        if source_type:
            criteria.append(Signal.source_type == source_type)
        search = request.args.get("filter[search]", "")[:100]
        if search:
            term = f"%{search}%"
            criteria.append(
                or_(
                    Signal.title.ilike(term),
                    Signal.summary.ilike(term),
                    Signal.source_name.ilike(term),
                )
            )
        selected = request.args.get("filter[selected_ids]")
        if selected:
            values = [value for value in selected.split(",") if value]
            if len(values) > 100:
                raise DomainValidationError("selected_ids admite como máximo 100 UUID.")
            try:
                criteria.append(DossierSignal.id.in_([uuid.UUID(value) for value in values]))
            except ValueError as error:
                raise DomainValidationError("selected_ids contiene un UUID no válido.") from error
        if request.args.get("filter[owner]") is not None:
            raise DomainValidationError("El listado de señales no admite filter[owner].")
        for argument, field, operator in (
            ("filter[date_from]", Signal.published_at, "from"),
            ("filter[date_to]", Signal.published_at, "to"),
        ):
            value = request.args.get(argument)
            if value:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as error:
                    raise DomainValidationError(
                        f"{argument} no es una fecha ISO válida."
                    ) from error
                criteria.append(field >= parsed if operator == "from" else field <= parsed)
        for argument, operator in (
            ("filter[score_min]", "min"),
            ("filter[score_max]", "max"),
        ):
            value = request.args.get(argument)
            if value is not None:
                try:
                    score = int(value)
                except ValueError as error:
                    raise DomainValidationError(f"{argument} debe ser entero.") from error
                if not 0 <= score <= 100:
                    raise DomainValidationError(f"{argument} debe estar entre 0 y 100.")
                criteria.append(
                    DossierSignal.overall_score >= score
                    if operator == "min"
                    else DossierSignal.overall_score <= score
                )

        query = (
            select(DossierSignal, Signal, StrategicDossier)
            .join(Signal, Signal.id == DossierSignal.signal_id)
            .join(StrategicDossier, StrategicDossier.id == DossierSignal.dossier_id)
            .where(*criteria)
        )
        count_query = (
            select(func.count(DossierSignal.id))
            .select_from(DossierSignal)
            .join(Signal, Signal.id == DossierSignal.signal_id)
            .join(StrategicDossier, StrategicDossier.id == DossierSignal.dossier_id)
            .where(*criteria)
        )
        order = sortable[sort].desc() if desc else sortable[sort].asc()
        rows = list(
            db.session.execute(
                query.order_by(order, DossierSignal.id.asc()).offset((page - 1) * size).limit(size)
            ).all()
        )
        dossiers = {dossier.id: dossier for _, _, dossier in rows}
        return {
            "data": [
                {"link": _serialize(link), "signal": _serialize(signal)} for link, signal, _ in rows
            ],
            "included": {
                "dossiers": [
                    _dossier_reference(dossier)
                    for dossier in sorted(
                        dossiers.values(), key=lambda value: value.title.casefold()
                    )
                ]
            },
            "meta": {
                "page": page,
                "size": size,
                "total": int(db.session.scalar(count_query) or 0),
            },
        }
    except DomainValidationError as error:
        return _domain_error(error)


def _dossier_or_404(dossier_id: uuid.UUID, *, write: bool = False) -> StrategicDossier | None:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=write
    ):
        return None
    return dossier


def _dossier_manage_or_404(dossier_id: uuid.UUID) -> StrategicDossier | None:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
        )
    )
    if dossier is None or not dossier_manageable(db.session(), dossier, current_user.id):
        return None
    return dossier


def _accessible_signal_dossier(signal_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
    links = db.session.scalars(select(DossierSignal).where(DossierSignal.signal_id == signal_id))
    return next(
        (
            dossier
            for link in links
            if (dossier := _dossier_or_404(link.dossier_id, write=write)) is not None
        ),
        None,
    )


def _evidence_dossier_access(evidence_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
    mappings = list(
        db.session.scalars(
            select(EvidenceDossier).where(EvidenceDossier.evidence_id == evidence_id)
        )
    )
    if not mappings:
        return None
    dossiers = [_dossier_or_404(mapping.dossier_id, write=write) for mapping in mappings]
    if write:
        if any(dossier is None for dossier in dossiers):
            return None
        if any(dossier is not None and dossier.status == "archived" for dossier in dossiers):
            raise DomainValidationError("La evidencia pertenece a un expediente archivado.")
        return dossiers[0]
    return next((dossier for dossier in dossiers if dossier is not None), None)


@bp.get("/dossiers/<uuid:dossier_id>")
@require_permission("dossier.read")
def dossier_get(dossier_id: uuid.UUID) -> Any:
    dossier = _dossier_or_404(dossier_id)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    return _serialize(dossier), 200, {"ETag": f'W/"{dossier.version}"'}


def _expected_version() -> int:
    raw = request.headers.get("If-Match", "").removeprefix('W/"').removesuffix('"')
    if not raw:
        raw = str(_payload().get("version", ""))
    try:
        return int(raw)
    except ValueError as error:
        raise DomainValidationError("If-Match o version es obligatorio.") from error


@bp.patch("/dossiers/<uuid:dossier_id>")
@require_permission("dossier.write")
def dossier_patch(dossier_id: uuid.UUID) -> Any:
    try:
        dossier = update_dossier(
            db.session(),
            dossier_id,
            _payload(),
            expected_version=_expected_version(),
            actor_id=current_user.id,
        )
        return _serialize(dossier), 200, {"ETag": f'W/"{dossier.version}"'}
    except (DomainValidationError, ResourceNotFound, VersionConflict) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.post("/dossiers/<uuid:dossier_id>/archive")
@require_permission("dossier.archive")
def dossier_archive(dossier_id: uuid.UUID) -> Any:
    try:
        dossier = archive_dossier(
            db.session(), dossier_id, actor_id=current_user.id, expected_version=_expected_version()
        )
        return _serialize(dossier), 200, {"ETag": f'W/"{dossier.version}"'}
    except (DomainValidationError, ResourceNotFound, VersionConflict) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.get("/dossiers/<uuid:dossier_id>/signals")
@require_permission("signal.read")
def dossier_signals(dossier_id: uuid.UUID) -> Any:
    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    try:
        page = _model_page(DossierSignal, criteria=(DossierSignal.dossier_id == dossier_id,))
        return {
            "data": [
                {
                    "link": link,
                    "signal": _serialize(db.session.get(Signal, uuid.UUID(link["signal_id"]))),
                }
                for link in page["data"]
            ],
            "meta": page["meta"],
        }
    except DomainValidationError as error:
        return _domain_error(error)


@bp.post("/signals/<uuid:link_id>/review")
@require_permission("signal.review")
def signal_review(link_id: uuid.UUID) -> Any:
    try:
        return _serialize(
            review_signal_link(db.session(), link_id, _payload(), actor_id=current_user.id)
        )
    except (
        DomainValidationError,
        ResourceNotFound,
        VersionConflict,
        TypeError,
        ValueError,
    ) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.post("/signals/<uuid:link_id>/promote")
@require_permission("signal.promote")
def signal_promote(link_id: uuid.UUID) -> Any:
    if not request.headers.get("Idempotency-Key"):
        return problem_response(
            422, detail="Idempotency-Key es obligatorio.", code="idempotency_key_required"
        )
    try:
        resource = promote_signal_link(
            db.session(),
            link_id,
            _payload(),
            idempotency_key=request.headers["Idempotency-Key"],
            actor_id=current_user.id,
        )
        return {
            "kind": "opportunity" if isinstance(resource, Opportunity) else "risk",
            "resource": _serialize(resource),
        }
    except (
        DomainValidationError,
        ResourceNotFound,
        VersionConflict,
        TypeError,
        ValueError,
    ) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.get("/signals/<uuid:signal_id>")
@require_permission("signal.read")
def signal_get(signal_id: uuid.UUID) -> Any:
    row = db.session.scalar(select(Signal).where(Signal.id == signal_id))
    if row is None:
        return problem_response(404, detail="Señal no encontrada.", code="not_found")
    if _accessible_signal_dossier(signal_id, write=False) is None:
        return problem_response(404, detail="Señal no encontrada.", code="not_found")
    return _serialize(row)


@bp.post("/watchlists/<uuid:watchlist_id>/monitors")
@require_permission("signal.review")
def monitor_create(watchlist_id: uuid.UUID) -> Any:
    watchlist = db.session.scalar(select(Watchlist).where(Watchlist.id == watchlist_id))
    if watchlist is None:
        return problem_response(404, detail="Watchlist no encontrada.", code="not_found")
    dossier = _dossier_or_404(watchlist.dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Watchlist no encontrada.", code="not_found")
    if dossier.status == "archived":
        return _domain_error(DomainValidationError("Un expediente archivado es de solo lectura."))
    payload = _payload()
    provider = str(payload.get("provider", "")).strip()
    if not provider:
        return _domain_error(DomainValidationError("provider es obligatorio."))
    row = SignalMonitor(
        tenant_id=g.active_tenant_id,
        watchlist_id=watchlist_id,
        provider=provider[:80],
        external_id=str(payload["external_id"])[:200] if payload.get("external_id") else None,
        status="active",
    )
    db.session.add(row)
    db.session.flush()
    append_audit_event(
        db.session,
        action="signal_monitor.created",
        resource_type="signal_monitor",
        resource_id=row.id,
        dossier_id=dossier.id,
        result="success",
    )
    db.session.commit()
    return _serialize(row), 201


@bp.get("/watchlists/<uuid:watchlist_id>/monitors")
@require_permission("signal.read")
def monitors_list(watchlist_id: uuid.UUID) -> Any:
    watchlist = db.session.scalar(select(Watchlist).where(Watchlist.id == watchlist_id))
    if watchlist is None or _dossier_or_404(watchlist.dossier_id) is None:
        return problem_response(404, detail="Watchlist no encontrada.", code="not_found")
    try:
        return _model_page(SignalMonitor, criteria=(SignalMonitor.watchlist_id == watchlist_id,))
    except DomainValidationError as error:
        return _domain_error(error)


@bp.post("/meetings/<uuid:meeting_id>/briefings")
@require_permission("meeting.write")
def briefing_create(meeting_id: uuid.UUID) -> Any:
    meeting = db.session.scalar(select(Meeting).where(Meeting.id == meeting_id))
    if meeting is None:
        return problem_response(404, detail="Reunión no encontrada.", code="not_found")
    dossier = _dossier_or_404(meeting.dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Reunión no encontrada.", code="not_found")
    if dossier.status == "archived":
        return _domain_error(DomainValidationError("Un expediente archivado es de solo lectura."))
    row = Briefing(
        tenant_id=g.active_tenant_id,
        meeting_id=meeting_id,
        content=dict(_payload().get("content", {})),
    )
    db.session.add(row)
    db.session.flush()
    append_audit_event(
        db.session,
        action="briefing.created",
        resource_type="briefing",
        resource_id=row.id,
        dossier_id=dossier.id,
        result="success",
    )
    db.session.commit()
    return _serialize(row), 201


@bp.get("/meetings/<uuid:meeting_id>/briefings")
@require_permission("meeting.read")
def briefings_list(meeting_id: uuid.UUID) -> Any:
    meeting = db.session.scalar(select(Meeting).where(Meeting.id == meeting_id))
    if meeting is None or _dossier_or_404(meeting.dossier_id) is None:
        return problem_response(404, detail="Reunión no encontrada.", code="not_found")
    try:
        return _model_page(Briefing, criteria=(Briefing.meeting_id == meeting_id,))
    except DomainValidationError as error:
        return _domain_error(error)


@bp.post("/evidence")
@require_permission("dossier.write")
def evidence_create() -> Any:
    payload = _payload()
    try:
        if not payload.get("signal_id"):
            raise DomainValidationError(
                "signal_id es obligatorio hasta que Document/Chunk se implemente en fase 10."
            )
        signal_id = uuid.UUID(str(payload["signal_id"]))
        if not payload.get("dossier_id"):
            raise DomainValidationError("dossier_id es obligatorio para contextualizar evidencia.")
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
        dossier = _dossier_or_404(dossier_id, write=True)
        if dossier is None:
            raise ResourceNotFound("Expediente o señal no encontrados.")
        if dossier.status == "archived":
            raise DomainValidationError("Un expediente archivado es de solo lectura.")
        link = db.session.scalar(
            select(DossierSignal).where(
                DossierSignal.dossier_id == dossier_id,
                DossierSignal.signal_id == signal_id,
            )
        )
        if link is None:
            raise ResourceNotFound("Expediente o señal no encontrados.")
        extract = str(payload.get("extract", ""))[:20000]
        if not extract:
            raise DomainValidationError("extract es obligatorio.")
        checksum = __import__("hashlib").sha256(extract.encode()).digest()
        row = Evidence(
            tenant_id=g.active_tenant_id,
            signal_id=signal_id,
            document_id=None,
            source_url=str(payload["source_url"])[:1500] if payload.get("source_url") else None,
            extract=extract,
            locator=dict(payload.get("locator", {})),
            checksum=checksum,
            classification=str(payload.get("classification", "internal")),
            provenance=dict(payload.get("provenance", {})),
        )
        db.session.add(row)
        db.session.flush()
        db.session.add(
            EvidenceDossier(
                tenant_id=g.active_tenant_id,
                evidence_id=row.id,
                dossier_id=dossier_id,
            )
        )
        append_audit_event(
            db.session,
            action="evidence.created",
            resource_type="evidence",
            resource_id=row.id,
            dossier_id=dossier.id,
            result="success",
        )
        db.session.commit()
        return _serialize(row), 201
    except (
        TypeError,
        ValueError,
        DomainValidationError,
        ResourceNotFound,
        IntegrityError,
    ) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.get("/dossiers/<uuid:dossier_id>/evidence")
@require_permission("signal.read")
def evidence_list(dossier_id: uuid.UUID) -> Any:
    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    try:
        evidence_ids = select(EvidenceDossier.evidence_id).where(
            EvidenceDossier.dossier_id == dossier_id
        )
        return _model_page(Evidence, criteria=(Evidence.id.in_(evidence_ids),))
    except DomainValidationError as error:
        return _domain_error(error)


NESTED: dict[str, tuple[type[Any], str, str]] = {
    "objectives": (DossierObjective, "dossier.read", "dossier.write"),
    "hypotheses": (Hypothesis, "dossier.read", "dossier.write"),
    "watchlists": (Watchlist, "dossier.read", "dossier.write"),
    "opportunities": (Opportunity, "opportunity.read", "opportunity.write"),
    "risks": (RiskItem, "risk.read", "risk.write"),
    "actors": (DossierActor, "actor.read", "actor.write"),
    "meetings": (Meeting, "meeting.read", "meeting.write"),
    "decisions": (Decision, "task.read", "task.write"),
    "tasks": (Task, "task.read", "task.write"),
    "insights": (Insight, "dossier.read", "dossier.write"),
    "reports": (Report, "report.read", "report.generate"),
}


def _safe_construct(model: type[Any], payload: dict[str, Any], dossier_id: uuid.UUID) -> Any:
    excluded = {"id", "tenant_id", "dossier_id", "created_at", "updated_at", "status", "version"}
    allowed = {column.key for column in model.__table__.columns} - excluded
    values = {key: value for key, value in payload.items() if key in allowed}
    if "title" in allowed and not str(values.get("title", "")).strip():
        raise DomainValidationError("title es obligatorio.")
    return model(tenant_id=g.active_tenant_id, dossier_id=dossier_id, **values)


def _model_page(model: type[Any], *, criteria: tuple[Any, ...] = ()) -> dict[str, Any]:
    page, size, sort, desc = _page_args()
    sortable = {
        key: getattr(model, key)
        for key in (
            "updated_at",
            "created_at",
            "title",
            "name",
            "canonical_name",
            "status",
            "overall_score",
            "due_date",
            "scheduled_at",
            "decided_at",
            "priority",
        )
        if hasattr(model, key)
    }
    if "sort" not in request.args and sort not in sortable:
        sort = "updated_at" if "updated_at" in sortable else "created_at"
    search_columns = tuple(
        getattr(model, key)
        for key in (
            "title",
            "name",
            "canonical_name",
            "statement",
            "description",
            "extract",
            "relationship_type",
            "action",
            "resource_type",
        )
        if hasattr(model, key)
    )
    rows, total = list_page(
        db.session(),
        model,
        page=page,
        size=size,
        sort_key=sort,
        descending=desc,
        filters={"status": request.args.get("filter[status]")},
        allow_sort=sortable,
        search_columns=search_columns,
        search=request.args.get("filter[search]", ""),
        extra_criteria=criteria + _typed_list_criteria(model),
    )
    return {
        "data": [_serialize(row) for row in rows],
        "meta": {"page": page, "size": size, "total": total},
    }


def _nested_list(resource: str, dossier_id: uuid.UUID) -> Any:
    model, _, _ = NESTED[resource]
    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    try:
        if model is Report:
            page, size, _, _ = _page_args()
            query = select(Report).where(Report.dossier_id == dossier_id)
            status = request.args.get("filter[status]")
            if status:
                query = query.where(Report.status == status)
            rows = list(
                db.session.scalars(
                    query.order_by(Report.created_at.desc()).offset((page - 1) * size).limit(size)
                )
            )
            count_query = select(func.count(Report.id)).where(Report.dossier_id == dossier_id)
            if status:
                count_query = count_query.where(Report.status == status)
            total = int(db.session.scalar(count_query) or 0)
            return {
                "data": [serialize_report(row) for row in rows],
                "meta": {"page": page, "size": size, "total": total},
            }
        return _model_page(model, criteria=(model.dossier_id == dossier_id,))
    except DomainValidationError as error:
        return _domain_error(error)


def _nested_create(resource: str, dossier_id: uuid.UUID) -> Any:
    model, _, _ = NESTED[resource]
    dossier = _dossier_or_404(dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    if dossier.status == "archived":
        return problem_response(
            422, detail="Un expediente archivado es de solo lectura.", code="domain_validation"
        )
    try:
        payload = _payload()
        row: Any
        if model is Report:
            idempotency_key = request.headers.get("Idempotency-Key", "")
            raw_options = payload.get("options")
            report_options: dict[str, Any] = raw_options if isinstance(raw_options, dict) else {}
            report, job, created = create_report_request(
                dossier,
                template_key=str(payload.get("template_key", "")),
                options=report_options,
                requested_by_user_id=current_user.id,
                idempotency_key=idempotency_key,
            )
            return {
                "report": serialize_report(report),
                "job_id": str(job.id),
                "replayed": not created,
            }, (202 if created else 200)
        if model in {Opportunity, RiskItem}:
            row = create_scored_resource(
                db.session(), model, dossier_id, payload, actor_id=current_user.id
            )
            return _serialize(row), 201
        if model is DossierActor:
            row = create_dossier_actor(db.session(), dossier_id, payload, actor_id=current_user.id)
            return _serialize(row), 201
        if payload.get("owner_user_id") is not None:
            owner_id = uuid.UUID(str(payload["owner_user_id"]))
            if not active_membership_exists(db.session(), g.active_tenant_id, owner_id):
                raise DomainValidationError("owner_user_id debe ser un miembro activo.")
        defaults = {
            Meeting: "planned",
            Decision: "proposed",
            Task: "open",
            Insight: "draft",
            Report: "pending",
        }
        row = _safe_construct(model, payload, dossier_id)
        if model in defaults:
            row.status = defaults[model]
        db.session.add(row)
        db.session.flush()
        append_audit_event(
            db.session,
            action=f"{resource}.created",
            resource_type=resource,
            resource_id=row.id,
            dossier_id=dossier_id,
            result="success",
        )
        db.session.commit()
        return _serialize(row), 201
    except ReportConflictError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="idempotency_conflict")
    except (
        KeyError,
        TypeError,
        ValueError,
        ReportWorkflowError,
        DomainValidationError,
        ResourceNotFound,
        IntegrityError,
    ) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="domain_validation")


def _register_nested_routes() -> None:
    for resource, (_, read_permission, write_permission) in NESTED.items():
        list_view = require_permission(read_permission)(
            lambda dossier_id, resource=resource: _nested_list(resource, dossier_id)
        )
        create_view = require_permission(write_permission)(
            lambda dossier_id, resource=resource: _nested_create(resource, dossier_id)
        )
        bp.add_url_rule(
            f"/dossiers/<uuid:dossier_id>/{resource}",
            endpoint=f"dossier_{resource}_list",
            view_func=list_view,
            methods=["GET"],
        )
        bp.add_url_rule(
            f"/dossiers/<uuid:dossier_id>/{resource}",
            endpoint=f"dossier_{resource}_create",
            view_func=create_view,
            methods=["POST"],
        )


_register_nested_routes()


DETAIL: dict[str, tuple[type[Any], str, str]] = {
    "objectives": (DossierObjective, "dossier.read", "dossier.write"),
    "hypotheses": (Hypothesis, "dossier.read", "dossier.write"),
    "watchlists": (Watchlist, "dossier.read", "dossier.write"),
    "opportunities": (Opportunity, "opportunity.read", "opportunity.write"),
    "risks": (RiskItem, "risk.read", "risk.write"),
    "actors": (Actor, "actor.read", "actor.write"),
    "dossier-actors": (DossierActor, "actor.read", "actor.write"),
    "meetings": (Meeting, "meeting.read", "meeting.write"),
    "briefings": (Briefing, "meeting.read", "meeting.write"),
    "decisions": (Decision, "task.read", "task.write"),
    "tasks": (Task, "task.read", "task.write"),
    "insights": (Insight, "dossier.read", "dossier.write"),
    "reports": (Report, "report.read", "report.generate"),
    "evidence": (Evidence, "signal.read", "dossier.write"),
    "relationships": (Relationship, "actor.read", "actor.write"),
    "feedback": (Feedback, "dossier.read", "dossier.write"),
}


def _detail(resource: str, resource_id: uuid.UUID) -> Any:
    model, _, _ = DETAIL[resource]
    row = db.session.scalar(select(model).where(model.id == resource_id))
    if row is None:
        return problem_response(404, detail="Recurso no encontrado.", code="not_found")
    if (
        isinstance(row, Actor)
        and db.session.scalar(select(Actor.id).where(Actor.id == row.id, _actor_access_clause()))
        is None
    ):
        return problem_response(404, detail="Recurso no encontrado.", code="not_found")
    dossier = None
    dossier_id = getattr(row, "dossier_id", None)
    if isinstance(row, SignalMonitor):
        watchlist = db.session.get(Watchlist, row.watchlist_id)
        dossier_id = watchlist.dossier_id if watchlist else None
    elif isinstance(row, Briefing):
        meeting = db.session.get(Meeting, row.meeting_id)
        dossier_id = meeting.dossier_id if meeting else None
    elif isinstance(row, Evidence):
        try:
            dossier = _evidence_dossier_access(row.id, write=request.method == "PATCH")
        except DomainValidationError as error:
            return _domain_error(error)
        if dossier is None:
            return problem_response(404, detail="Recurso no encontrado.", code="not_found")
        dossier_id = dossier.id
    if dossier_id is not None:
        dossier = _dossier_or_404(dossier_id, write=request.method == "PATCH")
        if dossier is None:
            return problem_response(404, detail="Recurso no encontrado.", code="not_found")
    if request.method == "GET":
        if isinstance(row, Report):
            return serialize_report(row, detail=True)
        return _serialize(row)
    if isinstance(row, Report):
        return problem_response(
            405,
            detail="Los informes se modifican mediante revisiones y workflow.",
            code="method_not_allowed",
        )
    payload = _payload()
    if dossier is not None and dossier.status == "archived":
        return problem_response(
            422, detail="Un expediente archivado es de solo lectura.", code="domain_validation"
        )
    if model in {Opportunity, RiskItem}:
        try:
            updated = update_scored_resource(
                db.session(),
                model,
                resource_id,
                payload,
                actor_id=current_user.id,
                expected_version=_expected_version(),
            )
            return _serialize(updated), 200, {"ETag": f'W/"{updated.version}"'}
        except (
            DomainValidationError,
            ResourceNotFound,
            VersionConflict,
            TypeError,
            ValueError,
        ) as error:
            db.session.rollback()
            return _domain_error(error)
    if model is DossierActor:
        try:
            updated_actor = update_dossier_actor(
                db.session(),
                resource_id,
                payload,
                actor_id=current_user.id,
                expected_version=_expected_version(),
            )
            return _serialize(updated_actor), 200, {"ETag": f'W/"{updated_actor.version}"'}
        except (
            DomainValidationError,
            ResourceNotFound,
            VersionConflict,
            TypeError,
            ValueError,
        ) as error:
            db.session.rollback()
            return _domain_error(error)
    if hasattr(row, "version"):
        try:
            expected = _expected_version()
        except DomainValidationError as error:
            return _domain_error(error)
        if row.version != expected:
            return _domain_error(VersionConflict("El recurso fue modificado por otro usuario."))
    if isinstance(row, Actor):
        if "actor_type" in payload:
            actor_type = str(payload["actor_type"])
            if actor_type not in {"person", "organization", "institution", "program", "other"}:
                return _domain_error(DomainValidationError("actor_type no válido."))
            row.actor_type = actor_type
        if "canonical_name" in payload:
            canonical_name = str(payload["canonical_name"]).strip()
            if not canonical_name:
                return _domain_error(DomainValidationError("canonical_name es obligatorio."))
            canonical_key = "-".join(canonical_name.casefold().split())[:320]
            duplicate = db.session.scalar(
                select(Actor.id).where(
                    Actor.canonical_key == canonical_key,
                    Actor.id != row.id,
                )
            )
            if duplicate is not None:
                return _domain_error(DomainValidationError("Ya existe un actor canónico."))
            row.canonical_name, row.canonical_key = canonical_name[:300], canonical_key
        for field in ("aliases", "identifiers", "provenance"):
            if field in payload:
                setattr(row, field, payload[field])
        if "metadata" in payload:
            row.actor_metadata = dict(payload["metadata"])
    allowed = {
        "title",
        "name",
        "description",
        "next_action",
        "mitigation",
        "owner_user_id",
        "due_date",
        "scheduled_at",
        "objective",
        "notes",
        "content",
        "status",
        "statement",
        "rationale",
        "confidence",
        "position",
        "metrics",
        "target_date",
        "query_config",
        "cadence",
        "roles",
        "facts",
        "inferences",
        "recommendation",
        "report_type",
        "template_key",
        "extract",
        "locator",
        "classification",
        "provider",
        "external_id",
        "rating",
        "correction",
        "comment",
        "relationship_type",
        "strength",
        "direction",
        "valid_from",
        "valid_to",
    } & {column.key for column in model.__table__.columns}
    transitions = {
        DossierObjective: {
            "open": {"in_progress", "achieved", "cancelled"},
            "in_progress": {"achieved", "cancelled"},
            "achieved": set(),
            "cancelled": set(),
        },
        Hypothesis: {
            "open": {"supported", "contradicted", "discarded"},
            "supported": {"contradicted", "discarded"},
            "contradicted": {"supported", "discarded"},
            "discarded": set(),
        },
        Watchlist: {
            "active": {"paused", "archived"},
            "paused": {"active", "archived"},
            "archived": set(),
        },
        SignalMonitor: {
            "active": {"paused", "error"},
            "paused": {"active"},
            "error": {"active", "paused"},
        },
        Meeting: {
            "planned": {"completed", "cancelled"},
            "completed": set(),
            "cancelled": set(),
        },
        Task: {
            "open": {"in_progress", "blocked", "done", "cancelled"},
            "in_progress": {"blocked", "done", "cancelled"},
            "blocked": {"in_progress", "done", "cancelled"},
            "done": set(),
            "cancelled": set(),
        },
        Decision: {
            "proposed": {"approved", "rejected"},
            "approved": {"superseded"},
            "rejected": set(),
            "superseded": set(),
        },
        Insight: {"draft": {"valid", "rejected"}, "valid": set(), "rejected": set()},
        Report: {
            "pending": {"generating", "failed"},
            "generating": {"completed", "failed"},
            "completed": set(),
            "failed": {"pending"},
        },
    }
    if "status" in payload and (
        model not in transitions
        or str(payload["status"]) not in transitions[model].get(row.status, set())
    ):
        return _domain_error(DomainValidationError("Transición de estado no válida."))
    previous_status = str(row.status) if "status" in payload else None
    for key, value in payload.items():
        if key in allowed:
            setattr(row, key, value)
    if isinstance(row, Evidence) and "extract" in payload:
        row.extract = str(payload["extract"])[:20000]
        row.checksum = __import__("hashlib").sha256(row.extract.encode()).digest()
    if hasattr(row, "version"):
        row.version += 1
    if previous_status is not None and dossier_id is not None:
        record_status_change(
            db.session(),
            dossier_id=dossier_id,
            resource_type=resource.removesuffix("s"),
            resource_id=row.id,
            from_status=previous_status,
            to_status=str(payload["status"]),
            actor_id=current_user.id,
            reason=str(payload.get("status_reason", "")),
        )
    append_audit_event(
        db.session,
        action=f"{resource}.updated",
        resource_type=resource,
        resource_id=row.id,
        dossier_id=dossier_id,
        result="success",
        metadata={"status_changed": previous_status is not None},
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _domain_error(DomainValidationError("Datos no válidos."))
    return _serialize(row), 200, ({"ETag": f'W/"{row.version}"'} if hasattr(row, "version") else {})


def _detail_delete(resource: str, resource_id: uuid.UUID) -> Any:
    model, _, _ = DETAIL[resource]
    row = db.session.scalar(select(model).where(model.id == resource_id))
    if row is None:
        return problem_response(404, detail="Recurso no encontrado.", code="not_found")
    dossier_id = getattr(row, "dossier_id", None)
    if isinstance(row, SignalMonitor):
        watchlist = db.session.get(Watchlist, row.watchlist_id)
        dossier_id = watchlist.dossier_id if watchlist else None
    elif isinstance(row, Briefing):
        meeting = db.session.get(Meeting, row.meeting_id)
        dossier_id = meeting.dossier_id if meeting else None
    elif isinstance(row, Evidence):
        try:
            dossier = _evidence_dossier_access(row.id, write=True)
        except DomainValidationError as error:
            return _domain_error(error)
        if dossier is None:
            return problem_response(404, detail="Recurso no encontrado.", code="not_found")
        dossier_id = dossier.id
    if dossier_id is not None:
        dossier = _dossier_or_404(dossier_id, write=True)
        if dossier is None:
            return problem_response(404, detail="Recurso no encontrado.", code="not_found")
        if dossier.status == "archived":
            return _domain_error(
                DomainValidationError("Un expediente archivado es de solo lectura.")
            )
    db.session.delete(row)
    append_audit_event(
        db.session,
        action=f"{resource}.deleted",
        resource_type=resource,
        resource_id=resource_id,
        dossier_id=dossier_id,
        result="success",
    )
    db.session.commit()
    return "", 204


for _resource, (_, _read_permission, _write_permission) in DETAIL.items():
    bp.add_url_rule(
        f"/{_resource}/<uuid:resource_id>",
        endpoint=f"{_resource}_get",
        view_func=require_permission(_read_permission)(
            lambda resource_id, resource=_resource: _detail(resource, resource_id)
        ),
        methods=["GET"],
    )
    bp.add_url_rule(
        f"/{_resource}/<uuid:resource_id>",
        endpoint=f"{_resource}_patch",
        view_func=require_permission(_write_permission)(
            lambda resource_id, resource=_resource: _detail(resource, resource_id)
        ),
        methods=["PATCH"],
    )
    if _resource != "actors":
        bp.add_url_rule(
            f"/{_resource}/<uuid:resource_id>",
            endpoint=f"{_resource}_delete",
            view_func=require_permission(_write_permission)(
                lambda resource_id, resource=_resource: _detail_delete(resource, resource_id)
            ),
            methods=["DELETE"],
        )


M2M: dict[
    str,
    tuple[type[Any], str, str, dict[str, tuple[type[Any], type[Any], str]]],
] = {
    "opportunities": (
        Opportunity,
        "opportunity_id",
        "opportunity.write",
        {
            "actors": (OpportunityActor, Actor, "actor_id"),
            "evidence": (OpportunityEvidence, Evidence, "evidence_id"),
            "signals": (OpportunitySignal, Signal, "signal_id"),
        },
    ),
    "risks": (
        RiskItem,
        "risk_id",
        "risk.write",
        {
            "actors": (RiskActor, Actor, "actor_id"),
            "evidence": (RiskEvidence, Evidence, "evidence_id"),
            "signals": (RiskSignal, Signal, "signal_id"),
        },
    ),
    "meetings": (
        Meeting,
        "meeting_id",
        "meeting.write",
        {
            "actors": (MeetingActor, Actor, "actor_id"),
            "evidence": (MeetingEvidence, Evidence, "evidence_id"),
        },
    ),
    "hypotheses": (
        Hypothesis,
        "hypothesis_id",
        "dossier.write",
        {"evidence": (HypothesisEvidence, Evidence, "evidence_id")},
    ),
    "dossier-actors": (
        DossierActor,
        "dossier_actor_id",
        "actor.write",
        {"evidence": (DossierActorEvidence, Evidence, "evidence_id")},
    ),
    "relationships": (
        Relationship,
        "relationship_id",
        "actor.write",
        {"evidence": (RelationshipEvidence, Evidence, "evidence_id")},
    ),
    "decisions": (
        Decision,
        "decision_id",
        "task.write",
        {"evidence": (DecisionEvidence, Evidence, "evidence_id")},
    ),
    "insights": (
        Insight,
        "insight_id",
        "dossier.write",
        {"evidence": (InsightEvidence, Evidence, "evidence_id")},
    ),
    "reports": (
        Report,
        "report_id",
        "report.generate",
        {"evidence": (ReportEvidence, Evidence, "evidence_id")},
    ),
}


def _m2m_parent(
    resource: str, resource_id: uuid.UUID, *, write: bool
) -> tuple[Any, uuid.UUID | None]:
    parent_model, _, _, _ = M2M[resource]
    parent = db.session.scalar(select(parent_model).where(parent_model.id == resource_id))
    if parent is None:
        raise ResourceNotFound("Recurso no encontrado.")
    dossier_id = getattr(parent, "dossier_id", None)
    if dossier_id is not None:
        dossier = _dossier_or_404(dossier_id, write=write)
        if dossier is None:
            raise ResourceNotFound("Recurso no encontrado.")
        if write and dossier.status == "archived":
            raise DomainValidationError("Un expediente archivado es de solo lectura.")
    return parent, dossier_id


def _m2m_list(resource: str, relation: str, resource_id: uuid.UUID) -> Any:
    try:
        _m2m_parent(resource, resource_id, write=False)
        _, parent_key, _, relations = M2M[resource]
        link_model, target_model, target_key = relations[relation]
        target_ids = select(getattr(link_model, target_key)).where(
            getattr(link_model, parent_key) == resource_id
        )
        return _model_page(target_model, criteria=(target_model.id.in_(target_ids),))
    except (DomainValidationError, ResourceNotFound) as error:
        return _domain_error(error)


def _m2m_mutate(
    resource: str,
    relation: str,
    resource_id: uuid.UUID,
    target_id: uuid.UUID,
) -> Any:
    try:
        _, dossier_id = _m2m_parent(resource, resource_id, write=True)
        _, parent_key, _, relations = M2M[resource]
        link_model, target_model, target_key = relations[relation]
        target = db.session.scalar(select(target_model).where(target_model.id == target_id))
        if target is None:
            raise ResourceNotFound("Recurso vinculado no encontrado.")
        if (
            isinstance(target, Evidence)
            and dossier_id is not None
            and db.session.get(
                EvidenceDossier,
                {
                    "tenant_id": g.active_tenant_id,
                    "evidence_id": target.id,
                    "dossier_id": dossier_id,
                },
            )
            is None
        ):
            raise ResourceNotFound("Recurso vinculado no encontrado.")
        if (
            isinstance(target, Signal)
            and dossier_id is not None
            and db.session.scalar(
                select(DossierSignal.id).where(
                    DossierSignal.dossier_id == dossier_id,
                    DossierSignal.signal_id == target.id,
                )
            )
            is None
        ):
            raise ResourceNotFound("Recurso vinculado no encontrado.")
        identity = {
            "tenant_id": g.active_tenant_id,
            parent_key: resource_id,
            target_key: target_id,
        }
        existing = db.session.get(link_model, identity)
        if request.method == "DELETE":
            if existing is None:
                raise ResourceNotFound("Vínculo no encontrado.")
            db.session.delete(existing)
            status = 204
        else:
            if existing is None:
                db.session.add(link_model(**identity))
            status = 200
        append_audit_event(
            db.session,
            action=f"{resource}.{relation}.{'removed' if request.method == 'DELETE' else 'linked'}",
            resource_type=resource,
            resource_id=resource_id,
            dossier_id=dossier_id,
            result="success",
            metadata={"target_id": str(target_id)},
        )
        db.session.commit()
        return ("", 204) if status == 204 else {"linked": True}
    except (DomainValidationError, ResourceNotFound, IntegrityError) as error:
        db.session.rollback()
        return _domain_error(error)


for _m2m_resource, _m2m_config in M2M.items():
    _m2m_write_permission = _m2m_config[2]
    _relations = _m2m_config[3]
    _m2m_read_permission = _m2m_write_permission.replace(".write", ".read").replace(
        "report.generate", "report.read"
    )
    for _relation in _relations:
        bp.add_url_rule(
            f"/{_m2m_resource}/<uuid:resource_id>/{_relation}",
            endpoint=f"{_m2m_resource}_{_relation}_list",
            view_func=require_permission(_m2m_read_permission)(
                lambda resource_id, resource=_m2m_resource, relation=_relation: _m2m_list(
                    resource, relation, resource_id
                )
            ),
            methods=["GET"],
        )
        bp.add_url_rule(
            f"/{_m2m_resource}/<uuid:resource_id>/{_relation}/<uuid:target_id>",
            endpoint=f"{_m2m_resource}_{_relation}_mutate",
            view_func=require_permission(_m2m_write_permission)(
                lambda resource_id, target_id, resource=_m2m_resource, relation=_relation: (
                    _m2m_mutate(resource, relation, resource_id, target_id)
                )
            ),
            methods=["PUT", "DELETE"],
        )


@bp.get("/opportunities")
@require_permission("opportunity.read")
def opportunities_list() -> Any:
    try:
        return _global_dossier_resource_page(Opportunity)
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/risks")
@require_permission("risk.read")
def risks_list() -> Any:
    try:
        return _global_dossier_resource_page(RiskItem)
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/meetings")
@require_permission("meeting.read")
def meetings_list() -> Any:
    try:
        return _global_dossier_resource_page(Meeting)
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/tasks")
@require_permission("task.read")
def tasks_list() -> Any:
    try:
        return _global_dossier_resource_page(Task)
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/actors")
@require_permission("actor.read")
def actors_list() -> Any:
    try:
        return _model_page(Actor, criteria=(_actor_access_clause(),))
    except DomainValidationError as error:
        return _domain_error(error)


@bp.post("/actors")
@require_permission("actor.write")
def actors_create() -> Any:
    payload = _payload()
    name = str(payload.get("canonical_name", "")).strip()
    actor_type = str(payload.get("actor_type", "organization"))
    if not name or actor_type not in {"person", "organization", "institution", "program", "other"}:
        return problem_response(
            422, detail="canonical_name es obligatorio.", code="validation_error"
        )
    canonical_key = "-".join(name.casefold().split())[:320]
    existing = db.session.scalar(select(Actor).where(Actor.canonical_key == canonical_key))
    if existing is not None:
        return _serialize(existing), 200
    row = Actor(
        tenant_id=g.active_tenant_id,
        actor_type=actor_type,
        canonical_name=name[:300],
        canonical_key=canonical_key,
        aliases=list(payload.get("aliases", [])),
        identifiers=dict(payload.get("identifiers", {})),
        actor_metadata=dict(payload.get("metadata", {})),
        provenance=dict(payload.get("provenance", {})),
    )
    db.session.add(row)
    db.session.commit()
    return _serialize(row), 201


@bp.post("/actors/<uuid:target_id>/merge")
@require_permission("actor.write")
def actors_merge(target_id: uuid.UUID) -> Any:
    payload = _payload()
    try:
        source_id = uuid.UUID(str(payload["source_actor_id"]))
        row = merge_actors(
            db.session(),
            target_id,
            source_id,
            actor_id=current_user.id,
            reason=str(payload.get("reason", "")),
        )
        return _serialize(row)
    except (KeyError, ValueError, DomainValidationError, ResourceNotFound, IntegrityError) as error:
        db.session.rollback()
        return _domain_error(error)


@bp.get("/dossiers/<uuid:dossier_id>/collaborators")
@require_permission("dossier.read")
def collaborators_list(dossier_id: uuid.UUID) -> Any:
    if _dossier_manage_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    rows = db.session.scalars(
        select(DossierCollaborator).where(DossierCollaborator.dossier_id == dossier_id)
    )
    return {"data": [_serialize(row) for row in rows]}


@bp.put("/dossiers/<uuid:dossier_id>/collaborators/<uuid:user_id>")
@require_permission("dossier.write")
def collaborators_put(dossier_id: uuid.UUID, user_id: uuid.UUID) -> Any:
    dossier = _dossier_manage_or_404(dossier_id)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    if dossier.status == "archived":
        return _domain_error(DomainValidationError("Un expediente archivado es de solo lectura."))
    role = str(_payload().get("role", "collaborator"))
    if role not in {"owner", "editor", "collaborator", "viewer"} or not active_membership_exists(
        db.session(), g.active_tenant_id, user_id
    ):
        return _domain_error(DomainValidationError("Colaborador o rol no válido."))
    row = db.session.get(
        DossierCollaborator,
        {"tenant_id": g.active_tenant_id, "dossier_id": dossier_id, "user_id": user_id},
    )
    if row is None:
        row = DossierCollaborator(
            tenant_id=g.active_tenant_id,
            dossier_id=dossier_id,
            user_id=user_id,
            role=role,
        )
        db.session.add(row)
    else:
        row.role = role
    append_audit_event(
        db.session,
        action="dossier.collaborator_set",
        resource_type="strategic_dossier",
        resource_id=dossier_id,
        dossier_id=dossier_id,
        result="success",
        metadata={"user_id": str(user_id), "role": role},
    )
    db.session.commit()
    return _serialize(row)


@bp.delete("/dossiers/<uuid:dossier_id>/collaborators/<uuid:user_id>")
@require_permission("dossier.write")
def collaborators_delete(dossier_id: uuid.UUID, user_id: uuid.UUID) -> Any:
    dossier = _dossier_manage_or_404(dossier_id)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    if dossier.status == "archived":
        return _domain_error(DomainValidationError("Un expediente archivado es de solo lectura."))
    row = db.session.get(
        DossierCollaborator,
        {"tenant_id": g.active_tenant_id, "dossier_id": dossier_id, "user_id": user_id},
    )
    if row is None:
        return problem_response(404, detail="Colaborador no encontrado.", code="not_found")
    db.session.delete(row)
    append_audit_event(
        db.session,
        action="dossier.collaborator_removed",
        resource_type="strategic_dossier",
        resource_id=dossier_id,
        dossier_id=dossier_id,
        result="success",
        metadata={"user_id": str(user_id)},
    )
    db.session.commit()
    return "", 204


@bp.get("/relationships")
@require_permission("actor.read")
def relationships_list() -> Any:
    accessible_ids = select(StrategicDossier.id).where(
        dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id)
    )
    try:
        return _model_page(
            Relationship,
            criteria=(
                or_(
                    Relationship.dossier_id.is_(None),
                    Relationship.dossier_id.in_(accessible_ids),
                ),
            ),
        )
    except DomainValidationError as error:
        return _domain_error(error)


@bp.post("/relationships")
@require_permission("actor.write")
def relationships_create() -> Any:
    try:
        payload = _payload()
        if payload.get("dossier_id") is not None:
            dossier_id = uuid.UUID(str(payload["dossier_id"]))
            dossier = _dossier_or_404(dossier_id, write=True)
            if dossier is None:
                raise ResourceNotFound("Expediente no encontrado.")
            if dossier.status == "archived":
                raise DomainValidationError("Un expediente archivado es de solo lectura.")
        row = Relationship(
            tenant_id=g.active_tenant_id,
            **{
                key: value
                for key, value in payload.items()
                if key
                in {column.key for column in Relationship.__table__.columns}
                - {"id", "tenant_id", "created_at", "updated_at"}
            },
        )
        db.session.add(row)
        db.session.flush()
        append_audit_event(
            db.session,
            action="relationship.created",
            resource_type="relationship",
            resource_id=row.id,
            dossier_id=row.dossier_id,
            result="success",
        )
        db.session.commit()
        return _serialize(row), 201
    except (
        TypeError,
        ValueError,
        DomainValidationError,
        ResourceNotFound,
        IntegrityError,
    ) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="domain_validation")


@bp.post("/feedback")
@require_permission("dossier.write")
def feedback_create() -> Any:
    try:
        payload = _payload()
        target_type = str(payload.get("target_type", ""))
        target_models: dict[str, type[Any]] = {
            "dossier": StrategicDossier,
            "opportunity": Opportunity,
            "risk": RiskItem,
            "meeting": Meeting,
            "task": Task,
            "insight": Insight,
        }
        if target_type not in target_models:
            raise DomainValidationError("target_type no válido.")
        target_id = uuid.UUID(str(payload["target_id"]))
        target = db.session.scalar(
            select(target_models[target_type]).where(target_models[target_type].id == target_id)
        )
        if target is None:
            raise ResourceNotFound("Recurso no encontrado.")
        dossier_id = target.id if isinstance(target, StrategicDossier) else target.dossier_id
        dossier = _dossier_or_404(dossier_id, write=True)
        if dossier is None:
            raise ResourceNotFound("Recurso no encontrado.")
        if dossier.status == "archived":
            raise DomainValidationError("Un expediente archivado es de solo lectura.")
        row = Feedback(
            tenant_id=g.active_tenant_id,
            dossier_id=dossier_id,
            actor_user_id=current_user.id,
            **{
                key: value
                for key, value in payload.items()
                if key in {"target_type", "target_id", "rating", "correction", "comment"}
            },
        )
        db.session.add(row)
        db.session.flush()
        append_audit_event(
            db.session,
            action="feedback.created",
            resource_type=target_type,
            resource_id=target_id,
            dossier_id=dossier_id,
            result="success",
        )
        db.session.commit()
        return _serialize(row), 201
    except (
        TypeError,
        ValueError,
        DomainValidationError,
        ResourceNotFound,
        IntegrityError,
    ) as error:
        db.session.rollback()
        return problem_response(422, detail=str(error), code="domain_validation")


@bp.get("/dossiers/<uuid:dossier_id>/feedback")
@require_permission("dossier.read")
def feedback_list(dossier_id: uuid.UUID) -> Any:
    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    try:
        return _model_page(Feedback, criteria=(Feedback.dossier_id == dossier_id,))
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/dossiers/<uuid:dossier_id>/living-summary")
@require_permission("dossier.read")
def living_summary_get(dossier_id: uuid.UUID) -> Any:
    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    row = db.session.scalar(select(LivingSummary).where(LivingSummary.dossier_id == dossier_id))
    if row is None:
        return problem_response(404, detail="Resumen no encontrado.", code="not_found")
    return _serialize(row)


@bp.put("/dossiers/<uuid:dossier_id>/living-summary")
@require_permission("dossier.write")
def living_summary_put(dossier_id: uuid.UUID) -> Any:
    dossier = _dossier_or_404(dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    if dossier.status == "archived":
        return _domain_error(DomainValidationError("Un expediente archivado es de solo lectura."))
    payload = _payload()
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return _domain_error(DomainValidationError("summary debe ser un objeto."))
    row = db.session.scalar(
        select(LivingSummary).where(LivingSummary.dossier_id == dossier_id).with_for_update()
    )
    if row is None:
        row = LivingSummary(
            tenant_id=g.active_tenant_id,
            dossier_id=dossier_id,
            summary=summary,
            last_refreshed_at=datetime.now().astimezone(),
        )
        db.session.add(row)
        status = 201
    else:
        expected = _expected_version()
        if row.version != expected:
            return _domain_error(VersionConflict("El resumen fue modificado."))
        row.summary = summary
        row.version += 1
        row.last_refreshed_at = datetime.now().astimezone()
        status = 200
    db.session.flush()
    append_audit_event(
        db.session,
        action="living_summary.updated",
        resource_type="living_summary",
        resource_id=row.id,
        dossier_id=dossier_id,
        result="success",
        metadata={"version": row.version},
    )
    db.session.commit()
    return _serialize(row), status, {"ETag": f'W/"{row.version}"'}


@bp.delete("/dossiers/<uuid:dossier_id>/living-summary")
@require_permission("dossier.write")
def living_summary_delete(dossier_id: uuid.UUID) -> Any:
    dossier = _dossier_or_404(dossier_id, write=True)
    if dossier is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    if dossier.status == "archived":
        return _domain_error(DomainValidationError("Un expediente archivado es de solo lectura."))
    row = db.session.scalar(select(LivingSummary).where(LivingSummary.dossier_id == dossier_id))
    if row is None:
        return problem_response(404, detail="Resumen no encontrado.", code="not_found")
    db.session.delete(row)
    append_audit_event(
        db.session,
        action="living_summary.deleted",
        resource_type="living_summary",
        resource_id=row.id,
        dossier_id=dossier_id,
        result="success",
    )
    db.session.commit()
    return "", 204


@bp.get("/dossiers/<uuid:dossier_id>/audit")
@require_permission("audit.read")
def dossier_audit(dossier_id: uuid.UUID) -> Any:
    from opn_oracle.platform.models import AuditEvent

    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    try:
        return _model_page(AuditEvent, criteria=(AuditEvent.dossier_id == dossier_id,))
    except DomainValidationError as error:
        return _domain_error(error)


@bp.get("/dossiers/<uuid:dossier_id>/status-history")
@require_permission("audit.read")
def dossier_status_history(dossier_id: uuid.UUID) -> Any:
    if _dossier_or_404(dossier_id) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    try:
        return _model_page(StatusHistory, criteria=(StatusHistory.dossier_id == dossier_id,))
    except DomainValidationError as error:
        return _domain_error(error)
