"""Testes da varredura com scroll, com um navegador falso.

A lista do Outlook Web é virtualizada: itens já vistos continuam no DOM
enquanto estiverem renderizados, e novos só aparecem depois de rolar. O
navegador falso aqui reproduz esse comportamento para testar a
deduplicação e a condição de parada sem depender de rede nem de login.
"""

from app_facilitador import browser_client


class FakeLocator:
    def __init__(self, page):
        self._page = page

    def count(self) -> int:
        return len(self._page.visible_items())

    def nth(self, index: int):
        return self

    def scroll_into_view_if_needed(self) -> None:
        self._page.scroll()


class FakePage:
    """Simula uma lista virtualizada que revela mais itens a cada scroll."""

    def __init__(self, pages_of_items: list[list[dict]], window: int = 3):
        self._pages = pages_of_items
        self._window = window
        self._revealed = 1

    def visible_items(self) -> list[dict]:
        # Só a "janela" mais recente continua renderizada, como na
        # virtualização real — itens antigos saem do DOM ao rolar.
        revealed = self._pages[: self._revealed]
        return [item for page in revealed[-self._window :] for item in page]

    def scroll(self) -> None:
        self._revealed = min(self._revealed + 1, len(self._pages))

    def locator(self, _selector):
        return FakeLocator(self)

    def evaluate(self, _script, _selector=None):
        return self.visible_items()

    def wait_for_timeout(self, _ms) -> None:
        pass


def _item(index: int) -> dict:
    return {
        "conv_id": f"conv-{index}",
        "aria_label": f"Fornecedor {index} Assunto {index} 01/01/2026",
        "sender_name": f"Fornecedor {index}",
        "sender_email": f"f{index}@exemplo.com",
        "subject": f"Assunto {index}",
        "date_title": "Qui, 01/01/2026 10:00",
        "preview": None,
    }


def test_scan_inbox_collects_across_scrolls():
    page = FakePage([[_item(0), _item(1)], [_item(2), _item(3)], [_item(4)]])

    messages = list(browser_client.scan_inbox(page))

    assert [m["conv_id"] for m in messages] == [
        "conv-0",
        "conv-1",
        "conv-2",
        "conv-3",
        "conv-4",
    ]


def test_scan_inbox_does_not_yield_duplicates():
    """O mesmo item reaparece na extração enquanto continuar renderizado."""
    page = FakePage([[_item(0)], [_item(0), _item(1)], [_item(1), _item(2)]])

    messages = list(browser_client.scan_inbox(page))

    conv_ids = [m["conv_id"] for m in messages]
    assert conv_ids == ["conv-0", "conv-1", "conv-2"]
    assert len(conv_ids) == len(set(conv_ids))


def test_scan_inbox_stops_at_max_messages():
    page = FakePage([[_item(i)] for i in range(20)])

    messages = list(browser_client.scan_inbox(page, max_messages=5))

    assert len(messages) == 5


def test_scan_inbox_stops_when_no_new_items_appear():
    """Chegando ao fim da lista, a varredura termina em vez de rolar para sempre."""
    page = FakePage([[_item(0), _item(1)]])

    messages = list(browser_client.scan_inbox(page))

    assert len(messages) == 2


def test_scan_inbox_reports_progress():
    page = FakePage([[_item(0), _item(1)], [_item(2)]])
    progress = []

    list(browser_client.scan_inbox(page, on_progress=progress.append))

    assert progress and progress[-1] == 3


def test_scan_inbox_returns_nothing_when_list_is_empty():
    page = FakePage([[]])

    assert list(browser_client.scan_inbox(page)) == []


def test_scan_inbox_terminates_when_items_have_no_conv_id():
    """Sem conv_id a dedupe cai no aria-label — senão a varredura nunca terminaria."""
    items = [{**_item(i), "conv_id": None} for i in range(3)]
    page = FakePage([[items[0]], [items[1]], [items[2]]])

    messages = list(browser_client.scan_inbox(page))

    assert len(messages) == 3
