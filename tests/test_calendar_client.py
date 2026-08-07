"""Testes da leitura de reuniões do calendário (parsing puro, sem navegador)."""

import json
from datetime import date, timedelta

import pytest

from app_facilitador import calendar_client, config


def test_parses_start_and_end_times():
    events = calendar_client.parse_event_labels(
        ["14:00 - 15:00 Reunião de obra com a Sabesp"]
    )

    assert events == [
        {"start": "14:00", "end": "15:00", "title": "Reunião de obra com a Sabesp"}
    ]


def test_parses_event_without_end_time():
    events = calendar_client.parse_event_labels(["09:30 Daily do time"])

    assert events == [{"start": "09:30", "end": None, "title": "Daily do time"}]


def test_pads_single_digit_hour():
    events = calendar_client.parse_event_labels(["9:05 - 9:35 Alinhamento"])

    assert events[0]["start"] == "09:05"
    assert events[0]["end"] == "09:35"


def test_ignores_interface_buttons_without_a_time():
    """A grade do calendário tem muitos botões que não são compromissos."""
    events = calendar_client.parse_event_labels(
        ["Nova reunião", "Ir para hoje", "10:00 - 11:00 Visita técnica"]
    )

    assert len(events) == 1
    assert events[0]["title"] == "Visita técnica"


def test_sorts_events_by_start_time():
    events = calendar_client.parse_event_labels(
        ["16:00 Tarde", "08:00 Manhã", "12:00 Meio-dia"]
    )

    assert [event["title"] for event in events] == ["Manhã", "Meio-dia", "Tarde"]


def test_removes_duplicates_from_overlapping_selectors():
    events = calendar_client.parse_event_labels(
        ["10:00 - 11:00 Visita", "10:00 - 11:00 Visita"]
    )

    assert len(events) == 1


def test_event_with_only_a_time_still_appears():
    """Melhor mostrar um compromisso sem título que escondê-lo."""
    events = calendar_client.parse_event_labels(["07:00 - 08:00"])

    assert events == [{"start": "07:00", "end": "08:00", "title": "(sem título)"}]


def test_no_events_returns_empty_list():
    assert calendar_client.parse_event_labels([]) == []


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "meetings.json"
    monkeypatch.setattr(config, "MEETINGS_CACHE_PATH", path)
    return path


def test_cached_meetings_is_empty_and_stale_without_a_cache(cache_path):
    cached = calendar_client.cached_meetings()

    assert cached["events"] == []
    assert cached["stale"] is True


def test_cached_meetings_from_today_is_fresh(cache_path):
    cache_path.write_text(
        json.dumps(
            {
                "events": [{"start": "10:00", "end": None, "title": "Visita"}],
                "updated_at": "06/08/2026 09:00",
                "day": date.today().isoformat(),
            }
        ),
        encoding="utf-8",
    )

    cached = calendar_client.cached_meetings()

    assert cached["stale"] is False
    assert cached["events"][0]["title"] == "Visita"


def test_cached_meetings_from_another_day_is_flagged_stale(cache_path):
    """Mostrar reuniões de ontem como se fossem de hoje seria pior que não mostrar."""
    cache_path.write_text(
        json.dumps(
            {
                "events": [{"start": "10:00", "end": None, "title": "Reunião de ontem"}],
                "updated_at": "05/08/2026 09:00",
                "day": (date.today() - timedelta(days=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    assert calendar_client.cached_meetings()["stale"] is True


def test_corrupted_cache_does_not_break_the_panel(cache_path):
    cache_path.write_text("{ isto não é json", encoding="utf-8")

    cached = calendar_client.cached_meetings()

    assert cached["events"] == []
    assert cached["stale"] is True
