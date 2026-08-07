# App Facilitador

Automação pessoal para organizar propostas de fornecedores e tarefas do dia a dia a partir do Outlook. Roda 100% local — sem servidor, sem backend remoto. Veja `PLANEJAMENTO.md` para o plano completo.

Como a Microsoft Graph API está bloqueada pela política de TI da organização (e o novo Outlook não mantém cache local legível), o app lê o Outlook Web em um navegador controlado localmente pelo Playwright, usando exatamente o login que o usuário já faz todo dia. Detalhes e alternativas descartadas em `PLANEJAMENTO.md`, seção 2.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Uso

### 1. Login (uma vez só)

```bash
python scripts/browser_login.py
```

Abre uma janela do navegador. Faça login normalmente com sua conta Microsoft até ver a caixa de entrada, volte ao terminal e aperte Enter. A sessão fica salva em `.browser_state.json` (arquivo local, nunca versionado) e é reaproveitada nas próximas execuções.

> No Windows, use o **PowerShell** comum, não o PowerShell ISE — o ISE não repassa o Enter para o script e a espera do login trava.

### 2. Cadastrar os processos que você acompanha

```bash
python scripts/processos.py            # modo interativo
python scripts/processos.py --listar
python scripts/processos.py --remover SUP.2026-197
```

Informe o código de cada cotação (`SUP.AAAA-NNN`) e, opcionalmente, o nome da obra. A busca procura cada processo **das duas formas** — pelo código e pelo nome da obra — porque uma reforça a outra: quando o fornecedor escreve o código de um jeito inesperado, o nome da obra no assunto ainda identifica o processo.

O código digitado é normalizado, então tanto faz escrever `SUP.2026-197`, `sup 2026 197` ou `SUP2026197`.

### 3. Varredura

```bash
python scripts/scan_inbox.py                      # Caixa de Entrada inteira
python scripts/scan_inbox.py --limite 50          # para depois de 50 e-mails
python scripts/scan_inbox.py --pasta "caixa real" # outra pasta
python scripts/scan_inbox.py --sem-janela         # sem abrir a janela
```

Percorre a pasta rolando a lista (o Outlook Web só mantém no DOM os itens visíveis, então alcançar o histórico exige rolar), identifica os processos cadastrados e registra tudo em `app_facilitador.db`.

O resumo separa duas coisas: os **processos identificados** (que você cadastrou) e os **códigos vistos mas não cadastrados** — assim uma cotação que você esqueceu de registrar aparece como pendência em vez de sumir.

Rodar duas vezes não duplica nada: o controle é por `conv_id` da conversa.

Para descobrir os nomes exatos das pastas:

```bash
python scripts/list_folders.py
```

### 4. Ver o que foi encontrado

```bash
python scripts/show_results.py
```

Lista os e-mails identificados, indicando por qual pista cada processo foi reconhecido (código, obra, ou ambos) — sem precisar abrir o navegador.

### Conferir a extração

```bash
python scripts/browser_list_inbox.py
```

Mostra os e-mails visíveis já com remetente, assunto, data e preview separados — útil para verificar rapidamente se a leitura da tela continua correta.

## Limitação atual da detecção

A busca cobre hoje o **assunto e o preview** que aparecem na lista de e-mails. Se o código do processo estiver apenas dentro do anexo (ou no meio do corpo, fora do trecho do preview), ele ainda não é encontrado — abrir cada mensagem e ler os anexos é o próximo passo do roadmap.

## Testes

```bash
pytest -q
```

Os testes não precisam de navegador nem de login: a lógica de parsing, o banco e a varredura com scroll são testados com dados reais capturados da caixa de entrada e com um navegador falso.

## Quando o Outlook Web mudar de layout

A extração depende da estrutura da página, que a Microsoft pode alterar sem aviso. Se a leitura parar de funcionar, rode o diagnóstico:

```bash
python scripts/browser_inbox_debug.py
```

Ele salva um screenshot e o HTML real dos itens da lista, que servem para recalibrar os seletores em `app_facilitador/browser_client.py`.
