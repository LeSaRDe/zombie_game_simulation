"""Independent ledger oracle for I08; all histories are disposable fixtures.

A controlled dense history covers keyset boundaries and legacy occurrence links;
a public-engine lifecycle history checks real recorded actions independently.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from unittest.mock import patch
import zlib

from zombie_sim.application import RunManager, ViewCancelled
from zombie_sim.config import initialize_world
from zombie_sim.storage import History, canonical, exact_time
from issue7_check import lifecycle_fixture


def audit(path):
    digest = hashlib.sha256()
    with sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for table in tables:
            digest.update(table.encode())
            for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                for value in row:
                    raw = value if isinstance(value, bytes) else repr(value).encode()
                    digest.update(len(raw).to_bytes(8, 'big')); digest.update(raw)
    return digest.hexdigest()


def controlled_fixture(root):
    directory = root / 'runs' / 'dense'; directory.mkdir(parents=True)
    config = {'scenario': 'issue8_controlled_query_fixture', 'seed': 123, 'horizon': 10,
              'agents': [{'id': identity, 'type': 'Human', 'x': 10 + i * 10, 'y': 10}
                         for i, identity in enumerate(('a', 'b', 'noise'))]}
    state = initialize_world(config); state.update(time='0', revision=0, occurrences={})
    writer = History(directory / 'run.sqlite', initial=state)
    try:
        occurrences = {f'noise-{i}': {'id': f'noise-{i}', 'actor': 'noise', 'target': 'noise',
                                    'intent_id': f'intent-{i}', 'details': 'x' * 200}
                       for i in range(5300)}
        writer.append(1, delta=[['set', ['time'], '1'], ['set', ['revision'], 1],
                                ['set', ['occurrences'], occurrences]],
                      records=[{'id': str(i), 'kind': 'query_fixture', 'time': '1',
                                'actor': 'noise', 'occurrence': f'noise-{i}'} for i in range(5300)])
        writer.append(1, delta=[['set', ['revision'], 2], ['set', ['occurrences', 'linked'],
            {'id': 'linked', 'actor': 'a', 'target': 'b', 'intent_id': 'linked-intent', 'outcome': 'ACTIVE'}]],
            records=[{'id': 'link-only', 'kind': 'draw', 'time': '1', 'occurrence': 'linked'},
                     {'id': 'alias-only', 'kind': 'result', 'time': '1', 'action_id': 'linked'},
                     {'id': 'other-actor-linked-target', 'kind': 'effect', 'time': '1', 'actor': 'noise', 'occurrence': 'linked'},
                     {'id': 'direct-actor', 'kind': 'direct', 'time': '1', 'actor': 'a'},
                     {'id': 'direct-target', 'kind': 'direct', 'time': '1', 'actor': 'noise', 'target': 'b'},
                     {'id': 'target-alias', 'kind': 'direct', 'time': '1', 'target_id': 'b'},
                     {'id': 'target-list', 'kind': 'direct', 'time': '1', 'targets': ['a', 'b']},
                     {'id': 'missing-link', 'kind': 'direct', 'time': '1', 'actor': 'a', 'occurrence': 'absent'}])
        # Exercise exact sequence transport above JavaScript's safe integer range.
        writer.connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name='events'", (2**53,))
        writer.connection.commit()
        writer.append(2, delta=[['set', ['time'], '2'], ['set', ['revision'], 3],
                                ['set', ['occurrences', 'linked', 'outcome'], 'COMPLETED']],
                      records=[{'id': 'large-sequence', 'kind': 'completed', 'time': '2', 'occurrence': 'linked'}])
    finally:
        writer.close()
    (directory / 'manifest.json').write_text(canonical({'run_id': 'dense', 'config': config, 'status': 'completed'}))
    return directory / 'run.sqlite'


def oracle(path, response, request):
    cursor = response['cursor']; selected = int(cursor['revision'])
    history = History(path, read_only=True)
    try:
        state = history.state_at(revision=selected)
        occurrences = state.get('occurrences', {})
        rows = history.connection.execute('SELECT sequence,revision,payload FROM events WHERE revision<=? ORDER BY sequence', (selected,))
        matching = []
        for sequence, revision, payload in rows:
            record = json.loads(zlib.decompress(payload))
            participants = {str(record[key]) for key in ('actor', 'agent', 'agent_id', 'target', 'target_id') if record.get(key) is not None}
            participants.update(str(value) for value in record.get('targets', []))
            occurrence = occurrences.get(str(record.get('occurrence', record.get('action_id'))))
            if occurrence:
                participants.update(str(occurrence[key]) for key in ('actor', 'target') if occurrence.get(key) is not None)
            if request.get('agent') is not None and str(request['agent']) not in participants:
                continue
            matching.append(dict(record, ledger_sequence=str(sequence), ledger_revision=str(revision),
                                 type=str(record.get('kind', 'event')).upper(),
                                 revision_before=str(max(0, revision - 1)), revision_after=str(revision)))
        before, after = request.get('before_sequence'), request.get('after_sequence')
        window = [row for row in matching if (before is None or int(row['ledger_sequence']) < int(before))
                  and (after is None or int(row['ledger_sequence']) > int(after))]
        limit = request.get('limit', 500)
        expected = window[:limit] if after is not None else window[-limit:]
        assert response['records'] == expected, (request, [r['ledger_sequence'] for r in response['records']], [r['ledger_sequence'] for r in expected])
        wanted = {str(row.get('occurrence', row.get('action_id'))) for row in expected}
        assert response['occurrences'] == {key: value for key, value in occurrences.items() if key in wanted}
        page = response['page']; assert page['loaded_count'] == len(expected) and page['limit'] == limit
        assert page['first_sequence'] == (expected[0]['ledger_sequence'] if expected else None)
        assert page['last_sequence'] == (expected[-1]['ledger_sequence'] if expected else None)
        assert page['has_older'] == bool(expected and any(int(r['ledger_sequence']) < int(expected[0]['ledger_sequence']) for r in matching))
        assert page['has_newer'] == bool(expected and any(int(r['ledger_sequence']) > int(expected[-1]['ledger_sequence']) for r in matching))
        assert response['agent'] == request.get('agent')
        assert selected <= request.get('revision', selected)
        if request.get('time') is not None:
            assert exact_time(cursor['time']) == exact_time(request['time'])
        return len(expected)
    finally:
        history.close()


def rejects(operation):
    try:
        operation()
    except ValueError as error:
        return str(error)
    raise AssertionError('Malformed timeline request was accepted')


def check(output):
    report = {'passed': False}
    with tempfile.TemporaryDirectory(prefix='zombie-issue8-ledger-') as temporary:
        root = Path(temporary); dense = controlled_fixture(root); lifecycle = lifecycle_fixture(root)
        real = root / 'runs' / lifecycle['run_id'] / 'run.sqlite'
        manager = RunManager(root); checked = 0; queries = 0
        private = []; original_history = manager.history
        def tracked(identity):
            history = original_history(identity); private.append(history); return history
        manager.history = tracked
        before_audits = {path.name + str(path.parent.name): audit(path) for path in (dense, real)}
        try:
            def query(identity='dense', **kwargs):
                nonlocal checked, queries
                with patch.object(History, 'state_at', side_effect=AssertionError('Timeline reconstructed the full world')):
                    response = manager.timeline(identity, **kwargs)
                checked += oracle(dense if identity == 'dense' else real, response, kwargs); queries += 1
                return response
            latest = query()
            assert len(latest['records']) == 500
            assert latest['records'][-1]['ledger_sequence'] == str(2**53 + 1)
            assert len(latest['occurrences']) <= 500
            # Previous implementation's earliest-window query demonstrably misses the newest records.
            with sqlite3.connect(dense) as db:
                old = [row[0] for row in db.execute('SELECT sequence FROM events ORDER BY sequence LIMIT 5000')]
            assert old[-1] == 5000 and int(latest['records'][-1]['ledger_sequence']) not in old
            for revision in (0, 1, 2, 3, 2, 1):
                for agent in (None, 'a', 'b', 'noise', 'nobody'):
                    query(revision=revision, agent=agent, limit=7)
            query(revision=3, time='3/2', agent='b')
            query(revision=2, time='1', agent='b', limit=5000)
            pages = []; response = query(revision=3, limit=337)
            while True:
                pages.append(response)
                if not response['page']['has_older']: break
                response = query(revision=3, limit=337, before_sequence=response['page']['first_sequence'])
            all_sequences = [row['ledger_sequence'] for page in reversed(pages) for row in page['records']]
            with sqlite3.connect(dense) as db:
                expected = [str(row[0]) for row in db.execute('SELECT sequence FROM events ORDER BY sequence')]
            assert all_sequences == expected and len(all_sequences) == len(set(all_sequences))
            ascending = []; response = pages[-1]
            while True:
                ascending.extend(row['ledger_sequence'] for row in response['records'])
                if not response['page']['has_newer']: break
                response = query(revision=3, limit=337, after_sequence=response['page']['last_sequence'])
            assert ascending == expected
            for boundary in (1, 99999999999999999):
                query(before_sequence=str(boundary), agent='nobody')
                query(after_sequence=str(boundary), agent='b')
            with sqlite3.connect(real) as db:
                real_revisions = [row[0] for row in db.execute('SELECT revision FROM commits ORDER BY revision')]
            for revision in real_revisions:
                for agent in (None, 'doctor', 'patient', 'mortal', 'biter'):
                    query(lifecycle['run_id'], revision=revision, agent=agent, limit=5)
            malformed = {
                'limit0': {'limit': 0}, 'limit5001': {'limit': 5001}, 'fractional limit': {'limit': 1.5},
                'negative revision': {'revision': -1}, 'future revision': {'revision': 100},
                'negative time': {'time': '-1'}, 'future time': {'time': '3'},
                'both boundaries': {'before_sequence': '5', 'after_sequence': '1'},
                'fractional boundary': {'before_sequence': '1.5'}, 'overflow boundary': {'after_sequence': str(2**64)},
            }
            report['invalid_requests'] = {name: rejects(lambda args=args: manager.timeline('dense', **args)) for name, args in malformed.items()}
            cancelled = threading.Event(); cancelled.set()
            try: manager.timeline('dense', cancel_event=cancelled)
            except ViewCancelled: pass
            else: raise AssertionError('Pre-cancelled timeline completed')
            with ThreadPoolExecutor(max_workers=4) as pool:
                concurrent = list(pool.map(lambda revision: manager.timeline('dense', revision=revision, agent='b', limit=2), (0, 1, 2, 3)))
            for revision, response in enumerate(concurrent): oracle(dense, response, {'revision': revision, 'agent': 'b', 'limit': 2})
            after_audits = {path.name + str(path.parent.name): audit(path) for path in (dense, real)}
            assert after_audits == before_audits
            # Deliberate fixture growth is outside the preceding read-only audit
            # window. The old pinned response must stay identical afterward.
            writer = History(dense)
            try:
                additions = {f'growth-{i}': {'id': f'growth-{i}', 'actor': 'noise', 'target': 'noise',
                                           'intent_id': f'growth-intent-{i}', 'details': 'x' * 200}
                             for i in range(5300)}
                delta = [['set', ['time'], '3'], ['set', ['revision'], 4]]
                delta += [['set', ['occurrences', key], value] for key, value in additions.items()]
                writer.append(3, delta=delta, records=[{'id': f'growth-{i}', 'kind': 'query_fixture', 'time': '3',
                                                       'actor': 'noise', 'occurrence': f'growth-{i}'} for i in range(5300)])
            finally:
                writer.close()
            growth_audit = audit(dense)
            assert manager.timeline('dense', revision=3) == latest
            growing = query()
            assert growing['page']['loaded_count'] == 500 and len(growing['occurrences']) == 500
            assert len(canonical(growing).encode()) < len(canonical(latest).encode()) * 1.5
            assert audit(dense) == growth_audit
            for history in private:
                try: history.connection.execute('SELECT 1')
                except sqlite3.ProgrammingError: pass
                else: raise AssertionError('Private timeline reader left open')
            report.update(passed=True, queries=queries, event_comparisons=checked, controlled_events=len(expected),
                          pagination_pages=len(pages), ascending_and_descending_complete=True,
                          large_sequence=str(2**53 + 1), linked_actor_target_filters=True,
                          legacy_cutoff_reproduced=True, real_engine_revisions=len(real_revisions),
                          no_ledger_changes=True, cancellation=True, concurrent_readers=4,
                          full_state_reconstruction_calls=0,
                          private_readers_closed=len(private), source_audits=after_audits,
                          latest_response_bytes=len(canonical(latest).encode()), returned_occurrences=len(latest['occurrences']),
                          growth={'events_before': len(expected), 'events_after': len(expected) + 5300,
                                  'response_bytes_after': len(canonical(growing).encode()), 'returned_records': 500,
                                  'returned_occurrences': 500, 'pinned_response_unchanged': True, 'read_audit_unchanged': True})
        finally:
            manager.close()
    report['workspace_removed'] = not root.exists()
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/issue8-timeline.json'))
    args = parser.parse_args(); result = check(args.output)
    print(json.dumps({key: value for key, value in result.items() if key not in ('source_audits', 'invalid_requests')}, indent=2))
