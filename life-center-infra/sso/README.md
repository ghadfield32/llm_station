# Authelia SSO: forward-auth and native OIDC

This opt-in tier supports two distinct integration styles behind Tailscale
Serve:

- **Forward-auth:** Caddy checks every request with Authelia before proxying to
  an app that has no usable native OIDC support. Stirling-PDF is the pilot.
- **Native OIDC:** the app is an OIDC relying party and exchanges tokens with
  Authelia directly. Mealie is the pilot; requests to Mealie do not pass
  through Caddy forward-auth.

Authelia remains container-network-only. Caddy exposes its login/OIDC portal
on loopback for Tailscale Serve and still exposes the separate Stirling-PDF
forward-auth pilot. Both apps retain their existing direct loopback mappings.

Before first start:

1. Copy `authelia/users_database.yml.example` to
   `${LC_APPDATA:-appdata}/authelia/users_database.yml` and replace
   `REPLACE_WITH_REAL_ARGON2_HASH` there with a real hash (`docker run --rm
   authelia/authelia:4.39.20 authelia crypto hash generate argon2 --random`).
   This file is deliberately NOT tracked in git — `authelia/` only ships the
   plaintext-secret-free `configuration.yml` template and this `.example`;
   the real database is runtime state like every other app's real credentials
   in this repo. An earlier version of this tier mounted the whole directory
   read-only from the tracked template, which would have meant committing a
   real password hash straight into git history — caught in independent
   review before merge, not after.
2. For Mealie account linking, add `email: 'changeme@example.com'` to the
   runtime Authelia user so it exactly matches the existing Mealie account
   (Mealie's default admin email, never changed in this pilot). Keep that
   Mealie user's authentication method unchanged; a non-OIDC user can use
   both the existing password and OIDC in Mealie v2.6.0. **Known
   identity-confusion risk, flagged in independent review and accepted for
   this single-user pilot, not fixed**: Mealie v2.6.0 looks up accounts by
   this email/username claim and does not pin to `sub`, so any Authelia user
   later assigned this same generic email would authenticate as this Mealie
   account. Before admitting a second real household user, change Mealie's
   admin email to something unique first, then update this field to match.
3. Generate the RSA issuer keypair (minimum 2048 bits; this pilot used 4096)
   and place ONLY the private key at
   `${LC_APPDATA:-appdata}/authelia/oidc-issuer-private.pem`, permissions
   tightened to owner-read-only (`chmod 600`) on any host where that's
   meaningful (no-op on Windows, real on this repo's actual target Linux
   host):
   ```bash
   docker run --rm authelia/authelia:4.39.20 authelia crypto pair rsa generate --directory /tmp -b 4096
   # docker cp the resulting /tmp/private.pem out of that container, discard public.pem
   ```
   It is mounted read-only at `/config/oidc-issuer-private.pem`; `appdata/`
   and `*.pem` are already gitignored.
4. Generate Mealie's OIDC client secret and its Argon2id digest together in
   one step, so the plaintext is never typed twice:
   ```bash
   docker run --rm authelia/authelia:4.39.20 authelia crypto hash generate argon2 --random
   ```
   Put the plaintext `Random Password` value in `.env` as
   `MEALIE_OIDC_CLIENT_SECRET` (Mealie receives it directly). Put the
   `Digest` value, with no trailing newline, at
   `${LC_APPDATA:-appdata}/authelia/mealie-client-secret-hash.txt` — **not**
   directly in `configuration.yml`. An Argon2id digest still enables offline
   guessing if it were committed, same reasoning as step 1's user password
   hash; `configuration.yml` loads it at runtime via
   `{{ secret "/config/mealie-client-secret-hash.txt" }}`, the same templating
   mechanism used for the RSA key above. An earlier version of this pilot
   embedded the digest directly in the tracked `configuration.yml` — caught
   in independent review before merge, not after.
5. Set `LC_TAILNET_HOST` in `.env` and ensure the five Authelia/Mealie secrets
   are present (`lc setup` generates values when it creates a fresh `.env`).
6. Expose Mealie's own port through Tailscale Serve if it isn't already (the
   OIDC redirect_uri is Mealie's existing public URL, not a new one, but the
   mapping must exist for the browser leg of the flow to reach it):
   ```bash
   tailscale serve --bg --https=9925 http://127.0.0.1:9925
   ```

Start the pilot apps and the opt-in SSO tier, then expose the portal through
Tailscale's TLS terminator:

```bash
tailscale serve --bg --https=9091 http://127.0.0.1:9091
```

## Native OIDC: Mealie

Mealie uses the public Authelia issuer:

```text
https://<LC_TAILNET_HOST>:<CADDY_AUTH_PORTAL_PORT>/.well-known/openid-configuration
```

This is intentional. Authelia does not support split public and internal OIDC
endpoints, and fetching discovery directly from `http://authelia:9091` would
advertise internal HTTP authorization and token endpoints. The browser and
Mealie backend must therefore use the same HTTPS issuer URL.

Before admitting OIDC, verify from inside Mealie that Docker DNS and routing on
the deployment host can reach that tailnet URL:

```bash
docker exec lc-mealie python -c \
  'import json, os, urllib.request; d=json.load(urllib.request.urlopen(os.environ["OIDC_CONFIGURATION_URL"])); print(d["issuer"]); print(d["token_endpoint"])'
```

Both printed URLs must use the public tailnet host and portal port. Docker does
not universally inherit host MagicDNS behavior. If this probe fails, fix
container DNS/routing to the public issuer; do not point Mealie at Authelia's
internal HTTP address. Authelia's documented Docker alternative is to put the
relying party and reverse proxy on a shared network and give the proxy the
issuer FQDN as a network alias, but that Caddy networking change is deliberately
outside this pilot's scope.

`OIDC_SIGNUP_ENABLED=false` makes this an account-linking pilot rather than a
second account-creation path. `OIDC_AUTO_REDIRECT=false` keeps the normal login
screen and the tested local-password fallback visible.

Mealie v2.6.0 starts Uvicorn with its `HOST_IP` setting as
`forwarded_allow_ips`; the image default is `*`. No Compose `command:` override
is required for Tailscale Serve's forwarded scheme/host headers.

### The one config that actually blocked login, found only by testing to completion

`identity_providers.oidc.clients[].claims_policy` (referencing a
`claims_policies` entry with `id_token: [email, name]`) is **required**.
Without it, Authelia issues an ID token with only the standard claims
(`sub`, `aud`, `iss`, ...) even when the client requests and is granted the
`email`/`profile` scopes — by design, Authelia puts no identity-revealing
claims in the ID token unless a policy explicitly says to. The token exchange
itself succeeds (`POST /api/oidc/token` returns 200), so this failure is easy
to miss if you stop verifying at "did the redirect happen" — Mealie's backend
only surfaces it as `[OIDC] Required claims not present. Expected: {'name',
'email'}` in its own logs, and returns a generic `401 Unauthorized` to the
client. Full login was proven working end-to-end (initiation → Authelia
1FA+2FA → consent → real authorization code → Mealie's actual
`/api/auth/oauth/callback` → a genuine Mealie access token whose `sub` matches
the existing linked admin account, not a new one) only after adding this
policy — not before.

## Forward-auth: Stirling-PDF

### Cut over

Keep the phone's existing public port and repoint only its Tailscale proxy
target from Stirling-PDF to Caddy:

```bash
tailscale serve --bg --https=8084 http://127.0.0.1:9099
```

### Instant revert

Point the same public port straight back at Stirling-PDF:

```bash
tailscale serve --bg --https=8084 http://127.0.0.1:8084
```

## Choose the pattern for the next app

Use native OIDC when the pinned app version has a maintained, verified
Authorization Code flow, supports a confidential client, and can preserve its
tested local login fallback. Register one least-privilege Authelia client and
verify account linking and backend reachability.

Use forward-auth when the app lacks usable native OIDC. In that case:

1. Add one new Caddy site block on a new container port: use the same
   `forward_auth` block (including the `Cookie` header-stripping line — the
   `authelia_session` cookie is domain-scoped, not port-scoped, so every app
   behind this tier receives it unless each site block strips it), then
   `reverse_proxy` the app's `lc_core` service name and container port.
2. Add a loopback-only host mapping for that Caddy port in `compose/sso.yml`.
3. Repoint that app's existing `tailscale serve` public port to the new Caddy
   host port. Keep the app's direct loopback mapping as its local bypass.

## Known limitations — deliberate for a pilot-only, single-user phase

- **Notifier is filesystem-based** (`/data/notification.txt` inside the
  Authelia container), not SMTP. Fine for a single operator who can read that
  file directly (used during setup to complete the identity-elevation step
  for 2FA registration); Authelia's own docs call this notifier
  testing-only. Replace with a real SMTP notifier before this tier fronts
  Phase 3/4's sensitive apps (Paperless, AdGuard, Home Assistant).
- **Images are version-tagged, not digest-pinned** — consistent with every
  other service in this repo (all carry the same `pin: @sha256 before real
  data` comment, none pinned yet). Not an SSO-specific gap.
