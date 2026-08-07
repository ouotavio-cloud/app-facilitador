"""Testes da navegação entre pastas, com um navegador falso.

Os rótulos usados aqui são os reais do painel de navegação do usuário,
capturados em execução: o Outlook anexa a contagem de itens ao nome da
pasta, e esse sufixo muda a cada e-mail que chega.
"""

import pytest

from app_facilitador import browser_client, inbox_parser

REAL_TREE_LABELS = [
    "Favoritos",
    "otavio.asantos@engeform.com.br",
    "Caixa de Entrada - 5.982 itens (2 não lidos)",
    "Rascunhos - 40 itens (0 não lidos)",
    "Itens Enviados - 731 itens (0 não lidos)",
    "Itens Excluídos - 825 itens (11 não lidos)",
    "Arquivo Morto - 62 itens (0 não lidos)",
    "caixa real - 4.410 itens (2 não lidos)",
    "Histórico de Conversa - 0 itens",
    "Lixo Eletrônico - 28 itens (28 não lidos)",
    "Observações - 1 item (0 não lido)",
    "ppt - 0 itens",
]


class FakeTreeItem:
    def __init__(self, label: str):
        self._label = label
        self.clicked = False

    def get_attribute(self, name: str):
        return self._label if name == "title" else None

    def inner_text(self) -> str:
        return self._label

    def click(self) -> None:
        self.clicked = True


class FakeTreeItems:
    def __init__(self, items: list[FakeTreeItem]):
        self._items = items

    def count(self) -> int:
        return len(self._items)

    def nth(self, index: int) -> FakeTreeItem:
        return self._items[index]


class FakeFoldersPage:
    def __init__(self, labels: list[str]):
        self._labels = labels
        self.items = [FakeTreeItem(label) for label in labels]

    def evaluate(self, script, _arg=None):
        if "treeitem" in script:
            return list(self._labels)
        return None

    def locator(self, _selector):
        class _Empty:
            def count(self):
                return 0

        return _Empty()

    def get_by_role(self, _role):
        return FakeTreeItems(self.items)

    def wait_for_timeout(self, _ms) -> None:
        pass

    def clicked_label(self) -> str | None:
        return next((item._label for item in self.items if item.clicked), None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("caixa real - 4.410 itens (2 não lidos)", "caixa real"),
        ("Caixa de Entrada - 5.982 itens (2 não lidos)", "Caixa de Entrada"),
        ("Observações - 1 item (0 não lido)", "Observações"),
        ("Histórico de Conversa - 0 itens", "Histórico de Conversa"),
        ("ppt - 0 itens", "ppt"),
        ("Favoritos", "Favoritos"),
        ("otavio.asantos@engeform.com.br", "otavio.asantos@engeform.com.br"),
    ],
)
def test_clean_folder_name_strips_item_count(raw, expected):
    assert inbox_parser.clean_folder_name(raw) == expected


def test_list_folders_returns_names_without_counts():
    page = FakeFoldersPage(REAL_TREE_LABELS)

    folders = browser_client.list_folders(page)

    assert "caixa real" in folders
    assert "Caixa de Entrada" in folders
    assert not any("itens" in name for name in folders)


def test_list_folders_removes_duplicates_from_favorites():
    """Uma pasta em Favoritos aparece duas vezes na árvore."""
    page = FakeFoldersPage(
        [
            "caixa real - 4.410 itens (2 não lidos)",
            "Caixa de Entrada - 5.982 itens (2 não lidos)",
            "caixa real - 4.410 itens (2 não lidos)",
        ]
    )

    assert browser_client.list_folders(page) == ["caixa real", "Caixa de Entrada"]


def test_open_folder_matches_despite_the_item_count_in_the_label():
    page = FakeFoldersPage(REAL_TREE_LABELS)

    browser_client.open_folder(page, "caixa real")

    assert page.clicked_label() == "caixa real - 4.410 itens (2 não lidos)"


def test_open_folder_ignores_case_typed_by_the_user():
    page = FakeFoldersPage(REAL_TREE_LABELS)

    browser_client.open_folder(page, "CAIXA REAL")

    assert page.clicked_label() == "caixa real - 4.410 itens (2 não lidos)"


def test_open_folder_does_not_match_a_different_folder_by_prefix():
    """'caixa real' não pode abrir 'Caixa de Entrada' por semelhança."""
    page = FakeFoldersPage(REAL_TREE_LABELS)

    browser_client.open_folder(page, "Arquivo Morto")

    assert page.clicked_label() == "Arquivo Morto - 62 itens (0 não lidos)"


def test_open_folder_raises_with_available_names_when_folder_is_missing():
    """Varrer a pasta errada em silêncio seria pior que falhar."""
    page = FakeFoldersPage(REAL_TREE_LABELS)

    with pytest.raises(RuntimeError, match="caixa real"):
        browser_client.open_folder(page, "Pasta Inexistente")
