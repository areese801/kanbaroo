---
name: kanbaroo-cage-bridge
description: |
  Use this skill when running cage-orchestrator workflows on a project
  that's wired up to Kanbaroo (the kanbaroo MCP server is active and
  mcp__kanbaroo__* tools are visible). Triggers when the user is about
  to dispatch a cage and a Kanbaroo story will represent the work.
  Augments cage-orchestrator's flow with story creation, progress
  comments, and a summary on export. No-ops gracefully if Kanbaroo
  MCP is not configured.
---

# Kanbaroo ↔ trusty-cage Bridge Skill

## Purpose

When an outer Claude session has BOTH the trusty-cage `cage-orchestrator`
skill AND the Kanbaroo MCP active, this skill mirrors cage dispatch
lifecycle events onto the Kanbaroo board. The cage runs the work; the
Kanbaroo story is the durable, audit-logged record of that work.

If either side is missing — no `mcp__kanbaroo__*` tools visible, or no
identifiable Kanbaroo workspace for the project — this skill no-ops and
`cage-orchestrator` runs untouched. See "No-Op Invariant" below.

## Relationship to Other Skills

- **`cage-orchestrator`** (trusty-cage plugin) owns the cage lifecycle:
  `tc launch`, monitoring the outbox, `tc inbox`, `tc export`. It
  drives every `tc` command. This skill never invokes `tc` directly.
- **`kanbaroo-workflow`** (sibling skill in this plugin) covers the
  general Kanbaroo workflow — story discovery, manual transitions,
  comment etiquette, attribution rules. The bridge is the cage-specific
  layer on top.

When both this skill and `kanbaroo-workflow` are active, defer to
`kanbaroo-workflow`'s wiring check, workspace discovery, and attribution
etiquette. This skill only adds the four hooks below.

## No-Op Invariant (load-bearing)

The bridge **does not activate** if any of the following are true:

- The `mcp__kanbaroo__*` tools are not in the session's tool list.
- The project has no `.mcp.json` referencing a `kanbaroo` MCP entry, or
  the token file referenced there does not resolve.
- No Kanbaroo workspace can be identified for the project (per the
  workspace-discovery rules in `kanbaroo-workflow`).

In any of those cases, do not attempt any of the four hooks below. Do
not surface errors to the user. Do not retry. Cage-orchestrator runs
exactly as it would without this skill installed.

This invariant is non-negotiable: the bridge must never block or
slow down a cage dispatch on a project that is not wired up to
Kanbaroo.

## The Four Hook Points

The hook numbering follows `cage-orchestrator`'s step list. If that
skill renumbers, re-anchor by name rather than by number.

### Hook 1 — Before Dispatch (cage-orchestrator Step 7: Launch Inner Claude)

Before `tc launch` fires:

- **If the user references an existing story** (e.g. "let's work on
  KAN-123"):
  1. Call `mcp__kanbaroo__get_story` to pull the full story context
     (title, description, comments, linkages, current state).
  2. Embed the story's human ID and a condensed context block into the
     cage task prompt that `cage-orchestrator` is composing.
  3. Surface the human ID to `cage-orchestrator` so it can also set it
     as a launch-time environment variable (commonly `KANBAROO_STORY_ID`)
     for the inner Claude. This lets the inner Claude reference the
     story in commit messages and PR descriptions.
  4. If the story is in `backlog` or `todo`, ask the user whether to
     transition it to `in_progress` before dispatch. If they confirm,
     call `mcp__kanbaroo__transition_story_state`.

- **If no story exists yet** for this dispatch:
  1. Draft a story title and description in markdown with the user.
     Keep the title action-oriented and under 80 chars.
  2. Confirm the workspace and (optionally) epic with the user before
     creating.
  3. Call `mcp__kanbaroo__create_story`. Surface the new human ID to
     the user.
  4. Call `mcp__kanbaroo__transition_story_state` to move the new
     story to `in_progress`.
  5. Embed the new human ID into the cage prompt and the launch
     environment as above.

The active story's human ID and UUID should be held in session memory
so subsequent hooks can address it without re-asking.

### Hook 2 — During Monitoring (cage-orchestrator Step 8: Monitor Progress)

Each `progress_update` message that `cage-orchestrator` surfaces from
the cage's outbox becomes a `mcp__kanbaroo__comment_on_story` call
against the active story.

**Throttle aggressively.** Comment edit and delete are not available
via MCP — once a comment is posted, it cannot be cleaned up by you.
Apply these rules before posting:

- If a `progress_update` arrives within 5 minutes of the last comment
  this skill posted, **batch or skip**. Either combine the new content
  into a single deferred comment (preferred) or drop it entirely if
  it is purely a heartbeat / "still working" duplicate of the previous
  one.
- If the cage emits more than one `progress_update` per minute over a
  sustained window, post a single rolled-up comment when the cadence
  settles rather than mirroring each event.
- Errors and `going_idle` messages are not throttled; post them
  promptly so the user can see them on the board.

Format each comment so it renders cleanly in the web UI. A condensed
status line plus a fenced code block for any structured detail is a
good default:

```
**Cage progress** — running tests

`detail: 3 of 5 passing`
```

### Hook 3 — After tc export (cage-orchestrator Step 9: Export)

Once `cage-orchestrator` runs `tc export` and surfaces the export
result, post a single summary comment to the active story. It should
include:

- A one-line summary of what changed.
- The list of files changed, as reported by `cage-orchestrator`.
- The output of `tc diff --stats` (or whatever stats summary
  `cage-orchestrator` provides), wrapped in a fenced markdown code
  block so the web UI renders it cleanly.

Example shape:

```markdown
**Cage exported.** Summary: <one line>.

Files changed:

- packages/kanbaroo-core/src/foo.py
- packages/kanbaroo-api/tests/test_foo.py

```text
 2 files changed, 47 insertions(+), 3 deletions(-)
```
```

After the summary comment is posted, ask the user whether to
`transition_story_state` to `in_review` (if a PR is being opened) or
`done` (if the work is complete and merged outside the cage). Do not
transition unilaterally — completion is a human judgment per
`kanbaroo-workflow`'s attribution etiquette.

### Hook 4 — On Revision (cage-orchestrator Step 11: Revision Decision)

When the user provides `task_revision` instructions for the cage:

1. **Comment first.** Post the revision instructions as a comment on
   the active story before `cage-orchestrator` runs `tc inbox`. The
   comment captures *what was asked of the cage* — invaluable when
   future-you reconstructs why a particular revision happened. Format
   it so the instructions are clearly demarcated, e.g.:

   ```markdown
   **Revision sent to cage.**

   ```text
   <verbatim task_revision instructions>
   ```
   ```

2. **Then `tc inbox`.** Hand back to `cage-orchestrator` to push the
   revision into the cage's inbox. The bridge does not invoke `tc`
   itself.

If the user provides revision instructions verbally without a
`task_revision` payload, paraphrase them faithfully into the comment
before `cage-orchestrator` formalizes the inbox message.

## Attribution Etiquette

The same per-project attribution rules apply as in
`kanbaroo-workflow`:

- Comments and state transitions are stamped with the active token's
  `actor_id` (typically `claude-<project-slug>`). You do not pass an
  actor on tool calls; the server stamps it from the token.
- Do not forge a different actor or attempt to imitate the user.
- The bridge's comments are highly visible on the board; write them
  like a PR comment, not like a chat message.
- Don't transition stories to `done` without explicit user
  confirmation, even when `tc export` has succeeded.

## Limitations

- **Comments cannot be edited or deleted via MCP.** Be especially
  careful with progress comments that may turn out to be wrong in
  retrospect — a misleading "tests passing" mid-flight comment cannot
  be corrected silently. When in doubt, post less.
- **`get_audit_trail` may 404** in Phase 1 (the underlying REST
  endpoint is not yet wired). If the bridge wants to surface audit
  history, expect failures and degrade gracefully.
- **`tc` invocation is owned by `cage-orchestrator`.** That skill
  handles the local-venv vs globally-installed `tc` selection
  (`venv/bin/tc` preference) and every `tc launch` / `tc inbox` /
  `tc export` call. The bridge only reacts to messages that
  `cage-orchestrator` surfaces; it never shells out to `tc` itself.
- **One active story per dispatch.** The bridge assumes a single
  Kanbaroo story represents the cage's work. If the user wants to
  span multiple stories, mirror only the primary one and let the
  others be linked manually via `kanbaroo-workflow`.

## Checklist Before Each Hook

1. Are the `mcp__kanbaroo__*` tools available in this session? If
   not, no-op.
2. Is there a known active story for this dispatch? If not, you are
   in Hook 1 territory — create or attach one before posting any
   comments.
3. Throttle window check (Hook 2 only): has more than 5 minutes
   passed since this skill's last comment on the active story?
4. Will the comment I'm about to post still be useful in a week, or
   is it noise? Default to less.
5. Am I about to transition state? If yes, the user must have
   confirmed.
