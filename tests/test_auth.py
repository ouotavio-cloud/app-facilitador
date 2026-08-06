from unittest.mock import MagicMock

import pytest

from app_facilitador import auth, config


@pytest.fixture(autouse=True)
def _isolated_token_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TOKEN_CACHE_PATH", tmp_path / ".token_cache.bin")


def test_get_access_token_reuses_silent_token(monkeypatch):
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = [{"username": "user@example.com"}]
    fake_app.acquire_token_silent.return_value = {"access_token": "cached-token"}
    monkeypatch.setattr(auth, "_build_app", lambda cache: fake_app)

    token = auth.get_access_token()

    assert token == "cached-token"
    fake_app.initiate_device_flow.assert_not_called()


def test_get_access_token_falls_back_to_device_flow(monkeypatch):
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    fake_app.initiate_device_flow.return_value = {
        "user_code": "ABC123",
        "message": "Vá em https://microsoft.com/devicelogin e digite ABC123",
    }
    fake_app.acquire_token_by_device_flow.return_value = {"access_token": "new-token"}
    monkeypatch.setattr(auth, "_build_app", lambda cache: fake_app)

    token = auth.get_access_token()

    assert token == "new-token"
    fake_app.acquire_token_by_device_flow.assert_called_once()


def test_get_access_token_raises_on_device_flow_start_failure(monkeypatch):
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    fake_app.initiate_device_flow.return_value = {"error_description": "tenant bloqueado"}
    monkeypatch.setattr(auth, "_build_app", lambda cache: fake_app)

    with pytest.raises(RuntimeError, match="tenant bloqueado"):
        auth.get_access_token()


def test_get_access_token_raises_on_token_error(monkeypatch):
    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    fake_app.initiate_device_flow.return_value = {"user_code": "ABC123", "message": "..."}
    fake_app.acquire_token_by_device_flow.return_value = {
        "error": "invalid_grant",
        "error_description": "código expirado",
    }
    monkeypatch.setattr(auth, "_build_app", lambda cache: fake_app)

    with pytest.raises(RuntimeError, match="invalid_grant"):
        auth.get_access_token()
