import pytest

from app.config import ConfigError, get_settings


def test_importing_config_without_credentials_does_not_raise():
    # The regression this guards: a missing key used to raise at import time,
    # which made the whole app -- /health included -- fail to start.
    settings = get_settings()
    assert settings.jev_api_key is None
    assert settings.persistence_enabled is False


def test_require_jev_raises_only_when_used():
    with pytest.raises(ConfigError, match="TYPESAFE_API_KEY"):
        get_settings().require_jev()


def test_persistence_needs_url_anon_key_and_jwt_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    get_settings.cache_clear()
    assert get_settings().persistence_enabled is False

    with pytest.raises(ConfigError) as exc:
        get_settings().require_crm()
    # Names every missing setting at once rather than one per attempt.
    assert "SUPABASE_ANON_KEY" in str(exc.value)
    assert "SUPABASE_JWT_SECRET" in str(exc.value)


def test_crm_role_defaults_to_the_least_privileged_role():
    assert get_settings().crm_role == "autogtm_writer"


def test_non_numeric_threshold_is_rejected(monkeypatch):
    monkeypatch.setenv("MIN_FIT_SCORE", "high")
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match="MIN_FIT_SCORE"):
        get_settings()
