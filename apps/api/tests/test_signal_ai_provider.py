from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from opn_oracle.ai.provider import LLMRequest, MockLLMProvider, SignalGovernedLLMProvider
from opn_oracle.ai.schemas import SignalTriageOutput


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
