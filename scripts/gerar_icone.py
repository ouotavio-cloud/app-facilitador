"""Gera o ícone .ico do executável a partir da mesma forma do logo.

Rodar só quando o desenho mudar:

    python scripts/gerar_icone.py

O resultado (`app_facilitador/web/static/icone.ico`) é versionado, para
que a compilação no GitHub Actions não dependa de nenhuma biblioteca de
imagem — o ícone é um dado do projeto, não algo a recalcular a cada build.

Escrevemos PNG e ICO na mão, sem Pillow, porque a única alternativa seria
adicionar uma dependência pesada usada uma vez na vida.
"""

import struct
import zlib
from pathlib import Path

SAIDA = Path(__file__).resolve().parent.parent / "app_facilitador" / "web" / "static" / "icone.ico"

TAMANHOS = [16, 32, 48, 64, 128, 256]

FUNDO = (74, 79, 212)     # mesmo roxo do logo em icone.svg
BARRA = (255, 255, 255)

# Amostragem por pixel para suavizar as bordas curvas. Sem isso o ícone
# fica serrilhado nos tamanhos pequenos, que são justamente os que
# aparecem na barra de tarefas.
AMOSTRAS = 4


def _dentro_do_retangulo_curvo(x: float, y: float, lado: float, raio: float) -> bool:
    """True se o ponto está dentro de um quadrado de cantos arredondados."""
    # Distância até a área central, que é reta em ambos os eixos; nos
    # cantos as duas distâncias são positivas e formam o raio do círculo.
    dx = max(raio - x, x - (lado - raio), 0.0)
    dy = max(raio - y, y - (lado - raio), 0.0)
    return dx * dx + dy * dy <= raio * raio


def _dentro_de_alguma_barra(x: float, y: float, lado: float) -> bool:
    """True se o ponto cai numa das três barras horizontais do logo."""
    escala = lado / 24.0  # o desenho original é feito numa grade de 24
    espessura = 2.0 * escala
    inicio = 5.0 * escala

    for centro_y, fim in ((8.5, 19.0), (12.0, 14.0), (15.5, 11.0)):
        cy = centro_y * escala
        if abs(y - cy) > espessura / 2:
            continue
        # As pontas são arredondadas (stroke-linecap="round"), o que no
        # eixo X vira meia espessura a mais de cada lado.
        if inicio - espessura / 2 <= x <= fim * escala + espessura / 2:
            return True
    return False


def _pixels(lado: int) -> bytes:
    """Imagem RGBA do ícone, linha a linha, no formato cru do PNG."""
    raio = lado * 6.0 / 24.0
    passo = 1.0 / AMOSTRAS
    linhas = []

    for py in range(lado):
        linha = bytearray([0])  # byte de filtro do PNG: 0 = sem filtro
        for px in range(lado):
            cobertura_fundo = 0
            cobertura_barra = 0
            for sy in range(AMOSTRAS):
                for sx in range(AMOSTRAS):
                    x = px + (sx + 0.5) * passo
                    y = py + (sy + 0.5) * passo
                    if not _dentro_do_retangulo_curvo(x, y, lado, raio):
                        continue
                    cobertura_fundo += 1
                    if _dentro_de_alguma_barra(x, y, lado):
                        cobertura_barra += 1

            total = AMOSTRAS * AMOSTRAS
            if cobertura_fundo == 0:
                linha.extend((0, 0, 0, 0))
                continue

            # Mistura fundo e barra conforme quanto de cada um cobre o
            # pixel; a opacidade vem de quanto do pixel está dentro da
            # forma.
            proporcao = cobertura_barra / cobertura_fundo
            cor = tuple(
                round(FUNDO[i] * (1 - proporcao) + BARRA[i] * proporcao)
                for i in range(3)
            )
            linha.extend((*cor, round(255 * cobertura_fundo / total)))
        linhas.append(bytes(linha))

    return b"".join(linhas)


def _bloco_png(tipo: bytes, dados: bytes) -> bytes:
    corpo = tipo + dados
    return struct.pack(">I", len(dados)) + corpo + struct.pack(">I", zlib.crc32(corpo))


def _png(lado: int) -> bytes:
    cabecalho = struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0)  # 8 bits, RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + _bloco_png(b"IHDR", cabecalho)
        + _bloco_png(b"IDAT", zlib.compress(_pixels(lado), 9))
        + _bloco_png(b"IEND", b"")
    )


def gerar() -> Path:
    imagens = [_png(lado) for lado in TAMANHOS]

    # Cabeçalho ICO: reservado, tipo 1 (ícone), quantidade de imagens.
    partes = [struct.pack("<HHH", 0, 1, len(imagens))]
    deslocamento = 6 + 16 * len(imagens)

    for lado, imagem in zip(TAMANHOS, imagens):
        partes.append(
            struct.pack(
                "<BBBBHHII",
                0 if lado >= 256 else lado,  # 0 significa 256 no formato ICO
                0 if lado >= 256 else lado,
                0,  # paleta: nenhuma, é RGBA
                0,  # reservado
                1,  # planos de cor
                32,  # bits por pixel
                len(imagem),
                deslocamento,
            )
        )
        deslocamento += len(imagem)

    partes.extend(imagens)
    SAIDA.write_bytes(b"".join(partes))
    return SAIDA


if __name__ == "__main__":
    caminho = gerar()
    print(f"Ícone gerado em {caminho} ({caminho.stat().st_size} bytes)")
