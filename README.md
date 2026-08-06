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

### 2. Varredura da caixa de entrada

```bash
python scripts/scan_inbox.py              # varre a caixa inteira
python scripts/scan_inbox.py --limite 50  # para depois de 50 e-mails
python scripts/scan_inbox.py --sem-janela # sem abrir a janela do navegador
```

Percorre a caixa rolando a lista (o Outlook Web só mantém no DOM os itens visíveis, então a varredura precisa rolar para alcançar o histórico), procura o código do processo de cotação (`SUP.AAAA-NNN`) e registra tudo em `app_facilitador.db`. Ao final imprime um resumo com quantos e-mails foram percorridos, quantos são novos e quais códigos apareceram.

Rodar duas vezes não duplica nada: o controle é por `conv_id` da conversa.

### 3. Conferir a extração

```bash
python scripts/browser_list_inbox.py
```

Mostra os e-mails visíveis já com remetente, assunto, data e preview separados — útil para verificar rapidamente se a leitura da tela continua correta.

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
