# RUNDOC — <ITEM-ID> · <Title>

<!-- PROC-2 template, distilled from the five run-docs that shipped on
2026-07-23 (KAN-24, KAN-25, KAN-2, KAN-26+4+8, KAN-3 packet 2). Copy to
docs/projects/<item-id>-<slug>/RUNDOC.md in the item's DESIGNATED repo,
replace every <angle> placeholder, delete comments. Every section is
mandatory — a section may be short, never absent (TODO_PROCESS.md rule).
KAN-11 automates this scaffold from the board; until then it is manual. -->

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop.

## 1. Objective & definition of done

<!-- Measurable, from the todo's own words. List the exact conditions that
make this DONE — each one checkable by a command, a test, or a visible
behavior. If the work splits into packets, say which packet this run-doc
covers and what is explicitly out of scope. -->

- <condition 1>
- <condition 2>

## 2. Research (verified, <date>)

<!-- ONLY true, verified findings: file paths + line numbers from a real
sweep (Explore agent or direct reads), links actually fetched, APIs actually
checked. No speculation stated as fact — unknowns go to §5. Include the
test anchors that pin current behavior (which suites will notice this
change), and any prior-packet lessons that apply. -->

- <seam / fact with path:line>
- Test anchors: <suites that pin the behavior being changed>

## 3. KPIs & baseline

<!-- Champion/challenger frame: metric(s), CURRENT measured baseline (never
invented — if unmeasured, measuring IS step 1), target, stop condition.
Quality KPIs separate from serving KPIs. -->

| KPI | Baseline | Target |
| --- | --- | --- |
| <metric> | <measured or "unmeasured — step 1 measures"> | <target> |

## 4. Plan (bounded)

<!-- Numbered steps, each independently verifiable. End with the two lists
that make the packet enforceable: -->

1. <step>

**Allowed files**: <exact paths — the packet's whole write surface>.
**Forbidden**: <files/dirs the packet must not touch, incl. .env, configs
unless governed, and any surface owned by an unmerged PR>.

## 5. Open questions / decisions

<!-- KPI-meeting stage. Either OPEN questions blocking execution (put them
to the operator), or DECISIONS taken as documented defaults under a standing
"continue" directive — with rationale, adjustable anytime. Never start
execution with a material question silently unanswered. -->

1. <question or decision + rationale>

## 6. Model allocation (resolved live <date>)

<!-- Resolve models live (codex debug models); never a remembered slug.
Profile per the workflow doc: throughput=high for mechanical/bounded,
deep_code=xhigh for durable-state/security/hard debugging. Reviewer is
never the author. Include the fallback rule. -->

- Implementation: <profile> → <resolved model> effort <level>, isolated
  worktree off origin/main, detached launch (no wrapper timeout shorter
  than the verify phase), fail-closed on blocked verification.
- Independent review: <Fable/Opus or fresh Sol — cross-family from author>.
- Fallback: if the executor is unavailable/blocked → STOP and surface;
  never a silent self-implementation logged as routine.

## 7. Links

- Master item: [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md) → <ITEM-ID>
- Board card: `grand_todo` / `grand-todo-<item-id-lowercase>`
- Related run-docs / precedents: <links>

## 8. Execution log

<!-- Append-only. Every entry dated. Record honestly: what ran, exact
commands + exit codes, incidents (hung pipes, sandbox blocks, squash cuts)
and their lessons, the reviewer's verdict, and any deviation from §4 with
its justification. The reviewer appends the verification + verdict entry;
the implementer appends its own results (including fail-closed reports). -->

- <date> — Run-doc created from <seam-map source>; packet launching.
