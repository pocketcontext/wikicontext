#!/usr/bin/env python3
"""Publication SSE exposes committed knowledge, never rolled-back manifests."""
import argparse
import json
import queue
import threading
import urllib.request

from integration import credentials, server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request:
        _, _, token = credentials(request)
        messages = queue.Queue()

        def query(sql):
            result = request('POST', '/api/context/query', {'sql': sql}, token)
            assert not result['truncated']
            return [dict(zip(result['columns'], row)) for row in result['rows']]

        def listen():
            try:
                with urllib.request.urlopen(request.base_url + '/api/realtime', timeout=15) as response:
                    event, data = '', ''
                    for raw in response:
                        line = raw.decode().strip()
                        if line.startswith('event:'):
                            event = line[6:].strip()
                        elif line.startswith('data:'):
                            data = line[5:].strip()
                        elif not line and event:
                            payload = json.loads(data)
                            if event.startswith('publications/'):
                                # Query immediately on receipt, concurrently with the publishing request.
                                record = payload['record']
                                rows = query("SELECT r.id, r.body, run.status FROM publications pub "
                                    "JOIN ingestion_runs run ON run.id=pub.run "
                                    "JOIN pages p ON 1=1 JOIN page_revisions r ON r.page=p.id "
                                    "AND r.id=json_extract(pub.manifest, '$.' || p.id) "
                                    f"WHERE pub.id='{record['id']}' AND r.archived=0")
                                assert rows and all(row['status'] == 'published' for row in rows), rows
                                payload['committed_rows'] = rows
                            messages.put((event, payload))
                            event, data = '', ''
            except Exception as error:
                messages.put(('error', repr(error)))

        threading.Thread(target=listen, daemon=True).start()
        event, data = messages.get(timeout=5)
        assert event == 'PB_CONNECT', (event, data)
        request('POST', '/api/realtime', {
            'clientId': data['clientId'], 'subscriptions': ['publications/*'],
        }, token, expected=204)

        def create(table, body):
            return request('POST', '/api/collections/' + table + '/records', body, token)

        def stage(key, base='', run_id=None):
            body = {'key': key, 'description': 'Synthetic publication notification', 'status': 'staging'}
            if run_id:
                body['id'] = run_id
            run = create('ingestion_runs', body)
            revision = create('page_revisions', {
                'run': run['id'], 'page': page['id'], 'base_revision': base,
                'title': 'Synthetic page', 'summary': 'Synthetic publication summary',
                'body': key + ' [needs verification]',
            })
            return run, revision

        def publish(run, expected=200):
            return request('PATCH', '/api/collections/ingestion_runs/records/' + run['id'], {
                'expected_revision': run['revision'], 'status': 'published',
            }, token, expected=expected)

        def notification(revision, sequence):
            event, payload = messages.get(timeout=5)
            assert event.startswith('publications/'), (event, payload)
            assert payload['action'] == 'create' and payload['record']['sequence'] == sequence, payload
            assert payload['committed_rows'] == [{
                'id': revision['id'], 'body': revision['body'], 'status': 'published',
            }], payload

        page = create('pages', {'slug': 'live-publication', 'kind': 'concept'})
        run, first = stage('initial-publication')
        publish(run)
        notification(first, 1)

        failed, _ = stage('rollback-publication', first['id'], 'pubfailure00001')
        publish(failed, expected=(400, 500))
        assert query('SELECT sequence FROM publications ORDER BY sequence') == [{'sequence': 1}]
        assert query("SELECT status FROM ingestion_runs WHERE id='pubfailure00001'") == [{'status': 'staging'}]
        try:
            unexpected = messages.get(timeout=0.75)
            raise AssertionError(('Rolled-back publication emitted a notification', unexpected))
        except queue.Empty:
            pass

        # The same connection remains live, and the failed transaction consumed no sequence.
        run, second = stage('following-publication', first['id'])
        publish(run)
        notification(second, 2)
    print('PASS: publication SSE observes committed manifests and suppresses rollback notifications')


if __name__ == '__main__':
    main()
