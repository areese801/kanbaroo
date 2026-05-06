---
name: kanbaroo-workflow
description: |
  Use this skill when working with Kanbaroo, a kanban-style issue tracker for
  managing software work across workspaces, epics, and stories. Triggers when
  the user asks to: work on a specific story by its human ID (e.g. "let's work
  on KAN-123"), review what's in progress or up next, create stories from a
  planning session, comment on or transition stories, or otherwise interact
  with the Kanbaroo board. Also triggers when the user is deep in a coding
  session and identifies follow-up work that should be captured on the board
  rather than held in context. Works standalone on any Kanbaroo instance;
  optionally integrates with trusty-cage for delegating story implementation
  to isolated inner Claude sessions.
---

# Kanbaroo Workflow Skill

## Purpose

Kanbaroo is a kanban-style issue tracker. This skill teaches you (outer Claude)
how to use its MCP tools to help the user manage work, and how to integrate
that workflow with a coding session.

## Core Mental Model

Kanbaroo has a three-level hierarchy:

- **Workspace**: A product, project, or engagement. Each workspace has a short
  key (e.g. `KAN`) used as a prefix for human-readable story IDs.
- **Epic** (optional): A container for related stories, usually a milestone or
  major feature. Stories may or may not belong to an epic.
- **Story**: The unit of work. Roughly one pull request. Human ID like
  `KAN-123`.

Stories move through a fixed state machine:
`backlog → todo → in_progress → in_review → done`, with a rework loop from
`in_review` back to `in_progress` and a reopen path from `done`.

Every mutation is attributed to an actor (`human`, `claude`, or `system`).
When you act on Kanbaroo via MCP, your mutations are stamped `claude`. When
the user acts via the TUI or CLI, mutations are stamped `human`. This
distinction is visible in the audit log and the UI.

## Per-Project Attribution

Kanbaroo's owner runs a single shared instance and points multiple Claude
Code sessions at it — one per project they work on. Each project gets its
own bearer token with a distinct `actor_id`, so the audit log can tell which
project's outer Claude did what.

Convention: `actor_id = claude-<project-slug>`. Examples: `claude-kanbaroo`,
`claude-diff-donkey`, `claude-snippets`. The actor is set at token-mint
time; you do not pass it in tool calls. Trust that whatever token the MCP
server is launched with already carries the right `actor_id` for the
current project.

What this means in practice:

- Don't worry about authoring as the wrong actor; you can't.
- When summarizing audit history to the user, refer to actors by their
  `actor_id` (e.g. "claude-diff-donkey moved this to in_progress").
- If you see the audit log show actions stamped as a different
  `claude-<other-project>` actor on a workspace you're operating in, that's
  another project's outer Claude legitimately reaching across workspaces —
  not an error.

## Wiring Check (Run This First)

Before doing anything Kanbaroo-related, confirm the current project is
wired up:

1. Look for a `.mcp.json` at the project root (`<cwd>/.mcp.json`). It
   should contain a `kanbaroo` mcpServers entry pointing at
   `kanbaroo-mcp` with `--token-file` set.
2. Look for the `mcp__kanbaroo__*` tools in your tool list. If they're
   absent, the MCP server didn't start — usually because Claude Code was
   launched before the wiring landed.

If wiring is missing or the token file referenced by `.mcp.json` doesn't
exist, do not improvise. Tell the user:

> "This project doesn't look wired up to Kanbaroo yet. Want me to walk
> you through `kb project init`? It creates the workspace, mints a
> per-project token, and writes the `.mcp.json` in one shot. You'll need
> to restart Claude Code afterward for the MCP entry to activate."

If the user agrees, the host CLI command is:

```bash
kb project init [--key KEY --name "Name" --actor-id claude-<slug>]
```

It accepts `--dry-run` and `--json`. Defaults derive everything sensible
from the cwd basename. After running, the user must restart Claude Code in
that project for the new MCP server to be picked up. Don't try to use the
new tools in the same session — they're only available after restart.

Only fire this prompt once per session, and only when the user has
already brought up Kanbaroo concepts (a story human ID, "the board",
asking about work to pick up). Don't volunteer it in plain coding
sessions.

## Discover the Active Workspace

Stories are workspace-scoped. Before any non-trivial workflow, pin down
which workspace you're operating in:

1. **Check `~/.kanbaroo/config.toml` for `default_workspace`.** If set,
   that's the user's preferred default and should be your first guess.
2. **Infer from the project's `.mcp.json` actor_id.** A token with
   `actor_id=claude-diff-donkey` strongly implies workspace key `DD` (or
   similar — `DIFFDONK`, derived from the project's cwd basename).
3. **Ask the user.** If neither signal is conclusive — or if the user's
   request mentions a story human ID with a different workspace prefix —
   ask before acting.

When you've identified the active workspace, pin it for the rest of the
session unless the user redirects.

## When to Use This Skill

Use it proactively when:

- The user names a story by its human ID and asks to work on it, discuss
  it, or check its state.
- The user is wrapping up a coding session and has identified follow-up
  work that should become new stories.
- The user asks "what's on my plate" or "what's in progress" or similar
  board-level questions.
- The user wants to add a comment, link two stories, change a priority,
  or move a story through the state machine.

Do **not** use it when:

- The user is asking about a story on a different platform (Jira, Linear,
  GitHub Issues). Different tools.
- The user is venting about their backlog without asking for a specific
  action.
- The user explicitly says "don't touch the board."

## Available MCP Tools

The `kanbaroo` MCP server exposes these tools. Full descriptions live on
the tools themselves; this is a quick reference of what's wired and known
to work.

**Reading:**
- `list_workspaces` — discover workspaces
- `get_workspace` — workspace with counts
- `list_stories` — search and filter (by workspace, state, priority, tag,
  epic, text)
- `get_story` — full story detail including comments and linkages
- `list_epics` — under a workspace
- `list_tags` — workspace-scoped tags

**Reading (limited):**
- `get_audit_trail` — history of a specific entity. The MCP tool exists,
  but the underlying REST endpoint
  (`GET /audit/entity/{entity_type}/{id}`) is not yet wired in Phase 1.
  Calls may 404 until the endpoint lands. If you need audit history,
  flag this to the user rather than retrying.

**Writing:**
- `create_story` — new story under a workspace (epic optional)
- `update_story` — patch title, description, priority, branch, commit,
  PR URL
- `transition_story_state` — move through the state machine
- `comment_on_story` — new comment or reply
- `link_stories` — create a typed linkage (relates_to, blocks, etc.)
- `unlink_stories` — remove a linkage
- `create_epic` / `update_epic` — epic lifecycle
- `add_tag_to_story` / `remove_tag_from_story` — tag management

**Not available via MCP** (requires human via CLI/TUI/web):
- Token management (`kb token create` etc.)
- Tag creation and deletion (you can attach existing tags but can't mint
  new ones)
- Comment edit and delete (your typo lives forever — write carefully)
- Soft-delete and restoration of stories, epics, workspaces
- Workspace creation (use `kb project init` or the web UI)

## Standard Workflows

### Workflow 1: "Let's work on KAN-123"

1. `get_story` with the human ID. Read title, description, comments,
   linkages, current state.
2. Summarize the story for the user: what it is, where it stands, any
   blockers from its linkages, relevant recent comments.
3. If the story is in `backlog` or `todo`, ask whether you should
   transition it to `in_progress` before starting.
4. If the user confirms, `transition_story_state` to `in_progress`. This
   stamps your `actor_id` on the state change.
5. Proceed with the actual work. Keep the story's branch name, commit
   SHA, and eventual PR URL in mind; these should be written back to
   the story when available via `update_story`.
6. When work is done, ask the user whether to transition the story to
   `in_review` (if PR exists) or `done` (if already merged).

### Workflow 2: "Capture this as a story"

When the user identifies follow-up work mid-session:

1. Draft the story title and description in markdown. Keep title under
   80 chars, action-oriented ("Add X", "Fix Y", not "X is broken").
2. Show the draft to the user for approval before calling `create_story`.
3. Ask which workspace if ambiguous (use the active workspace from the
   discovery step above as the default). Ask whether it belongs under
   an existing epic (use `list_epics` to show options) or directly
   under the workspace.
4. Ask about priority. Default to `none` if the user doesn't have a
   strong opinion; it's cheap to set later.
5. `create_story` with the confirmed values. Surface the new human ID
   to the user.

### Workflow 3: "What's in progress?"

1. `list_stories` filtered by `state=in_progress` for the active
   workspace (or, if the user asks across all, repeat per workspace
   from `list_workspaces`).
2. For each, note priority, last update, any blocking linkages (you
   may need `get_story` to see linkages in detail).
3. Present as a compact list, flagging anything that's been in progress
   a long time or is blocked.

### Workflow 4: Integration with trusty-cage

The companion `kanbaroo-cage-bridge` skill (shipped in this plugin)
automates the hooks below when both `cage-orchestrator` and the
Kanbaroo MCP are active in the same session. If the bridge skill is
not active — or you are driving the integration manually — the steps
below describe what to do by hand:

1. `get_story` to pull full context (title, description, comments,
   linkages).
2. Transition to `in_progress` if not already there.
3. Compose the cage prompt from the story's description plus any
   relevant comments. Include the story's human ID in the prompt so
   the inner Claude can reference it in commit messages.
4. Launch the cage via `tc launch` (cage-orchestrator skill handles
   this).
5. Monitor the cage outbox. When the inner Claude signals completion:
   - `update_story` with the branch name and commit SHA.
   - Ask the user whether to `transition_story_state` to `in_review`
     or `done`.
   - Optionally `comment_on_story` with a summary of what was done.
6. If the inner Claude signals it's blocked or needs input, relay to
   the user and optionally `comment_on_story` to capture the blocker.

## Attribution Etiquette

You stamp your `actor_id` (`claude-<project-slug>`) on everything you do.
Keep this in mind:

- **Don't close stories unilaterally.** Even if the code looks done,
  ask the user before transitioning to `done`. Humans should confirm
  completion.
- **Comments from you are visible as Claude comments.** Write them like
  you'd write a PR comment: useful, specific, and attributable. Don't
  write "I did this" as if you were the user.
- **Don't invent priority.** If the user didn't set a priority and
  didn't ask you to, leave it `none`. Priority is a human judgment.
- **Respect the audit log.** Everything you do is logged with your
  `actor_id`. Don't try to be clever with batch updates that obscure
  what changed.
- **Comment edit and delete aren't available to you.** Compose comments
  carefully — typos and reconsidered drafts will require human cleanup.

## Error Handling

- **Optimistic concurrency conflicts (412)**: Another actor modified the
  entity between your read and your write. Refetch, re-evaluate, and
  retry or ask the user.
- **Not found (404)**: The human ID might be wrong, OR the audit
  endpoint may not be wired (see `get_audit_trail` note above). Ask
  the user to confirm.
- **Validation errors (400)**: Surface the error details to the user;
  don't guess at the fix.
- **Permission errors**: Token resolution may have failed. Suggest the
  user check `~/.kanbaroo/tokens/claude-<project-slug>` exists and is
  readable, and that `.mcp.json` points at the right path.

## Things This Skill Does NOT Handle

- **Creating workspaces or epics from scratch as a greenfield planning
  exercise.** That's a bigger conversation; ask the user to do it via
  `kb project init` (for workspaces) or the TUI/web UI (for epics).
- **Bulk operations** (moving 10 stories at once). Phase 1 MCP doesn't
  support these cleanly; iterate one at a time or defer.
- **Anything outside Kanbaroo.** If the user wants to mirror to Jira or
  post to Slack, that's out of scope.

## Checklist Before Committing a Mutation

1. Did the user ask for this specific action, or am I inferring?
2. Am I operating on the right workspace and story? (Re-read the human
   ID; check the active-workspace pin.)
3. Am I about to transition state? If yes, did I confirm with the user?
4. Am I about to soft-delete something? Soft-deletes are recoverable in
   theory, but the schema currently has UNIQUE constraints that block
   key reuse after delete (Kanbaroo bug KAN-11). Confirm with the user
   before any soft-delete.
5. Is my comment or description well-formed markdown?

If you're unsure on any of these, stop and confirm with the user.
