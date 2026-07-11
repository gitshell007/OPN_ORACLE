"""Deterministic synthetic Oracle demo seed."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import click
from flask import Flask, current_app
from sqlalchemy import select

from opn_oracle.extensions import db
from opn_oracle.oracle.models import (
    Actor,
    Decision,
    DossierActor,
    DossierObjective,
    DossierSignal,
    Hypothesis,
    Insight,
    Meeting,
    Opportunity,
    RiskItem,
    ScoreHistory,
    Signal,
    StrategicDossier,
    Task,
    Watchlist,
)
from opn_oracle.oracle.scoring import (
    score_actor_priority,
    score_opportunity,
    score_risk,
    score_signal,
)
from opn_oracle.platform.models import Tenant, Workspace
from opn_oracle.tenants.context import TenantContext, tenant_context

SEED_NAMESPACE = uuid.UUID("342684bc-6b48-5b2c-9360-7a95a84fbca1")
FIXED_DATE = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
DOSSIERS = (
    ("expansion-regional", "Expansión regional", "market"),
    ("alianza-tecnologica", "Alianza tecnológica", "partnership"),
    ("convocatoria-innovacion", "Convocatoria de innovación", "tender_or_grant"),
    ("cuenta-estrategica", "Cuenta estratégica ficticia", "strategic_account"),
    ("lanzamiento-producto", "Lanzamiento de producto", "product_launch"),
    ("inversion-capacidad", "Inversión en capacidad", "investment"),
    ("vigilancia-regulatoria", "Vigilancia regulatoria", "regulatory_affair"),
    ("tecnologia-emergente", "Tecnología emergente", "technology"),
)


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, name)


def register_oracle_cli(app: Flask) -> None:
    @app.cli.command("seed-oracle-demo")
    @click.option("--tenant-id", type=click.UUID, required=True)
    @click.option("--allow-production", is_flag=True)
    def seed_oracle_demo(tenant_id: uuid.UUID, allow_production: bool) -> None:
        """Seed eight neutral synthetic dossiers idempotently."""

        if current_app.config["APP_ENV"] == "production" and not allow_production:
            raise click.ClickException("Producción exige --allow-production explícito.")
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            tenant = db.session.get(Tenant, tenant_id)
            workspace = db.session.scalar(
                select(Workspace).where(
                    Workspace.tenant_id == tenant_id,
                    Workspace.is_default.is_(True),
                )
            )
            if tenant is None or workspace is None:
                raise click.ClickException("Tenant o workspace principal no encontrado.")
            shared_signal = Signal(
                id=stable_id(f"{tenant_id}:shared-signal"),
                tenant_id=tenant_id,
                provider="synthetic",
                external_id="shared-market-shift",
                title="Cambio transversal en prioridades de inversión",
                summary="Una fuente sintética indica un cambio que afecta a varios expedientes.",
                source_type="synthetic_report",
                source_name="Observatorio Sintético",
                published_at=FIXED_DATE,
                ingested_at=FIXED_DATE,
                language="es",
                raw_hash=hashlib.sha256(b"shared-market-shift").digest(),
                credibility=75,
                raw_payload={"synthetic_data": True},
            )
            if db.session.get(Signal, shared_signal.id) is None:
                db.session.add(shared_signal)
            for index, (key, title, dossier_type) in enumerate(DOSSIERS):
                dossier_id = stable_id(f"{tenant_id}:dossier:{key}")
                dossier = db.session.get(StrategicDossier, dossier_id)
                if dossier is None:
                    dossier = StrategicDossier(
                        id=dossier_id,
                        tenant_id=tenant_id,
                        workspace_id=workspace.id,
                        title=title,
                        description=f"Expediente sintético para evaluar {title.lower()}.",
                        dossier_type=dossier_type,
                        status="active",
                        strategic_goal=(
                            "Convertir señales verificables en una siguiente acción concreta."
                        ),
                        geography=["Europa"],
                        sectors=["configurable"],
                        languages=["es"],
                        synthetic_data=True,
                        created_at=FIXED_DATE,
                        updated_at=FIXED_DATE,
                    )
                    db.session.add(dossier)
                    db.session.flush()
                objective_id = stable_id(f"{tenant_id}:objective:{key}")
                if db.session.get(DossierObjective, objective_id) is None:
                    db.session.add(
                        DossierObjective(
                            id=objective_id,
                            tenant_id=tenant_id,
                            dossier_id=dossier_id,
                            title="Validar oportunidad y siguiente acción",
                            priority="high",
                            position=0,
                        )
                    )
                hypothesis_id = stable_id(f"{tenant_id}:hypothesis:{key}")
                if db.session.get(Hypothesis, hypothesis_id) is None:
                    db.session.add(
                        Hypothesis(
                            id=hypothesis_id,
                            tenant_id=tenant_id,
                            dossier_id=dossier_id,
                            statement="La señal justifica una acción de validación.",
                            rationale="Hipótesis sintética y verificable.",
                            position=0,
                        )
                    )
                watchlist_id = stable_id(f"{tenant_id}:watchlist:{key}")
                if db.session.get(Watchlist, watchlist_id) is None:
                    db.session.add(
                        Watchlist(
                            id=watchlist_id,
                            tenant_id=tenant_id,
                            dossier_id=dossier_id,
                            name="Seguimiento sintético",
                            query_config={"synthetic_data": True, "keywords": [key]},
                        )
                    )
                link_id = stable_id(f"{tenant_id}:link:{key}")
                if db.session.get(DossierSignal, link_id) is None:
                    signal_score = score_signal(
                        {
                            "relevance": 70 + index,
                            "novelty": 65,
                            "confidence": 75,
                            "strategic_impact": 72,
                            "source_credibility": 75,
                        }
                    )
                    db.session.add(
                        DossierSignal(
                            id=link_id,
                            tenant_id=tenant_id,
                            dossier_id=dossier_id,
                            signal_id=shared_signal.id,
                            status="reviewed",
                            relevance=70 + index,
                            novelty=65,
                            confidence=75,
                            strategic_impact=72,
                            overall_score=signal_score.score,
                            score_details=signal_score.as_dict(),
                            why_it_matters=(
                                "Puede modificar la prioridad y el calendario del expediente."
                            ),
                            recommended_action="Contrastar la señal con dos fuentes adicionales.",
                            reviewed_at=FIXED_DATE,
                        )
                    )
                actor_id = stable_id(f"{tenant_id}:actor:{key}")
                if db.session.get(Actor, actor_id) is None:
                    db.session.add(
                        Actor(
                            id=actor_id,
                            tenant_id=tenant_id,
                            actor_type="organization",
                            canonical_name=f"Entidad Sintética {index + 1}",
                            canonical_key=f"entidad-sintetica-{index + 1}",
                            actor_metadata={"synthetic_data": True},
                        )
                    )
                dossier_actor_id = stable_id(f"{tenant_id}:dossier-actor:{key}")
                if db.session.get(DossierActor, dossier_actor_id) is None:
                    actor_components = {
                        "influence": 60,
                        "relevance_to_dossier": 70,
                        "relationship_strength": 50,
                        "accessibility": 55,
                        "strategic_alignment": 65,
                        "recent_activity": 50,
                    }
                    actor_score = score_actor_priority(actor_components)
                    db.session.add(
                        DossierActor(
                            id=dossier_actor_id,
                            tenant_id=tenant_id,
                            dossier_id=dossier_id,
                            actor_id=actor_id,
                            roles=["aliado"],
                            priority=actor_score.score,
                            score_details=actor_score.as_dict(),
                            **actor_components,
                        )
                    )
                if index % 2 == 0:
                    opportunity_id = stable_id(f"{tenant_id}:opportunity:{key}")
                    components = {
                        "strategic_fit": 75,
                        "urgency": 60,
                        "expected_value": 70,
                        "actionability": 65,
                        "relationship_leverage": 55,
                        "timing": 60,
                        "confidence": 70,
                        "effort": 35,
                        "blocking_risk": 25,
                    }
                    score = score_opportunity(components, calculated_at=FIXED_DATE)
                    if db.session.get(Opportunity, opportunity_id) is None:
                        db.session.add(
                            Opportunity(
                                id=opportunity_id,
                                tenant_id=tenant_id,
                                dossier_id=dossier_id,
                                title=f"Oportunidad de {title.lower()}",
                                overall_score=score.score,
                                score_details=score.as_dict(),
                                **components,
                            )
                        )
                    score_id = stable_id(f"{tenant_id}:score:opportunity:{key}")
                    if db.session.get(ScoreHistory, score_id) is None:
                        db.session.add(
                            ScoreHistory(
                                id=score_id,
                                tenant_id=tenant_id,
                                dossier_id=dossier_id,
                                resource_type="opportunity",
                                resource_id=opportunity_id,
                                score=score.score,
                                algorithm_version=score.algorithm_version,
                                details=score.as_dict(),
                            )
                        )
                else:
                    risk_id = stable_id(f"{tenant_id}:risk:{key}")
                    components = {
                        "impact": 65,
                        "likelihood": 55,
                        "velocity": 50,
                        "exposure": 45,
                        "uncertainty": 40,
                        "controllability": 60,
                    }
                    score = score_risk(components, calculated_at=FIXED_DATE)
                    if db.session.get(RiskItem, risk_id) is None:
                        db.session.add(
                            RiskItem(
                                id=risk_id,
                                tenant_id=tenant_id,
                                dossier_id=dossier_id,
                                title=f"Riesgo de {title.lower()}",
                                confidence=70,
                                overall_score=score.score,
                                score_details=score.as_dict(),
                                **components,
                            )
                        )
                    score_id = stable_id(f"{tenant_id}:score:risk:{key}")
                    if db.session.get(ScoreHistory, score_id) is None:
                        db.session.add(
                            ScoreHistory(
                                id=score_id,
                                tenant_id=tenant_id,
                                dossier_id=dossier_id,
                                resource_type="risk",
                                resource_id=risk_id,
                                score=score.score,
                                algorithm_version=score.algorithm_version,
                                details=score.as_dict(),
                            )
                        )
                graph_resources = (
                    (
                        Meeting,
                        stable_id(f"{tenant_id}:meeting:{key}"),
                        {
                            "title": "Reunión sintética de validación",
                            "status": "planned",
                            "objective": "Validar hechos y siguiente acción.",
                        },
                    ),
                    (
                        Decision,
                        stable_id(f"{tenant_id}:decision:{key}"),
                        {
                            "title": "Decisión sintética pendiente",
                            "status": "proposed",
                            "rationale": "Pendiente de evidencia adicional.",
                        },
                    ),
                    (
                        Task,
                        stable_id(f"{tenant_id}:task:{key}"),
                        {"title": "Contrastar señal", "status": "open", "priority": "high"},
                    ),
                    (
                        Insight,
                        stable_id(f"{tenant_id}:insight:{key}"),
                        {
                            "title": "Insight sintético",
                            "status": "draft",
                            "insight_type": "opportunity",
                            "facts": ["Dato sintético"],
                            "inferences": ["Inferencia sintética"],
                        },
                    ),
                )
                for model, resource_id, values in graph_resources:
                    if db.session.get(model, resource_id) is None:
                        db.session.add(
                            model(
                                id=resource_id,
                                tenant_id=tenant_id,
                                dossier_id=dossier_id,
                                **values,
                            )
                        )
            db.session.commit()
        click.echo("Seed sintético Oracle listo: 8 expedientes, 1 señal, 8 actores y 80 hijos.")
