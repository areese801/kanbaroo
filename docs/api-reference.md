# Kanbaroo REST API

Generated file. Do not edit by hand. Run `uv run python scripts/build_api_reference.py` to regenerate.

Source: `packages/kanbaroo-api/src/kanbaroo_api/` OpenAPI schema.


## Endpoints

### audit

- `GET /api/v1/audit` - List Audit
    Return a newest-first page of audit events with filters applied.
  - Response `200` (Successful Response) -> `AuditListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/audit/entity/{entity_type}/{entity_id}` - List Audit For Entity
    Return a newest-first page of audit events for a single entity.
  - Response `200` (Successful Response) -> `AuditListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

### comments

- `DELETE /api/v1/comments/{comment_id}` - Soft Delete Comment
    Soft-delete a comment. Requires ``If-Match: <version>``. Does not
    cascade to replies.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/comments/{comment_id}` - Get Comment
    Return a single comment. Responds with ``404`` if the id is
    unknown or soft-deleted (unless ``include_deleted`` is set).
  - Response `200` (Successful Response) -> `CommentRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `PATCH /api/v1/comments/{comment_id}` - Update Comment
    Patch a comment's body. Requires ``If-Match: <version>``; a
    mismatch returns 412. ``parent_id`` is intentionally not patchable.
  - Request body: `CommentUpdate`
  - Response `200` (Successful Response) -> `CommentRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/stories/{story_id}/comments` - List Comments
    Return every comment on ``story_id`` chronologically.
  - Response `200` (Successful Response) -> `CommentListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/stories/{story_id}/comments` - Create Comment
    Create a new comment on ``story_id`` and return it with ETag and
    Location headers. Threading is limited to one level; replies to
    replies are rejected with ``400 validation_error``.
  - Request body: `CommentCreate`
  - Response `201` (Successful Response) -> `CommentRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

### epics

- `GET /api/v1/epics/by-key/{human_id}` - Get Epic By Human Id
    Return an epic by its ``{KEY}-{N}`` human identifier.
    
    Mirrors :func:`get_story_by_human_id`; the CLI uses this so that
    the ``--epic KAN-N`` flag can be translated to a UUID without a
    workspace-wide list scan.
  - Response `200` (Successful Response) -> `EpicRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `DELETE /api/v1/epics/{epic_id}` - Soft Delete Epic
    Soft-delete an epic. Requires ``If-Match: <version>``; does not
    cascade to the epic's stories.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/epics/{epic_id}` - Get Epic
    Return a single epic. Responds with ``404`` if the id is unknown
    or the row is soft-deleted (unless ``include_deleted`` is set).
  - Response `200` (Successful Response) -> `EpicRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `PATCH /api/v1/epics/{epic_id}` - Update Epic
    Patch an epic. Requires ``If-Match: <version>``; a mismatch
    returns 412.
  - Request body: `EpicUpdate`
  - Response `200` (Successful Response) -> `EpicRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/epics/{epic_id}/close` - Close Epic
    Convenience endpoint that sets the epic's state to ``closed``.
    Idempotent; requires ``If-Match``.
  - Response `200` (Successful Response) -> `EpicRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/epics/{epic_id}/reopen` - Reopen Epic
    Convenience endpoint that sets the epic's state to ``open``.
    Idempotent; requires ``If-Match``.
  - Response `200` (Successful Response) -> `EpicRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/workspaces/{workspace_id}/epics` - List Epics
    Return a page of epics belonging to ``workspace_id``.
  - Response `200` (Successful Response) -> `EpicListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/workspaces/{workspace_id}/epics` - Create Epic
    Create a new epic inside ``workspace_id`` and return it with ETag
    and Location headers.
  - Request body: `EpicCreate`
  - Response `201` (Successful Response) -> `EpicRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

### linkages

- `POST /api/v1/linkages` - Create Linkage
    Create a linkage. ``blocks`` / ``is_blocked_by`` pairs are
    auto-mirrored on the other endpoint; other link types are
    unidirectional.
  - Request body: `LinkageCreate`
  - Response `201` (Successful Response) -> `LinkageRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `DELETE /api/v1/linkages/{linkage_id}` - Delete Linkage
    Soft-delete a linkage. The mirror end is soft-deleted in the same
    transaction for blocking pairs. No ``If-Match`` required.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/stories/{story_id}/linkages` - List Story Linkages
    Return every linkage touching ``story_id`` (as source or target),
    ordered by creation time.
  - Response `200` (Successful Response) -> `LinkageListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

### stories

- `GET /api/v1/stories/by-key/{human_id}` - Get Story By Human Id
    Return a story by its ``{KEY}-{N}`` human identifier.
  - Response `200` (Successful Response) -> `StoryRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `DELETE /api/v1/stories/{story_id}` - Soft Delete Story
    Soft-delete a story. Requires ``If-Match: <version>``.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/stories/{story_id}` - Get Story
    Return a single story. Responds with ``404`` if the id is unknown
    or the row is soft-deleted (unless ``include_deleted`` is set).
  - Response `200` (Successful Response) -> `StoryRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `PATCH /api/v1/stories/{story_id}` - Update Story
    Patch a story. Requires ``If-Match: <version>``; a mismatch returns
    412. State transitions go through the dedicated transition
    endpoint, not this one.
  - Request body: `StoryUpdate`
  - Response `200` (Successful Response) -> `StoryRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/stories/{story_id}/tags` - Add Tags To Story
    Associate tags with a story. Idempotent: already-associated tags
    are silently skipped. Cross-workspace tagging returns 400
    ``validation_error``. No ``If-Match`` required (association is
    orthogonal to story version).
  - Request body: `StoryTagAddRequest`
  - Response `200` (Successful Response) -> `StoryRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `DELETE /api/v1/stories/{story_id}/tags/{tag_id}` - Remove Tag From Story
    Remove a tag from a story. Idempotent: removing a non-associated
    tag is a no-op and does not emit an audit row. No ``If-Match``
    required.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/stories/{story_id}/transition` - Transition Story
    Move a story to a new state, enforcing the state machine defined
    in ``docs/spec.md`` section 4.3. Requires ``If-Match``.
  - Request body: `StoryTransitionRequest`
  - Response `200` (Successful Response) -> `StoryRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/workspaces/{workspace_id}/stories` - List Stories
    Return a page of stories in ``workspace_id`` with optional filters.
  - Response `200` (Successful Response) -> `StoryListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/workspaces/{workspace_id}/stories` - Create Story
    Create a new story in ``workspace_id`` and return it with ETag and
    Location headers.
  - Request body: `StoryCreate`
  - Response `201` (Successful Response) -> `StoryRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

### tags

- `DELETE /api/v1/tags/{tag_id}` - Soft Delete Tag
    Soft-delete a tag and detach it from every story in the same
    transaction. No ``If-Match`` (tags do not carry a version column,
    per spec §3.3).
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `PATCH /api/v1/tags/{tag_id}` - Update Tag
    Rename or recolour a tag. No ``If-Match`` (tags do not carry a
    version column, per spec §3.3).
  - Request body: `TagUpdate`
  - Response `200` (Successful Response) -> `TagRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/workspaces/{workspace_id}/tags` - List Tags
    Return every tag in ``workspace_id``, alphabetised by name.
  - Response `200` (Successful Response) -> `TagListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/workspaces/{workspace_id}/tags` - Create Tag
    Create a workspace-scoped tag. Collisions on ``(workspace_id,
    name)`` return 400 ``validation_error``.
  - Request body: `TagCreate`
  - Response `201` (Successful Response) -> `TagRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

### tokens

- `GET /api/v1/tokens` - List Tokens
    Return every API token as a masked read model (``token_hash`` only,
    no plaintext).
  - Response `200` (Successful Response) -> `array<ApiTokenRead>`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/tokens` - Create Token
    Issue a new token and return it with its plaintext.
    
    The plaintext appears in this response body only; all subsequent
    reads of the same row return :class:`ApiTokenRead` without it. The
    client is responsible for storing it securely.
  - Request body: `ApiTokenCreate`
  - Response `201` (Successful Response) -> `ApiTokenCreatedRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `DELETE /api/v1/tokens/{token_id}` - Revoke Token
    Revoke a token. Idempotent: revoking an already-revoked token is a
    204. An unknown id is a 404.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

### workspaces

- `GET /api/v1/workspaces` - List Workspaces
    Return a page of workspaces plus the next cursor.
  - Response `200` (Successful Response) -> `WorkspaceListResponse`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `POST /api/v1/workspaces` - Create Workspace
    Create a new workspace and return it with its ETag and Location.
  - Request body: `WorkspaceCreate`
  - Response `201` (Successful Response) -> `WorkspaceRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/workspaces/by-key/{key}` - Get Workspace By Key
    Return a workspace by its short ``key`` (``KAN``, ``ENG``, ...).
    
    Mirrors ``GET /stories/by-key`` and ``GET /epics/by-key``: clients
    that know only the human handle can resolve to a full workspace
    without paginating the list surface. Soft-deleted rows 404 unless
    ``include_deleted`` is set.
  - Response `200` (Successful Response) -> `WorkspaceRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `DELETE /api/v1/workspaces/{workspace_id}` - Soft Delete Workspace
    Soft-delete a workspace. Requires ``If-Match: <version>``; a
    mismatch returns 412. Soft delete does not cascade.
  - Response `204` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/workspaces/{workspace_id}` - Get Workspace
    Return a single workspace. Responds with ``404`` if the id is
    unknown or the row is soft-deleted (unless ``include_deleted`` is
    set).
  - Response `200` (Successful Response) -> `WorkspaceRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `PATCH /api/v1/workspaces/{workspace_id}` - Update Workspace
    Patch a workspace. Requires ``If-Match: <version>``; a mismatch
    returns 412.
  - Request body: `WorkspaceUpdate`
  - Response `200` (Successful Response) -> `WorkspaceRead`
  - Response `422` (Validation Error) -> `HTTPValidationError`

- `GET /api/v1/workspaces/{workspace_id}/export` - Export Workspace
    Stream the workspace's full export archive back to the caller.
    
    The archive is built in memory before the first byte ships so the
    response can carry a ``Content-Length`` header (also lets the
    service layer raise a clean 404 before a partial body is sent).
  - Response `200` (Successful Response)
  - Response `422` (Validation Error) -> `HTTPValidationError`

## Schemas

### `ActorType`

Type of actor performing a mutation.

See ``docs/spec.md`` section 3.2.

Enum values: `human`, `claude`, `system`

### `ApiTokenCreate`

Payload for ``POST /tokens``.

``actor_type`` and ``actor_id`` are deliberately caller-supplied:
the API is single-user in v1 so the caller is trusted to tag its
own tokens (e.g. ``claude`` for an MCP-facing token vs. ``human``
for a personal token).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `actor_type` | `ActorType` | yes |  |
| `actor_id` | `string` | yes | Actor Id |
| `name` | `string` | yes | Name |

### `ApiTokenCreatedRead`

One-shot response for ``POST /tokens``.

Extends :class:`ApiTokenRead` with the ``plaintext`` field. This
plaintext is only ever present in the create response; subsequent
reads return :class:`ApiTokenRead` without it.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `token_hash` | `string` | yes | Token Hash |
| `actor_type` | `ActorType` | yes |  |
| `actor_id` | `string` | yes | Actor Id |
| `name` | `string` | yes | Name |
| `created_at` | `string` | yes | Created At |
| `last_used_at` | `string \| null` | yes | Last Used At |
| `revoked_at` | `string \| null` | yes | Revoked At |
| `plaintext` | `string` | yes | Plaintext |

### `ApiTokenRead`

Server response for any token read. ``token_hash`` is exposed because
callers (admin tools) may need to identify a token without seeing its
plaintext.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `token_hash` | `string` | yes | Token Hash |
| `actor_type` | `ActorType` | yes |  |
| `actor_id` | `string` | yes | Actor Id |
| `name` | `string` | yes | Name |
| `created_at` | `string` | yes | Created At |
| `last_used_at` | `string \| null` | yes | Last Used At |
| `revoked_at` | `string \| null` | yes | Revoked At |

### `AuditEntityType`

Entity types that can appear in the audit log.

Enum values: `workspace`, `epic`, `story`, `comment`, `linkage`, `tag`

### `AuditEventRead`

Server response for any audit event read.

``diff`` is a structured ``{"before": <dict | null>, "after":
<dict | null>}`` object. The underlying column is TEXT holding a
JSON blob; the validator below parses it on construction so API
consumers do not have to.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `occurred_at` | `string` | yes | Occurred At |
| `actor_type` | `ActorType` | yes |  |
| `actor_id` | `string` | yes | Actor Id |
| `entity_type` | `AuditEntityType` | yes |  |
| `entity_id` | `string` | yes | Entity Id |
| `action` | `string` | yes | Action |
| `diff` | `object` | yes | Diff |

### `AuditListResponse`

Paginated envelope for audit listing responses.

Matches the shape used by every other list endpoint so clients can
reuse the cursor-pagination helper they already have.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<AuditEventRead>` | yes | Items |
| `next_cursor` | `string \| null` | yes | Next Cursor |

### `CommentCreate`

Payload for ``POST /stories/{id}/comments``. The actor is derived
from the auth token; the client never supplies it.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `body` | `string` | yes | Body |
| `parent_id` | `string \| null` | no | Parent Id |

### `CommentListResponse`

Envelope for comment list responses. No pagination in this
milestone: the flat list is expected to stay small per story.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<CommentRead>` | yes | Items |

### `CommentRead`

Server response for any comment read.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `story_id` | `string` | yes | Story Id |
| `parent_id` | `string \| null` | yes | Parent Id |
| `body` | `string` | yes | Body |
| `actor_type` | `ActorType` | yes |  |
| `actor_id` | `string` | yes | Actor Id |
| `created_at` | `string` | yes | Created At |
| `updated_at` | `string` | yes | Updated At |
| `deleted_at` | `string \| null` | yes | Deleted At |
| `version` | `integer` | yes | Version |

### `CommentUpdate`

Payload for ``PATCH /comments/{id}``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `body` | `string \| null` | no | Body |

### `EpicCreate`

Payload for creating an epic. ``human_id`` is allocated server-side
via the workspace's shared issue counter and is not supplied by the
client.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `string` | yes | Title |
| `description` | `string \| null` | no | Description |

### `EpicListResponse`

Paginated envelope for epic list responses.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<EpicRead>` | yes | Items |
| `next_cursor` | `string \| null` | yes | Next Cursor |

### `EpicRead`

Server response for any epic read.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `workspace_id` | `string` | yes | Workspace Id |
| `human_id` | `string` | yes | Human Id |
| `title` | `string` | yes | Title |
| `description` | `string \| null` | yes | Description |
| `state` | `EpicState` | yes |  |
| `created_at` | `string` | yes | Created At |
| `updated_at` | `string` | yes | Updated At |
| `deleted_at` | `string \| null` | yes | Deleted At |
| `version` | `integer` | yes | Version |

### `EpicState`

Epic lifecycle state.

Enum values: `open`, `closed`

### `EpicUpdate`

Payload for ``PATCH /epics/{id}``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `string \| null` | no | Title |
| `description` | `string \| null` | no | Description |
| `state` | `EpicState \| null` | no |  |

### `HTTPValidationError`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detail` | `array<ValidationError>` | no | Detail |

### `LinkEndpointType`

Allowed entity types as the source or target of a linkage.

Enum values: `story`, `epic`

### `LinkType`

Allowed linkage relationship types.

The ``blocks`` / ``is_blocked_by`` pair is mirrored by the service layer
when one is created (see milestone 6 / spec section 3.1).

Enum values: `relates_to`, `blocks`, `is_blocked_by`, `duplicates`, `is_duplicated_by`

### `LinkageCreate`

Payload for ``POST /linkages``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_type` | `LinkEndpointType` | yes |  |
| `source_id` | `string` | yes | Source Id |
| `target_type` | `LinkEndpointType` | yes |  |
| `target_id` | `string` | yes | Target Id |
| `link_type` | `LinkType` | yes |  |

### `LinkageListResponse`

Envelope for linkage list responses. No pagination in this
milestone.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<LinkageRead>` | yes | Items |

### `LinkageRead`

Server response for any linkage read.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `source_type` | `LinkEndpointType` | yes |  |
| `source_id` | `string` | yes | Source Id |
| `target_type` | `LinkEndpointType` | yes |  |
| `target_id` | `string` | yes | Target Id |
| `link_type` | `LinkType` | yes |  |
| `created_at` | `string` | yes | Created At |
| `deleted_at` | `string \| null` | yes | Deleted At |

### `StoryCreate`

Payload for ``POST /workspaces/{id}/stories``.

``human_id`` and ``state`` are server-controlled; the initial state
is always ``backlog``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `string` | yes | Title |
| `description` | `string \| null` | no | Description |
| `priority` | `StoryPriority` | no |  |
| `epic_id` | `string \| null` | no | Epic Id |
| `branch_name` | `string \| null` | no | Branch Name |
| `commit_sha` | `string \| null` | no | Commit Sha |
| `pr_url` | `string \| null` | no | Pr Url |

### `StoryListResponse`

Paginated envelope for story list responses.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<StoryRead>` | yes | Items |
| `next_cursor` | `string \| null` | yes | Next Cursor |

### `StoryPriority`

Story priority level. Default is ``none``.

Enum values: `none`, `low`, `medium`, `high`

### `StoryRead`

Server response for any story read.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `workspace_id` | `string` | yes | Workspace Id |
| `epic_id` | `string \| null` | yes | Epic Id |
| `human_id` | `string` | yes | Human Id |
| `title` | `string` | yes | Title |
| `description` | `string \| null` | yes | Description |
| `priority` | `StoryPriority` | yes |  |
| `state` | `StoryState` | yes |  |
| `state_actor_type` | `ActorType \| null` | yes |  |
| `state_actor_id` | `string \| null` | yes | State Actor Id |
| `branch_name` | `string \| null` | yes | Branch Name |
| `commit_sha` | `string \| null` | yes | Commit Sha |
| `pr_url` | `string \| null` | yes | Pr Url |
| `created_at` | `string` | yes | Created At |
| `updated_at` | `string` | yes | Updated At |
| `deleted_at` | `string \| null` | yes | Deleted At |
| `version` | `integer` | yes | Version |

### `StoryState`

Story lifecycle state.

Transition rules live in ``docs/spec.md`` section 4.3 and are enforced
by the (forthcoming) service layer; this enum only defines the legal
domain of values.

Enum values: `backlog`, `todo`, `in_progress`, `in_review`, `done`

### `StoryTagAddRequest`

Payload for ``POST /stories/{id}/tags``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tag_ids` | `array<string>` | yes | Tag Ids |

### `StoryTransitionRequest`

Payload for ``POST /stories/{id}/transition``.

``to_state`` is the target state; ``reason`` is an optional
free-text note surfaced in the audit row under ``transition_reason``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to_state` | `StoryState` | yes |  |
| `reason` | `string \| null` | no | Reason |

### `StoryUpdate`

Payload for ``PATCH /stories/{id}``.

``state`` is intentionally not patchable here: state changes must go
through ``POST /stories/{id}/transition`` so the API can record the
state actor.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `string \| null` | no | Title |
| `description` | `string \| null` | no | Description |
| `priority` | `StoryPriority \| null` | no |  |
| `epic_id` | `string \| null` | no | Epic Id |
| `branch_name` | `string \| null` | no | Branch Name |
| `commit_sha` | `string \| null` | no | Commit Sha |
| `pr_url` | `string \| null` | no | Pr Url |

### `TagCreate`

Payload for ``POST /workspaces/{id}/tags``.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | yes | Name |
| `color` | `string \| null` | no | Color |

### `TagListResponse`

Envelope for tag list responses. No pagination: tag volume per
workspace is expected to stay well within a single page.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<TagRead>` | yes | Items |

### `TagRead`

Server response for any tag read.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `workspace_id` | `string` | yes | Workspace Id |
| `name` | `string` | yes | Name |
| `color` | `string \| null` | yes | Color |
| `created_at` | `string` | yes | Created At |
| `deleted_at` | `string \| null` | yes | Deleted At |

### `TagUpdate`

Payload for ``PATCH /tags/{id}``. Both fields are optional so a tag
can be renamed or recoloured independently.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string \| null` | no | Name |
| `color` | `string \| null` | no | Color |

### `ValidationError`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `loc` | `array<string \| integer>` | yes | Location |
| `msg` | `string` | yes | Message |
| `type` | `string` | yes | Error Type |
| `input` | `object` | no | Input |
| `ctx` | `object` | no | Context |

### `WorkspaceCreate`

Payload for ``POST /workspaces``. ``key`` is the short prefix used for
human IDs (``KAN``, ``ENG``, ...).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | `string` | yes | Key |
| `name` | `string` | yes | Name |
| `description` | `string \| null` | no | Description |

### `WorkspaceListResponse`

Paginated envelope for workspace list responses.

``next_cursor`` is ``null`` on the last page. Clients follow the
cursor until they get back ``null`` to walk the entire collection.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | `array<WorkspaceRead>` | yes | Items |
| `next_cursor` | `string \| null` | yes | Next Cursor |

### `WorkspaceRead`

Server response for any workspace read.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Id |
| `key` | `string` | yes | Key |
| `name` | `string` | yes | Name |
| `description` | `string \| null` | yes | Description |
| `next_issue_num` | `integer` | yes | Next Issue Num |
| `created_at` | `string` | yes | Created At |
| `updated_at` | `string` | yes | Updated At |
| `deleted_at` | `string \| null` | yes | Deleted At |
| `version` | `integer` | yes | Version |

### `WorkspaceUpdate`

Payload for ``PATCH /workspaces/{id}``.

``key`` is intentionally omitted: re-keying a workspace would
invalidate every previously-issued human ID.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string \| null` | no | Name |
| `description` | `string \| null` | no | Description |
