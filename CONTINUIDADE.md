# Onde o projeto está e o que fazer a seguir

Documento de passagem de bastão. Quem pegar o projeto daqui lê **este
arquivo primeiro**, depois `PLANEJAMENTO.md` (as decisões e o porquê de
cada uma) e `README.md` (como usar).

## O que o app é

App local que lê o Outlook Web do usuário (Otávio, suprimentos na
Engeform) para acompanhar cotações com fornecedores. Roda 100% na máquina
dele: sem servidor, sem nuvem.

Distribuído como `AppFacilitador-windows.zip` numa release do GitHub —
extrai a pasta, dá dois cliques no `.exe`. Nada a instalar antes.

- Repositório: `ouotavio-cloud/app-facilitador`
- Branch de trabalho: `claude/task-proposal-management-app-vt4xvm`
  (**é também o branch padrão** — não existe outro, por isso não dá para
  abrir PR: o 422 "base invalid" é esperado, não é erro a corrigir)
- Cada push nesse branch compila e publica uma release nova (`v1`, `v2`…)

## Estado atual

Funciona, confirmado pelo usuário na máquina dele ("ele funciona
perfeito"). 173 testes passando, nenhum precisa de navegador ou login.

| Item do pedido | Situação |
|---|---|
| 1.1 Identificar proposta pelo código `SUP.AAAA-NNN` | Pronto |
| 1.2 Arquivar em Obra/Processo/Fornecedor | Pronto (v6) |
| 1.3 Baixar o anexo, varrendo a caixa inteira | Calibrado (v8) para "Salvar como"; confirmar na máquina do usuário |
| 1.4 Avisar ao terminar a varredura | Pronto (resumo na tela) |
| Botão de parar a varredura | Pronto (v7) |
| Interruptor "baixar anexos" (liga/desliga o download) | Pronto (v7) |
| 2.1 E-mails novos da "caixa real", mais recentes primeiro | Pronto |
| 2.2 Reuniões do dia e horários | Pronto |
| 2.3 Indicador de prazo do processo | Pronto |
| 3 Sugestões adicionais | Listadas, nenhuma implementada |

## O que fazer a seguir, em ordem

### 1. Confirmar que o download funciona de verdade

**É o próximo passo e o mais importante.** O download de anexos foi
escrito sem nunca ter sido testado contra o Outlook real — não tenho
acesso à caixa do usuário, e diferente do resto do app (calibrado contra
HTML real que ele colou), a estrutura do painel de leitura é palpite.

Peça a ele: cadastrar um processo que tenha proposta com anexo, rodar a
varredura, e dizer se o arquivo apareceu na pasta.

Se não funcionar, o caminho é o mesmo que já resolveu isso duas vezes
neste projeto: pedir o HTML real. `browser_client.dump_message_debug()`
salva o painel de leitura inteiro. Com esse HTML dá para acertar os
seletores em `_JS_FIND_ATTACHMENTS`, `_baixar_pelo_botao` e
`_baixar_pelo_menu`.

### 2. Ler o corpo do e-mail e o conteúdo dos anexos

Hoje a detecção do código cobre **assunto e preview**. Se o fornecedor
escreveu o código só dentro do PDF, o e-mail não é reconhecido e o anexo
não é baixado. É o maior buraco que resta no Bloco 1.

Ordem sugerida: corpo do e-mail (fácil, o painel de leitura já é aberto)
→ texto de PDF → planilhas → OCR para PDF escaneado.

### 3. Sugestões do Bloco 3, se ele quiser

Por ordem de retorno, na minha leitura:

1. **Mapa comparativo automático** — quando 2+ fornecedores respondem ao
   mesmo processo, montar planilha comparando valores. O que mais poupa
   tempo dele.
2. **Cobrança de quem não respondeu** — cadastrar os fornecedores
   convidados por processo; o app avisa quem falta quando o prazo aperta.
3. **Histórico de preços por fornecedor.**
4. **Notificação do Windows** ao chegar proposta nova.
5. **Varredura agendada** pelo Agendador de Tarefas.

## Armadilhas — todas custaram uma versão quebrada

Estas já morderam. Não repita.

**Não troque o Chromium por Edge/Chrome do sistema.** Tentei, para
economizar 150 MB no download. No Windows corporativo dele o Edge **não
preserva a conta** entre execuções. Custou três versões sem conseguir
conectar. O Chromium vai empacotado e é o único caminho — não há nem
fallback, de propósito, para não reintroduzir o problema em silêncio.

**Não volte para `storage_state.json`.** Ele salva cookies e localStorage
mas não IndexedDB, onde o login da Microsoft guarda parte do que precisa —
a sessão morria em pouco tempo. O app usa perfil persistente
(`launch_persistent_context`), que guarda tudo.

**Não deduza "janela fechada" de uma exceção qualquer.** O login da
Microsoft é uma cadeia de redirecionamentos; consultar a página no meio de
um deles levanta `Execution context was destroyed` sem que nada esteja
errado. Pergunte com `page.is_closed()`. Eu fiz esse erro e ele abortava o
login antes de a pessoa digitar a senha.

**Não confie só na detecção automática do fim do login.** O botão "Já
entrei" existe porque a detecção falhou na máquina dele e a espera nunca
terminava. Mantenha a saída manual.

**Não abra e-mails em massa.** Abrir marca como lido no Outlook dele. Só
e-mails que casam com processo cadastrado são abertos.

**O download tem de acontecer durante a varredura.** A lista do Outlook é
virtualizada: numa segunda passada a linha não está mais no DOM e não há
onde clicar.

**O download é setinha (˅) → "Salvar como", não um botão "Baixar".** No
Outlook do usuário o cartão do anexo não tem botão de baixar visível: tem
um menu suspenso (Visualização, Abrir, Salvar no OneDrive, Copiar, Salvar
como). O item que baixa para a máquina é "Salvar como" — "Salvar no
OneDrive" salva na nuvem e nem gera download local. Os seletores foram
calibrados contra print real que o usuário mandou; se parar de funcionar,
`scanner._salvar_diagnostico` já salva o HTML do painel em
`diagnostico-anexo.html` na pasta de dados na primeira falha, e o caminho
aparece no resumo da varredura.

**Não saia de um `expect_download` por `continue`.** Sair do bloco `with
page.expect_download()` pela porta normal faz o Playwright *esperar* o
download inteiro (o timeout todo) por um clique que talvez nunca tenha
acontecido. Com timeout de 2 min e duas tentativas, cada anexo prendia o
app por minutos — parecia travado. Para pular a espera, levante uma exceção
de dentro do bloco (`_SemAcionador`). E separe o timeout de *começar* o
download (curto, ~20 s) do de *terminar* (longo): um seletor errado precisa
falhar rápido; um arquivo pesado precisa de tempo.

**Dados do usuário nunca na pasta do programa.** No `.exe` ela é
temporária e o Windows a apaga. Tudo em `%LOCALAPPDATA%\AppFacilitador`
via `paths.data_dir()`.

**`pytest` sem `pytest.ini` não acha o pacote.** Já resolvido, mas foi o
que quebrou a primeira compilação.

**Nomes de pasta do Outlook trazem a contagem de itens** ("caixa real -
4.410 itens"). Por isso `clean_folder_name`.

**Localize elementos por conteúdo, não por classe de CSS.** As classes do
Outlook (`.ESO13`, `.IjzWp`) são geradas pelo build da Microsoft e mudam
sem aviso. Onde deu, usei o conteúdo — anexos são achados por "termina em
.pdf", pastas por nome limpo. Prefira sempre esse caminho.

## Mapa do código

```
app.py                      entrada; --verificar e --verificar-navegador (usados no CI)
app_facilitador/
  paths.py                  dados vs. recursos; onde o .exe grava
  config.py                 caminhos, URLs, regex do código do processo
  browser_client.py         Playwright: login, varredura com scroll, pastas, anexos
  inbox_parser.py           parsing puro da lista de e-mails
  proposal_detector.py      casa o texto com os processos cadastrados
  attachments.py            decide pasta e nome de cada proposta (puro)
  deadlines.py              semáforo de prazo, dias corridos
  calendar_client.py        reuniões do dia
  storage.py                SQLite: mensagens, códigos, processos, anexos, settings
  scanner.py                junta tudo; é aqui que a varredura acontece
  web/server.py             Flask; rotas do painel
  web/jobs.py               ScanJob, LoginJob, MeetingsJob (threads)
  web/templates|static      a interface
AppFacilitador.spec         empacotamento (onedir + Chromium embutido)
.github/workflows/          compila no Windows e publica a release
```

O parsing é separado do navegador de propósito: `inbox_parser`,
`attachments`, `proposal_detector` e `deadlines` são puros e testados com
dados reais capturados da caixa dele.

## Como falar com este usuário

Ele não é programador, mas é ótimo observador — a hipótese dele sobre o
Edge estava certa na conclusão ("larga esse navegador") mesmo com a causa
um pouco diferente. Vale escutar.

Ele reporta com prints e log do terminal. Responda em português, direto,
com o que fazer primeiro. Quando algo quebrar, diga o que era e assuma o
erro sem rodeios — foi assim que as três regressões saíram do lugar.
