import type { JSX } from 'react';
import { useStoryAudit } from '../queries/audit';
import { ACTOR_LABELS, type ActorType, type AuditEvent } from '../types/api';

const ACTOR_DOT_COLOR: Record<ActorType, string> = {
  human: '#7faa3a',
  claude: '#a569ff',
  system: '#888',
};

const ACTION_ICON: Record<string, string> = {
  created: '+',
  updated: 'E',
  soft_deleted: 'X',
  state_changed: '>',
  commented: 'C',
  linked: 'L',
  unlinked: 'U',
  tag_added: 'T',
  tag_removed: 't',
};

const TRUNCATE_AT = 40;

function truncate(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  const raw = typeof value === 'string' ? value : JSON.stringify(value);
  if (raw.length <= TRUNCATE_AT) {
    return raw;
  }
  return `${raw.slice(0, TRUNCATE_AT - 1)}\u2026`;
}

function tagNameFromDiff(diff: Record<string, unknown> | null): string | null {
  if (!diff) {
    return null;
  }
  if (typeof diff.name === 'string') {
    return diff.name;
  }
  if (typeof diff.tag_id === 'string') {
    return diff.tag_id;
  }
  return null;
}

function summarizeEvent(event: AuditEvent): JSX.Element {
  const actor = ACTOR_LABELS[event.actor_type];
  if (event.action === 'state_changed') {
    const before =
      event.diff.before && typeof event.diff.before.state === 'string'
        ? event.diff.before.state
        : '?';
    const after =
      event.diff.after && typeof event.diff.after.state === 'string'
        ? event.diff.after.state
        : '?';
    return (
      <>
        {actor} moved this from <code>{before}</code> to <code>{after}</code>.
      </>
    );
  }
  if (event.action === 'updated') {
    const before = event.diff.before ?? {};
    const after = event.diff.after ?? {};
    const changedKeys = Object.keys(after).filter((key) => {
      const b = (before as Record<string, unknown>)[key];
      const a = (after as Record<string, unknown>)[key];
      return JSON.stringify(a) !== JSON.stringify(b);
    });
    if (changedKeys.length === 0) {
      return <>{actor} updated this.</>;
    }
    return (
      <>
        {actor} edited{' '}
        {changedKeys.map((key, index) => (
          <span key={key}>
            {index > 0 ? ', ' : ''}
            <code>{key}</code>
            <span className="muted small">
              {' '}
              ({truncate((before as Record<string, unknown>)[key])} →{' '}
              {truncate((after as Record<string, unknown>)[key])})
            </span>
          </span>
        ))}
        .
      </>
    );
  }
  if (event.action === 'tag_added') {
    const name = tagNameFromDiff(event.diff.after);
    return (
      <>
        {actor} added tag{' '}
        <code>{name ?? 'unknown'}</code>.
      </>
    );
  }
  if (event.action === 'tag_removed') {
    const name = tagNameFromDiff(event.diff.before);
    return (
      <>
        {actor} removed tag{' '}
        <code>{name ?? 'unknown'}</code>.
      </>
    );
  }
  if (event.action === 'commented') {
    return <>{actor} commented.</>;
  }
  if (event.action === 'created') {
    return <>{actor} created this.</>;
  }
  if (event.action === 'soft_deleted') {
    return <>{actor} deleted this.</>;
  }
  if (event.action === 'linked') {
    return <>{actor} added a linkage.</>;
  }
  if (event.action === 'unlinked') {
    return <>{actor} removed a linkage.</>;
  }
  return <>{actor} performed {event.action}.</>;
}

export type AuditTrailProps = {
  storyId: string;
};

export default function AuditTrail({ storyId }: AuditTrailProps): JSX.Element {
  const query = useStoryAudit(storyId);

  if (query.isLoading) {
    return (
      <section className="audit-trail" aria-busy="true">
        <p className="muted small">Loading audit trail...</p>
      </section>
    );
  }
  if (query.isError) {
    return (
      <section className="audit-trail" role="alert">
        <p className="error-text small">Could not load audit trail.</p>
        <button
          type="button"
          className="secondary"
          onClick={() => query.refetch()}
        >
          Retry
        </button>
      </section>
    );
  }
  const events = query.data ?? [];
  if (events.length === 0) {
    return <p className="muted small">No audit events yet.</p>;
  }
  return (
    <section className="audit-trail" aria-label="Audit trail">
      <header className="audit-trail-header">
        <h3>Activity</h3>
      </header>
      <ol className="audit-timeline">
        {events.map((event) => (
          <li key={event.id} className="audit-row" data-action={event.action}>
            <span
              className="audit-icon"
              aria-hidden="true"
              title={event.action}
            >
              {ACTION_ICON[event.action] ?? '?'}
            </span>
            <span
              className="actor-dot"
              aria-hidden="true"
              style={{ backgroundColor: ACTOR_DOT_COLOR[event.actor_type] }}
            />
            <span className="audit-summary">{summarizeEvent(event)}</span>
            <span className="audit-timestamp muted small">{event.occurred_at}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
