"""Autenticação OAuth2 (device code flow) contra a Microsoft Graph API.

Fluxo: tenta reaproveitar um token salvo em cache local (arquivo
`.token_cache.bin`, nunca versionado). Se não houver token válido, pede
para o usuário logar via device code (abre uma página no navegador e
digita um código) — sem senha passando pelo script, sem servidor local.
"""

import sys

import msal

from app_facilitador import config


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if config.TOKEN_CACHE_PATH.exists():
        cache.deserialize(config.TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        config.TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _build_app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=config.CLIENT_ID,
        authority=config.AUTHORITY,
        token_cache=cache,
    )


def get_access_token() -> str:
    """Retorna um access token válido, autenticando o usuário se necessário."""
    cache = _load_cache()
    app = _build_app(cache)

    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(config.SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=config.SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Falha ao iniciar o login: {flow.get('error_description', flow)}")

        print(flow["message"], file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(
            "Falha na autenticação: "
            f"{result.get('error')} - {result.get('error_description')}"
        )

    return result["access_token"]
