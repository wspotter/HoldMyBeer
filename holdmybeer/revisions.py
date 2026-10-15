"""Bounded, read-only procedure history shared by HTTP and MCP adapters."""
import json


def read_revisions(db, session_id: str, revision: int | None = None,
                   before_revision: int | None = None) -> dict:
    for value in (revision, before_revision):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError('revision must be a positive integer')
    if db.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone() is None:
        raise LookupError('session not found')
    if revision is not None:
        rows = db.execute('SELECT data,saved_at,source FROM procedure_revisions WHERE session_id=? AND revision=?',
                          (session_id, revision)).fetchall()
        if not rows:
            raise LookupError('procedure revision not found')
    else:
        rows = db.execute('''SELECT data,saved_at,source FROM procedure_revisions
            WHERE session_id=? AND (? IS NULL OR revision < ?)
            ORDER BY revision DESC LIMIT 50''', (session_id, before_revision, before_revision)).fetchall()
    entries = [{'procedure': json.loads(row[0]), 'saved_at': row[1], 'source': row[2]} for row in rows]
    if revision is not None:
        return entries[0]
    return {'revisions': entries, 'next_before_revision': entries[-1]['procedure']['revision'] if len(entries) == 50 else None}
