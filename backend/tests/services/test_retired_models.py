"""Final session 1 (1B): a retired model gives a plain sentence, never a provider's raw 404 (F-564).

A customer who saved a routing policy that names a model the provider has since retired used to see "The AI request
could not be processed as sent." The messages below are what the provider's own SDK raises for a model that does not
exist (the shapes are the providers' documented ones: Google `status: NOT_FOUND`, OpenAI and Azure `model_not_found`,
Anthropic `not_found_error`, Mistral and Groq `model_not_found`).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import byok_providers
from app.schemas.ai_settings import AIProvider

pytestmark = pytest.mark.no_db


def _http_error(status: int, message: str, body: dict | None = None) -> Exception:
    class ProviderError(Exception):
        pass

    exc = ProviderError(message)
    exc.status_code = status  # type: ignore[attr-defined]
    exc.body = body  # type: ignore[attr-defined]
    return exc


GOOGLE_404 = _http_error(
    404,
    "404 NOT_FOUND. {'error': {'code': 404, 'message': 'models/gemini-1.5-pro is not found for API version v1beta, "
    "or is not supported for generateContent.', 'status': 'NOT_FOUND'}}",
)
OPENAI_404 = _http_error(
    404, "Error code: 404 - {'error': {'message': 'The model `gpt-4-0613` does not exist or you do not have access to it.', "
         "'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}}",
)
ANTHROPIC_404 = _http_error(404, "Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', 'message': 'model: claude-2.1'}}")
MISTRAL_404 = _http_error(404, "API error occurred: Status 404. Body: {\"object\":\"error\",\"message\":\"Invalid model: mistral-medium\",\"type\":\"invalid_model\"}")
GROQ_404 = _http_error(404, "Error code: 404 - {'error': {'message': 'The model `llama-3.1-70b` has been decommissioned', 'type': 'invalid_request_error', 'code': 'model_decommissioned'}}")


@pytest.mark.parametrize(
    ("provider", "model", "exc", "vendor"),
    [
        ("gemini", "gemini-1.5-pro", GOOGLE_404, "Google"),
        ("openai", "gpt-4-0613", OPENAI_404, "OpenAI"),
        ("azure_openai", "my-gpt4", OPENAI_404, "Azure OpenAI"),
        ("anthropic", "claude-2.1", ANTHROPIC_404, "Anthropic"),
        ("mistral", "mistral-medium", MISTRAL_404, "Mistral"),
        ("groq", "llama-3.1-70b", GROQ_404, "Groq"),
    ],
)
def test_every_providers_model_not_found_becomes_a_plain_sentence(provider, model, exc, vendor):
    message = byok_providers.model_unavailable_message(provider, model, exc)
    assert message is not None
    assert vendor in message and model in message and "choose another model" in message.lower()
    assert "404" not in message and "NOT_FOUND" not in message and "{" not in message


def test_a_model_we_know_is_retired_says_so_even_before_a_call():
    assert byok_providers.model_unavailable_message("gemini", "gemini-1.5-pro") == (
        "Google retired gemini-1.5-pro; choose another model in AI settings."
    )
    assert "gemini-2.0-flash" in byok_providers.model_unavailable_message("gemini", "gemini-2.0-flash")


def test_other_errors_are_not_mistaken_for_a_retired_model():
    for exc in (_http_error(429, "rate limit exceeded"), _http_error(401, "invalid_api_key"), _http_error(503, "overloaded"),
                ValueError("boom")):
        assert byok_providers.model_unavailable_message("openai", "gpt-5.5", exc) is None


def test_no_suggested_model_is_a_retired_one():
    """A suggestion that errors out is worse than none (F-564)."""
    for key, spec in byok_providers.PROVIDER_REGISTRY.items():
        for model in spec.suggested_models:
            assert byok_providers.model_unavailable_message(key, model) is None, f"{key} suggests the retired {model}"


def test_a_saved_policy_naming_a_retired_model_is_answered_plainly_by_the_call_path(monkeypatch):
    import importlib

    module = importlib.import_module("app.services.llm_service")

    def refuses(*, prompt, temperature, ai_settings, client):
        raise GOOGLE_404

    monkeypatch.setattr(module.llm_service, "_query_gemini", refuses)
    settings_row = SimpleNamespace(provider=AIProvider.GEMINI, model="gemini-1.5-pro", temperature=0.2, max_output_tokens=512,
                                   top_p=1.0, frequency_penalty=0.0, presence_penalty=0.0)
    with pytest.raises(HTTPException) as caught:
        module.llm_service._execute_query(prompt="Hello", temperature=0.2, ai_settings=settings_row, byok_client=object(),
                                          organization_id=uuid.uuid4())
    assert caught.value.status_code == 400
    assert caught.value.detail == "Google retired gemini-1.5-pro; choose another model in AI settings."
