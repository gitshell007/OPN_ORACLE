"""SV2-PROSA · pulido opcional de prosa del borrador (coste 0, ollama_titan).

Reescribe SOLO ``our_response_draft`` (semillas) y el párrafo del ``statement``.
Nunca toca requirement, gaps, checklist, cifras ni citas de forma intencional;
un post-check determinista descarta cualquier pulido que invente tokens
protegidos o elimine la etiqueta ``[borrador declarado — no es hecho]``.

Task gobernada: ``draft_prose_polish`` vía Signal ``/ai/run`` (consumer oracle).
Timeout corto por sección; si el LLM falla → fallback silencioso a la semilla.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import Field

from opn_oracle.ai.draft_offer import _PROSE_ENGINE, _RESPONSE_TAG
from opn_oracle.ai.schemas import StrictModel

logger = logging.getLogger(__name__)

_TASK_KEY = "draft_prose_polish"
_SECTION_TIMEOUT_S = 25.0
_MAX_SECTIONS_TO_POLISH = 6

# Tokens protegidos: números/importes/fechas/siglas (F.2, F.3, CPV, €) presentes
# en el texto pulido deben existir ya en la semilla original.
_PROTECTED_TOKEN_RE = re.compile(
    r"(?:"
    r"F\.\s*[23]"  # F.2 / F.3
    r"|CPV"
    r"|€"
    r"|\bEUR\b"
    r"|\b\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\b"  # 1.471.410 / 1 471 410
    r"|\b\d+[.,]\d+\b"  # 1,5 / 5.45
    r"|\b\d{4}-\d{2}-\d{2}\b"  # ISO date
    r"|\b\d{8}\b"  # CPV codes
    r"|\b\d{4,}\b"  # long numbers (years of 4 digits ok if in seed)
    r")",
    re.IGNORECASE,
)

_SYSTEM_POLISH = (
    "Eres redactor comercial senior de licitaciones públicas en España. "
    "Reescribes SOLO el tono de un párrafo semilla de borrador de oferta para "
    "que suene natural a un director comercial, sin inventar datos.\n"
    "REGLAS DURAS:\n"
    "1) Conserva literalmente la etiqueta "
    f"«{_RESPONSE_TAG}» al inicio (o reinsertala si se pierde).\n"
    "2) No inventes números, importes, fechas, códigos CPV, siglas F.2/F.3 "
    "ni cifras que no estén en el texto original.\n"
    "3) No cambies hechos: solo estilo (más fluido, menos robótico).\n"
    "4) No añadas promesas, certificaciones ni resultados.\n"
    "5) Devuelve exclusivamente JSON con la clave polished_text."
)


class DraftProsePolishOutput(StrictModel):
    """Respuesta mínima del task draft_prose_polish (una sección)."""

    polished_text: str = Field(min_length=1, max_length=2000)


class DraftProseSectionItem(StrictModel):
    key: str = Field(min_length=1, max_length=80)
    polished_text: str = Field(min_length=1, max_length=2000)


class DraftProseBatchOutput(StrictModel):
    """Pulido en un solo round-trip (semillas + statement)."""

    sections: list[DraftProseSectionItem] = Field(default_factory=list)
    statement: str | None = Field(default=None, max_length=4000)


class _StructuredProvider(Protocol):
    def generate_structured(self, request: Any, schema: type[Any]) -> Any: ...


PolishFn = Callable[[str, str], str]
"""(section_key_or_statement, seed_text) -> polished_text"""


def extract_protected_tokens(text: str) -> set[str]:
    """Extrae tokens protegidos normalizados (casefold, sin espacios internos F.X)."""

    found: set[str] = set()
    for match in _PROTECTED_TOKEN_RE.finditer(text or ""):
        token = match.group(0)
        # Normaliza F.2 / F. 2 → f.2
        compact = re.sub(r"\s+", "", token).casefold()
        found.add(compact)
    return found


def validate_prose_polish(seed: str, polished: str) -> tuple[bool, str]:
    """Post-check anti-invención. True si el pulido es seguro.

    Razones de rechazo (``prose_polish_reason``):
    - ``missing_draft_label``: desaparece la etiqueta de borrador.
    - ``invented_tokens``: números/siglas/€ nuevos.
    - ``empty``: texto vacío.
    """

    seed_text = str(seed or "").strip()
    polished_text = str(polished or "").strip()
    if not polished_text:
        return False, "empty"
    if not seed_text:
        return False, "empty"

    # Etiqueta obligatoria: literal o fragmentos «borrador declarado» + «no es hecho».
    has_literal = _RESPONSE_TAG in polished_text
    has_soft = (
        "borrador declarado" in polished_text.casefold()
        and "no es hecho" in polished_text.casefold()
    )
    if not (has_literal or has_soft):
        return False, "missing_draft_label"

    seed_tokens = extract_protected_tokens(seed_text)
    polished_tokens = extract_protected_tokens(polished_text)
    invented = sorted(polished_tokens - seed_tokens)
    if invented:
        preview = ",".join(invented[:8])
        return False, f"invented_tokens:{preview}"

    return True, "ok"


def _ensure_draft_label(text: str) -> str:
    body = str(text or "").strip()
    if not body:
        return f"{_RESPONSE_TAG} "
    if _RESPONSE_TAG in body:
        return body
    if "borrador declarado" in body.casefold() and "no es hecho" in body.casefold():
        return body
    return f"{_RESPONSE_TAG} {body}"


def polish_text_with_guardrail(
    seed: str,
    polished_candidate: str,
) -> tuple[str, bool, str]:
    """Aplica guardarraíl: devuelve (texto_final, polished?, reason)."""

    seed_text = str(seed or "").strip()
    candidate = _ensure_draft_label(str(polished_candidate or "").strip())
    ok, reason = validate_prose_polish(seed_text, candidate)
    if ok:
        return candidate[:2000], True, reason
    return seed_text, False, reason


def _batch_llm_polish(
    provider: _StructuredProvider,
    *,
    sections: list[tuple[str, str]],
    statement: str,
    max_output_tokens: int = 2800,
) -> DraftProseBatchOutput:
    """Un solo round-trip Signal (task_key draft_prose_polish)."""

    from opn_oracle.ai.provider import LLMRequest

    payload_sections = [{"key": key, "seed": seed[:1800]} for key, seed in sections if seed]
    task_prompt = (
        "Reescribe con prosa natural de director comercial los siguientes textos "
        "de un borrador de oferta. Conserva en cada semilla la etiqueta "
        f"«{_RESPONSE_TAG}» y todos los datos (F.2, F.3, CPV, €, fechas, cifras). "
        "No inventes nada. Devuelve JSON con:\n"
        "- sections: lista de {key, polished_text}\n"
        "- statement: párrafo de statement pulido (sin inventar cifras)\n\n"
        f"SEEDS JSON:\n{payload_sections!r}\n\n"
        f"STATEMENT ORIGINAL:\n{statement[:3500]}"
    )

    def _run(task_key: str) -> DraftProseBatchOutput:
        request = LLMRequest(
            agent=task_key,
            model="qwen3.6:27b",
            system_prompt=_SYSTEM_POLISH,
            task_prompt=task_prompt,
            context={
                "draft_prose_polish": _PROSE_ENGINE,
                "allowed_evidence_ids": [],
            },
            max_output_tokens=max_output_tokens,
            classification="internal",
        )
        result = provider.generate_structured(request, DraftProseBatchOutput)
        output = result.output
        if isinstance(output, DraftProseBatchOutput):
            return output
        if isinstance(output, dict):
            return DraftProseBatchOutput.model_validate(output)
        return DraftProseBatchOutput.model_validate(
            {
                "sections": getattr(output, "sections", []) or [],
                "statement": getattr(output, "statement", None),
            }
        )

    # Cadena: draft_prose_polish → opportunity (autorizada en vivo) →
    # tender_summary. Mismo /ai/run, ollama_titan, coste 0. Engine=sv2_prosa_v1.
    last_exc: Exception | None = None
    for task_key in (_TASK_KEY, "opportunity", "tender_summary"):
        try:
            if task_key != _TASK_KEY:
                logger.info("draft_prose_polish fallback task_key=%s", task_key)
            return _run(task_key)
        except Exception as exc:
            last_exc = exc
            msg = str(exc).casefold()
            if (
                "task_not_allowed" in msg
                or "no está autorizada" in msg
                or "no esta autorizada" in msg
                or "aiunavailable" in type(exc).__name__.casefold()
            ):
                continue
            raise
    assert last_exc is not None
    raise last_exc


def polish_draft_offer_prose(
    draft: Any,
    *,
    provider: _StructuredProvider | None = None,
    polish_fn: PolishFn | None = None,
    max_sections: int = _MAX_SECTIONS_TO_POLISH,
) -> dict[str, Any]:
    """Pule semillas y statement del borrador; fallback silencioso por sección.

    - ``polish_fn``: inyectable en tests (evita red) — una llamada por key.
    - ``provider``: Signal/Ollama real vía ``generate_structured`` (1 batch).
    Si ambos son None, no hace nada (semillas intactas, ``prose_polished=false``).
    """

    if not isinstance(draft, dict):
        return {}
    result = dict(draft)
    result["prose_engine"] = _PROSE_ENGINE

    # Preparar secciones y semillas.
    prepared: list[dict[str, Any]] = []
    seeds_for_batch: list[tuple[str, str]] = []
    for idx, sec in enumerate(result.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        sec_out = dict(sec)
        seed = str(sec_out.get("our_response_seed") or sec_out.get("our_response_draft") or "")
        if seed and not sec_out.get("our_response_seed"):
            sec_out["our_response_seed"] = seed
        key = str(sec_out.get("key") or f"section_{idx}")
        sec_out["_polish_key"] = key
        sec_out["_polish_seed"] = seed
        if seed and idx < max_sections:
            seeds_for_batch.append((key, seed))
        prepared.append(sec_out)

    statement_seed = str(result.get("statement_seed") or result.get("statement") or "")
    if statement_seed and not result.get("statement_seed"):
        result["statement_seed"] = statement_seed

    can_polish = polish_fn is not None or provider is not None
    polished_count = 0
    polished_by_key: dict[str, str] = {}
    statement_candidate: str | None = None
    batch_error: str | None = None

    if can_polish and seeds_for_batch:
        try:
            if polish_fn is not None:
                for key, seed in seeds_for_batch:
                    polished_by_key[key] = polish_fn(key, seed)
                if statement_seed:
                    statement_candidate = polish_fn("statement", statement_seed)
            elif provider is not None:
                batch = _batch_llm_polish(
                    provider,
                    sections=seeds_for_batch,
                    statement=statement_seed,
                )
                for item in batch.sections or []:
                    polished_by_key[str(item.key)] = str(item.polished_text or "")
                if batch.statement:
                    statement_candidate = str(batch.statement)
        except Exception as exc:
            batch_error = type(exc).__name__
            logger.info("draft_prose_polish batch fallback reason=%s", batch_error)

    sections_out: list[dict[str, Any]] = []
    for sec_out in prepared:
        key = str(sec_out.pop("_polish_key", sec_out.get("key") or ""))
        seed = str(sec_out.pop("_polish_seed", "") or "")
        if not can_polish or not seed:
            sec_out.setdefault("prose_polished", False)
            if not can_polish:
                sec_out.setdefault("prose_polish_reason", "polish_disabled")
            sections_out.append(sec_out)
            continue
        if batch_error and key not in polished_by_key:
            sec_out["our_response_draft"] = seed
            sec_out["prose_polished"] = False
            sec_out["prose_polish_reason"] = f"fallback:{batch_error}"
            sections_out.append(sec_out)
            continue
        candidate = polished_by_key.get(key)
        if not candidate:
            sec_out["our_response_draft"] = seed
            sec_out["prose_polished"] = False
            sec_out["prose_polish_reason"] = "fallback:no_candidate"
            sections_out.append(sec_out)
            continue
        final, ok, reason = polish_text_with_guardrail(seed, candidate)
        sec_out["our_response_draft"] = final
        sec_out["prose_polished"] = ok
        sec_out["prose_polish_reason"] = reason
        if ok:
            polished_count += 1
        sections_out.append(sec_out)

    result["sections"] = sections_out

    # Statement: tokens protegidos (sin etiqueta de semilla).
    if can_polish and statement_seed and statement_candidate:
        seed_tokens = extract_protected_tokens(statement_seed)
        cand_tokens = extract_protected_tokens(statement_candidate)
        invented = cand_tokens - seed_tokens
        if invented or not str(statement_candidate or "").strip():
            result["statement"] = statement_seed
            result["statement_prose_polished"] = False
            result["statement_prose_polish_reason"] = (
                f"invented_tokens:{','.join(sorted(invented)[:8])}" if invented else "empty"
            )
        else:
            result["statement"] = str(statement_candidate).strip()[:4000]
            result["statement_prose_polished"] = True
            result["statement_prose_polish_reason"] = "ok"
            polished_count += 1
    elif can_polish and statement_seed and batch_error:
        result["statement"] = statement_seed
        result["statement_prose_polished"] = False
        result["statement_prose_polish_reason"] = f"fallback:{batch_error}"
    else:
        result.setdefault("statement_prose_polished", False)

    result["prose_polished_count"] = polished_count
    return result
