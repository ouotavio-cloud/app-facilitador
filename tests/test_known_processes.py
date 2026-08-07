"""Casamento do texto do e-mail contra os processos cadastrados pelo usuário."""

from app_facilitador import proposal_detector

PROCESSES = [
    {"code": "SUP.2026-197", "obra": "Sabesp Lote 4"},
    {"code": "SUP.2026-198", "obra": "Blocos e Lajes Itaim"},
    {"code": "SUP.2026-199", "obra": None},
]


def test_matches_process_by_code():
    matches = proposal_detector.match_known_processes(
        "Proposta referente ao SUP.2026-197", PROCESSES
    )

    assert matches == [{"code": "SUP.2026-197", "matched_by": ["código"]}]


def test_matches_process_by_obra_when_code_is_absent():
    """A obra é a pista reserva quando o fornecedor não cita o código."""
    matches = proposal_detector.match_known_processes(
        "Segue nossa proposta para Blocos e Lajes Itaim", PROCESSES
    )

    assert matches == [{"code": "SUP.2026-198", "matched_by": ["obra"]}]


def test_reports_both_clues_when_code_and_obra_appear():
    matches = proposal_detector.match_known_processes(
        "SUP.2026-197 - Sabesp Lote 4 - proposta comercial", PROCESSES
    )

    assert matches == [{"code": "SUP.2026-197", "matched_by": ["código", "obra"]}]


def test_obra_match_ignores_case_and_accents():
    processes = [{"code": "SUP.2026-200", "obra": "Estação São João"}]

    matches = proposal_detector.match_known_processes(
        "PROPOSTA - ESTACAO SAO JOAO", processes
    )

    assert matches == [{"code": "SUP.2026-200", "matched_by": ["obra"]}]


def test_code_written_loosely_still_matches():
    """O fornecedor escreve o código de qualquer jeito ao responder."""
    matches = proposal_detector.match_known_processes("ref sup 2026 197", PROCESSES)

    assert matches == [{"code": "SUP.2026-197", "matched_by": ["código"]}]


def test_very_short_obra_is_ignored_as_a_clue():
    """Uma obra de nome curto casaria com quase qualquer texto."""
    processes = [{"code": "SUP.2026-201", "obra": "SP"}]

    matches = proposal_detector.match_known_processes(
        "Nota fiscal emitida em SP hoje", processes
    )

    assert matches == []


def test_no_match_returns_empty():
    matches = proposal_detector.match_known_processes("Newsletter semanal", PROCESSES)

    assert matches == []


def test_process_without_obra_matches_only_by_code():
    matches = proposal_detector.match_known_processes("Proposta SUP.2026-199", PROCESSES)

    assert matches == [{"code": "SUP.2026-199", "matched_by": ["código"]}]


def test_find_unknown_codes_flags_processes_not_registered():
    unknown = proposal_detector.find_unknown_codes(
        "Cotações SUP.2026-197 e SUP.2026-888", PROCESSES
    )

    assert unknown == ["SUP.2026-888"]


def test_find_unknown_codes_returns_empty_when_all_are_registered():
    assert proposal_detector.find_unknown_codes("SUP.2026-197", PROCESSES) == []


def test_everything_is_unknown_when_nothing_is_registered():
    assert proposal_detector.find_unknown_codes("SUP.2026-197", []) == ["SUP.2026-197"]
