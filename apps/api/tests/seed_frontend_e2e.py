"""Deterministic identities for the disposable frontend E2E database."""

from datetime import UTC, datetime

from opn_oracle import create_app
from opn_oracle.auth.passwords import PasswordHasher, PasswordPolicy
from opn_oracle.extensions import db
from opn_oracle.platform.models import MembershipRole, Tenant, TenantMembership, User, Workspace
from opn_oracle.platform.rbac import seed_system_roles
from opn_oracle.tenants.context import TenantContext, tenant_context

PASSWORD = "Oracle E2E segura 2026"


def seed() -> None:
    app = create_app()
    with app.app_context():
        hasher = PasswordHasher(PasswordPolicy(12, 1024))
        tenant = Tenant(slug="asterion-e2e", name="Asterion E2E", status="active")
        second_tenant = Tenant(slug="boreal-e2e", name="Boreal E2E", status="active")
        owner = User(
            email="owner@oracle-e2e.test",
            display_name="Olivia Owner",
            status="active",
            password_hash=hasher.hash(PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        viewer = User(
            email="viewer@oracle-e2e.test",
            display_name="Víctor Viewer",
            status="active",
            password_hash=hasher.hash(PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        platform = User(
            email="platform@oracle-e2e.test",
            display_name="Paula Plataforma",
            status="active",
            platform_role="super_admin",
            password_hash=hasher.hash(PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        db.session.add_all([tenant, second_tenant, owner, viewer, platform])
        db.session.flush()
        db.session.add(
            Workspace(
                tenant_id=tenant.id,
                slug="principal",
                name="Principal",
                status="active",
                is_default=True,
            )
        )
        db.session.add(
            Workspace(
                tenant_id=second_tenant.id,
                slug="principal",
                name="Principal",
                status="active",
                is_default=True,
            )
        )
        membership = TenantMembership(
            tenant_id=tenant.id, user_id=owner.id, status="active", accepted_at=datetime.now(UTC)
        )
        second_membership = TenantMembership(
            tenant_id=second_tenant.id,
            user_id=owner.id,
            status="active",
            accepted_at=datetime.now(UTC),
        )
        viewer_membership = TenantMembership(
            tenant_id=tenant.id, user_id=viewer.id, status="active", accepted_at=datetime.now(UTC)
        )
        db.session.add_all([membership, second_membership, viewer_membership])
        db.session.flush()
        tenant_id, second_tenant_id, owner_id = tenant.id, second_tenant.id, owner.id
        membership_id, second_membership_id, viewer_membership_id = (
            membership.id,
            second_membership.id,
            viewer_membership.id,
        )
        db.session.commit()
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=owner_id)):
            roles = seed_system_roles(db.session, tenant_id)
            db.session.add(
                MembershipRole(
                    tenant_id=tenant_id, membership_id=membership_id, role_id=roles["owner"].id
                )
            )
            db.session.add(
                MembershipRole(
                    tenant_id=tenant_id,
                    membership_id=viewer_membership_id,
                    role_id=roles["viewer"].id,
                )
            )
            db.session.commit()
        with tenant_context(TenantContext(tenant_id=second_tenant_id, actor_id=owner_id)):
            roles = seed_system_roles(db.session, second_tenant_id)
            db.session.add(
                MembershipRole(
                    tenant_id=second_tenant_id,
                    membership_id=second_membership_id,
                    role_id=roles["owner"].id,
                )
            )
            db.session.commit()

        # G-20-B E2E: market dossier with discovery profile + candidate artifact fixture.
        # Real API/DB seed (no browser network mock). Playwright opens this dossier.
        _seed_g20b_market_actor_fixture(tenant_id=tenant_id, owner_id=owner_id)
        # G-14: opportunity artifacts served by the real API from disposable PostgreSQL.
        _seed_g14_opportunity_fixtures(tenant_id=tenant_id, owner_id=owner_id)


def _seed_g20b_market_actor_fixture(
    *,
    tenant_id,
    owner_id,
) -> None:
    """Insert market dossier + structured candidate artifact for Playwright G-20-B."""

    import hashlib
    import uuid
    from datetime import UTC, datetime

    from opn_oracle.ai.citable_sources import content_checksum, server_owned_candidate_id
    from opn_oracle.ai.models import AIArtifact
    from opn_oracle.oracle.jobs import AIAuditLog
    from opn_oracle.oracle.models import StrategicDossier
    from opn_oracle.platform.models import Workspace
    from opn_oracle.tenants.context import TenantContext, tenant_context

    with tenant_context(
        TenantContext(
            tenant_id=tenant_id,
            actor_id=owner_id,
            platform_access=False,
            access_reason="g20b-e2e-seed",
        )
    ):
        ws = db.session.query(Workspace).filter_by(tenant_id=tenant_id, slug="principal").one()
        dossier = StrategicDossier(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            workspace_id=ws.id,
            title="G-20-B Market actor discovery E2E",
            description="Fixture desechable para Playwright sin page.route",
            dossier_type="market",
            status="active",
            owner_user_id=owner_id,
            profile_config={
                "discovery_intent": ("grupos de investigación en Francia que trabajen en grafeno"),
                "discovery_actor_type": "research_group",
            },
        )
        db.session.add(dossier)
        db.session.flush()

        s1 = str(uuid.uuid5(uuid.NAMESPACE_URL, "g20b-e2e-source-neel"))
        c1 = server_owned_candidate_id(
            execution_key="g20b-e2e", name="Institut Néel", evidence_ids=[s1]
        )
        title = "Institut Néel"
        url = "https://example.test/g20b-e2e/neel"
        snippet = "graphene lab FR"
        reserved = {
            "source_id": s1,
            "title": title,
            "url": url,
            "snippet": snippet,
            "provider": "hal_structure",
            "rank": 1,
            "content_checksum": content_checksum(title=title, snippet=snippet, url=url),
            "origin": "structured",
            "domain": "example.test",
            "label": title,
            "origin_label": "Fuente estructurada",
        }
        digest = hashlib.sha256(b"g20b-e2e-fixture").digest()
        now = datetime.now(UTC)
        audit = AIAuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            dossier_id=dossier.id,
            requested_by_user_id=owner_id,
            use_case="market_actor_discovery",
            agent="market_actor_discovery",
            action="generate",
            provider="mock",
            model="mock-v1",
            prompt_name="market_actor_discovery",
            prompt_version="v1",
            prompt_hash=digest,
            context_hash=digest,
            schema_name="MarketActorDiscoveryOutput",
            schema_version="v1",
            input_hash=digest,
            output_hash=digest,
            source_ids=[],
            status="succeeded",
            data_classification="internal",
            redaction_applied=False,
            redaction_summary={},
            input_tokens=0,
            output_tokens=0,
            actual_cost_micros=0,
            currency="EUR",
            attempt_count=1,
            started_at=now,
            completed_at=now,
            human_review_state="not_required",
        )
        db.session.add(audit)
        db.session.flush()
        artifact = AIArtifact(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            audit_log_id=audit.id,
            dossier_id=dossier.id,
            target_type="market_actor_discovery",
            target_id=dossier.id,
            agent="market_actor_discovery",
            schema_name="MarketActorDiscoveryOutput",
            schema_version="v1",
            status="candidate",
            version=1,
            output={
                "candidates": [
                    {
                        "candidate_id": c1,
                        "actor_type": "research_group",
                        "organization": "Institut Néel",
                        "affiliation": "CNRS",
                        "country": "FR",
                        "summary": "Lab de grafeno (fixture E2E)",
                        "evidence_ids": [s1],
                        "confidence": 85,
                        "ids": {"ror": "04dbzz632", "rnsr": "200717524X"},
                        "identity_status": "validated",
                        "score": 70.0,
                        "score_breakdown": {"identity": 40.0, "country": 10.0},
                        "ranking_reasons": ["identity_validated"],
                        "citable_sources": [
                            {
                                "source_id": s1,
                                "title": title,
                                "url": url,
                                "snippet": snippet,
                                "domain": "example.test",
                                "label": title,
                                "origin": "structured",
                                "origin_label": "Fuente estructurada",
                            }
                        ],
                    }
                ],
                "warnings": [],
                "reserved_citable_sources": [reserved],
            },
            output_hash=digest,
        )
        db.session.add(artifact)
        db.session.commit()


def _seed_g14_opportunity_fixtures(*, tenant_id, owner_id) -> None:
    """Seed fit/no-fit opportunity dossiers for Playwright without ``page.route``."""

    import hashlib
    import json
    import uuid
    from datetime import UTC, datetime
    from pathlib import Path

    from opn_oracle.ai.models import AIArtifact
    from opn_oracle.oracle.jobs import AIAuditLog
    from opn_oracle.oracle.models import StrategicDossier
    from opn_oracle.platform.models import Workspace
    from opn_oracle.tenants.context import TenantContext, tenant_context

    fixtures_dir = Path(__file__).resolve().parents[3] / "tests" / "e2e" / "fixtures"
    fixture_specs = (
        (
            "G-14 Encaje y borrador E2E real",
            fixtures_dir / "sv2-opportunity-fit-draft.json",
        ),
        (
            "G-14 Estado vacío E2E real",
            fixtures_dir / "sv2-opportunity-no-fit.json",
        ),
    )
    with tenant_context(
        TenantContext(
            tenant_id=tenant_id,
            actor_id=owner_id,
            platform_access=False,
            access_reason="g14-e2e-seed",
        )
    ):
        workspace = (
            db.session.query(Workspace).filter_by(tenant_id=tenant_id, slug="principal").one()
        )
        for title, fixture_path in fixture_specs:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            output = dict(fixture["artifact"]["output"])
            dossier = StrategicDossier(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                workspace_id=workspace.id,
                title=title,
                description="Fixture G-14 desechable: API y PostgreSQL reales",
                dossier_type="tender",
                status="active",
                owner_user_id=owner_id,
            )
            db.session.add(dossier)
            db.session.flush()

            digest = hashlib.sha256(
                json.dumps(output, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).digest()
            now = datetime.now(UTC)
            audit = AIAuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                dossier_id=dossier.id,
                requested_by_user_id=owner_id,
                use_case="opportunity",
                agent="opportunity",
                action="generate",
                provider="mock",
                model="mock-v1",
                prompt_name="opportunity",
                prompt_version="v1",
                prompt_hash=digest,
                context_hash=digest,
                schema_name="OpportunityOutput",
                schema_version="v1",
                input_hash=digest,
                output_hash=digest,
                source_ids=[],
                status="succeeded",
                data_classification="internal",
                redaction_applied=False,
                redaction_summary={"e2e_fixture": True},
                input_tokens=0,
                output_tokens=0,
                actual_cost_micros=0,
                currency="EUR",
                attempt_count=1,
                started_at=now,
                completed_at=now,
                human_review_state="not_required",
            )
            db.session.add(audit)
            db.session.flush()
            db.session.add(
                AIArtifact(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    audit_log_id=audit.id,
                    dossier_id=dossier.id,
                    target_type="strategic_dossier",
                    target_id=dossier.id,
                    agent="opportunity",
                    schema_name="OpportunityOutput",
                    schema_version="v1",
                    status="candidate",
                    version=1,
                    output=output,
                    output_hash=digest,
                )
            )
        db.session.commit()


if __name__ == "__main__":
    seed()
