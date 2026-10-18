import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from likethis.app import create_app


def test_revision_conflicts_are_atomic_and_history_survives_restart(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    session = client.post('/api/sessions', json={'title': 'Teaching'}).json()
    url = f"/api/sessions/{session['id']}"
    second = {'revision': 2, 'steps': [{'goal': 'Save', 'check': 'Receipt'}]}
    assert client.put(url, json={'procedure': second}).status_code == 200
    # Same revision and content is an idempotent save, not another history row.
    assert client.put(url, json={'procedure': second}).status_code == 200
    for revision in (1, 2, 4):
        response = client.put(url, json={'notes': 'must not persist', 'procedure': {
            'revision': revision, 'steps': [{'goal': 'Changed', 'check': 'New receipt'}]}})
        assert response.status_code == 409
    assert client.get(url).json()['notes'] == ''
    third = {**second, 'revision': 3}
    assert client.put(url, json={'procedure': third}).status_code == 200
    restarted = TestClient(create_app(tmp_path))
    history = restarted.get(url + '/procedure-revisions').json()['revisions']
    assert [item['procedure']['revision'] for item in history] == [3, 2, 1]
    assert restarted.get(url + '/procedure-revisions/2').json()['procedure']['steps'] == second['steps']
    assert restarted.get(url + '/procedure-revisions/99').status_code == 404
    assert restarted.get('/api/sessions/missing/procedure-revisions').status_code == 404
    assert restarted.get(url + '/procedure-revisions?before_revision=3').json()['revisions'] == history[1:]


def test_competing_saves_preserve_winner_and_independent_notes(tmp_path):
    client = TestClient(create_app(tmp_path))
    sid = client.post('/api/sessions', json={'title': 'Two editors'}).json()['id']
    url = f'/api/sessions/{sid}'
    # Separate app instances/connections simulate clients sharing the data directory.
    def save(goal):
        with TestClient(create_app(tmp_path)) as editor:
            return editor.put(url, json={'procedure': {'revision': 2, 'steps': [
                {'goal': goal, 'check': 'Receipt'}]}}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ['First editor', 'Second editor'])) == [200, 409]
    assert client.put(url, json={'notes': 'Independent notes'}).status_code == 200
    assert client.get(url).json()['procedure']['revision'] == 2
    assert len(client.get(url + '/procedure-revisions').json()['revisions']) == 2


def test_legacy_store_seeds_only_known_current_revision(tmp_path):
    import sqlite3
    data = {'id': 'legacy', 'title': 'Old teaching', 'procedure': {'revision': 7, 'steps': []}}
    with sqlite3.connect(tmp_path / 'holdmybeer.sqlite3') as db:
        db.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        db.execute('INSERT INTO sessions VALUES (?,?)', ('legacy', json.dumps(data)))
    client = TestClient(create_app(tmp_path))
    history = client.get('/api/sessions/legacy/procedure-revisions').json()['revisions']
    assert len(history) == 1
    assert history[0]['procedure'] == data['procedure']
    assert history[0]['source'] == 'legacy_current'
    assert client.get('/api/sessions/legacy/procedure-revisions/6').status_code == 404


def test_history_pages_without_gaps_and_rejects_invalid_cursor(tmp_path):
    client = TestClient(create_app(tmp_path))
    sid = client.post('/api/sessions', json={'title': 'Many corrections'}).json()['id']
    url = f'/api/sessions/{sid}'
    for revision in range(2, 54):
        assert client.put(url, json={'procedure': {'revision': revision, 'steps': []}}).status_code == 200
    first = client.get(url + '/procedure-revisions').json()
    assert len(first['revisions']) == 50
    second = client.get(url + '/procedure-revisions', params={'before_revision': first['next_before_revision']}).json()
    assert [item['procedure']['revision'] for item in first['revisions'] + second['revisions']] == list(range(53, 0, -1))
    assert second['next_before_revision'] is None
    assert client.get(url + '/procedure-revisions?before_revision=0').status_code == 422
