# MCP Setup

Short guide for wiring an AI agent (Claude Desktop or Claude Code) to Kanberoo via the Model Context Protocol.

## What the MCP server does

`kanberoo-mcp` is a thin translator between the MCP tool protocol and the Kanberoo REST API. It runs as a subprocess of the outer agent, speaks JSON-RPC over stdio, authenticates to the Kanberoo server with its own bearer token, and surfaces a curated set of tools for AI consumption.

Tool names and descriptions are crafted so an outer agent can pick the right tool without seeing REST endpoint names. Every mutation the agent makes is attributed to the MCP token's actor (you want that to be `claude`, not `human`) and recorded in Kanberoo's audit log.

## Prerequisites

- A running Kanberoo server. Either `kb server start` (docker) or `uv run kanberoo-api` in a checkout.
- The `kanberoo[all]` pip package installed, or at minimum `kanberoo-mcp` plus `kanberoo-cli` for token creation.

## 1. Create a claude-typed token

Mint a dedicated API token with `actor_type=claude` so every mutation the agent makes is attributed correctly. The plaintext is shown exactly once, at creation time.

```bash
kb token create --actor-type claude --actor-id outer-claude --name "claude"
```

Copy the plaintext into an environment variable rather than pasting it into a config file:

```bash
export KANBEROO_MCP_TOKEN="kbr_..."
```

If you ever need to rotate it, revoke the old token with `kb token revoke` and mint a new one.

## 2. Add the server to your agent config

The config block for Claude Desktop / Claude Code's `mcpServers` section:

```json
{
  "mcpServers": {
    "kanberoo": {
      "command": "kanberoo-mcp",
      "args": ["--api-url", "http://localhost:8080", "--token-env", "KANBEROO_MCP_TOKEN"]
    }
  }
}
```

Flags:

- `--api-url`: base URL of the Kanberoo server. Use `http://localhost:8080` for the default docker compose setup.
- `--token-env`: name of an environment variable holding the token plaintext. Preferred over `--token` because the plaintext never lands on the command line or in the config file.

Restart the agent after editing its config. The MCP server will start on demand the first time the agent invokes a tool.

## 3. Smoke test

Ask the agent to list workspaces. A healthy response calls `list_workspaces` and returns something like:

```json
{
  "items": [
    {
      "id": "0191a3c0-...",
      "key": "KAN",
      "name": "My Work",
      "next_issue_num": 3,
      "version": 1
    }
  ],
  "next_cursor": null
}
```

A few failure modes and what they mean:

- `[config_error] KANBEROO_MCP_TOKEN is not set`: the env var is missing from the agent's process environment. Most agents need a restart after `export`.
- `[unauthorized] ...`: the token is wrong or revoked. Run `kb token list` to confirm, rotate if needed.
- Tool result is empty list: the server is reachable but you have not created any workspaces yet. Run `kb workspace create --key KAN --name "My Work"` and retry.

On startup the server logs a warning if the resolved token is not `actor_type=claude`. The server still runs in that case; you just get audit rows attributed to whatever actor type the token carries.

## Tool reference

Every tool the MCP server exposes, grouped by resource. Matches spec section 6.2.

| Tool | Purpose |
|------|---------|
| `list_workspaces` | Discover available workspaces with pagination. |
| `get_workspace` | Fetch one workspace by short key (`KAN`) or UUID. |
| `list_epics` | List epics inside a workspace. |
| `create_epic` | Create a new epic under a workspace. |
| `update_epic` | Patch an epic's title, description, or state. |
| `list_stories` | Search and filter stories (state, priority, tag, epic). |
| `get_story` | Full story detail including comments and linkages. |
| `create_story` | Create a new story under a workspace (epic optional). |
| `update_story` | Patch title, description, priority, branch, commit, PR. |
| `transition_story_state` | Move a story through the state machine. |
| `comment_on_story` | Post a comment or a one-level reply. |
| `link_stories` | Create a typed linkage between two stories. |
| `unlink_stories` | Remove a linkage. |
| `list_tags` | List tags inside a workspace. |
| `add_tag_to_story` | Attach a tag to a story. |
| `remove_tag_from_story` | Detach a tag from a story. |
| `get_audit_trail` | Read the audit history for a specific entity. |

`update_story` deliberately does not accept a `state` field. State changes flow through `transition_story_state` so the transition is validated against the state machine and attributed with a clean `state_changed` audit action.

## Going deeper

- [`docs/api-reference.md`](api-reference.md): the underlying REST endpoints, every schema, every status code. Useful when an MCP tool response references a schema name.
- [`docs/spec.md`](spec.md) section 6: design intent for the MCP layer.
- [`docs/future-skill-draft.md`](future-skill-draft.md): draft workflow skill for agents using Kanberoo via MCP.
