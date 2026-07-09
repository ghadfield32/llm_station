# Cockpit Mobile, Open Source, and Storage Setup

Date: 2026-07-09

## Decision

Use the first-party cockpit PWA as the main app on desktop and phone. Keep
AppFlowy as an optional native-mobile fallback/projection, not the main control
plane.

This is not "AppFlowy with our name on it." The cockpit at
`services/agent_kanban_ui/` is our FastAPI + React/Vite app. The phone install
is a Progressive Web App (PWA): the browser reads `manifest.webmanifest`,
registers `sw.js`, and installs the cockpit with its own icon/name.

## What shows up on the phone

- App type: installed web app / PWA.
- Full manifest name: `Agent Kanban Cockpit`.
- Home-screen short name: `Kanban`.
- Start URL: `/` on the Tailscale HTTPS cockpit route.
- AppFlowy name/icon appears only if the user opens the AppFlowy mobile app.

It will not appear automatically. The user opens the cockpit HTTPS URL once and
chooses the phone browser install action.

## Current route status

Configured on 2026-07-09:

```text
https://vengeance.taile6a055.ts.net:8787/
-> http://127.0.0.1:8787
```

Existing AppFlowy route remains separate:

```text
https://vengeance.taile6a055.ts.net/
-> http://127.0.0.1:8081
```

The cockpit is therefore under the explicit `:8787` route, not the root
AppFlowy route.

## Phone install steps

1. Start the cockpit:

```powershell
docker compose --profile ui up -d --build agent-kanban-ui
```

2. Confirm local health:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/health
Invoke-RestMethod http://127.0.0.1:8787/manifest.webmanifest
```

3. Confirm or create the Tailscale route:

```powershell
tailscale serve status
tailscale serve --bg --https=8787 http://127.0.0.1:8787
```

4. On the phone, turn on Tailscale and sign into the same tailnet.
5. Open:

```text
https://vengeance.taile6a055.ts.net:8787/
```

6. Install:

- iPhone/iPad Safari: Share -> Add to Home Screen.
- Android Chrome/Edge/Samsung Internet: Install app or Add to Home screen.

## Current validation

Validated locally on 2026-07-09:

- `http://127.0.0.1:8787/api/health` returned `ok`.
- `http://127.0.0.1:8787/manifest.webmanifest` returned
  `name=Agent Kanban Cockpit`, `short_name=Kanban`, `display=standalone`.
- Manifest and HTML include install icons for SVG favicon, 192px/512px PNG PWA
  icons, a 512px maskable PNG icon, and `apple-touch-icon.png`.
- `http://127.0.0.1:8787/icons/apple-touch-icon.png` returned HTTP 200.
- Tailscale Serve status shows the cockpit route at
  `https://vengeance.taile6a055.ts.net:8787`.

Validated with local mobile browser emulation on 2026-07-09:

- All Boards, Controls, and Chat render at a 390px phone viewport without
  document-level horizontal overflow.
- All Boards tabs, Jobs mode tabs, wide board lanes, and Chat recent-thread
  shortcuts use top horizontal scrollbars.
- Horizontal scroll areas use momentum scrolling, gentle snap points,
  overscroll containment, and hidden bottom/native horizontal scrollbars.
- Bottom navigation is constrained to the viewport and scrolls internally.
- Long Controls file paths wrap inside their cards instead of widening the
  page.
- Chat defaults to the `chat` model role once config loads, keeps the input
  above the bottom nav, and avoids autofocus scroll jumps.

Still requires physical phone validation:

- Open the `:8787` URL on an online tailnet phone/browser.
- Install it as `Kanban`.
- Confirm Safari/Chrome touch inertia feels natural on real hardware.
- Confirm Tailscale-off failure is obvious and Tailscale-on recovery works.

## Acceptance status

Complete on the host:

- Cockpit opens locally at `http://127.0.0.1:8787`.
- Cockpit is exposed tailnet-only at
  `https://vengeance.taile6a055.ts.net:8787/`.
- Root Tailscale URL remains AppFlowy, so cockpit review must use `:8787`.
- Manifest identifies the app as `Agent Kanban Cockpit` / `Kanban`.
- Static shell assets and install icons are cacheable.
- `/api/*` and non-GET requests are not cached by the service worker.
- Main navigation is now `All Boards`, `Controls`, `Router`, `Status`,
  `Metrics`, `Activity`, and `Chat`.
- Mobile All Boards tab and lane regions use top horizontal scrollbars so phone
  users do not have to reach to the bottom of wide boards.
- All horizontal cockpit option strips now share the same mobile scroll
  contract: top scrollbar, hidden bottom scrollbar, momentum scrolling,
  proximity snap, and overscroll containment.
- Chat recent-thread shortcuts also use the same top-scrollbar pattern, so
  returning to an earlier cockpit conversation is reachable near the top of the
  phone screen. The thread list is shared through cockpit server metadata, with
  browser local storage as a fallback cache.
- Controls -> All Boards can add/remove/update domain boards by validating and
  writing `configs/domain_surfaces.yaml` in full-console mode.
- Job-search daily limits and role-focus keywords are edited through Controls
  and stored in `data/job_search/profile/search_settings.yml`.
- Focused cockpit tests and web production build pass.

## Mobile UX Plan

The mobile app is the same first-party PWA as desktop, with phone-specific
layout rules rather than a separate fork.

Navigation:

- **All Boards** is the default operating surface. Jobs, Posts, Books, Papers,
  Repos, DAGs, Upkeep, Missions, and Tasks live there.
- **Controls** is the configuration surface for board schema, job-search role
  focus, daily limits, profile defaults, and runtime APIs.
- **Chat** is the agent surface and specialist handoff surface.
- Router, Status, Metrics, and Activity stay available but are secondary on
  phone.

Touch and scrolling:

- Use top horizontal scrollbars for board tabs, board lanes, Jobs mode tabs,
  legacy board tabs, and recent chat shortcuts.
- Hide bottom/native horizontal scrollbars inside those strips to prevent two
  competing scroll affordances.
- Use momentum scrolling and proximity snap so swipes land on useful columns
  without feeling locked.
- Keep page-level horizontal overflow at zero; wide content must scroll inside
  its own contained strip.
- Keep tap targets at 44px or larger.

Cards and board movement:

- Desktop can still drag cards.
- Phone should use each card's `Move to...` menu for governed moves.
- Approve, merge, deploy, submit, and delete remain outside the cockpit action
  surface.

Chat:

- The active chat runtime is GatewayCore + LiteLLM.
- Recent chat shortcuts are shared metadata at `KANBAN_CHAT_THREADS`; full
  transcripts are not stored by this index.
- ORCA, OmniAgent/Omnigent, and OxyGent are optional external handoff links, not
  governing runtimes.

Storage and attachments:

- The cockpit backend/event log remains canonical state.
- Google Drive and OneDrive should be attachment/link providers, not the primary
  database.
- Provider OAuth, file pickers, and sync checks remain future work.

Native app decision:

- Stay PWA-first until there is a concrete need for app-store distribution,
  push notifications, background sync, or native file APIs.
- If needed later, wrap the existing PWA with Capacitor rather than rebuilding
  the app twice.

Still requires device setup/manual validation:

- Open the `:8787` URL on iPhone Safari and install it as `Kanban`.
- Open the `:8787` URL on the laptop and install it as an app.
- Confirm the same mission/card is visible on laptop and phone.
- Confirm Tailscale-off failure is obvious and Tailscale-on recovery works.
- Google Drive and OneDrive attachment connectors are not implemented yet.

## Open source recommendation

Open-source the first-party cockpit as its own project under Apache-2.0 unless
there is a strong reason to choose MIT.

Reasons:

- Apache-2.0 is permissive and includes an explicit patent grant, useful for
  company/contributor adoption.
- MIT is simpler but has less patent language.
- AppFlowy should stay an external optional integration. Forking or deeply
  modifying AppFlowy means accepting its AGPL project boundary.

Do not open-source private runtime data:

- `data/job_search/`
- generated application materials
- secrets and `.env`
- private Ledger databases
- real chat transcripts unless explicitly redacted

## Storage connector direction

Google Drive and OneDrive should not become the primary database. The cockpit
should keep canonical app state in its own backend/event log and store only
file references from cloud drives.

Provider-neutral attachment metadata:

```yaml
provider: google_drive | one_drive | local
provider_item_id: string
drive_id: string | null
name: string
mime_type: string | null
web_url: string
modified_at: datetime | null
etag: string | null
sync_token_ref: string | null
attached_to_type: job_application | mission | repo | dag | task
attached_to_id: string
```

Implementation order:

1. Picker-only MVP: user picks a Drive/OneDrive file; cockpit stores metadata.
2. Open/link support: file links render on desktop and phone.
3. Sync check: refresh changed metadata with provider delta/webhook APIs.
4. Optional upload/write support only after read/link flows are validated.

Provider setup still needed:

- Google Cloud project + OAuth client + Drive Picker/API scopes.
- Microsoft Entra app registration + Graph delegated file scopes.
- Redirect/callback URLs for the cockpit Tailscale URL or future public domain.

## Native app path

Do not rewrite natively yet. Use the PWA now. If app-store distribution, deeper
push notifications, or native file APIs become necessary, wrap the same web app
with Capacitor later.

## Agent runtime watch-list

GatewayCore + LiteLLM is the active cockpit runtime and write authority. The
Chat tab can expose optional external handoff links, but those links do not get
direct governed-write permissions.

Current comparison:

| System | Best use | Cockpit decision |
|---|---|---|
| ORCA | Document visual QA: PDFs, resumes, application packets, screenshots, tables, forms, and debate/stress-checking | Best first optional specialist for job materials; configure with `ORCA_CHAT_URL` when a real endpoint exists |
| OmniAgent / Omnigent | Long video, audio/video evidence, screen recordings, and active inspection of relevant moments | Later specialist, useful only after video/audio evidence enters the workflow; configure with `OMNIAGENT_CHAT_URL` or `OMNIGENT_CHAT_URL` |
| OxyGent | Modular agent/tool/model components, dynamic planning, visual debugging, and auditability | Framework watch-list/spike; configure `OXYGENT_CHAT_URL` only for an external dashboard or pilot |

Current references:

- ORCA: `https://arxiv.org/abs/2603.02438`
- OmniAgent: `https://arxiv.org/abs/2606.19341`
- OxyGent: `https://github.com/jd-opensource/OxyGent` and
  `https://arxiv.org/abs/2604.25602`

Do not add any of these as a runtime dependency until a scoped pilot proves it
improves the cockpit without weakening the Ledger/action wall.
