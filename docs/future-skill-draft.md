---
name: kanbaroo-workflow
description: |
  [DRAFT - NEEDS TUNING AFTER PHASE 1 IS BUILT]

  Use this skill when working with Kanbaroo, a kanban tool for managing software
  work across workspaces, epics, and stories. Triggers when the user asks to:
  work on a specific story by its human ID (e.g. "let's work on KAN-123"),
  review what's in progress or up next, create stories from a planning session,
  comment on or transition stories, or otherwise interact with the Kanbaroo
  board. Also triggers when the user is deep in a coding session and identifies
  follow-up work that should be captured on the board rather than held in
  context. Works standalone on any Kanbaroo instance; optionally integrates
  with trusty-cage for delegating story implementation to isolated inner Claude
  sessions.
---

# Kanbaroo Workflow Skill

> **DRAFT STATUS**: This skill was written during Kanbaroo's design phase, before
> the MCP server was implemented. Tool names, parameter shapes, and specific
> workflows below reflect *intended* behavior and will need to be reconciled
> against the actual MCP implementation once available. Anywhere this skill
> says "the MCP exposes `tool_name`", verify against the real tool list before
> relying on it. Sections marked `TUNE:` are explicit pointers to things that
> likely need revision.

## Purpose

Kanbaroo is a kanban-style issue tracker. This skill teaches you (outer Claude)
how to use its MCP tools to help the user manage work, and how to integrate that
workflow with a coding session.

## Core Mental Model

Kanbaroo has a three-level hierarchy:

- **Workspace**: A product, project, or engagement. Each workspace has a short
  key (e.g. `KAN`) used as a prefix for human-readable story IDs.
- **Epic** (optional): A container for related stories, usually a milestone or
  major feature. Stories may or may not belong to an epic.
- **Story**: The unit of work. Roughly one pull request. Human ID like `KAN-123`.

Stories move through a fixed state machine:
`backlog → todo → in_progress → in_review → done`, with a rework loop from
`in_review` back to `in_progress` and a reopen path from `done`.

Every mutation is attributed to an actor (`human`, `claude`, or `system`). When
you act on Kanbaroo via MCP, your mutations are stamped `claude`. When the user
acts via the TUI or CLI, mutations are stamped `human`. This distinction is
visible in the audit log and the UI.

## When to Use This Skill

Use it proactively when:

- The user names a story by its human ID and asks to work on it, discuss it,
  or check its state.
- The user is wrapping up a coding session and has identified follow-up work
  that should become new stories.
- The user asks "what's on my plate" or "what's in progress" or similar
  board-level questions.
- The user wants to add a comment, link two stories, change a priority, or
  move a story through the state machine.

Do **not** use it when:

- The user is asking about a story on a different platform (Jira, Linear,
  GitHub Issues). Different tools.
- The user is venting about their backlog without asking for a specific action.
- The user explicitly says "don't touch the board."

## Available MCP Tools

> **TUNE**: Verify this list against the actual `kanbaroo-mcp` server. The tool
> names and parameter shapes below are the design intent; the implementation
> may differ.

The `kanbaroo` MCP server exposes these tools. Full descriptions live on the
tools themselves; this is a quick reference.

**Reading:**
- `list_workspaces` — discover workspaces
- `get_workspace` — workspace with counts
- `list_stories` — search and filter (by workspace, state, priority, tag, epic, text)
- `get_story` — full story detail including comments and linkages
- `list_epics` — under a workspace
- `get_audit_trail` — history of a specific entity
- `list_tags` — workspace-scoped tags

**Writing:**
- `create_story` — new story under a workspace (epic optional)
- `update_story` — patch title, description, priority, branch, commit, PR URL
- `transition_story_state` — move through the state machine
- `comment_on_story` — new comment or reply
- `link_stories` — create a typed linkage (relates_to, blocks, etc.)
- `unlink_stories` — remove a linkage
- `create_epic` / `update_epic` — epic lifecycle
- `add_tag_to_story` / `remove_tag_from_story` — tag management

**Not available via MCP** (requires human):
- Token management
- Soft-delete restoration
- Workspace deletion

## Standard Workflows

### Workflow 1: "Let's work on KAN-123"

1. `get_story` with the human ID. Read title, description, comments, linkages,
   current state.
2. Summarize the story for the user: what it is, where it stands, any blockers
   from its linkages, relevant recent comments.
3. If the story is in `backlog` or `todo`, ask whether you should transition it
   to `in_progress` before starting.
4. If the user confirms, `transition_story_state` to `in_progress`. This stamps
   `actor_type=claude` on the state change.
5. Proceed with the actual work. Keep the story's branch name, commit SHA, and
   eventual PR URL in mind; these should be written back to the story when
   available via `update_story`.
6. When work is done, ask the user whether to transition the story to
   `in_review` (if PR exists) or `done` (if already merged).

### Workflow 2: "Capture this as a story"

When the user identifies follow-up work mid-session:

1. Draft the story title and description in markdown. Keep title under 80 chars,
   action-oriented ("Add X", "Fix Y", not "X is broken").
2. Show the draft to the user for approval before calling `create_story`.
3. Ask which workspace if ambiguous. Ask whether it belongs under an existing
   epic (use `list_epics` to show options) or directly under the workspace.
4. Ask about priority. Default to `none` if the user doesn't have a strong
   opinion; it's cheap to set later.
5. `create_story` with the confirmed values. Surface the new human ID to the
   user.

### Workflow 3: "What's in progress?"

1. `list_stories` filtered by `state=in_progress` for the relevant workspace(s).
2. For each, note priority, last update, any blocking linkages (you may need
   `get_story` to see linkages in detail).
3. Present as a compact list, flagging anything that's been in progress a long
   time or is blocked.

### Workflow 4: Integration with trusty-cage

> **TUNE**: This section assumes the cage orchestrator and the Kanbaroo skill
> are both active. Coordinate with the `cage-orchestrator` skill.

When delegating a story's implementation to an inner Claude via trusty-cage:

1. `get_story` to pull full context (title, description, comments, linkages).
2. Transition to `in_progress` if not already there.
3. Compose the cage prompt from the story's description plus any relevant
   comments. Include the story's human ID in the prompt so the inner Claude
   can reference it in commit messages.
4. Launch the cage via `tc launch` (cage-orchestrator skill handles this).
5. Monitor the cage outbox. When the inner Claude signals completion:
   - `update_story` with the branch name and commit SHA.
   - Ask the user whether to `transition_story_state` to `in_review` or `done`.
   - Optionally `comment_on_story` with a summary of what was done.
6. If the inner Claude signals it's blocked or needs input, relay to the user
   and optionally `comment_on_story` to capture the blocker.

## Attribution Etiquette

You stamp `actor_type=claude` on everything you do. Keep this in mind:

- **Don't close stories unilaterally.** Even if the code looks done, ask the
  user before transitioning to `done`. Humans should confirm completion.
- **Comments from you are visible as Claude comments.** Write them like you'd
  write a PR comment: useful, specific, and attributable. Don't write "I did
  this" as if you were the user.
- **Don't invent priority.** If the user didn't set a priority and didn't ask
  you to, leave it `none`. Priority is a human judgment.
- **Respect the audit log.** Everything you do is logged. Don't try to be
  clever with batch updates that obscure what changed.

## Error Handling

- **Optimistic concurrency conflicts (412)**: Another actor modified the entity
  between your read and your write. Refetch, re-evaluate, and retry or ask the
  user.
- **Not found (404)**: The human ID might be wrong. Ask the user to confirm.
- **Validation errors (400)**: Surface the error details to the user; don't
  guess at the fix.

## Things This Skill Does NOT Handle

- **Creating workspaces or epics from scratch as a greenfield planning
  exercise.** That's a bigger conversation; ask the user to do it via the TUI.
- **Bulk operations** (moving 10 stories at once). Phase 1 MCP doesn't support
  these cleanly; iterate one at a time or defer.
- **Anything outside Kanbaroo.** If the user wants to mirror to Jira or post
  to Slack, that's out of scope.

## Checklist Before Committing a Mutation

1. Did the user ask for this specific action, or am I inferring?
2. Am I operating on the right workspace and story? (Re-read the human ID.)
3. Am I about to transition state? If yes, did I confirm with the user?
4. Am I about to delete something? (Soft deletes are recoverable, but still
   confirm.)
5. Is my comment or description well-formed markdown?

If you're unsure on any of these, stop and confirm with the user.

---

## Revision Notes

> **TUNE** this skill after phase 1 of Kanbaroo is implemented. Specifically:
>
> 1. Reconcile the tool list in "Available MCP Tools" against the actual
>    `kanbaroo-mcp` server output.
> 2. Update parameter shapes and example calls based on real tool signatures.
> 3. Validate the workflows end-to-end by running through each one manually.
> 4. Coordinate with the `cage-orchestrator` skill on the handoff protocol
>    described in Workflow 4.
> 5. Consider adding a short "common pitfalls" section based on actual usage
>    patterns observed in the first few weeks.
