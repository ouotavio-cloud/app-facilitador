from unittest.mock import MagicMock

from app_facilitador import graph_client


def test_list_recent_messages_returns_values(monkeypatch):
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"value": [{"subject": "Proposta SUP.2026-197"}]}
    fake_response.raise_for_status.return_value = None
    monkeypatch.setattr(graph_client.requests, "get", MagicMock(return_value=fake_response))

    messages = graph_client.list_recent_messages("fake-token", top=5)

    assert messages == [{"subject": "Proposta SUP.2026-197"}]


def test_get_retries_after_429(monkeypatch):
    throttled = MagicMock(status_code=429, headers={"Retry-After": "0"})
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"value": []}
    ok.raise_for_status.return_value = None

    mock_get = MagicMock(side_effect=[throttled, ok])
    monkeypatch.setattr(graph_client.requests, "get", mock_get)
    monkeypatch.setattr(graph_client.time, "sleep", lambda _seconds: None)

    result = graph_client._get("https://example.test", "fake-token")

    assert result == {"value": []}
    assert mock_get.call_count == 2
