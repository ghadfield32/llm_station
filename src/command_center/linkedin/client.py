"""LinkedIn official-API client: 3-legged OAuth + text post creation.

Verified against LinkedIn's versioned REST API (Marketing/Community Management):
  authorize : GET  {auth_base}/authorization?response_type=code&client_id=...
  token     : POST {auth_base}/accessToken   (form-encoded)
  member id : GET  {userinfo_url}            -> sub  -> urn:li:person:{sub}
  publish   : POST {api_base}{posts_path}    (LinkedIn-Version + Restli 2.0.0)

Design rules (match the repo standards):
  - No silent fallback. Anything unexpected raises LinkedInError; the publisher
    leaves the row In Progress so it retries, rather than pretending success.
  - No hardcoded API constants in the publisher: endpoints/scopes/version come
    from configs/content.yaml (the LinkedInApi contract).
  - Secrets only from the environment (the .env keys named in content.yaml).
  - Media/image posting is NOT implemented yet; create_post refuses non-text
    posts loudly instead of dropping the media (no fake "success").
"""
from __future__ import annotations

import json
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx


class LinkedInError(RuntimeError):
    """Any LinkedIn auth/publish failure. Raised loudly; never swallowed."""


@dataclass
class TokenStore:
    """Persisted OAuth token (gitignored JSON under generated/)."""
    path: Path
    access_token: str = ""
    expires_at: float = 0.0
    refresh_token: str = ""
    refresh_expires_at: float = 0.0
    member_urn: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "TokenStore":
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(path=p, **{k: data.get(k, getattr(cls, k, ""))
                              for k in ("access_token", "expires_at", "refresh_token",
                                        "refresh_expires_at", "member_urn")})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "access_token": self.access_token, "expires_at": self.expires_at,
            "refresh_token": self.refresh_token,
            "refresh_expires_at": self.refresh_expires_at,
            "member_urn": self.member_urn,
        }, indent=2), encoding="utf-8")

    @property
    def valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at


class _CodeCatcher(BaseHTTPRequestHandler):
    """One-shot handler that captures the ?code= from LinkedIn's redirect."""
    code: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _CodeCatcher.code = params.get("code", [None])[0]
        _CodeCatcher.error = params.get("error_description", params.get("error", [None]))[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "LinkedIn authorization received - you can close this tab." \
            if _CodeCatcher.code else f"Authorization failed: {_CodeCatcher.error}"
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

    def log_message(self, *a):  # silence the default stderr logging
        return


class LinkedInClient:
    def __init__(self, api, env: dict[str, str]):
        """`api` is the validated LinkedInApi contract; `env` is the merged
        .env/os.environ map. Missing required secrets raise immediately."""
        self.api = api
        self.client_id = self._require(env, api.client_id_env)
        self.client_secret = self._require(env, api.client_secret_env)
        self.redirect_uri = self._require(env, api.redirect_uri_env)
        self.tokens = TokenStore.load(api.token_store)

    @staticmethod
    def _require(env: dict[str, str], key: str) -> str:
        value = env.get(key, "")
        if not value:
            raise LinkedInError(f"missing required env value {key}")
        return value

    # ----- OAuth -----
    def authorize_url(self, scopes: list[str], state: str) -> str:
        q = urllib.parse.urlencode({
            "response_type": "code", "client_id": self.client_id,
            "redirect_uri": self.redirect_uri, "state": state,
            "scope": " ".join(scopes),
        })
        return f"{self.api.auth_base}/authorization?{q}"

    def login(self, scopes: list[str]) -> None:
        """Interactive 3-legged OAuth. Opens a browser, captures the redirect on
        the redirect_uri's host/port, exchanges the code, persists the token."""
        parsed = urllib.parse.urlparse(self.redirect_uri)
        host, port = parsed.hostname or "localhost", parsed.port or 80
        state = f"cc-{int(time.time())}"
        url = self.authorize_url(scopes, state)
        print(f"Opening LinkedIn authorization in your browser:\n  {url}\n"
              f"Listening on {host}:{port}{parsed.path} for the redirect...")
        _CodeCatcher.code = _CodeCatcher.error = None
        server = HTTPServer((host, port), _CodeCatcher)
        webbrowser.open(url)
        server.handle_request()  # blocks until LinkedIn redirects back once
        server.server_close()
        if not _CodeCatcher.code:
            raise LinkedInError(f"no authorization code received: {_CodeCatcher.error}")
        self._exchange_code(_CodeCatcher.code)
        self.resolve_member_urn()
        self.tokens.save()
        print(f"Authorized. Token stored at {self.tokens.path} "
              f"(expires {time.strftime('%Y-%m-%d', time.localtime(self.tokens.expires_at))}).")

    def _exchange_code(self, code: str) -> None:
        r = httpx.post(f"{self.api.auth_base}/accessToken", data={
            "grant_type": "authorization_code", "code": code,
            "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
        }, timeout=30)
        self._apply_token_response(r)

    def _refresh(self) -> None:
        if not (self.tokens.refresh_token and time.time() < self.tokens.refresh_expires_at):
            raise LinkedInError("access token expired and no valid refresh token; "
                                "run `cc linkedin-publish --login` again")
        r = httpx.post(f"{self.api.auth_base}/accessToken", data={
            "grant_type": "refresh_token", "refresh_token": self.tokens.refresh_token,
            "client_id": self.client_id, "client_secret": self.client_secret,
        }, timeout=30)
        self._apply_token_response(r)
        self.tokens.save()

    def _apply_token_response(self, r: httpx.Response) -> None:
        if r.status_code != 200:
            raise LinkedInError(f"token exchange failed [{r.status_code}]: {r.text[:300]}")
        body = r.json()
        self.tokens.access_token = body["access_token"]
        self.tokens.expires_at = time.time() + int(body["expires_in"])
        if body.get("refresh_token"):
            self.tokens.refresh_token = body["refresh_token"]
            self.tokens.refresh_expires_at = time.time() + int(
                body.get("refresh_token_expires_in", 0))

    def _ensure_token(self) -> str:
        if not self.tokens.access_token:
            raise LinkedInError("no LinkedIn token; run `cc linkedin-publish --login` first")
        if not self.tokens.valid:
            self._refresh()
        return self.tokens.access_token

    # ----- identity -----
    def resolve_member_urn(self) -> str:
        """The person URN for member posts, from the OIDC userinfo `sub`."""
        if self.tokens.member_urn:
            return self.tokens.member_urn
        token = self._ensure_token()
        r = httpx.get(self.api.userinfo_url,
                      headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code != 200:
            raise LinkedInError(f"userinfo failed [{r.status_code}]: {r.text[:300]}")
        sub = r.json().get("sub")
        if not sub:
            raise LinkedInError("userinfo returned no `sub` (member id)")
        self.tokens.member_urn = f"urn:li:person:{sub}"
        return self.tokens.member_urn

    def list_admined_orgs(self) -> list[str]:
        """Organization URNs the authenticated member administers (approved),
        via organizationAcls. Needs an org scope (Community Management API);
        raises loudly on 403 so the caller knows to re-login with --include-org.
        Lets you read the WMS Page URN instead of hunting it in the admin UI."""
        r = httpx.get(
            f"{self.api.api_base}/v2/organizationAcls",
            params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
            headers={"Authorization": f"Bearer {self._ensure_token()}",
                     "LinkedIn-Version": self.api.version,
                     "X-Restli-Protocol-Version": "2.0.0"}, timeout=30)
        if r.status_code != 200:
            raise LinkedInError(f"organizationAcls failed [{r.status_code}]: "
                                f"{r.text[:300]} (org scope required - re-run "
                                "--login --include-org)")
        urns = [e.get("organizationalTarget") or e.get("organization")
                for e in r.json().get("elements", [])]
        return [u for u in urns if u]

    # ----- publish -----
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._ensure_token()}",
                "LinkedIn-Version": self.api.version,
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json"}

    def create_text_post(self, author_urn: str, text: str) -> str:
        """Publish a text post; returns the created post URN. Raises on any
        non-success so the caller never records a fake publish."""
        if not text.strip():
            raise LinkedInError("refusing to publish an empty post body")
        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED",
                             "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = httpx.post(f"{self.api.api_base}{self.api.posts_path}",
                       headers=self._headers(), json=payload, timeout=30)
        if r.status_code not in (200, 201):
            raise LinkedInError(f"post failed [{r.status_code}]: {r.text[:400]}")
        urn = r.headers.get("x-restli-id") or r.json().get("id", "")
        if not urn:
            raise LinkedInError(f"post returned no id; headers={dict(r.headers)}")
        return urn
