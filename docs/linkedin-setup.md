# LinkedIn content pipeline — setup runbook

The ordered, do-this-then-that path to take the content pipeline live. Design and
architecture are in [MASTER.md §6.6](MASTER.md); this is the operator checklist.

**Mental model.** Claude Code drafts posts onto two AppFlowy boards as *In Queue*.
You approve by dragging a card to *In Progress* (that drag is the only thing that
authorizes a post — the agent can't). A scheduled publisher (`cc linkedin-publish`)
posts each approved, due card to LinkedIn's official API and moves it to *Completed*.
It is the **only** thing that publishes; there is no MCP or second path.

**Check where you are at any time** (offline, reads real state, prints no secrets):

```
cc linkedin-publish --preflight
```

It prints an OK/MISSING line per requirement and names the single next action.
Already green right now: the two boards, the 60 drafts, and the config. Everything
below is the remaining work, in order.

---

## 1. Create the LinkedIn Developer app

**Identities:** the personal board posts to your personal *profile* (`author:
member`); the WMS board posts to a company **Page** (`author: organization`). A
profile is not a Page. **One** developer app + **one** OAuth login from you covers
*both* — you don't need two apps.

**Prerequisite — the WMS Company Page must exist** (it's the thing the org board
posts to and the thing the app is linked to). If it doesn't exist yet: LinkedIn →
*For Business* → *Create a Company Page* (free, ~5 min); you become its **super
admin** automatically. If it already exists and you admin it, skip this.

At <https://www.linkedin.com/developers/apps> → **Create app**.

1. Associate the app with the **World Model Sports LLC** Page (the app must be
   linked to a Page you admin; use the WMS Page so org posting is possible later).
   This link is ownership only — it does not stop the app posting as your personal
   profile too.
2. On the app's **Settings**, complete **Page verification** — click **Verify**
   next to the associated Page, open the generated URL as the Page's super admin,
   confirm. **Do this before step 4's Community Management API request**: until the
   app is verified against the Page, that product's "Request access" button is
   **disabled**.
3. On **Auth**, add the **Authorized redirect URL** exactly:
   `http://localhost:3000/callback` (must match `LINKEDIN_REDIRECT_URI`).
4. On **Products**, request:
   - **Sign In with LinkedIn using OpenID Connect** (grants `openid profile`)
   - **Share on LinkedIn** (grants `w_member_social` — personal posting)
   - **Community Management API** (grants `w_organization_social` — WMS Page
     posting). Requires Page verification first (step 2), and is then **reviewed
     by LinkedIn** — a use-case form, decided by email over days, and not
     guaranteed for a brand-new app. Personal posting works without it, so don't
     wait on it. **Fallback until it clears:** publish WMS posts by hand — the
     board drafts them; open the WMS Page → *Start a post* → paste. Only the final
     click is manual; `--apply` takes over once the scope is granted.

Why these and nothing more: the pipeline only needs to *post*. No `email`, no read
scopes — least privilege (`configs/content.yaml` `member_scopes`/`organization_scopes`).

## 2. Put the app credentials in `.env`

Copy the values from the app's **Auth** tab into the gitignored `.env`
(`.env.example` documents them):

```
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
LINKEDIN_REDIRECT_URI=http://localhost:3000/callback
```

Never commit these or paste them into YAML, `.mcp.json`, logs, or AppFlowy.

## 3. Confirm the API version, then validate

LinkedIn's `LinkedIn-Version` header is monthly **YYYYMM** and each version is sunset
~12 months after release. Open
<https://learn.microsoft.com/linkedin/marketing/integrations/recent-changes>, read
the current **Latest**, and set it in `configs/content.yaml` → `linkedin.version`
(it is `202605` as of 2026-06-13; bump it when LinkedIn deprecates the month). Then:

```
cc validate
cc linkedin-publish --preflight
```

Preflight should now show the app creds as OK and point you to `--login`.

## 4. Authorize personal posting

Request personal scopes only first (don't gate the personal path on the org review):

```
cc linkedin-publish --login
```

A browser opens for consent; the publisher catches the redirect on
`localhost:3000/callback`, exchanges the code, resolves your member URN, and stores
the token at `generated/linkedin-token.json` (gitignored). The token lasts ~60 days;
every `--apply` prints its expiry — re-run `--login` before it lapses.

## 5. Live-smoke ONE personal post

1. In AppFlowy open `geoffhadfield32_content`. Pick one low-stakes draft. **Read it
   and its `Source`**, edit freely.
2. Set `Format = Text`, leave `Media` empty (image posting is not wired yet — the
   publisher refuses non-text loudly rather than dropping the image).
3. Set `ScheduledFor` to now (or a moment in the past) and drag it to **In Progress**.
4. Dry-run just this account — it should list exactly that one row:

   ```
   cc linkedin-publish --account geoffhadfield32_content
   ```

5. Publish it:

   ```
   cc linkedin-publish --account geoffhadfield32_content --apply
   ```

   Confirm all four: the post is live on LinkedIn · the card is **Completed** ·
   `PostURN` is set · `PublishedAt` is set. If publishing succeeds but the card
   doesn't move, just re-run `--apply` — the durable ledger reconciles it and will
   **not** post twice.

## 6. Activate the WMS Page (only after Community Management API approval)

Treat this as a separate gate — do not assume it works because personal did.

1. Re-authorize including org scope:

   ```
   cc linkedin-publish --login --include-org
   ```

2. Read the Page URN straight from LinkedIn (no manual hunting through vanity
   slugs) and set `LINKEDIN_WMS_ORG_URN=urn:li:organization:<id>` in `.env`:

   ```
   cc linkedin-publish --orgs
   ```

3. Repeat step 5's one-post smoke for `--account world_model_sports_content`.

## 7. One-time AppFlowy UI cleanup

REST can't do these:

- On each board's **Board** view, confirm **Group by → Status** (so you see the
  In Queue / In Progress / Completed columns).
- Delete the 3 blank starter rows each grid ships with (right-click → delete).

## 8. Schedule the publisher (do this LAST)

Only after both relevant live smokes pass. Windows Task Scheduler — run whether
logged in or not, restart on failure, log to a rotating file, one host only (the
in-code process lock also prevents overlap):

```powershell
$Repo = "C:\Users\ghadf\vscode_projects\docker_projects\llm_station"
Register-ScheduledTask -TaskName "LinkedInContentPublisher" `
  -Action (New-ScheduledTaskAction -Execute "$Repo\.venv\Scripts\python.exe" `
    -Argument "-m command_center.cli.linkedin_publish --apply" -WorkingDirectory $Repo) `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15))
```

The 15-minute cadence is operational, not load-bearing (one post/account/day) — the
publisher only ships rows whose `ScheduledFor` is due, so cadence just sets timing
granularity.

---

## Daily operation (after setup)

- **Claude Code drafts** more posts into *In Queue* (re-run the seed or ask Claude to
  add cards; `scripts/seed_content.py` is clobber-safe — it never overwrites a card
  you've moved).
- **You review + approve** by dragging *In Queue → In Progress* and setting
  `ScheduledFor`.
- The scheduled publisher does the rest and stamps *Completed*.
- `cc linkedin-publish` (no flags) any time = dry-run preview of what's due.
- A card stuck after an ambiguous send shows as `RECONCILE_REQUIRED` in the ledger
  (`generated/linkedin-published.json`) and is never auto-retried — resolve by hand.

## Token renewal (every ~60 days — there is no auto-login)

LinkedIn issues standard apps a ~60-day access token and **no refresh token**, so
there is no way to stay authorized indefinitely — a human must re-run
`cc linkedin-publish --login` before it lapses. The tool reminds you:

- `--preflight` and every `--apply` print a `WARN`/`WARNING` line starting
  `token_warn_days` before expiry (14 by default; `configs/content.yaml`
  `linkedin.token_warn_days`), e.g. *"LinkedIn token expires in 9d (2026-08-12)…"*.
- The scheduled publisher's log carries the same warning each run. Because that's
  easy to miss, also put a calendar reminder a week before the printed expiry date
  (a `/schedule` routine, or a dated card on the `todos` board).
- After re-`--login`, `--preflight` shows the new `valid until` date — nothing else
  changes (same boards, drafts, org URN).
