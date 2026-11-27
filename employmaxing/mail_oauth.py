#!/usr/bin/env python3
"""
mail_oauth.py - Zero-dependency OAuth 2.0 + PKCE (S256) engine for Single-Provider Mail Auth.
Supports:
  - Google (Sign in with Google -> Gmail REST API, 2FA/Passkey native)
  - Microsoft (Sign in with Microsoft -> Microsoft Graph API, 2FA/Authenticator native)
  - Yahoo (Yahoo OAuth2 -> XOAUTH2 Mail, or 2FA App Password)
  - Proton (Proton Mail Bridge local loopback TLS)
  - Custom API (Custom REST Mail API / Resend / Postmark / Mailgun)

Enforces STRICTLY ONE active mail provider at a time in ~/.employmaxing/mail-config.json (chmod 600).
Licensed under GNU GPL v3.0.
"""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import requests

from employmaxing.store import EmploymaxingStore

ALLOWED_PROVIDERS = ("thunderbird", "google", "microsoft", "yahoo", "proton", "custom_api")

OAUTH_SPECS = {
    "google": {
        "label": "Google (Gmail)",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scopes": "openid email profile https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        "extra_auth_params": {"access_type": "offline", "prompt": "consent"},
        "env_client_id": "EMPLOYMAXING_GOOGLE_CLIENT_ID",
        "env_client_secret": "EMPLOYMAXING_GOOGLE_CLIENT_SECRET",
    },
    "microsoft": {
        "label": "Microsoft (Outlook / M365)",
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "scopes": "openid email profile offline_access User.Read Mail.Read Mail.Send",
        "extra_auth_params": {"prompt": "select_account"},
        "env_client_id": "EMPLOYMAXING_MICROSOFT_CLIENT_ID",
        "env_client_secret": "EMPLOYMAXING_MICROSOFT_CLIENT_SECRET",
    },
    "yahoo": {
        "label": "Yahoo Mail",
        "auth_url": "https://api.login.yahoo.com/oauth2/request_auth",
        "token_url": "https://api.login.yahoo.com/oauth2/get_token",
        "userinfo_url": "https://api.login.yahoo.com/openid/v1/userinfo",
        "scopes": "openid email mail-r mail-w",
        "extra_auth_params": {},
        "env_client_id": "EMPLOYMAXING_YAHOO_CLIENT_ID",
        "env_client_secret": "EMPLOYMAXING_YAHOO_CLIENT_SECRET",
    },
}

# In-memory short-lived PKCE state store (local loopback session only)
_PENDING_OAUTH: dict[str, dict] = {}
DEFAULTS_FILE = Path(__file__).resolve().parent / "oauth_defaults.json"


def _load_bundled_oauth_defaults() -> dict:
    if DEFAULTS_FILE.exists():
        try:
            return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _load_user_oauth_apps(store: EmploymaxingStore) -> dict:
    p = store.data_dir / "oauth-apps.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_user_oauth_app(store: EmploymaxingStore, provider: str, client_id: str, client_secret: str = ""):
    """Persist user's OAuth app credentials separately so switching/disconnecting mail never loses them."""
    apps = _load_user_oauth_apps(store)
    apps[provider] = {"client_id": client_id.strip(), "client_secret": client_secret.strip()}
    p = store.data_dir / "oauth-apps.json"
    p.write_text(json.dumps(apps, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)


def resolve_oauth_client(store: EmploymaxingStore, provider: str, override_id: str = "", override_secret: str = "") -> tuple[str, str]:
    """Resolve OAuth Client ID/Secret: explicit override -> ~/.employmaxing/oauth-apps.json -> env -> bundled defaults."""
    spec = OAUTH_SPECS[provider]
    user_apps = _load_user_oauth_apps(store).get(provider, {})
    bundled = _load_bundled_oauth_defaults().get(provider, {})
    existing = load_active_mail_config(store)
    active_cid = existing.get("client_id", "") if existing.get("provider") == provider else ""
    active_csec = existing.get("client_secret", "") if existing.get("provider") == provider else ""

    cid = (
        override_id.strip()
        or user_apps.get("client_id", "").strip()
        or active_cid.strip()
        or os.environ.get(spec["env_client_id"], "").strip()
        or bundled.get("client_id", "").strip()
    )
    csec = (
        override_secret.strip()
        or user_apps.get("client_secret", "").strip()
        or active_csec.strip()
        or os.environ.get(spec["env_client_secret"], "").strip()
        or bundled.get("client_secret", "").strip()
    )
    return cid, csec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def get_mail_config_path(store: EmploymaxingStore) -> Path:
    return store.data_dir / "mail-config.json"


def load_active_mail_config(store: EmploymaxingStore) -> dict:
    """Load the single active mail provider configuration (never returns multiple providers)."""
    p = get_mail_config_path(store)
    cfg = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    # Env overrides for headless/CI convenience
    if os.environ.get("EMPLOYMAXING_MAIL_PROVIDER") and not cfg.get("provider"):
        cfg["provider"] = os.environ["EMPLOYMAXING_MAIL_PROVIDER"].lower()
    cfg.setdefault("daily_send_limit", 20)
    cfg.setdefault("send_delay_seconds", 4)
    return cfg


def save_single_provider_config(store: EmploymaxingStore, provider: str, settings: dict) -> dict:
    """
    STRICT SINGLE-PROVIDER ENFORCEMENT:
    Replaces any previously connected provider so only ONE provider is active at a time.
    """
    provider = provider.lower().strip()
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"Unsupported mail provider '{provider}'. Choose one of: {', '.join(ALLOWED_PROVIDERS)}")

    clean_cfg = {
        "provider": provider,
        "auth_mode": settings.get("auth_mode", "oauth2"),
        "email": (settings.get("email") or "").strip(),
        "display_name": (settings.get("display_name") or "").strip(),
        "connected": bool(settings.get("connected", False)),
        "daily_send_limit": int(settings.get("daily_send_limit", 20)),
        "send_delay_seconds": float(settings.get("send_delay_seconds", 4)),
        "updated_at": store._now(),
    }

    # Copy only fields relevant to the chosen single provider
    allowed_fields = {
        "thunderbird": ("profile_dir", "mail_dir", "inbox_files", "sent_files", "command"),
        "google": ("client_id", "client_secret", "access_token", "refresh_token", "expires_at"),
        "microsoft": ("client_id", "client_secret", "access_token", "refresh_token", "expires_at", "tenant"),
        "yahoo": ("client_id", "client_secret", "access_token", "refresh_token", "expires_at", "password", "imap_host", "imap_port", "smtp_host", "smtp_port"),
        "proton": ("password", "imap_host", "imap_port", "smtp_host", "smtp_port"),
        "custom_api": ("api_preset", "send_url", "inbox_url", "api_key", "auth_header", "auth_prefix", "from_email"),
    }
    for k in allowed_fields[provider]:
        if k in settings and settings[k] is not None:
            clean_cfg[k] = settings[k]

    if provider == "thunderbird":
        clean_cfg["auth_mode"] = "thunderbird_local"
    elif provider == "proton":
        clean_cfg.setdefault("auth_mode", "proton_bridge")
        clean_cfg.setdefault("imap_host", "127.0.0.1")
        clean_cfg.setdefault("imap_port", 1143)
        clean_cfg.setdefault("smtp_host", "127.0.0.1")
        clean_cfg.setdefault("smtp_port", 1025)
    elif provider == "yahoo" and clean_cfg.get("auth_mode") == "app_password":
        clean_cfg.setdefault("imap_host", "imap.mail.yahoo.com")
        clean_cfg.setdefault("imap_port", 993)
        clean_cfg.setdefault("smtp_host", "smtp.mail.yahoo.com")
        clean_cfg.setdefault("smtp_port", 465)

    p = get_mail_config_path(store)
    p.write_text(json.dumps(clean_cfg, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)
    store.log_event("mail_provider_configured", f"Active mail provider set to {provider.upper()} ({clean_cfg['email'] or clean_cfg['auth_mode']})")
    return clean_cfg


def disconnect_mail_provider(store: EmploymaxingStore) -> bool:
    p = get_mail_config_path(store)
    if p.exists():
        p.unlink()
        store.log_event("mail_provider_disconnected", "Disconnected active mail provider and cleared local tokens.")
        return True
    return False


def get_public_mail_status(store: EmploymaxingStore) -> dict:
    """Return UI-safe mail configuration status with ALL secrets/tokens stripped."""
    cfg = load_active_mail_config(store)
    secret_keys = {"password", "client_secret", "access_token", "refresh_token", "api_key"}
    safe = {k: v for k, v in cfg.items() if k not in secret_keys}
    provider = cfg.get("provider", "")
    has_oauth = bool(cfg.get("access_token") or cfg.get("refresh_token"))
    has_pass = bool(cfg.get("password"))
    has_api = bool(cfg.get("api_key") and cfg.get("send_url"))
    safe["configured"] = bool(provider and (has_oauth or has_pass or has_api or cfg.get("connected")))
    safe["has_client_id"] = bool(cfg.get("client_id"))
    safe["has_refresh_token"] = bool(cfg.get("refresh_token"))
    safe["oauth_ready"] = {
        prov: bool(resolve_oauth_client(store, prov)[0])
        for prov in OAUTH_SPECS
    }
    return safe


def start_oauth_flow(
    store: EmploymaxingStore,
    provider: str,
    redirect_uri: str,
    client_id: str = "",
    client_secret: str = "",
    display_name: str = "",
) -> dict:
    """Build the OAuth 2.0 + PKCE authorization URL for Google, Microsoft, or Yahoo."""
    provider = provider.lower().strip()
    if provider not in OAUTH_SPECS:
        raise ValueError(f"OAuth2 sign-in is supported for google, microsoft, and yahoo (got '{provider}').")

    spec = OAUTH_SPECS[provider]
    cid, csec = resolve_oauth_client(store, provider, client_id, client_secret)

    if not cid:
        raise ValueError(f"OAUTH_NOT_REGISTERED:{provider}")

    if client_id.strip():
        save_user_oauth_app(store, provider, cid, csec)

    state = secrets.token_urlsafe(24)
    verifier, challenge = _generate_pkce()
    _PENDING_OAUTH[state] = {
        "provider": provider,
        "client_id": cid,
        "client_secret": csec,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "display_name": display_name.strip(),
        "created_at": time.time(),
    }

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": spec["scopes"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **spec["extra_auth_params"],
    }
    auth_url = f"{spec['auth_url']}?{urllib.parse.urlencode(params)}"
    return {"provider": provider, "auth_url": auth_url, "state": state, "redirect_uri": redirect_uri}


def complete_oauth_callback(store: EmploymaxingStore, provider: str, code: str, state: str) -> dict:
    """Exchange OAuth authorization code + PKCE verifier for tokens and save as the sole active provider."""
    pending = _PENDING_OAUTH.pop(state, None)
    if not pending or pending["provider"] != provider:
        raise ValueError("Invalid or expired OAuth state token. Please start Sign-In again.")

    spec = OAUTH_SPECS[provider]
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        "client_id": pending["client_id"],
        "code_verifier": pending["code_verifier"],
    }
    if pending.get("client_secret"):
        token_payload["client_secret"] = pending["client_secret"]

    resp = requests.post(spec["token_url"], data=token_payload, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"{spec['label']} token exchange failed ({resp.status_code}): {resp.text[:300]}")
    tok = resp.json()
    access_token = tok.get("access_token", "")
    refresh_token = tok.get("refresh_token", "")
    expires_at = int(time.time()) + int(tok.get("expires_in", 3600)) - 60

    # Fetch signed-in user email & display name
    user_email = ""
    disp_name = pending.get("display_name", "")
    try:
        u_resp = requests.get(spec["userinfo_url"], headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        if u_resp.status_code == 200:
            u = u_resp.json()
            user_email = u.get("email") or u.get("mail") or u.get("userPrincipalName") or ""
            disp_name = disp_name or u.get("name") or u.get("displayName") or ""
    except Exception:
        pass

    saved = save_single_provider_config(
        store,
        provider,
        {
            "auth_mode": "oauth2",
            "email": user_email,
            "display_name": disp_name,
            "client_id": pending["client_id"],
            "client_secret": pending.get("client_secret", ""),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "connected": True,
        },
    )
    return {"provider": provider, "email": saved["email"], "display_name": saved["display_name"], "connected": True}


def ensure_valid_access_token(store: EmploymaxingStore) -> tuple[str, dict]:
    """Return a fresh OAuth2 access token, silently refreshing via refresh_token if expired."""
    cfg = load_active_mail_config(store)
    provider = cfg.get("provider", "")
    if provider not in OAUTH_SPECS:
        raise RuntimeError(f"Active provider '{provider}' does not use OAuth2 tokens.")

    now = int(time.time())
    if cfg.get("access_token") and now < int(cfg.get("expires_at", 0)):
        return cfg["access_token"], cfg

    if not cfg.get("refresh_token"):
        raise RuntimeError(f"{OAUTH_SPECS[provider]['label']} session expired and no refresh token is stored. Please sign in again.")

    spec = OAUTH_SPECS[provider]
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": cfg["refresh_token"],
        "client_id": cfg.get("client_id", ""),
    }
    if cfg.get("client_secret"):
        payload["client_secret"] = cfg["client_secret"]

    resp = requests.post(spec["token_url"], data=payload, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed refreshing {spec['label']} token ({resp.status_code}): {resp.text[:240]}")

    tok = resp.json()
    cfg["access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        cfg["refresh_token"] = tok["refresh_token"]
    cfg["expires_at"] = now + int(tok.get("expires_in", 3600)) - 60
    save_single_provider_config(store, provider, cfg)
    return cfg["access_token"], cfg
