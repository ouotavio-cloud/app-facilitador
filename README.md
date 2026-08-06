# App Facilitador

Automação pessoal para organizar propostas de fornecedores e tarefas do dia a dia a partir do Outlook (Microsoft Graph API). Roda 100% local — sem servidor, sem backend remoto. Veja `PLANEJAMENTO.md` para o plano completo.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Testes

```bash
pytest -q
```

## Teste manual de autenticação (Fase 0)

```bash
python scripts/smoke_test_auth.py
```

Na primeira execução, o script mostra um link e um código de 9 dígitos (`https://microsoft.com/devicelogin`). Abra o link, digite o código e aceite a permissão de leitura de e-mail/calendário. As próximas execuções reaproveitam o login salvo em `.token_cache.bin` (arquivo local, nunca versionado).

Não é necessário registrar um app no Azure AD: o projeto usa o client_id público "Microsoft Graph Command Line Tools", da própria Microsoft (ver `PLANEJAMENTO.md`, seção 2).
