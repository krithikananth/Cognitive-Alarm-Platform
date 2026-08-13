"""
Tests for AI-backed cognitive challenge generation.

Covers:
- Provider resolution (configured / disabled / missing key / cooldown)
- Prompt construction and model-response parsing
- GeminiChallengeProvider calling the SDK (SDK is mocked — no API key needed)
- ChallengeService actually reaching the AI path and tagging ``source="ai"``
- Deterministic procedural fallback whenever the provider is unavailable,
  fails, or returns unusable content
- End-to-end reachability through GET /api/v1/alarms/{id}/challenge
"""

import sys
import types

import pytest

from app.core.config import settings
from app.models.alarm import ChallengeType
from app.services import ai_challenge_provider as provider_module
from app.services.ai_challenge_provider import (
    AIProviderError,
    GeminiChallengeProvider,
    build_challenge_prompt,
    get_challenge_provider,
    parse_challenge_json,
)
from app.services.challenge_service import ChallengeService


VALID_AI_JSON = (
    '{"prompt": "Which planet is closest to the Sun?", '
    '"answer": "Mercury", '
    '"options": ["Mercury", "Venus", "Mars", "Jupiter"]}'
)


class _StubProvider:
    """Minimal AI provider used to prove the AI path is reachable."""

    name = "stub"
    model_name = "stub-model-1"

    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.calls = []

    def is_available(self):
        return True

    def generate(self, challenge_type, difficulty, *, exclude_prompts=None):
        self.calls.append((challenge_type, difficulty, set(exclude_prompts or [])))
        if self._error is not None:
            raise self._error
        payload = dict(self._payload or {})
        payload.setdefault("type", challenge_type.value.upper())
        return payload


def _quiz_payload(prompt="Which planet is closest to the Sun?"):
    return {
        "prompt": prompt,
        "answer": "Mercury",
        "options": ["Mercury", "Venus", "Mars", "Jupiter"],
    }


@pytest.fixture
def use_stub_provider(monkeypatch):
    """Install a stub AI provider into the challenge generation path."""

    def _install(provider):
        monkeypatch.setattr(
            provider_module, "get_challenge_provider", lambda: provider
        )
        return provider

    return _install


@pytest.fixture
def ai_enabled(monkeypatch):
    """Enable AI generation with a fake key (no network calls are made)."""
    monkeypatch.setattr(settings, "AI_CHALLENGE_ENABLED", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    provider_module.reset_provider_state()
    yield
    provider_module.reset_provider_state()


# ═══════════════════════════════════════════════════════════════
# Provider resolution
# ═══════════════════════════════════════════════════════════════

class TestProviderResolution:
    def test_no_provider_without_api_key(self, monkeypatch):
        monkeypatch.setattr(settings, "AI_CHALLENGE_ENABLED", True)
        monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
        provider_module.reset_provider_state()
        assert get_challenge_provider() is None

    def test_no_provider_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "AI_CHALLENGE_ENABLED", False)
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
        provider_module.reset_provider_state()
        assert get_challenge_provider() is None

    def test_provider_returned_when_configured(self, ai_enabled):
        provider = get_challenge_provider()
        assert isinstance(provider, GeminiChallengeProvider)
        assert provider.model_name == settings.AI_CHALLENGE_MODEL
        assert provider.is_available() is True

    def test_failure_trips_cooldown(self, ai_enabled):
        assert get_challenge_provider() is not None
        provider_module.note_provider_failure()
        assert provider_module.in_cooldown() is True
        assert get_challenge_provider() is None
        provider_module.reset_provider_state()
        assert get_challenge_provider() is not None

    def test_zero_cooldown_setting_does_not_suppress(self, ai_enabled, monkeypatch):
        monkeypatch.setattr(settings, "AI_CHALLENGE_COOLDOWN_SECONDS", 0)
        provider_module.note_provider_failure()
        assert get_challenge_provider() is not None


# ═══════════════════════════════════════════════════════════════
# Prompt construction / response parsing
# ═══════════════════════════════════════════════════════════════

class TestPromptAndParsing:
    def test_prompt_includes_type_and_difficulty(self):
        text = build_challenge_prompt(ChallengeType.RIDDLE, "hard")
        assert "RIDDLE" in text
        assert "hard" in text
        assert "JSON" in text

    def test_prompt_lists_recent_prompts_to_avoid(self):
        text = build_challenge_prompt(
            ChallengeType.QUIZ, "medium", {"what has keys but no locks?"}
        )
        assert "what has keys but no locks?" in text

    def test_parse_strips_code_fences(self):
        data = parse_challenge_json(f"```json\n{VALID_AI_JSON}\n```")
        assert data["answer"] == "Mercury"
        assert len(data["options"]) == 4

    def test_parse_rejects_non_json(self):
        with pytest.raises(AIProviderError):
            parse_challenge_json("sorry, I cannot do that")

    def test_parse_rejects_missing_keys(self):
        with pytest.raises(AIProviderError):
            parse_challenge_json('{"prompt": "x", "answer": "y"}')

    def test_parse_rejects_non_list_options(self):
        with pytest.raises(AIProviderError):
            parse_challenge_json(
                '{"prompt": "x", "answer": "y", "options": "y"}'
            )


# ═══════════════════════════════════════════════════════════════
# Gemini provider (SDK mocked — no real API key required)
# ═══════════════════════════════════════════════════════════════

def _install_fake_genai(monkeypatch, *, text=VALID_AI_JSON, error=None):
    """Install a fake ``google.generativeai`` module and return a call recorder."""
    recorder = {"configured": None, "model": None, "prompt": None, "options": None}

    class _FakeResponse:
        def __init__(self, payload):
            self.text = payload

    class _FakeModel:
        def __init__(self, model_name):
            recorder["model"] = model_name

        def generate_content(self, prompt, **kwargs):
            recorder["prompt"] = prompt
            recorder["options"] = kwargs.get("request_options")
            if error is not None:
                raise error
            return _FakeResponse(text)

    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda api_key=None: recorder.update({"configured": api_key})
    fake.GenerativeModel = _FakeModel

    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    return recorder


class TestGeminiProvider:
    def test_generate_calls_sdk_and_normalizes_payload(self, monkeypatch):
        recorder = _install_fake_genai(monkeypatch)
        provider = GeminiChallengeProvider("test-key", "gemini-1.5-flash", 4)

        result = provider.generate(
            ChallengeType.QUIZ, "medium", exclude_prompts={"old prompt"}
        )

        assert recorder["configured"] == "test-key"
        assert recorder["model"] == "gemini-1.5-flash"
        assert "QUIZ" in recorder["prompt"]
        assert "old prompt" in recorder["prompt"]
        assert recorder["options"] == {"timeout": 4}
        assert result["type"] == "QUIZ"
        assert result["answer"] == "Mercury"
        assert result["options"] == ["Mercury", "Venus", "Mars", "Jupiter"]

    def test_generate_raises_provider_error_on_sdk_failure(self, monkeypatch):
        _install_fake_genai(monkeypatch, error=RuntimeError("network down"))
        provider = GeminiChallengeProvider("test-key")
        with pytest.raises(AIProviderError):
            provider.generate(ChallengeType.QUIZ, "medium")

    def test_generate_raises_provider_error_on_bad_json(self, monkeypatch):
        _install_fake_genai(monkeypatch, text="not json at all")
        provider = GeminiChallengeProvider("test-key")
        with pytest.raises(AIProviderError):
            provider.generate(ChallengeType.QUIZ, "medium")

    def test_generate_requires_api_key(self):
        with pytest.raises(AIProviderError):
            GeminiChallengeProvider("").generate(ChallengeType.QUIZ, "medium")


# ═══════════════════════════════════════════════════════════════
# ChallengeService → AI path
# ═══════════════════════════════════════════════════════════════

class TestChallengeServiceAIPath:
    def test_gemini_sdk_path_reachable_end_to_end(self, ai_enabled, monkeypatch):
        """No provider stub: ChallengeService → Gemini provider → (mocked) SDK."""
        recorder = _install_fake_genai(monkeypatch)

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, difficulty="medium", current_hour=10
        )

        assert recorder["configured"] == "test-key"
        assert recorder["model"] == settings.AI_CHALLENGE_MODEL
        assert result["source"] == "ai"
        assert result["generator"] == settings.AI_CHALLENGE_MODEL
        assert result["prompt"] == "Which planet is closest to the Sun?"

    def test_gemini_sdk_failure_falls_back_end_to_end(self, ai_enabled, monkeypatch):
        _install_fake_genai(monkeypatch, error=RuntimeError("503 unavailable"))

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, difficulty="medium", current_hour=10
        )

        assert result["source"] == "procedural"
        assert result["type"] == "QUIZ"
        assert result["answer"] in result["options"]

    def test_ai_path_is_reachable_and_tagged(self, ai_enabled, use_stub_provider):
        stub = use_stub_provider(_StubProvider(_quiz_payload()))

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, difficulty="medium", current_hour=10
        )

        assert stub.calls, "AI provider was never invoked"
        assert result["source"] == "ai"
        assert result["ai_generated"] is True
        assert result["generator"] == "stub-model-1"
        assert result["prompt"] == "Which planet is closest to the Sun?"
        assert result["answer"] == "Mercury"
        assert sorted(result["options"]) == sorted(
            ["Mercury", "Venus", "Mars", "Jupiter"]
        )
        assert "_generator" not in result

    def test_ai_receives_resolved_type_and_effective_difficulty(
        self, ai_enabled, use_stub_provider
    ):
        stub = use_stub_provider(_StubProvider(_quiz_payload()))

        result = ChallengeService.generate_challenge(
            ChallengeType.RIDDLE,
            difficulty="hard",
            current_hour=10,
            apply_adaptive_difficulty=False,
        )

        challenge_type, difficulty, _ = stub.calls[0]
        assert challenge_type == ChallengeType.RIDDLE
        assert difficulty == "hard"
        # The served payload is labelled with the requested type, not the
        # model's own idea of the type.
        assert result["type"] == "RIDDLE"
        assert result["difficulty"] == "hard"

    def test_ai_receives_recent_prompts_to_avoid(self, ai_enabled, use_stub_provider):
        stub = use_stub_provider(_StubProvider(_quiz_payload()))

        ChallengeService.generate_challenge(
            ChallengeType.QUIZ,
            difficulty="medium",
            current_hour=10,
            exclude_prompts=["An earlier puzzle"],
        )

        _, _, excluded = stub.calls[0]
        assert "an earlier puzzle" in excluded

    def test_time_of_day_softening_still_applies_to_ai(
        self, ai_enabled, use_stub_provider
    ):
        stub = use_stub_provider(_StubProvider(_quiz_payload()))

        ChallengeService.generate_challenge(
            ChallengeType.QUIZ,
            difficulty="hard",
            current_hour=4,
            apply_adaptive_difficulty=False,
        )

        _, difficulty, _ = stub.calls[0]
        assert difficulty == "easy"  # hard → -2 levels at 04:00

    def test_allow_ai_false_skips_provider(self, ai_enabled, use_stub_provider):
        stub = use_stub_provider(_StubProvider(_quiz_payload()))

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, current_hour=10, allow_ai=False
        )

        assert stub.calls == []
        assert result["source"] == "procedural"
        assert result["ai_generated"] is False

    def test_memory_type_never_uses_ai(self, ai_enabled, use_stub_provider):
        stub = use_stub_provider(_StubProvider(_quiz_payload()))

        result = ChallengeService.generate_challenge(
            ChallengeType.MEMORY, current_hour=10
        )

        assert stub.calls == [], "MEMORY has a typed-sequence UI contract"
        assert result["source"] == "procedural"
        assert result["prompt"].isdigit()
        assert result["options"] is None


class TestChallengeServiceFallback:
    def test_no_provider_falls_back_to_procedural(self, use_stub_provider):
        use_stub_provider(None)

        result = ChallengeService.generate_challenge(
            ChallengeType.MATH, current_hour=10
        )

        assert result["source"] == "procedural"
        assert result["ai_generated"] is False
        assert result["generator"] == "procedural"
        assert result["type"] == "MATH"
        assert len(result["options"]) == 4

    def test_provider_failure_falls_back_and_trips_cooldown(
        self, ai_enabled, use_stub_provider
    ):
        stub = use_stub_provider(
            _StubProvider(error=AIProviderError("gemini unreachable"))
        )

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, current_hour=10
        )

        assert len(stub.calls) == 1, "failed provider must not be retried in-loop"
        assert result["source"] == "procedural"
        assert result["type"] == "QUIZ"
        assert result["answer"] in result["options"]
        assert provider_module.in_cooldown() is True

    def test_unexpected_provider_exception_falls_back(
        self, ai_enabled, use_stub_provider
    ):
        use_stub_provider(_StubProvider(error=RuntimeError("boom")))

        result = ChallengeService.generate_challenge(
            ChallengeType.RIDDLE, current_hour=10
        )

        assert result["source"] == "procedural"
        assert result["type"] == "RIDDLE"

    @pytest.mark.parametrize(
        "bad_payload",
        [
            # Answer missing from the options
            {
                "prompt": "Which planet is closest to the Sun?",
                "answer": "Mercury",
                "options": ["Venus", "Mars", "Jupiter", "Saturn"],
            },
            # Duplicate options
            {
                "prompt": "Which planet is closest to the Sun?",
                "answer": "Mercury",
                "options": ["Mercury", "mercury", "Mars", "Jupiter"],
            },
            # Wrong option count
            {
                "prompt": "Which planet is closest to the Sun?",
                "answer": "Mercury",
                "options": ["Mercury", "Venus"],
            },
            # Empty prompt
            {"prompt": "   ", "answer": "Mercury", "options": ["Mercury"]},
            # Inappropriate content
            {
                "prompt": "How would you kill a process?",
                "answer": "Mercury",
                "options": ["Mercury", "Venus", "Mars", "Jupiter"],
            },
        ],
    )
    def test_invalid_ai_content_is_discarded(
        self, ai_enabled, use_stub_provider, bad_payload
    ):
        use_stub_provider(_StubProvider(bad_payload))

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, current_hour=10
        )

        assert result["source"] == "procedural"
        assert result["prompt"] != bad_payload["prompt"].strip()
        assert result["answer"] in (result["options"] or [result["answer"]])

    def test_duplicate_ai_prompt_is_regenerated(self, ai_enabled, use_stub_provider):
        stub = use_stub_provider(_StubProvider(_quiz_payload("Repeated puzzle?")))

        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ,
            current_hour=10,
            exclude_prompts=["Repeated puzzle?"],
        )

        # AI attempts are capped, then procedural generation takes over.
        assert len(stub.calls) == 2
        assert result["source"] == "procedural"
        assert result["prompt"].lower() != "repeated puzzle?"


# ═══════════════════════════════════════════════════════════════
# End-to-end through the alarm challenge endpoint
# ═══════════════════════════════════════════════════════════════

class TestAIChallengeEndpoint:
    def _create_alarm(self, client, auth_headers):
        res = client.post(
            "/api/v1/alarms/",
            json={
                "title": "AI Alarm",
                "alarm_time": "07:00",
                "challenge_type": "quiz",
                "challenge_count": 1,
            },
            headers=auth_headers,
        )
        assert res.status_code == 201
        return res.json()["id"]

    def test_endpoint_serves_ai_challenge_without_leaking_answer(
        self, client, test_user, auth_headers, db_session, ai_enabled, use_stub_provider
    ):
        use_stub_provider(_StubProvider(_quiz_payload()))
        alarm_id = self._create_alarm(client, auth_headers)

        res = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )

        assert res.status_code == 200
        data = res.json()
        assert data["source"] == "ai"
        assert data["ai_generated"] is True
        assert data["prompt"] == "Which planet is closest to the Sun?"
        assert "answer" not in data

        from app.models.challenge_session import ChallengeSession

        row = (
            db_session.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == test_user.id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        assert row.answer == "Mercury"

    def test_endpoint_falls_back_when_provider_unavailable(
        self, client, test_user, auth_headers, ai_enabled, use_stub_provider
    ):
        use_stub_provider(_StubProvider(error=AIProviderError("offline")))
        alarm_id = self._create_alarm(client, auth_headers)

        res = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )

        assert res.status_code == 200
        data = res.json()
        assert data["source"] == "procedural"
        assert data["ai_generated"] is False
        assert data["prompt"]

    def test_ai_answer_verifies_and_dismisses(
        self, client, test_user, auth_headers, db_session, ai_enabled, use_stub_provider
    ):
        use_stub_provider(_StubProvider(_quiz_payload()))
        alarm_id = self._create_alarm(client, auth_headers)
        challenge = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": "Mercury",
                "time_taken_seconds": 5,
                "challenge_prompt": challenge["prompt"],
                "challenge_difficulty": challenge["difficulty"],
            },
            headers=auth_headers,
        )

        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is True
        assert data["wake_confirmed"] is True

    def test_practice_endpoint_serves_ai_challenge(
        self, client, test_user, auth_headers, ai_enabled, use_stub_provider
    ):
        use_stub_provider(_StubProvider(_quiz_payload()))

        res = client.post(
            "/api/v1/alarms/challenge/practice",
            json={"challenge_type": "quiz", "difficulty": "medium"},
            headers=auth_headers,
        )

        assert res.status_code == 200
        data = res.json()
        assert data["source"] == "ai"
        assert data["mode"] == "practice"
        assert "answer" not in data
