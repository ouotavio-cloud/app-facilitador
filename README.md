# App Facilitador

App local para acompanhar propostas de fornecedores e organizar as tarefas do dia a partir do Outlook. Roda inteiramente na sua máquina — sem servidor, sem nuvem.

## Baixar e usar (Windows)

1. Baixe o **`AppFacilitador.exe`** na [página de releases](../../releases/latest).
2. Dê dois cliques.

Não precisa instalar Python, nem rodar `pip`, nem baixar navegador. O app usa o Microsoft Edge que já vem no Windows para ler seu Outlook.

Na primeira vez, o Windows pode mostrar um aviso azul de **SmartScreen** — o programa não tem assinatura digital paga. Clique em **Mais informações** → **Executar assim mesmo**.

Abre uma janela preta (é o app rodando; feche-a para encerrar) e o painel no navegador. No painel, clique em **Conectar ao Outlook**: abre uma janela para você entrar com sua conta Microsoft, e o app detecta sozinho quando você terminou. Esse acesso fica salvo em `%LOCALAPPDATA%\AppFacilitador` e não precisa ser repetido.

## O que o painel faz

**Números do dia** — no topo: quantos processos estão vencendo, quantas propostas chegaram, quantos códigos apareceram sem estar cadastrados, quantas reuniões você tem hoje.

**Processos que você acompanha** — cadastre o código de cada cotação (`SUP.AAAA-NNN`), o nome da obra e o prazo. Cada processo mostra um semáforo de vencimento:

| Selo | Quando |
|---|---|
| Vencido | o prazo já passou |
| Vence já | até 2 dias |
| Atenção | até 7 dias |
| No prazo | mais de 7 dias |

A contagem é em dias corridos: o prazo dado ao fornecedor é uma data de calendário, e tratar sábado como "dia que não conta" faria o app dizer que ainda há prazo quando o cliente já cobra.

**Varredura do Outlook** — percorre a pasta escolhida rolando a lista inteira (o Outlook Web só mantém na página os e-mails visíveis, então alcançar o histórico exige rolar) e identifica os processos cadastrados. Roda em segundo plano: o andamento aparece na tela e você pode continuar usando o painel. Rodar duas vezes não duplica nada.

Cada processo é procurado **das duas formas** — pelo código e pelo nome da obra — porque uma cobre a falha da outra: quando o fornecedor escreve o código de um jeito inesperado, o nome da obra no assunto ainda identifica o processo.

**Propostas identificadas** — os e-mails ligados aos seus processos, indicando por qual pista cada um foi reconhecido. Códigos que apareceram nos e-mails mas não estão cadastrados aparecem marcados, com um botão para cadastrar na hora — assim uma cotação esquecida vira pendência visível em vez de sumir.

**Reuniões de hoje** — lê os compromissos do calendário. Clique em *atualizar* para consultar; o resultado fica em cache para o painel abrir rápido. Se o cache for de outro dia, o app avisa em vez de mostrar reuniões de ontem como se fossem de hoje.

**E-mails recentes** — os últimos e-mails registrados, filtráveis por pasta.

## Limitações atuais

Duas coisas do escopo original ainda não estão prontas:

- **A busca cobre assunto e preview**, que é o que a lista de e-mails expõe. Se o código do processo estiver apenas dentro do anexo, ainda não é encontrado — abrir cada mensagem e ler os anexos é o próximo passo.
- **Não há arquivamento em pastas** `Obra / Processo / Fornecedor / Proposta`. Falta decidir onde essas pastas devem ficar.

## Por que ler a tela do Outlook, e não uma API

A Microsoft Graph API está bloqueada pela política de TI da organização, e o novo Outlook não mantém cache local legível. O app abre o Outlook Web num navegador controlado localmente, usando o mesmo login que você já faz todo dia. As alternativas descartadas estão em `PLANEJAMENTO.md`, seção 2.

A consequência prática: a leitura depende da estrutura da página, que a Microsoft pode alterar sem aviso. Se parar de funcionar, `scripts/browser_inbox_debug.py` salva um screenshot e o HTML real dos itens, que servem para recalibrar os seletores em `app_facilitador/browser_client.py`.

---

## Rodando pelo código-fonte

Para desenvolver ou rodar fora do Windows:

```bash
python -m venv .venv
.venv\Scripts\activate        # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # só se não houver Edge ou Chrome na máquina
python app.py
```

O painel abre em `http://127.0.0.1:5000` (ou na próxima porta livre).

Os dados ficam na pasta do projeto quando rodando assim, e em `%LOCALAPPDATA%\AppFacilitador` no executável. `APP_FACILITADOR_DATA` força outro lugar.

### Compilar o executável

A compilação acontece sozinha no GitHub Actions a cada push (`.github/workflows/build-windows.yml`), que publica a release. Para compilar na mão, **numa máquina Windows** — o PyInstaller empacota o interpretador da máquina onde roda, não há compilação cruzada:

```bash
pip install pyinstaller
pyinstaller --clean --noconfirm AppFacilitador.spec
dist\AppFacilitador.exe --verificar
```

### Linha de comando

O painel cobre o uso normal. Os scripts existem para automação e diagnóstico:

```bash
python scripts/scan_inbox.py --pasta "caixa real" --limite 300
python scripts/processos.py --listar
python scripts/show_results.py
python scripts/list_folders.py
python scripts/browser_list_inbox.py
```

### Testes

```bash
pytest -q
```

Nenhum teste precisa de navegador ou login: o parsing, o banco, o painel, a escolha do navegador, os caminhos de dados do executável e a varredura com scroll são testados com dados reais capturados da caixa de entrada e com um navegador falso.
