# Passwords and SSO runbook

Two related but distinct systems. Don't conflate them:

- **Vaultwarden** — passive storage. Holds a unique, strong password per app.
  It cannot log into anything, generate an app's password for you, or push a
  rotation anywhere. It stores what you put in it and autofills it back.
- **Authelia + Caddy (the `sso` tier)** — an opt-in forward-auth gate that puts
  ONE login (with mandatory 2FA) in front of specific apps, so you stop needing
  a separate password for those apps at all. Currently fronts exactly one app
  (Stirling-PDF, the pilot). See `sso/README.md` for the gate's own design,
  the exact cutover/revert commands, and the phased-rollout plan.

Every credential in this system is either **in Vaultwarden** or it's wrong.
`.env`, `catalog.py`, and this repo's git history must never hold a real
credential value — only variable/item *names* (see `Auth.credential_ref` and
`Auth.password_manager_item_ref` in `catalog.py`).

## Why rotation can't be automated — the real reason, not a policy statement

Vaultwarden's master password is the encryption key for everything inside it.
For anything to auto-write a new password into the vault, that automation
would need the master key sitting somewhere a script can reach — which
destroys the exact property the vault exists to provide (one key, held only
by the human, unlocks everything else). This is true for Vaultwarden's own
master password by definition, and it's *chosen* to be true for the Authelia
SSO credential too, because that credential now guards every app admitted
behind it — the same single-point-of-failure reasoning applies.

Nothing here is "not automated yet." It's not automated on purpose.

## The correct pattern: human-in-the-loop rotation

For **every** app-specific password (Nextcloud, Immich, Paperless, Calibre-Web,
etc. — anything with its own login):

1. Log into the app with its current password.
2. In Vaultwarden, open (or create) that app's item → click the password
   generator (⟳) → generate a new one.
3. Change the password **inside the app** to the generated value.
4. **Save the vault item before leaving the app's password-change page.** If
   you change the app's password first and the browser extension doesn't
   save it, you're locked out of both the app and the record of what you set.
5. Set `Auth.password_manager_item_ref` on that service's `catalog.py` entry
   to the Vaultwarden item name (e.g. `"vaultwarden:Immich"`), so the Kanban
   reflects real migration status instead of staying silently stale.

For the **Authelia SSO credential** specifically (the one exception, because
you can't log into Authelia to change Authelia's own password the normal way
if you're mid-rotation):

1. In Vaultwarden's `Authelia SSO` item, click the password generator.
2. Hash it: `docker run --rm authelia/authelia:4.39.20 authelia crypto hash
   generate argon2 --password '<new password>'` (or `--random` to have the
   tool generate and hash together in one step, avoiding the value ever
   appearing twice).
3. Put the resulting `$argon2id$...` string into
   `${LC_APPDATA}/authelia/users_database.yml`'s `password:` field. This file
   is gitignored runtime state — **never** the tracked
   `sso/authelia/users_database.yml.example`, which must only ever contain
   the literal placeholder `REPLACE_WITH_REAL_ARGON2_HASH`. An earlier draft
   of this tier got this wrong and staged a real hash into a tracked file;
   caught in independent review before merge, not after — see PR #93's
   history for exactly what that looked like.
4. Restart: `docker compose --project-directory . --env-file .env -f
   compose/foundation.yml -f compose/sso.yml up -d --force-recreate authelia`
5. Verify live before trusting it — don't just assume the restart worked:
   ```
   curl -s -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" \
     -d '{"username":"ghadfield32","password":"<new password>"}' \
     https://<LC_TAILNET_HOST>:9091/api/firstfactor
   ```
   `200` = the new password authenticates. Anything else, stop and check
   `docker logs lc-authelia` before touching anything further.
6. Update the Vaultwarden item's saved password to match. If 2FA also needs
   re-enrolling (only if you're resetting the whole account, not for a plain
   password rotation), the flow is: fresh login → `POST
   /api/user/session/elevation` → read the one-time code from
   `docker exec lc-authelia cat /data/notification.txt` (filesystem notifier,
   pilot-phase only, see `sso/README.md`'s known limitations) → `PUT` that
   code back to the same endpoint → `PUT
   /api/secondfactor/totp/register` with `{"algorithm":"SHA1","period":30,
   "digits":6,"length":6}` → save the returned `base32_secret` into
   Vaultwarden's Authenticator key (TOTP) field *before* confirming — Bitwarden-
   compatible vaults display a live, refreshing code once that field holds a
   real secret, which is what you actually enter to complete registration.

## Which apps are password-eligible, and current status

Everything with its own login is eligible. As of this rollout:

| App | Status |
|---|---|
| Immich, Linkwarden, Homebox, Mealie | Provisioned via each app's own API earlier this session; unique credentials, not yet confirmed saved to Vaultwarden — verify `password_manager_item_ref` is set before trusting the badge |
| Nextcloud, Paperless-ngx, Calibre-Web, Uptime Kuma, FreshRSS, AdGuard, Home Assistant, Audiobookshelf, Jellyfin | Human-driven migration, per-app, following the loop above. Check each entry's `password_manager_item_ref` for real status |
| Authelia SSO | **Done** — unique password + TOTP in Vaultwarden, verified live |
| Vaultwarden itself | Not eligible — its master password cannot be stored inside itself by definition |
| Dockge, restic | Never — see `sso/README.md`'s explicit "Never" list; Dockge is Docker-socket-privileged and desktop-loopback-only by design, restic's password guards every backup and losing it is unrecoverable |

**The catalog is the source of truth for status, not this table** — this table
is a snapshot from the day this runbook was written. Check
`Auth.password_manager_item_ref` per `catalog.py` entry (surfaced on the
Kanban Life Center Services board) for what's actually current.

## Phone and desktop access — already solved, don't rebuild it

Every link above (Authelia's portal, the gated app) resolves through the same
`LC_TAILNET_HOST` scheme the rest of this catalog uses — `lc.py`'s
`_tailnetify()` rewrites `http://127.0.0.1:<port>` links to
`https://<LC_TAILNET_HOST>:<port>` whenever that env var is set, which is why
these same URLs work identically from the phone and the desktop without a
separate mobile path. Nothing SSO-specific was needed here; it inherited the
existing mechanism.
