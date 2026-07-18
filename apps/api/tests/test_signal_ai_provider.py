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
