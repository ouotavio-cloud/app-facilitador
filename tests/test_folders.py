"""Testes da navegação entre pastas, com um navegador falso."""

import pytest

from app_facilitador import browser_client


class FakeTreeItem:
    def __init__(self, matches: int):
        self._matches = matches
        self.clicked = False

    @property
    def first(self):
        return self

    def count(self) -> int:
        return self._matches

    def click(self) -> None:
        self.clicked = True


class FakeFoldersPage:
    def __init__(self, folder_names: list[str], existing: set[str] | None = None):
        self._folder_names = folder_names
        self._existing = existing if existing is not None else set(folder_names)
        self.tree_items: dict[str, FakeTreeItem] = {}

    def evaluate(self, script, _arg=None):
        if "treeitem" in script:
            return list(self._folder_names)
        return None

    def locator(self, _selector):
        class _Empty:
            def count(self):
                return 0

        return _Empty()

    def get_by_role(self, _role, name=None, exact=False):
        item = FakeTreeItem(1 if name in self._existing else 0)
        self.tree_items[name] = item
        return item

    def wait_for_timeout(self, _ms) -> None:
        pass


def test_list_folders_returns_visible_names():
    page = FakeFoldersPage(["Caixa de Entrada", "Itens Enviados", "caixa real"])

    assert browser_client.list_folders(page) == [
        "Caixa de Entrada",
        "Itens Enviados",
        "caixa real",
    ]


def test_list_folders_removes_duplicates_from_favorites():
    """Uma pasta em Favoritos aparece duas vezes na árvore."""
    page = FakeFoldersPage(["Caixa de Entrada", "caixa real", "Caixa de Entrada"])

    assert browser_client.list_folders(page) == ["Caixa de Entrada", "caixa real"]


def test_open_folder_clicks_the_matching_folder():
    page = FakeFoldersPage(["Caixa de Entrada", "caixa real"])

    browser_client.open_folder(page, "caixa real")

    assert page.tree_items["caixa real"].clicked is True


def test_open_folder_raises_with_available_names_when_folder_is_missing():
    """Varrer a pasta errada em silêncio seria pior que falhar."""
    page = FakeFoldersPage(["Caixa de Entrada", "caixa real"], existing=set())

    with pytest.raises(RuntimeError, match="caixa real"):
        browser_client.open_folder(page, "Pasta Inexistente")
