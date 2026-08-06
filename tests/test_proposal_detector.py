import pytest

from app_facilitador import proposal_detector


@pytest.mark.parametrize(
    "text",
    [
        "Segue nossa proposta referente a SUP.2026-197.",
        "Segue nossa proposta referente a SUP 2026-197.",
        "Segue nossa proposta referente a SUP2026-197.",
        "Segue nossa proposta referente a sup.2026197.",
        "Segue nossa proposta referente a  SUP.  2026 - 197 .",
    ],
)
def test_find_proposal_codes_normalizes_variations(text):
    assert proposal_detector.find_proposal_codes(text) == ["SUP.2026-197"]


def test_find_proposal_codes_returns_multiple_without_duplicates():
    text = "Cotações SUP.2026-197 e SUP.2026-198, reforçando SUP.2026-197 novamente."

    codes = proposal_detector.find_proposal_codes(text)

    assert codes == ["SUP.2026-197", "SUP.2026-198"]


def test_find_proposal_codes_returns_empty_when_no_match():
    assert proposal_detector.find_proposal_codes("Nenhum código aqui.") == []


def test_find_proposal_codes_accepts_custom_patterns():
    custom_patterns = [r"COT-(?P<year>\d{4})/(?P<seq>\d{3})"]

    codes = proposal_detector.find_proposal_codes("Ref. COT-2026/042", patterns=custom_patterns)

    assert codes == ["SUP.2026-042"]


def test_contains_proposal_code():
    assert proposal_detector.contains_proposal_code("Proposta SUP.2026-197") is True
    assert proposal_detector.contains_proposal_code("Sem código aqui") is False
