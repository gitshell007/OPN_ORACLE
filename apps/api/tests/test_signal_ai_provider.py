from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from opn_oracle.ai.provider import LLMRequest, MockLLMProvider, SignalGovernedLLMProvider
from opn_oracle.ai.schemas import DossierSituationSummaryOutput, ReportOutput, SignalTriageOutput


def test_signal_governed_provider_uses_the_confirmed_ai_run_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_id = UUID("00000000-0000-4000-8000-000000000001")
    request = LLMRequest(
        agent="signal_triage",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Evalúa la señal.",
        context={"allowed_evidence_ids": [str(evidence_id)]},
        max_output_tokens=500,
        classification="public",
    )
    output = MockLLMProvider("fixture").generate_structured(request, SignalTriageOutput).output

    def post(url: str, **kwargs: object) -> httpx.Response:
        assert url == "https://signal.test/api/v1/ai/run"
        body = kwargs["json"]
        assert isinstance(body, dict)
        assert body["task_key"] == "signal_triage"
        assert body["input"]["format"] == "json"
        request_http = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request_http,
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "fallback_used": False,
                "usage": {"input_tokens": 123, "output_tokens": 45},
                "result": {"message": {"content": output.model_dump_json()}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    result = provider.generate_structured(request, SignalTriageOutput)

    assert result.output == output
    assert (result.provider, result.model, result.cost_micros) == ("ollama", "qwen3.5:9b", 0)


def test_signal_governed_provider_repairs_one_invalid_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_id = UUID("00000000-0000-4000-8000-000000000001")
    request = LLMRequest(
        agent="signal_triage",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Evalúa la señal.",
        context={"allowed_evidence_ids": [str(evidence_id)]},
        max_output_tokens=500,
        classification="public",
    )
    output = MockLLMProvider("fixture").generate_structured(request, SignalTriageOutput).output
    calls = 0

    def post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = kwargs["json"]
        assert isinstance(body, dict)
        if calls == 2:
            messages = body["input"]["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert "reparador de JSON" in messages[0]["content"]
            assert messages[1]["role"] == "user"
            assert "allowed_evidence_ids" not in messages[1]["content"]
            assert "literal_error" in messages[1]["content"]
        content = '{"category": 7}' if calls == 1 else output.model_dump_json()
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "result": {"message": {"content": content}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    result = provider.generate_structured(request, SignalTriageOutput)

    assert result.output == output
    assert calls == 2
    assert (result.input_tokens, result.output_tokens) == (20, 10)


def test_signal_governed_provider_repairs_unauthorized_evidence_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invented_id = UUID("00000000-0000-4000-8000-000000000099")
    request = LLMRequest(
        agent="signal_triage",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Evalúa la señal.",
        context={"allowed_evidence_ids": []},
        max_output_tokens=500,
        classification="public",
    )
    invalid = (
        MockLLMProvider("fixture")
        .generate_structured(
            LLMRequest(
                agent=request.agent,
                model=request.model,
                system_prompt=request.system_prompt,
                task_prompt=request.task_prompt,
                context={"allowed_evidence_ids": [str(invented_id)]},
                max_output_tokens=request.max_output_tokens,
                classification=request.classification,
            ),
            SignalTriageOutput,
        )
        .output
    )
    calls = 0

    def post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = kwargs["json"]
        assert isinstance(body, dict)
        if calls == 2:
            assert "lista está vacía" in body["input"]["messages"][0]["content"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "result": {"message": {"content": invalid.model_dump_json()}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    result = provider.generate_structured(request, SignalTriageOutput)

    assert result.output.facts == []
    assert "citas no autorizadas" in " ".join(result.output.warnings)
    assert calls == 2


def test_signal_governed_provider_uses_safe_summary_after_two_invalid_empty_evidence_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = LLMRequest(
        agent="dossier_situation_summary",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Resume el expediente.",
        context={"allowed_evidence_ids": []},
        max_output_tokens=500,
        classification="internal",
    )
    calls = 0

    def post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "result": {"message": {"content": '{"headline":7}'}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    result = provider.generate_structured(request, DossierSituationSummaryOutput)

    assert result.output.confidence == 0
    assert result.output.facts == []
    assert "fallback seguro" in " ".join(result.output.warnings)
    assert result.safe_fallback_used is True
    assert calls == 2


def test_signal_governed_provider_raises_schema_error_after_failed_repair_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_id = UUID("00000000-0000-4000-8000-000000000001")
    request = LLMRequest(
        agent="signal_triage",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Evalúa la señal.",
        context={"allowed_evidence_ids": [str(evidence_id)]},
        max_output_tokens=500,
        classification="internal",
    )
    calls = 0

    def post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "result": {"message": {"content": '{"category":7}'}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    with pytest.raises(ValueError):
        provider.generate_structured(request, SignalTriageOutput)
    assert calls == 2


def test_signal_governed_provider_never_publishes_model_claims_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = LLMRequest(
        agent="dossier_situation_summary",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Resume el expediente.",
        context={"allowed_evidence_ids": []},
        max_output_tokens=500,
        classification="internal",
    )
    candidate = (
        MockLLMProvider("fixture")
        .generate_structured(request, DossierSituationSummaryOutput)
        .output
    )

    def post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "result": {"message": {"content": candidate.model_dump_json()}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    result = provider.generate_structured(request, DossierSituationSummaryOutput)

    assert result.safe_fallback_used is True
    assert result.output.confidence == 0
    assert result.output.recommended_actions[0].action.startswith("Vincular evidencias")


def test_signal_governed_provider_normalizes_report_writer_shape_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_id = UUID("00000000-0000-4000-8000-000000000001")
    invented_id = UUID("00000000-0000-4000-8000-000000000099")
    request = LLMRequest(
        agent="report_writer",
        model="qwen3.5:9b",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Redacta un informe.",
        context={"allowed_evidence_ids": [str(evidence_id)]},
        max_output_tokens=500,
        classification="internal",
    )
    candidate = {
        "facts": [
            {"statement": "Hecho con cita válida", "evidence_ids": [str(evidence_id)]},
            {"statement": "Hecho sin cita", "evidence_ids": []},
        ],
        "inferences": ["La ventana requiere revisión comercial."],
        "recommendations": [{"action": "Preparar agenda", "priority": "urgent"}],
        "confidence": "82",
        "open_questions": "¿Qué actor decide el siguiente hito?",
        "warnings": [],
        "title": "Informe CATL",
        "executive_summary": "Resumen ejecutivo",
        "sections": [
            {
                "heading": "Objetivo",
                "paragraphs": [
                    {
                        "text": "El proyecto avanza, pero esta frase venía sin cita.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [],
                    },
                    {
                        "text": "Esta cita inventada no puede pasar.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [str(invented_id)],
                    },
                ],
            }
        ],
        "recommended_actions": [{"action": "No debe quedar como dict"}],
        "source_index": [{"evidence_id": str(invented_id), "label": "Inventada", "locator": "x"}],
    }

    def post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "result": {"message": {"content": json.dumps(candidate)}},
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )

    result = provider.generate_structured(request, ReportOutput)

    assert len(result.output.facts) == 1
    assert result.output.facts[0].statement == "Hecho con cita válida"
    assert result.output.facts[0].evidence_ids == [evidence_id]
    assert result.output.recommendations[0].priority == "medium"
    assert result.output.sections[0].paragraphs[0].kind == "inference"
    assert result.output.sections[0].paragraphs[0].evidence_ids == []
    assert result.output.sections[0].paragraphs[1].kind == "inference"
    assert result.output.sections[0].paragraphs[1].evidence_ids == []
    assert result.output.source_index == []


def _dqa_safe_validated(*, answer_text: str = "Respuesta segura sin citas.") -> dict:
    return {
        "answer_text": answer_text,
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 0,
        "open_questions": ["evidencia_autorizada"],
        "warnings": ["empty_allowlist"],
        "citations": [],
        "claims": [],
        "conflicts": [],
        "unknowns": ["evidencia_en_memoria"],
    }


def test_dossier_question_answer_consumes_validated_output_not_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malicious payload.result must not reach the message; only validated_output."""
    from opn_oracle.ai.schemas import DossierQuestionAnswerOutput

    trusted = _dqa_safe_validated(answer_text="Respuesta validada por RT-07.")
    malicious = {
        **trusted,
        "answer_text": "INYECCIÓN maliciosa desde result crudo.",
        "citations": [{"evidence_id": "foreign-evil", "quote": "hack"}],
    }

    def post(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "mock-rt07",
                "model": "mock-dqa",
                "usage": {"input_tokens": 11, "output_tokens": 7},
                "runtime": {
                    "runtime_id": "RT-07",
                    "prompt_sha256": "p" * 64,
                    "schema_sha256": "s" * 64,
                    "schema_version": "dossier_question_answer.v1",
                    "prompt_version": "1.0.0",
                },
                # Raw provider content intentionally differs from validated_output.
                "result": {"message": {"content": json.dumps(malicious)}},
                "validated_output": {
                    **trusted,
                    "citation_count": 0,
                    "schema_version": "dossier_question_answer.v1",
                },
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )
    request = LLMRequest(
        agent="dossier_question_answer",
        model="mock-dqa",
        system_prompt="JSON estricto.",
        task_prompt="Responde.",
        context={"allowed_evidence_ids": []},
        max_output_tokens=500,
        classification="public",
    )
    result = provider.generate_structured(request, DossierQuestionAnswerOutput)
    assert result.output.answer_text == "Respuesta validada por RT-07."
    assert "INYECCIÓN" not in result.output.answer_text
    assert result.output.citations == []
    assert result.validated_output_sha256
    assert len(result.validated_output_sha256) == 64


def test_dossier_question_answer_missing_validated_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opn_oracle.ai.provider import AIUnavailable
    from opn_oracle.ai.schemas import DossierQuestionAnswerOutput

    safe = _dqa_safe_validated()

    def post(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "mock",
                "model": "m",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "result": {"message": {"content": json.dumps(safe)}},
                # validated_output deliberately omitted
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=3
    )
    request = LLMRequest(
        agent="dossier_question_answer",
        model="m",
        system_prompt="s",
        task_prompt="t",
        context={"allowed_evidence_ids": []},
        max_output_tokens=100,
        classification="public",
    )
    with pytest.raises(AIUnavailable, match="validated_output"):
        provider.generate_structured(request, DossierQuestionAnswerOutput)


def test_dossier_question_answer_altered_validated_output_schema_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opn_oracle.ai.provider import AIUnavailable
    from opn_oracle.ai.schemas import DossierQuestionAnswerOutput

    def post(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "provider": "mock",
                "model": "m",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "runtime": {
                    "runtime_id": "RT-07",
                    "prompt_sha256": "p" * 64,
                    "schema_sha256": "s" * 64,
                },
                "result": {"message": {"content": "{}"}},
                "validated_output": {
                    # missing required answer_text / agent fields
                    "answer_text": "",
                    "facts": "not-a-list",
                },
            },
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=3
    )
    request = LLMRequest(
        agent="dossier_question_answer",
        model="m",
        system_prompt="s",
        task_prompt="t",
        context={"allowed_evidence_ids": []},
        max_output_tokens=100,
        classification="public",
    )
    with pytest.raises(AIUnavailable):
        provider.generate_structured(request, DossierQuestionAnswerOutput)


def test_signal_output_parses_all_upstream_shapes() -> None:
    """Signal reenvía la respuesta cruda del proveedor; hay tres formas posibles.

    OpenRouter/OpenAI usa choices[0].message.content; sin esa rama, cambiar la task a
    OpenRouter hacía fallar la lectura pese a un 200 real (regresión del 2026-07-17).
    """
    from opn_oracle.ai.provider import AIUnavailable, _signal_output

    # Ollama chat
    assert _signal_output({"result": {"message": {"content": '{"ok": true}'}}}) == '{"ok": true}'
    # Ollama generate
    assert _signal_output({"result": {"response": '{"ok": true}'}}) == '{"ok": true}'
    # OpenRouter / OpenAI
    openrouter = {"result": {"choices": [{"message": {"content": '{"ok": true}'}}]}}
    assert _signal_output(openrouter) == '{"ok": true}'
    # Sin contenido reconocible → error claro
    import pytest

    with pytest.raises(AIUnavailable):
        _signal_output({"result": {"choices": []}})


def test_stripping_unauthorized_citations_keeps_the_authorized_ones() -> None:
    """La red de seguridad debe depurar citas no autorizadas sin morir en el intento.

    _strip_unauthorized_evidence_blocks vuelca a JSON y revalida. Al hacerlo en modo
    Python sobre contratos strict=True, los evidence_ids supervivientes (ya cadenas)
    se rechazaban con "Input should be an instance of UUID": la red fallaba justo
    cuando actúa, tirando el informe entero en vez de salvarlo. Nunca se vio porque
    hasta ahora los informes no citaban evidencia, o citaban solo la autorizada.
    """
    from opn_oracle.ai.provider import _strip_unauthorized_evidence_blocks

    permitida = UUID("00000000-0000-4000-8000-0000000000aa")
    intrusa = UUID("00000000-0000-4000-8000-0000000000bb")
    output = ReportOutput.model_validate_json(
        json.dumps(
            {
                "title": "Informe",
                "executive_summary": "Resumen.",
                "facts": [],
                "inferences": [],
                "recommendations": [],
                "confidence": 80,
                "open_questions": [],
                "warnings": [],
                "sections": [
                    {
                        "heading": "Hallazgos",
                        "paragraphs": [
                            {
                                "kind": "fact",
                                "text": "Bloque con cita autorizada.",
                                "confidence": 100,
                                "evidence_ids": [str(permitida)],
                            },
                            {
                                "kind": "fact",
                                "text": "Bloque con cita inventada, debe desaparecer.",
                                "confidence": 100,
                                "evidence_ids": [str(intrusa)],
                            },
                        ],
                    }
                ],
            }
        )
    )

    limpio = _strip_unauthorized_evidence_blocks(output, [str(permitida)])

    parrafos = limpio.sections[0].paragraphs
    assert len(parrafos) == 1
    assert parrafos[0].evidence_ids == [permitida]
    assert "inventada" not in parrafos[0].text


def test_merge_allowed_evidence_ids_unions_top_level_and_requested_scope() -> None:
    """SV2-REGRESION-ASK: dual-memory scope must not be dropped when top-level is non-empty.

    Regression: top-level had 1 oracle Evidence id while requested_scope held ~20
    dual-memory ids. Provider used only top-level → Signal allowlist=1, model cited
    dual ids → local _validate_allowed_evidence raised AIUnavailable after HTTP 200.
    """
    from opn_oracle.ai.provider import _merge_allowed_evidence_ids

    top = "b15d77de-2e99-40d2-8087-1eaa79709e3a"
    dual_a = "c030c465-8294-438c-91a7-14b49657f91f"
    dual_b = "49a5073d-6b29-43ec-8dd9-d87deec011b9"
    merged = _merge_allowed_evidence_ids(
        {
            "allowed_evidence_ids": [top, dual_a],
            "requested_scope": {"allowed_evidence_ids": [dual_a, dual_b, ""]},
        }
    )
    assert merged == [top, dual_a, dual_b]


def test_dossier_question_sends_merged_allowlist_to_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Body.allowed_evidence_ids must be the union of top-level + dual scope."""
    from opn_oracle.ai.provider import AIUnavailable
    from opn_oracle.ai.schemas import DossierQuestionAnswerOutput

    top = "b15d77de-2e99-40d2-8087-1eaa79709e3a"
    dual = "c030c465-8294-438c-91a7-14b49657f91f"
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> httpx.Response:
        body = kwargs["json"]
        assert isinstance(body, dict)
        captured["allowed"] = list(body.get("allowed_evidence_ids") or [])
        request_http = httpx.Request("POST", url)
        # Fail after capture; we only assert the outbound allowlist.
        return httpx.Response(500, request=request_http, text="boom")

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=3
    )
    request = LLMRequest(
        agent="dossier_question_answer",
        model="m",
        system_prompt="s",
        task_prompt="t",
        context={
            "allowed_evidence_ids": [top],
            "requested_scope": {"allowed_evidence_ids": [dual]},
        },
        max_output_tokens=100,
        classification="public",
    )
    with pytest.raises(AIUnavailable):
        provider.generate_structured(request, DossierQuestionAnswerOutput)
    assert captured["allowed"] == [top, dual]
