# App Facilitador

App local para acompanhar propostas de fornecedores e organizar as tarefas do dia a partir do Outlook. Roda inteiramente na sua máquina — sem servidor, sem nuvem.

## Baixar e usar (Windows)

1. Baixe o **`AppFacilitador-windows.zip`** na [página de releases](../../releases/latest).
2. Extraia a pasta.
3. Dê dois cliques em **`AppFacilitador.exe`** dentro dela.

Não precisa instalar Python, nem rodar `pip`, nem baixar navegador: o Chromium que o app usa vem junto. É por isso que o download é grande, e por isso que é um zip e não um `.exe` solto — num arquivo único o Windows teria de descompactar o navegador inteiro a cada abertura.

O que vem junto é **um** navegador, e só. O `playwright install` deixa três coisas na pasta (o Chromium, um segundo navegador "headless shell" de ~320 MB e o ffmpeg); o app executa apenas o primeiro, e a compilação embarca apenas ele — ver `AppFacilitador.spec`.

Na primeira vez, o Windows pode mostrar um aviso azul de **SmartScreen** — o programa não tem assinatura digital paga. Clique em **Mais informações** → **Executar assim mesmo**.

Abre uma janela preta (é o app rodando; feche-a para encerrar) e o painel no navegador. No painel, clique em **Conectar ao Outlook**: abre uma janela para você entrar com sua conta Microsoft, e o app detecta sozinho quando você terminou. Se ele não perceber, o botão **Já entrei** encerra a espera.

O acesso fica guardado num perfil de navegador próprio do app, em `%LOCALAPPDATA%\AppFacilitador`, e dura o mesmo que duraria no seu navegador do dia a dia.

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

**Download das propostas** — quando um e-mail casa com um processo cadastrado, o app abre a mensagem, baixa os anexos que são documentos e os arquiva em:

```
<pasta escolhida>/ Obra / Processo / Fornecedor / arquivo
```

O **fornecedor** vem do domínio do e-mail (`comercial@aciotubos.com.br` → `Aciotubos`), não do nome de quem escreveu: no mês seguinte pode ser outra pessoa da mesma empresa respondendo, e as propostas precisam ficar juntas. Em e-mail pessoal (gmail e afins) o domínio não diz nada, e aí vale o nome do remetente. O nome do fornecedor entra também **no nome do arquivo** (`Aciotubos - Proposta Comercial.pdf`), para que a proposta continue identificada mesmo depois de sair da pasta — anexada de volta num e-mail ou jogada numa planilha de comparação.

Logotipos e assinaturas não são baixados — só documentos (`.pdf`, `.xlsx`, `.docx`, `.dwg`, `.zip`…). Proposta revisada **não sobrescreve** a anterior: vira `Aciotubos - Orçamento (2).pdf` ao lado da original, porque comparar as duas versões é parte do trabalho.

A **pasta é a fonte da verdade**: antes de baixar, o app confere se a proposta já está lá. Se estiver, não baixa de novo (nem reabre o e-mail); se você tiver apagado o arquivo, a próxima varredura o traz de volta.

Duas coisas a saber: para pegar o anexo o app precisa **abrir o e-mail**, o que o marca como lido no Outlook — por isso só e-mails de processos cadastrados são abertos, nunca a caixa inteira. E a pasta de destino é editável no painel; o padrão é `Documentos\App Facilitador\Propostas`, que em máquina corporativa costuma estar sincronizada com o OneDrive.

**Reuniões de hoje** — lê os compromissos do calendário. Clique em *atualizar* para consultar; o resultado fica em cache para o painel abrir rápido. Se o cache for de outro dia, o app avisa em vez de mostrar reuniões de ontem como se fossem de hoje.

**E-mails recentes** — os últimos e-mails registrados, filtráveis por pasta.

## Vasculhar corpo e PDF

A busca normal procura o código no **assunto e no preview** — o que a lista de e-mails expõe sem abrir nada. Mas o fornecedor às vezes escreve o código só no corpo do e-mail, ou só dentro do PDF da proposta.

Marque **"Vasculhar corpo e PDF"** na varredura para fechar esse buraco: o app abre também os e-mails com anexo que não bateram pelo assunto, lê o corpo e extrai o texto do PDF, e procura o código ali. Se achar um processo cadastrado, baixa e arquiva a proposta normalmente.

É opt-in porque tem custo: abrir um e-mail o **marca como lido** no Outlook, e a varredura fica mais lenta (abre muito mais e-mails). Para os e-mails que já baixam propostas, o corpo e o PDF são lidos de qualquer forma — isso confirma o código e pega processos adicionais citados no texto, sem custo extra.

PDF escaneado (imagem, sem camada de texto) não é lido — precisaria de OCR, que ficou de fora para não pesar o download.

## Limitações atuais

- **O botão de download depende do layout do Outlook Web.** O app aciona o menu do anexo ("Salvar como"). Se a Microsoft mudar a interface, é aqui que quebra primeiro — a cada falha, `diagnostico-anexo.html` é salvo na pasta de dados com a estrutura real de cada anexo (os controles ao redor) para recalibrar.

## Registro (log)

Tudo o que o app faz — cada varredura, cada e-mail aberto, cada anexo encontrado e cada tentativa de download com o resultado — fica registrado em **`app.log`** na pasta de dados (`%LOCALAPPDATA%\App Facilitador`, ou `%LOCALAPPDATA%\AppFacilitador`). O arquivo tem rotação (não cresce sem limite). Quando algo não funciona, esse arquivo mostra exatamente onde travou — é o que me mande junto do `diagnostico-anexo.html` se o download falhar.

## Por que ler a tela do Outlook, e não uma API

A Microsoft Graph API está bloqueada pela política de TI da organização, e o novo Outlook não mantém cache local legível. O app abre o Outlook Web num navegador controlado localmente, usando o mesmo login que você já faz todo dia. As alternativas descartadas estão em `PLANEJAMENTO.md`, seção 2.

A consequência prática: a leitura depende da estrutura da página, que a Microsoft pode alterar sem aviso. Se parar de funcionar, `scripts/browser_inbox_debug.py` salva um screenshot e o HTML real dos itens, que servem para recalibrar os seletores em `app_facilitador/browser_client/`.

Esse pacote tem um arquivo por assunto, e é neles que se mexe quando algo quebra:

| Arquivo | Cuida de |
|---|---|
| `session.py` | abrir o Chromium, o login, entregar a página pronta |
| `inbox.py` | a lista: pastas, rolagem, abrir e ler uma mensagem |
| `downloads.py` | os anexos do e-mail aberto: achar e baixar |
| `diagnostics.py` | os despejos da página real, para recalibrar seletores |

---

## Rodando pelo código-fonte

Para desenvolver ou rodar fora do Windows:

```bash
python -m venv .venv
.venv\Scripts\activate        # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
playwright install --no-shell chromium
python app.py
```

O painel abre em `http://127.0.0.1:5000` (ou na próxima porta livre).

Os dados ficam na pasta do projeto quando rodando assim, e em `%LOCALAPPDATA%\AppFacilitador` no executável. `APP_FACILITADOR_DATA` força outro lugar.

### Compilar o executável

A compilação acontece sozinha no GitHub Actions a cada push (`.github/workflows/build-windows.yml`), que publica a release. Para compilar na mão, **numa máquina Windows** — o PyInstaller empacota o interpretador da máquina onde roda, não há compilação cruzada:

```bash
pip install pyinstaller
set PLAYWRIGHT_BROWSERS_PATH=%CD%\pw-browsers
playwright install --no-shell chromium
pyinstaller --clean --noconfirm AppFacilitador.spec
dist\AppFacilitador\AppFacilitador.exe --verificar
dist\AppFacilitador\AppFacilitador.exe --verificar-navegador
```

O `PLAYWRIGHT_BROWSERS_PATH` é o que faz o Chromium cair dentro do projeto, onde o empacotador consegue incluí-lo. Sem esse passo o app compila, abre o painel e falha só na hora de conectar ao Outlook.

O `--no-shell` é o que evita baixar o "chrome-headless-shell", um segundo navegador de ~320 MB que o app nunca executa — ele só seria usado em modo headless, e `open_browser_context` pede `channel="chromium"` justamente para que também o modo headless use o Chromium comum. Se você já tiver uma pasta `pw-browsers` de antes, apague-a: o `AppFacilitador.spec` ignora o que não for Chromium, mas o download já terá acontecido.

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

Quase nenhum teste precisa de navegador ou login: o parsing, o banco, o painel, a escolha do navegador, os caminhos de dados do executável e a varredura com scroll são testados com dados reais capturados da caixa de entrada e com um navegador falso. A exceção é `tests/test_find_attachments_dom.py`, que roda o JavaScript de produção num Chromium de verdade — ele se pula sozinho quando não há navegador instalado.
