# App Facilitador

App local para acompanhar propostas de fornecedores e organizar as tarefas do dia a partir do Outlook. Roda inteiramente na sua máquina — sem servidor, sem nuvem.

Como a Microsoft Graph API está bloqueada pela política de TI da organização (e o novo Outlook não mantém cache local legível), o app lê o Outlook Web em um navegador controlado localmente, usando o mesmo login que você já faz todo dia. Detalhes e alternativas descartadas em `PLANEJAMENTO.md`, seção 2.

## Instalação (uma vez)

```bash
python -m venv .venv
.venv\Scripts\activate        # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Login no Outlook (uma vez)

```bash
python scripts/browser_login.py
```

Abre uma janela do navegador. Faça login com sua conta Microsoft até ver a caixa de entrada, volte ao terminal e aperte Enter. A sessão fica salva em `.browser_state.json` (local, nunca versionado) e é reaproveitada depois.

> No Windows use o **PowerShell** comum, não o PowerShell ISE — o ISE não repassa o Enter para o script e a espera do login trava.

## Abrir o app

Duplo clique em **`Abrir App Facilitador.bat`**, ou pelo terminal:

```bash
python app.py
```

O painel abre no navegador em `http://127.0.0.1:5000`.

## O que o painel faz

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

## Uso por linha de comando

O painel cobre o uso normal. Os scripts existem para automação e diagnóstico:

```bash
python scripts/scan_inbox.py --pasta "caixa real" --limite 300
python scripts/processos.py --listar
python scripts/show_results.py
python scripts/list_folders.py
python scripts/browser_list_inbox.py
```

## Testes

```bash
pytest -q
```

Nenhum teste precisa de navegador ou login: o parsing, o banco, o painel e a varredura com scroll são testados com dados reais capturados da caixa de entrada e com um navegador falso.

## Quando o Outlook Web mudar de layout

A leitura depende da estrutura da página, que a Microsoft pode alterar sem aviso. Se parar de funcionar:

```bash
python scripts/browser_inbox_debug.py
```

Salva um screenshot e o HTML real dos itens, que servem para recalibrar os seletores em `app_facilitador/browser_client.py`.
