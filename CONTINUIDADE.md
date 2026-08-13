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
| 1.3 Baixar o anexo, varrendo a caixa inteira | Pronto (v8), confirmado pelo usuário ("baixou os itens") |
| Fornecedor no nome do arquivo | Pronto (v9) |
| Não rebaixar se o arquivo já está na pasta (disco manda) | Pronto (v9) |
| Ler corpo do e-mail e texto do PDF (código fora do assunto) | Pronto (v10) |
| Fornecedor por arquivo (e-mail com vários fornecedores) | Pronto (v11) |
| Priorizar proposta comercial (PC) sobre técnica (PT) | Pronto (v11) |
| 1.4 Avisar ao terminar a varredura | Pronto (resumo na tela) |
| Botão de parar a varredura | Pronto (v7) |
| Interruptor "baixar anexos" (liga/desliga o download) | Pronto (v7) |
| 2.1 E-mails novos da "caixa real", mais recentes primeiro | Pronto |
| 2.2 Reuniões do dia e horários | Pronto |
| 2.3 Indicador de prazo do processo | Pronto |
| 3 Sugestões adicionais | Listadas, nenhuma implementada |

## RESOLVIDO (v13): o download errava o alvo e fixava e-mails

O usuário mandou `app.log`, o banco e o `diagnostico-anexo.html` **com a
estrutura certa** (o relatório por anexo que a v12 passou a salvar). Com
isso o defeito parou de ser palpite: dá para rodar o JavaScript de produção
contra a página real e ver o que ele devolve. **Uma causa só explicava os
três sintomas** que ele relatou — pastas vazias, não baixa, fixa e-mail.

`_JS_FIND_ATTACHMENTS` varria `[aria-label], [title]` da **página inteira**
atrás de qualquer rótulo terminado em `.pdf`/`.xlsx`. Só que as **linhas da
lista de mensagens** também exibem o nome dos arquivos que cada e-mail
carrega. Rodando o JS antigo na página real dele: 7 "anexos", dos quais só 4
eram do e-mail aberto — e os outros 4 caíram na linha da lista. Daí em
diante:

- **anexo do e-mail errado** — arquivo de outra conversa arquivado na pasta
  desta (bate com o `app.log` das 15:02, em que um e-mail com 1 anexo
  aparece com 5);
- **fixou e-mail** — marcada a linha, `_baixar_pelo_menu` não achava
  `aria-haspopup` e caía na reserva "clica no último botão do alvo". Numa
  linha de mensagem o último botão é **"Manter esta mensagem na parte
  superior de sua pasta"**. Cada anexo que o app tentava baixar fixava um
  e-mail;
- **pasta vazia** — o `scanner` criava `Obra/Processo/Fornecedor` ao montar
  o caminho, antes de saber se o arquivo viria. Download falhando, sobrava a
  árvore montada e vazia.

O que separa um do outro, conferido no HTML real: linha de mensagem tem
`data-convid` e **nenhum** `aria-haspopup`; cartão de anexo tem
`aria-haspopup` (a setinha ˅ "Mais ações") e **nenhum** `data-convid`, e
vive num `[role="listbox"][aria-label="anexos de arquivo"]`. Feito na v13:

- `_JS_FIND_ATTACHMENTS` parte do **cartão** (`[role="option"]` com setinha,
  fora de `[data-convid]`), não do nome do arquivo, e **limpa as marcas do
  e-mail anterior** antes de marcar;
- `_baixar_pelo_menu` perdeu a reserva do "último botão" — sem setinha,
  desiste. Clique às cegas em caixa de e-mail alheia não tem como ser seguro;
- `_baixar_pelo_botao` procura só **dentro do cartão** (antes varria a página
  e podia acertar o "Baixar tudo", salvando o pacote inteiro como se fosse a
  proposta de um fornecedor);
- a pasta nasce **depois** de o download começar, e a varredura recolhe as
  pastas vazias que ficaram (`attachments.remove_empty_dirs`);
- marca perdida (o Outlook remonta o painel sozinho) agora é **refeita** em
  vez de derrubar o e-mail inteiro — era o "não foi marcado na página" que
  aparecia 4-5 vezes no mesmo segundo no log;
- Esc fecha o menu que uma tentativa falha deixava aberto por cima da tela.

**Teste que trava isso:** `tests/test_find_attachments_dom.py` roda o JS de
produção num Chromium de verdade contra um HTML com a estrutura real (papéis,
atributos e a ordem dos botões da linha copiados do diagnóstico; conteúdo
inventado, para não guardar e-mail de ninguém no repositório). Ele se pula
quando não há navegador — a CI compila antes de instalar o Chromium.

**Desafixar os e-mails que sobraram fixados (v13, mesma leva):** o app não
sabe quais foram atingidos — `save_message` usa `ON CONFLICT DO NOTHING`,
então `is_pinned` congela na primeira vez que a conversa é vista e não
registrou as fixadas depois. Em vez de pedir para o usuário desafixar um por
um no Outlook, o painel ganhou uma seção "Desafixar e-mails" que percorre a
pasta ao vivo (o estado "Fixado" vem fresco do DOM a cada e-mail,
`scanner.unpin_all`) e desafixa o que reconhece com segurança.

**Ressalva importante:** não há captura real do rótulo do botão já
FIXADO — só vimos, no diagnóstico, o rótulo de "Manter esta mensagem..."
quando a mensagem ainda não estava fixada. `browser_client._find_unpin_control`
cobre as variações mais prováveis ("não manter", "desafixar", "remover
fixado" etc.) e, como reserva, `aria-pressed="true"` no mesmo botão. Segue a
mesma disciplina que corrigiu o bug original: **nunca** cai para "o botão
que houver" — sem rótulo reconhecível, pula o e-mail e lista o assunto para
o usuário resolver à mão. Se a busca voltar com muita coisa em
"não identificado", é sinal de que o rótulo real é outro — peça um
`app.log` depois de rodar (`unpin_message` grava o que tentou e o que
pulou) e, se precisar, uma captura de uma linha fixada para calibrar
igual foi feito com os anexos.

## v14: por que propostas não eram achadas (duas causas) e o cadastro de fornecedores

O usuário mandou prints de duas propostas que o app não achou — molivetto2
(28/07) e daniel@dhlsaneamento (22/07), ambas respondendo à CARTA CONVITE da
SUP.2026-185, com o código **no assunto**. Cruzando com o banco real:

**Causa 1 — o flag "Tem anexos" barrava 61% dos e-mails casados.** Dos 18
e-mails que casaram com processo cadastrado, **11** morriam em
`if not has_attachments: continue` — todos respostas de fornecedor a carta
convite. O flag sai do rótulo da linha, e o Outlook simplesmente não o põe em
várias delas (conferido no HTML real: `Emanuel Moraes Raszl RE: CARTA CONVITE |
SUP.2026-197 …` não tem "Tem anexos", e é um dos 11). Pior, o parser tinha dois
defeitos no mesmo lugar: sem `sender_name` o prefixo saía vazio e a flag era
**impossível** (235 dos 1115 e-mails), e com `sender_name` ausente do rótulo o
`split` devolvia o rótulo inteiro e qualquer "Fixado" do assunto virava flag.

Corrigido: o flag perdeu o poder de veto sobre o sinal forte (código no
assunto) — quem decide se há anexo é o painel aberto. Ele continua valendo
para a varredura **profunda**, onde é a única pista e sem ele a caixa inteira
seria aberta. E `inbox_parser._leading_flags` lê as marcas ancoradas no começo
do rótulo, sem depender do remetente.

**Causa 2 — a lista é por CONVERSA e só a última mensagem abre.** Para a
SUP.2026-185 existem **2 linhas** no banco (Angolini 07/08, Emanuel 05/08),
embora pelo menos 4 fornecedores tenham respondido. `dhlsaneamento` aparece
**0 vezes** em 1115 e-mails. As propostas estão *dentro* das threads: o painel
de leitura mostra 1 `[role="document"]` (conferido no dump), então os anexos
das mensagens anteriores nem chegam ao DOM.

**Isto ainda NÃO está resolvido.** Alcançar as mensagens recolhidas exige
clicar num cabeçalho de mensagem cuja estrutura eu nunca vi — e adivinhar
acionador foi o que fez o app fixar e-mail (ver v13). `dump_message_debug`
agora salva um **RELATÓRIO DA CONVERSA** (`corpos_de_mensagem_no_painel`,
`candidatos_a_expandir` com `aria-expanded` e rótulo). Peça o
`diagnostico-anexo.html` novo e calibre com ele, como foi feito com os anexos.

**Mitigação que já vale: cadastro de fornecedores (opcional).** Tabela
`suppliers` (`match` = e-mail inteiro ou domínio, `name` opcional) e uma seção
no painel. Dá um **segundo critério, independente do assunto**: e-mail de
fornecedor cadastrado é aberto mesmo sem código casado, cai no caminho da
varredura profunda, e o corpo revela o processo. É como a proposta da DHL
passa a ser achada sem depender de expandir a thread. De quebra resolve o
pedido antigo de "apelido de fornecedor": `name` vira o nome da pasta, o que
conserta o e-mail pessoal (`molivetto2@gmail.com` virava pasta "Molivetto2").
Precedência ao nomear: nome do arquivo (convenção PT/PC) > cadastro > domínio.

Vazio por padrão — quem não cadastrar nada não vê diferença nenhuma.

## Download falhando — pista do cache do usuário (v12)

O usuário mandou o banco real: **21 anexos falharam** ("não foi possível
baixar pelo Outlook") e o `diagnostico-anexo.html` capturou o menu da
MENSAGEM ("Denunciar como lixo eletrônico"), não o do anexo. Diagnóstico:
a marcação do cartão (`_JS_FIND_ATTACHMENTS`) subia demais e englobava a
barra da mensagem, então `_baixar_pelo_menu` clicava o menu "..." da
mensagem em vez da setinha do anexo. Feito na v12:
- marcação para de subir ao cruzar role=toolbar/main/region/document e ao
  achar um controle → cartão fica justo no anexo;
- `dump_message_debug` agora salva um RELATÓRIO por anexo (controles ao
  redor: botões, menus, aria-haspopup) + o body inteiro — o dump antigo
  pegava só [role=main], que não contém os anexos no novo Outlook;
- **log** novo (`app_facilitador/logs.py`) grava tudo em `app.log` na pasta
  de dados: varredura, e-mail aberto, anexos achados, cada tentativa de
  download e o resultado. É o que o usuário pediu ("função de log").

**Se ainda falhar:** pedir o novo `diagnostico-anexo.html` (agora traz a
estrutura certa) e o `app.log`, e calibrar `_baixar_pelo_menu`/marcação com
isso. Também limpei nomes de fornecedor ruins vindos do banco: candidato só
com números ("2026") é rejeitado, e e-mail cru como pasta
("vendas.angolini@yahoo...") vira "Angolini".

## Em andamento (retomar aqui)

Pedidos do usuário depois da v10, **em ordem**:

1. **Fornecedor por ARQUIVO, não por e-mail.** FEITO (v11). Print mostrou um
   e-mail interno (`engeform.com.br`) com propostas de BERMAD, RTS e SAINT
   GOBAIN juntas. Agora `attachments.supplier_from_filename` pega o nome
   depois do marcador PT/PC e `supplier_for` prefere isso ao domínio; o
   scanner decide fornecedor **por arquivo** (`select_proposals`).
2. **Priorizar a COMERCIAL sobre a TÉCNICA.** FEITO (v11).
   `classify_proposal` → comercial/tecnica/None; `select_proposals` pula a
   técnica quando há comercial do mesmo fornecedor **no mesmo e-mail**
   (seguro: só-técnica é mantida). Coluna `tipo` no banco, badge no painel,
   toggle "Baixar técnica também". **PENDENTE confirmar com o usuário**: se
   PT e PC vierem em e-mails SEPARADOS, o "pular" atual (por e-mail) não
   pega — precisaria ser por processo+fornecedor. Perguntei; ver resposta.
3. **Otimizar a varredura com a BARRA DE PESQUISA do Outlook.** NÃO FEITO —
   é a próxima e maior tarefa. Hoje rola a caixa inteira (750 e-mails). Ideia:
   digitar cada código cadastrado na busca do Outlook e varrer só os
   resultados. Ganho enorme e a busca indexa o corpo (pega código fora do
   assunto de graça). Precisa calibrar o seletor da caixa de busca contra
   HTML real — provável uma rodada de ajuste. Analisei para o usuário; ver
   se ele topou antes de construir.

## O que fazer a seguir, em ordem

### 1. Confirmar a v13 na caixa real

O seletor de anexo **deixou de ser palpite**: agora é conferido contra o
`diagnostico-anexo.html` da caixa dele, e o teste roda o JS de produção num
Chromium de verdade. Mas quem prova é o Outlook, não o teste.

Peça a ele: rodar a varredura e dizer três coisas —
1. **os arquivos apareceram** dentro de `Obra/Processo/Fornecedor`;
2. **nenhum e-mail novo foi fixado** (os já fixados são das versões
   anteriores; ver o fim da seção da v13);
3. **não sobrou pasta vazia** — a varredura recolhe as antigas e informa
   quantas no resumo.

Se ainda falhar, o caminho é o mesmo de sempre: `app.log` +
`diagnostico-anexo.html` novos. O relatório por anexo do dump traz os
controles ao redor de cada arquivo, que é o que permite acertar o clique.

### 2. Apelido de fornecedor (próximo pedido do usuário)

Ele pediu, junto com "ler corpo + PDF", um jeito de **corrigir manualmente
o nome do fornecedor**. O nome hoje sai do domínio do e-mail
(`attachments.supplier_folder`), que erra em dois casos: e-mail genérico
(gmail do vendedor) e domínio que abrevia diferente do nome comercial. A
decisão foi: manter o domínio como base e resolver as exceções com um
apelido manual (tabela de-para: domínio ou remetente → nome preferido),
**não** tentar ler a assinatura do e-mail (frágil, formato varia demais).
Falta implementar: uma tabela `supplier_aliases` no storage e uma tela para
o usuário editar; `supplier_folder` consulta o apelido antes do domínio.

### 3. Já feito: ler corpo do e-mail e conteúdo do PDF (v10)

A detecção agora vai além do assunto/preview. Para e-mails que já são
abertos (proposta identificada), o corpo e o texto do PDF baixado são lidos
e os códigos achados ali entram com a pista "conteúdo" (`pdf_text.py` +
`browser_client.read_message_body` + `scanner._enriquecer_pelo_conteudo`).
E há a **varredura profunda** opt-in (`scanner._deep_scan_message`): abre os
e-mails com anexo que não bateram, baixa para uma pasta temporária só para
ler, e arquiva se casar. Falta ainda: planilhas (xlsx) e OCR para PDF
escaneado — deliberadamente fora por ora.

### 4. Sugestões do Bloco 3, se ele quiser

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

**Nunca clique "o primeiro/último botão que houver" num alvo.** Foi assim
que o app passou a fixar e-mails: sem `aria-haspopup`, `_baixar_pelo_menu`
caía no último botão do alvo, e numa linha da lista de mensagens o último
botão é "Manter esta mensagem na parte superior de sua pasta". Os botões de
uma linha são fixar, sinalizar e marcar como não lido — nenhum é inofensivo.
Clique em controle **identificado** (por papel ou rótulo) ou não clique.

**Não procure anexo pelo nome do arquivo na página inteira.** As linhas da
lista de mensagens também exibem o nome dos arquivos que cada e-mail carrega:
varrer tudo mistura anexo de conversas diferentes e faz o app mirar a linha
em vez do anexo. Parta do **cartão** (`[role="option"]` com setinha, fora de
`[data-convid]`). Ver v13 acima.

**Não crie a pasta de destino antes de o download começar.** Pasta vazia
afirma que a proposta está lá. Quem cria é `download_attachment`, com o
arquivo já vindo.

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
