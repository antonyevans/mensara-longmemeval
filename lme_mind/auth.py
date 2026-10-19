"""Sign in to a Mind the way Codex and Claude do: OAuth with dynamic client registration and PKCE.

`python -m lme_mind login --mind-url https://<your-mind>/mcp` opens your browser once. Tokens are
kept, readable only by you, in ~/.mensara-longmemeval/<host>.json and refreshed automatically.
(On Windows the file gets your user profile's permissions.) A signed-in owner writes at the
Mind's normal trust level, so imports apply directly and the
harness can approve its own delete proposals. (A personal access token from `mint_owner_token`
works for reading but its writes wait for approval, so the harness does not use one.)
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

REDIRECT_PORT = 53682
REDIRECT = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPE = "openid profile email offline_access"


class AuthError(RuntimeError):
    pass


def _http_json(url: str, *, json_body=None, form=None) -> dict:
    headers = {"accept": "application/json", "user-agent": "mensara-longmemeval/1"}
    data = None
    if json_body is not None:
        data, headers["content-type"] = json.dumps(json_body).encode(), "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["content-type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise AuthError(f"{url} returned {exc.code}: {exc.read().decode(errors='replace')[:200]}") from None


def store_path(mind_url: str) -> Path:
    override = os.environ.get("MENSARA_TOKEN_FILE")
    if override:
        return Path(override)
    host = urllib.parse.urlsplit(mind_url).hostname
    return Path.home() / ".mensara-longmemeval" / f"{host}.json"


def _save(path: Path, record: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def logout(mind_url: str) -> None:
    store_path(mind_url).unlink(missing_ok=True)


def _stamp(tokens: dict) -> dict:
    return {**tokens, "expires_at": time.time() + int(tokens.get("expires_in", 300))}


def check_url(mind_url: str) -> None:
    host = urllib.parse.urlsplit(mind_url).hostname or ""
    if not mind_url.startswith("https://") and host not in {"127.0.0.1", "localhost"}:
        raise AuthError("the Mind URL must start with https://")


def login(mind_url: str) -> Path:
    check_url(mind_url)
    base = mind_url.split("/mcp")[0]
    resource = _http_json(base + "/.well-known/oauth-protected-resource")
    meta = _http_json(resource["authorization_servers"][0].rstrip("/")
                      + "/.well-known/oauth-authorization-server")
    client_id = _http_json(meta["registration_endpoint"], json_body={
        "client_name": "mensara-longmemeval", "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none"})["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(12)
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "scope": SCOPE, "resource": resource["resource"]})
    got: dict = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            got.update(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab.")

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Callback)
    threading.Thread(target=server.handle_request, daemon=True).start()
    print(f"Sign in to your Mind in the browser. If it does not open, visit:\n{url}")
    webbrowser.open(url)
    deadline = time.time() + 600
    while not got and time.time() < deadline:
        time.sleep(0.5)
    server.server_close()
    if got.get("state") != state or not got.get("code"):
        raise AuthError(f"sign-in did not complete: {got.get('error', 'no callback')}")
    tokens = _http_json(meta["token_endpoint"], form={
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier, "resource": resource["resource"]})
    path = store_path(mind_url)
    _save(path, {"client_id": client_id, "resource": resource["resource"], "mcp_url": mind_url,
                 "token_endpoint": meta["token_endpoint"], "tokens": _stamp(tokens)})
    return path


def access_token(mind_url: str, force_refresh: bool = False) -> str:
    """A current access token, refreshed when it is within a minute of expiring."""
    check_url(mind_url)
    path = store_path(mind_url)
    if not path.exists():
        raise AuthError(f"not signed in; run: python -m lme_mind login --mind-url {mind_url}")
    record = json.loads(path.read_text(encoding="utf-8"))
    tokens = record["tokens"]
    if not force_refresh and tokens.get("expires_at", 0) - 60 > time.time():
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        raise AuthError("sign-in expired; run login again")
    fresh = _http_json(record["token_endpoint"], form={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        "client_id": record["client_id"], "resource": record["resource"]})
    fresh.setdefault("refresh_token", tokens["refresh_token"])
    record["tokens"] = _stamp(fresh)
    _save(path, record)
    return record["tokens"]["access_token"]
