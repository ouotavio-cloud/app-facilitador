"""Log do app: liga sem quebrar e escreve no arquivo da pasta de dados."""

import importlib

from app_facilitador import config


def test_setup_escreve_no_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    import app_facilitador.logs as logs

    # Recarrega para o LOG_PATH apontar para a pasta temporária.
    logs = importlib.reload(logs)
    monkeypatch.setattr(logs, "_configurado", False)

    logs.setup()
    logs.get_logger("teste").info("linha de teste %d", 1)

    conteudo = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "linha de teste 1" in conteudo


def test_get_logger_nao_exige_setup():
    """Num teste sem setup, logar não pode levantar erro."""
    from app_facilitador import logs

    logs.get_logger("qualquer").info("isto não deve quebrar")
