"""Versioned, tenant-neutral starting points for strategic dossiers.

These profiles create editable working context only.  They never create a
Signal monitor or make external calls: activating a monitor needs an explicit
tenant-scoped integration connection and user review.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StarterProfile:
    objective_title: str
    objective_focus: str
    hypotheses: tuple[tuple[str, str], ...]
    source_types: tuple[str, ...]


STARTER_PROFILE_VERSION = "v1"

STARTER_PROFILES: dict[str, StarterProfile] = {
    "project": StarterProfile(
        "Asegurar el avance del proyecto",
        "Definir los hitos, dependencias, actores y decisiones necesarias para avanzar.",
        (
            ("El alcance y los hitos actuales son viables.", "Validar con fuentes y responsables."),
            (
                "Existe una siguiente acción prioritaria que puede desbloquear el avance.",
                "Contrastar señales, riesgos y oportunidades.",
            ),
        ),
        (
            "company_signal",
            "market_signal",
            "official_publication",
            "opportunity_signal",
            "risk_signal",
        ),
    ),
    "market": StarterProfile(
        "Entender la evolución del mercado objetivo",
        "Identificar demanda, competidores, barreras de entrada y movimientos relevantes.",
        (
            (
                "El mercado presenta una oportunidad relevante para la organización.",
                "Validar tamaño, evolución y encaje estratégico.",
            ),
            (
                "Los cambios competitivos o regulatorios pueden alterar el momento de entrada.",
                "Contrastar fuentes de mercado y publicaciones oficiales.",
            ),
        ),
        ("market_signal", "company_signal", "news", "regulatory_signal", "official_publication"),
    ),
    "strategic_account": StarterProfile(
        "Desarrollar la cuenta estratégica",
        "Comprender prioridades, actores, iniciativas y oportunidades de relación con la cuenta.",
        (
            (
                "La cuenta tiene una necesidad o iniciativa alineada con nuestra propuesta.",
                "Validar mediante señales públicas y contexto relacional autorizado.",
            ),
            (
                "Existe una vía de relación que puede acelerar una conversación relevante.",
                "Contrastar actores, interacciones y prioridades declaradas.",
            ),
        ),
        (
            "company_signal",
            "relationship_signal",
            "news",
            "opportunity_signal",
            "official_publication",
        ),
    ),
    "tender_or_grant": StarterProfile(
        "Preparar una respuesta competitiva y conforme",
        "Controlar requisitos, plazos, adjudicadores, aliados y evidencias necesarias.",
        (
            (
                "Cumplimos los requisitos de elegibilidad y solvencia.",
                "Comprobar bases, anexos y criterios oficiales.",
            ),
            (
                "La propuesta puede diferenciarse de forma demostrable.",
                "Contrastar criterios de valoración, capacidades y alianzas.",
            ),
        ),
        (
            "tender_or_grant",
            "official_publication",
            "company_signal",
            "relationship_signal",
            "risk_signal",
        ),
    ),
    "partnership": StarterProfile(
        "Validar y estructurar la alianza",
        "Evaluar el encaje estratégico, las complementariedades y las condiciones de colaboración.",
        (
            (
                "Las capacidades de las partes son complementarias.",
                "Validar propuesta de valor, referencias y alcance.",
            ),
            (
                "Existe un modelo de colaboración viable para ambas partes.",
                "Contrastar incentivos, riesgos y decisiones necesarias.",
            ),
        ),
        ("company_signal", "relationship_signal", "news", "opportunity_signal", "risk_signal"),
    ),
    "regulatory_affair": StarterProfile(
        "Anticipar y gestionar el impacto regulatorio",
        "Seguir normas, consultas, organismos, plazos y obligaciones que afectan al asunto.",
        (
            (
                "El cambio regulatorio tendrá un impacto material en la estrategia.",
                "Validar alcance, calendario y aplicabilidad.",
            ),
            (
                "Existe una acción de posicionamiento o adaptación que debe prepararse.",
                "Contrastar consultas, guías y decisiones del regulador.",
            ),
        ),
        ("regulatory_signal", "official_publication", "news", "risk_signal", "relationship_signal"),
    ),
    "competitive_intelligence": StarterProfile(
        "Entender y anticipar el movimiento competitivo",
        "Comparar capacidades, compradores y contratación para decidir dónde actuar.",
        (
            (
                "Los competidores priorizados muestran patrones de adjudicación relevantes.",
                "Contrastar adjudicaciones, compradores, CPV, importes y evolución temporal.",
            ),
            (
                "Existe una diferenciación defendible para competir o colaborar.",
                "Validar capacidades, evidencias, socios y criterios de participación.",
            ),
        ),
        ("company_signal", "market_signal", "tender_or_grant", "official_publication"),
    ),
    "custom": StarterProfile(
        "Aclarar la prioridad estratégica",
        "Delimitar el contexto, los actores, la evidencia disponible y la siguiente decisión.",
        (
            (
                "El expediente responde a una prioridad estratégica concreta.",
                "Definir el resultado esperado y cómo se medirá.",
            ),
            (
                "La información disponible permite decidir la siguiente acción.",
                "Identificar vacíos de evidencia y responsables.",
            ),
        ),
        ("news", "official_publication", "company_signal", "market_signal", "risk_signal"),
    ),
}

# These values are accepted by the API even though they are not exposed by the
# first creation dialog. Keeping a neutral fallback avoids silently omitting a
# starting point when a dossier is created through the API or AI intake.
for _type in ("technology", "investment", "product_launch", "risk_watch"):
    STARTER_PROFILES[_type] = STARTER_PROFILES["custom"]


def starter_profile_for(dossier_type: str) -> StarterProfile:
    return STARTER_PROFILES.get(dossier_type, STARTER_PROFILES["custom"])
