# Authelia + Caddy SSO

This opt-in tier adds a plain-HTTP Caddy forward-auth boundary behind Tailscale
Serve. Authelia is container-network-only; Caddy exposes the login portal and
one gated Stirling-PDF pilot on loopback. Stirling-PDF's existing direct
`127.0.0.1:8084` mapping remains unchanged as the desktop/loopback bypass.

Before first start:

1. Copy `authelia/users_database.yml.example` to
   `${LC_APPDATA:-appdata}/authelia/users_database.yml` and replace
   `REPLACE_WITH_REAL_ARGON2_HASH` there with a real hash (`docker run --rm
   authelia/authelia:4.39.20 authelia crypto hash generate argon2 --random`).
   This file is deliberately NOT tracked in git — `authelia/` only ships the
   secret-free `configuration.yml` template and this `.example`; the real
   database is runtime state like every other app's real credentials in this
   repo. An earlier version of this tier mounted the whole directory
   read-only from the tracked template, which would have meant committing a
   real password hash straight into git history — caught in independent
   review before merge, not after.
2. Set `LC_TAILNET_HOST` in `.env` and ensure the three Authelia secrets are
   present (`lc setup` generates them when it creates a fresh `.env`).

Start the pilot app and the opt-in SSO tier, then expose the portal through
Tailscale's TLS terminator:

```bash
tailscale serve --bg --https=9091 http://127.0.0.1:9091
```

## Cut over Stirling-PDF

Keep the phone's existing public port and repoint only its Tailscale proxy
target from Stirling-PDF to Caddy:

```bash
tailscale serve --bg --https=8084 http://127.0.0.1:9099
```

## Instant revert

Point the same public port straight back at Stirling-PDF:

```bash
tailscale serve --bg --https=8084 http://127.0.0.1:8084
```

## Add the next app

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
