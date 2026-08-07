# App Facilitador — Planejamento do Projeto

Documento de planejamento antes de iniciar a implementação. Cobre escopo, arquitetura, escolha de tecnologia, fases, testes e riscos.

## 1. Escopo funcional (a partir do pedido do usuário)

### Bloco 1 — Captura e organização de propostas de fornecedores
- **1.1** Analisar a caixa de e-mail (Outlook) e identificar respostas de fornecedores que sejam propostas comerciais vinculadas a um processo de cotação enviado pelo usuário. Identificação por código no padrão `SUP.AAAA-NNN` (ex.: `SUP.2026-197`).
- **1.2** Armazenar cada proposta seguindo a hierarquia de pastas: `Obra / Processo / Fornecedor / Proposta`.
- **1.3** Extrair a proposta independentemente do formato do anexo (PDF, DOCX, XLSX, imagem escaneada) e varrer o Outlook por completo (histórico, não só e-mails novos).
- **1.4** Notificar o usuário ao final da varredura, com um resumo do que foi encontrado/arquivado.

### Bloco 2 — Painel de tarefas do dia a dia
- **2.1** Listar e-mails novos da caixa de entrada "real" (a principal, não a de fornecedores), ordenados do mais recente para o mais antigo.
- **2.2** Conferir reuniões agendadas e horários do dia (Outlook Calendar).
- **2.3** Indicador de tempo restante até o vencimento de cada processo de cotação em andamento (semáforo de prazo).

### Bloco 3 — Sugestões adicionais
Ver seção 8.

## 2. Esclarecimento importante: execução local vs. registro no Azure AD

Critério essencial do usuário: **o app roda somente na máquina dele** (sem servidor, sem backend remoto, sem dado armazenado em nuvem além do necessário).

Ambiente confirmado: **Windows + "novo Outlook"** (interface reformulada da Microsoft, também chamada de Monarch/One Outlook). Isso muda o que é tecnicamente possível:

- O **novo Outlook não expõe automação COM** (o que o Outlook clássico expõe via `pywin32`). Não há como ler a caixa de e-mail do novo Outlook sem o programa conversar, de alguma forma, com os servidores da Microsoft — a mensagem em si vive na nuvem, o novo Outlook não mantém um arquivo local completo e navegável como o `.ost` do clássico.
- As alternativas avaliadas foram: (A) IMAP com usuário/senha local, (B) leitura do cache interno não documentado do novo Outlook, (C) OAuth pessoal via um registro mínimo no Azure AD.
- **Decisão confirmada com o usuário: opção (C).** Um registro de app no Azure AD, nesse caso, é **gratuito, feito pela própria pessoa em poucos minutos, sem aprovação de TI** (para permissões delegadas de leitura como `Mail.Read`/`Calendars.Read` no próprio usuário) e **não implica nenhum servidor ou infraestrutura na nuvem** — ele serve apenas como identidade para o handshake OAuth, da mesma forma que o próprio Outlook já autentica o usuário. Nenhum dado passa por infraestrutura própria; o app roda inteiramente na máquina do usuário e fala diretamente com a Microsoft Graph API, como qualquer cliente de e-mail (Outlook, Thunderbird, app do celular) já faz.
- Ou seja: **"rodar só na minha máquina" está preservado** — o que não existe mais é a opção de fazer isso via COM/automação local pura, porque o cliente instalado (novo Outlook) não permite.

**Atualização 1 (bloqueio de TI encontrado na prática):** ao tentar criar o App Registration, o usuário recebeu erro de acesso negado (401 "Você não tem acesso") no portal Azure — a organização (tenant Engeform) restringe o "App registrations" a administradores. Tentativa seguinte: usar um client_id público já existente e mantido pela própria Microsoft, o "Microsoft Graph Command Line Tools" (`14d82eec-204b-4c2f-b7e8-296a70dab67e`), que normalmente só pede consentimento comum do usuário. **Também bloqueado**: a tela de consentimento voltou pedindo "Aprovação necessária" do administrador para `Mail.Read`/`Calendars.Read` mesmo nesse app oficial da Microsoft — ou seja, o tenant exige aprovação de TI para qualquer permissão de leitura de e-mail/calendário via Graph API, não importa o app.

**Atualização 2 (opções B e A também descartadas):**
- **Opção B (ler cache local do novo Outlook)**: verificado na prática — a pasta `LocalState` do novo Outlook (`%LOCALAPPDATA%\Packages\Microsoft.OutlookForWindows_8wekyb3d8bbwe\LocalState`) só contém ícones `.png` e um arquivo de 57 bytes de controle. **Não existe nenhum cache de e-mail local navegável** — confirmado que o novo Outlook é só uma janela para o servidor da Microsoft, sem dado substancial em disco. Opção descartada.
- **Opção A (IMAP usuário/senha)**: ainda a testar (script `scripts/test_imap.py`), mas alta chance de estar bloqueada também, já que a Microsoft desativou por padrão o "Basic Auth" em contas Microsoft 365 corporativas desde 2022.

**Decisão final adotada: Opção D — automação do Outlook na Web (navegador) via Playwright.** Como a Graph API está bloqueada por política de TI (mesmo para apps oficiais da Microsoft) e não existe cache local, a alternativa que sobra sem depender de aprovação de ninguém é abrir o Outlook Web (`outlook.office.com`) num navegador local controlado pelo script, com o usuário fazendo login manualmente (o mesmo login que ele já faz todo dia, sem nenhuma permissão especial). A sessão de login fica salva localmente (`.browser_state.json`, nunca versionado) para não precisar logar toda vez.
- **Vantagem:** não depende de TI, não depende de Azure AD, não depende de cache não documentado — usa exatamente o acesso que o usuário já tem.
- **Desvantagem:** não é uma API suportada, é automação de interface (lê a tela). Mais lento que uma API, e pode quebrar se a Microsoft mudar o layout do Outlook Web — exigirá ajustes pontuais ao longo do tempo.
- **"Rodar só na minha máquina" continua preservado:** o navegador automatizado roda localmente, controlado pelo script Python local, sem servidor.

## 3. Premissas que precisam ser validadas com o usuário

Estas são decisões de negócio que impactam a implementação e que assumo como hipótese razoável até confirmação:

| Ponto em aberto | Hipótese assumida |
|---|---|
| Onde ficam armazenadas as pastas Obra/Processo/Fornecedor | Localmente em uma pasta base, com opção futura de sincronizar com OneDrive/SharePoint |
| ~~Como o sistema sabe qual Obra/Processo corresponde a um processo de cotação enviado~~ **RESOLVIDO** | **O usuário informa.** Em vez de o sistema tentar adivinhar quais cotações existem, ele cadastra os processos que está acompanhando (código + nome da obra) em `scripts/processos.py`. A busca então usa as duas pistas de forma redundante — código e nome da obra — porque uma cobre a falha da outra. Ainda falta acrescentar prazo e fornecedores convidados ao cadastro. |
| Como casar a resposta do fornecedor com o processo original | Pelo thread do e-mail (`In-Reply-To`/`References`) e/ou pelo código do processo citado no corpo/assunto |
| O padrão `SUP.AAAA-NNN` é fixo ou varia por fornecedor | Regex configurável (lista de padrões), não fixo no código |
| Reprocessar e-mails já varridos | Não — controle de estado por `message-id` processado, evitando duplicidade |

Essas hipóteses devem ser confirmadas no início da Fase 0, pois mudam o desenho do banco de dados e das regras de negócio.

## 4. Escolha de tecnologia

**Requisito central:** integração robusta com Outlook (e-mail + calendário), leitura de anexos em múltiplos formatos, varredura em lote, execução periódica/agendada e um painel simples — tudo rodando localmente na máquina do usuário.

**Integração com Outlook:** usar a **Microsoft Graph API** (não IMAP/EWS legado) — é a API oficial e suportada, dá acesso a mensagens, pastas, anexos, calendário e OneDrive/SharePoint com o mesmo modelo de autenticação (OAuth2, usando o client_id público "Microsoft Graph Command Line Tools" com consentimento de usuário, conforme decidido na seção 2 — sem App Registration próprio). O app é apenas um cliente dessa API, exatamente como o próprio Outlook — não há servidor nem backend do lado do desenvolvedor.

**Linguagem/stack recomendada: Python 3.11+**
- Parsing de documentos e OCR têm o ecossistema mais maduro em Python: `pdfplumber`/`PyPDF2` (PDF), `python-docx` (Word), `openpyxl` (Excel), `pytesseract` + `Pillow` (OCR de imagens/PDF escaneado).
- `msal` (autenticação OAuth2/Azure AD) + `httpx`/`requests` ou a lib `O365` como wrapper de mais alto nível para Graph API.
- `APScheduler` para rodar a varredura periodicamente (ou Task Scheduler do Windows/cron chamando um script).
- `SQLite` + `SQLAlchemy` para persistir estado (e-mails processados, tabela de processos, prazos) — leve, sem servidor de banco separado.
- `FastAPI` para expor uma API local e servir o painel (dashboard), com frontend simples em Jinja2/HTML no MVP, podendo evoluir para React se necessário.

**Alternativa mais rápida para o MVP do painel:** `Streamlit` no lugar de FastAPI+Jinja2 — menos flexível visualmente, mas reduz o tempo para ter uma tela funcional exibindo e-mails novos, reuniões e prazos.

**Alternativa sem código (mencionar, não recomendar como principal):** Power Automate consegue mover e-mails com regras simples, mas não resolve bem extração de texto de anexos variados (OCR, tabelas dentro de PDF) nem a varredura histórica completa com deduplicação — por isso Python com Graph API é a escolha principal.

## 5. Arquitetura (visão geral)

```
[Agendador] --> [Conector Graph API] --> [Detector de Proposta] --> [Extrator de Anexo/OCR]
                                                                        |
                                                                        v
                                                            [Classificador Obra/Processo/Fornecedor]
                                                                        |
                                                                        v
                                                            [Gerenciador de Armazenamento (pastas)]
                                                                        |
                                                                        v
                                                                [Banco de estado (SQLite)]
                                                                        |
                                                                        v
                                                              [Notificador] + [Painel/Dashboard]
```

Componentes:
1. **Auth (MSAL)** — login OAuth2, refresh de token.
2. **Conector Graph** — lista mensagens/pastas/calendário, baixa anexos, usa paginação e delta query.
3. **Detector de Proposta** — regex configurável para o código (`SUP\.\d{4}-\d{3}` e variações).
4. **Extrator de Anexo** — roteia por tipo de arquivo; usa OCR como fallback quando não há texto extraível.
5. **Classificador** — resolve Obra/Processo/Fornecedor usando a tabela de referência e o thread do e-mail.
6. **Gerenciador de Armazenamento** — cria a árvore de pastas, evita duplicidade (hash do arquivo + message-id).
7. **Banco de estado (SQLite)** — mensagens já processadas, processos e prazos, fornecedores.
8. **Notificador** — resumo ao final da varredura (notificação no sistema, e-mail ou Teams).
9. **Painel** — e-mails novos, reuniões do dia, prazos em risco.

## 6. Roadmap por fases (com testes em cada uma)

### Fase 0 — Descoberta e setup (1–2 dias)
- Validar as premissas da seção 3 com o usuário.
- Usar o client_id público "Microsoft Graph Command Line Tools" (sem App Registration próprio, ver seção 2), com consentimento de usuário para `Mail.Read`, `Calendars.Read`.
- Estrutura inicial do projeto, ambiente virtual, dependências.
- **Teste:** autenticação OAuth (fluxo device code) e smoke test listando os 5 últimos e-mails.

### Fase 1 — Conector Outlook (leitura)
- Autenticação MSAL, listagem/paginação de mensagens (`/me/messages`, `/me/mailFolders`), leitura de anexos.
- **Testes:** unitários com respostas mockadas do Graph API; teste manual contra a caixa real verificando paginação (limite de página do Graph) e `@odata.nextLink`.
- **Erros a tratar:** token expirado, rate limit 429 (respeitar `Retry-After`), mensagens sem anexo, anexos inline vs. regulares, múltiplas subpastas (Inbox, Arquivo Morto, etc.).

### Fase 2 — Motor de identificação de propostas
- Regex configurável para o código da proposta; busca no assunto, corpo e nome/texto do anexo.
- Extração de texto por tipo de arquivo, com OCR como fallback.
- **Testes:** casos com a proposta de exemplo fornecida pelo usuário, variações de formatação do código (com/sem ponto, espaços), PDF escaneado exigindo OCR, anexo protegido por senha (deve falhar de forma controlada e registrar o erro, não travar a varredura), anexo corrompido.
- **Riscos:** falso positivo (código citado em contexto que não é proposta), múltiplos códigos no mesmo e-mail.

### Fase 3 — Classificação e armazenamento
- Resolver Obra/Processo/Fornecedor via tabela de referência + thread do e-mail.
- Criar a árvore de pastas e salvar o anexo original + metadados (JSON com remetente, data, código, processo).
- Deduplicação por hash de arquivo + message-id.
- **Testes:** árvore de pastas criada corretamente; idempotência (rodar a varredura duas vezes não duplica); comportamento em caso de proposta revisada (substituir vs. versionar — decidir com o usuário).

### Fase 4 — Notificação de fim de varredura
- Relatório final: quantidade de propostas novas, processos atualizados, erros encontrados.
- Canal de notificação (notificação do sistema, e-mail-resumo ou Teams).
- **Teste:** rodar varredura sem novidades vs. com novidades, garantir que a mensagem reflete corretamente cada caso.

### Fase 5 — Painel de tarefas
- E-mails novos da caixa principal (via delta query do Graph, mais eficiente que listar tudo de novo).
- Reuniões do dia (`/me/calendarView`), com atenção a fuso horário.
- Indicador de prazo (dias restantes por processo em aberto), com destaque visual (verde/amarelo/vermelho).
- **Testes:** delta query após reinício do app não perde nem duplica e-mails; horários de reunião corretos considerando fuso horário; cálculo de prazo em dias corridos vs. úteis (confirmar qual faz sentido para o usuário).

### Fase 6 — Hardening e testes finais
- Logging estruturado com rotação de arquivo.
- Tratamento de erro em cada etapa (rede, parsing, escrita em disco) sem interromper a varredura inteira por causa de um item problemático.
- Segurança: token/credenciais nunca em texto puro (usar `keyring` local ou variável de ambiente), permissões mínimas necessárias no App Registration.
- Teste end-to-end com a caixa real do usuário (ambiente piloto).

### Fase 7 — Entrega e acompanhamento
- Piloto de 1–2 semanas, ajuste de regex/regras de classificação com base em casos reais que falharem.
- Documentação de uso (README) e forma de execução (agendada via Task Scheduler/cron, ou app residente na bandeja do sistema).

## 7. Estratégia geral de testes

- **Unitários:** parsing de regex do código de proposta, extração de texto por tipo de arquivo, cálculo de prazo.
- **Integração com mocks:** respostas gravadas da Graph API para não depender de rede/caixa real em CI.
- **Integração real (ambiente piloto):** rodar contra a caixa do usuário em modo leitura, sem mover/apagar nada, validando os resultados antes de habilitar qualquer ação automática (como mover e-mails ou criar pastas de fato).
- **Regressão:** conjunto de e-mails/anexos de exemplo (incluindo o modelo já enviado pelo usuário) versionado como fixture de teste, para garantir que mudanças futuras não quebrem a detecção.

## 8. Riscos e como mitigar

| Risco | Mitigação |
|---|---|
| Throttling da Graph API em varredura completa de caixa grande | Paginação + backoff exponencial + processamento incremental (delta query) |
| Proposta em anexo sem texto extraível (imagem/scan de baixa qualidade) | OCR como fallback + fila de "revisão manual" para itens não identificados automaticamente |
| Ambiguidade entre Obra/Processo/Fornecedor quando o e-mail não segue o padrão esperado | Marcar como "não classificado" e listar no painel para o usuário resolver manualmente, em vez de arquivar errado |
| Perda de acesso/token expirado durante execução agendada | Refresh automático de token + alerta se a reautenticação manual for necessária |
| Duplicação de arquivos entre execuções | Controle de estado por message-id + hash do conteúdo |

## 9. Sugestões adicionais (Bloco 3)

- **Mapa comparativo automático:** quando 2+ fornecedores responderem ao mesmo processo, montar automaticamente uma planilha comparando os valores extraídos das propostas.
- **Cobrança automática de fornecedores:** alertar (e sugerir e-mail de cobrança) quando um processo está perto do prazo e algum fornecedor convidado ainda não respondeu.
- **Busca full-text** no acervo de propostas já arquivadas.
- **KPIs de fornecedores:** tempo médio de resposta, taxa de resposta por fornecedor, histórico de preços.
- **Rascunho assistido de resposta** para e-mails novos da caixa principal.
- **Priorização de e-mails novos** (ex.: sinalizar e-mails de clientes/obras críticas primeiro).
- **Integração com Teams/WhatsApp** para notificações fora do horário em que o app estiver aberto.

## 10. Próximos passos imediatos

1. Confirmar com o usuário as premissas da seção 3 (principalmente: onde ficam as pastas e como a tabela de Processos é alimentada).
2. ~~Registrar App no Azure AD~~ — descartado (bloqueado por política de TI); usando client_id público da Microsoft (seção 2). **Feito**, mas depois **superado**: a própria Graph API foi bloqueada pelo tenant (ver seção 2, Atualização 1) — a autenticação MSAL (`app_facilitador/auth.py`, `app_facilitador/graph_client.py`) fica como código de referência, mas o caminho ativo agora é a automação do Outlook Web (Opção D).
3. **Fase 1 concluída** (pivotada para automação do Outlook Web via Playwright). Login manual em `scripts/browser_login.py`; seletores calibrados contra o HTML real da caixa de entrada via `scripts/browser_inbox_debug.py`, rodado localmente pelo usuário — automação de navegador com login real precisa rodar na máquina dele, não em ambiente headless de CI/agente. `browser_client.scan_inbox()` percorre a caixa **inteira** rolando a lista virtualizada, com deduplicação por `conv_id` e parada quando não aparecem itens novos (seção 1.3). O parsing puro está isolado em `inbox_parser.py`, testável sem navegador, com fixtures de dados reais.
4. **Fase 2 parcialmente concluída.** `proposal_detector.py` reconhece o código `SUP.AAAA-NNN` com variações de formatação (ponto, espaço, hífen opcionais) via regex configurável (`config.PROPOSAL_CODE_PATTERNS`), já ligado à varredura. **Cobertura atual:** assunto e preview da lista. **Falta:** abrir cada mensagem para ler o corpo completo e baixar/extrair texto dos anexos (PDF, DOCX, XLSX, OCR).
5. **Fase 4 (relatório de fim de varredura) em versão inicial:** `scanner.run_and_report()` imprime quantos e-mails foram percorridos, quantos são novos, quais códigos apareceram e quantos itens deram erro. Falta o canal de notificação fora do terminal.
6. **Estado local implementado** (`storage.py`, SQLite em `app_facilitador.db`): mensagens já vistas e códigos encontrados, garantindo idempotência entre execuções.

7. **Tabela de Processos alimentada pelo usuário**, resolvendo a premissa em aberto da seção 3. A busca casa cada processo por código **e** por nome da obra, e o resultado separa os processos identificados dos códigos vistos mas não cadastrados — para que uma cotação esquecida vire pendência visível em vez de sumir.
8. **Navegação entre pastas**, necessária porque o usuário mantém uma pasta própria ("caixa real") com os e-mails importantes, separada da Caixa de Entrada. Atende também o Bloco 2.1.
9. **App com interface (Fase 5)** — `app.py` sobe um painel local em Flask, aberto no navegador da própria máquina. Escolhemos Flask, e não FastAPI, porque o Playwright que lê o Outlook é síncrono: um framework assíncrono traria a complexidade de conciliar os dois sem ganho aqui. A varredura roda numa thread separada com o andamento consultável, já que leva minutos e não caberia no ciclo de uma requisição HTTP. O painel cobre: cadastro de processos com semáforo de prazo (2.3), varredura com progresso (1.4), propostas identificadas (1.1), e-mails recentes por pasta (2.1) e reuniões do dia (2.2).
10. **Indicador de prazo (2.3)** em `deadlines.py`, contado em dias corridos — o prazo dado ao fornecedor é data de calendário, e ignorar fins de semana faria o app afirmar que ainda há prazo quando o cliente já cobra.
11. **Reuniões do dia (2.2)** em `calendar_client.py`, lidas da grade do calendário do Outlook Web e guardadas em cache para o painel abrir rápido. Cache de outro dia é sinalizado como desatualizado, em vez de exibir reuniões de ontem como se fossem de hoje.

12. **Distribuição como executável (Fase 7)** — o app virou um `AppFacilitador.exe` único, baixável de uma release do GitHub. Três decisões sustentam isso:

    - **Compilação no Windows via GitHub Actions** (`.github/workflows/build-windows.yml`). O PyInstaller não faz compilação cruzada: ele empacota o interpretador da máquina onde roda. Como o desenvolvimento acontece no Linux, quem produz o `.exe` é um runner `windows-latest`. O mesmo workflow roda os testes e executa `AppFacilitador.exe --verificar` antes de publicar — compilar sem erro não prova que o executável acha os templates.
    - **Navegador: o Edge já instalado**, e não um Chromium embutido (`_BROWSER_CHANNELS` em `browser_client.py`). Evita ~150 MB no download e elimina o passo `playwright install`, coerente com o pedido de "baixar e usar, sem instalar nada antes". O Chromium empacotado continua como último recurso para quem roda pelo código-fonte.
    - **Separação entre recursos e dados** (`paths.py`). No modo arquivo único o PyInstaller descompacta o programa numa pasta temporária que o Windows apaga ao fechar. Gravar o banco lá faria o usuário perder login e processos a cada vez que fechasse o app — silenciosamente. Os dados vão para `%LOCALAPPDATA%\AppFacilitador`; templates e CSS continuam junto do programa.

13. **Login dentro do app**, sem terminal. A versão anterior pedia `python scripts/browser_login.py` e um Enter no console — impossível num `.exe` de duplo clique. Agora um botão abre a janela de login e o app detecta sozinho que terminou, quando a lista de e-mails aparece: o mesmo sinal de que a sessão serve para a varredura.

### Próximo passo em aberto
- **Ler corpo completo e anexos** (resto da Fase 2): a detecção hoje cobre assunto e preview. Propostas cujo código só aparece dentro do PDF ainda passam batido — é o pedaço que falta para o Bloco 1.3, e o de maior impacto.
- **Onde ficam as pastas de arquivamento** (Bloco 1.2): a árvore `Obra / Processo / Fornecedor / Proposta` depende de decidir onde essas pastas ficam (pasta local? OneDrive sincronizado?) e o que fazer com proposta revisada — substituir ou versionar. Precisa ser confirmado antes de implementar.
