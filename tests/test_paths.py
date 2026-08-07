"""Onde o app grava seus arquivos — a diferença entre código-fonte e .exe.

Estes testes existem por causa de uma falha que só apareceria depois de
distribuído: no executável "arquivo único", a pasta do programa é
temporária e o Windows a apaga ao fechar. Gravar o banco lá faria o
usuário perder login e processos cadastrados a cada vez que fechasse o
app — sem nenhuma mensagem de erro.
"""

import sys

from app_facilitador import paths


def test_variavel_de_ambiente_tem_precedencia(tmp_path, monkeypatch):
    destino = tmp_path / "escolhida"
    monkeypatch.setenv("APP_FACILITADOR_DATA", str(destino))

    assert paths.data_dir() == destino


def test_a_pasta_de_dados_e_criada_se_nao_existir(tmp_path, monkeypatch):
    destino = tmp_path / "ainda-nao-existe" / "dados"
    monkeypatch.setenv("APP_FACILITADOR_DATA", str(destino))

    paths.data_dir()

    assert destino.is_dir()


def test_pelo_codigo_fonte_os_dados_ficam_na_pasta_do_projeto(monkeypatch):
    monkeypatch.delenv("APP_FACILITADOR_DATA", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert paths.data_dir() == paths.resource_dir()


def test_no_executavel_os_dados_vao_para_o_perfil_do_usuario(tmp_path, monkeypatch):
    """O ponto central: dados do usuário fora da pasta temporária do .exe."""
    monkeypatch.delenv("APP_FACILITADOR_DATA", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "temporaria"), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    pasta = paths.data_dir()

    assert pasta == tmp_path / "AppData" / "Local" / paths.APP_FOLDER_NAME
    assert pasta.is_dir()
    assert "temporaria" not in str(pasta)


def test_no_executavel_os_recursos_vem_da_pasta_do_pyinstaller(tmp_path, monkeypatch):
    """Templates e CSS moram junto do programa, não junto dos dados."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "descompactado"), raising=False)

    assert paths.resource_dir() == tmp_path / "descompactado"
