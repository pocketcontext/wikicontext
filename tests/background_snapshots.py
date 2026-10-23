#!/usr/bin/env python3
"""Synthetic application consistency and requester-generation boundaries."""
import argparse
from integration import server, credentials


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request:
        admin, user, token = credentials(request)
        request('GET', '/api/context/snapshot', expected=(401, 403))
        space = request('POST', '/api/wiki/spaces/personal', {}, token)['id']
        sql = "SELECT count(*) AS n FROM pages WHERE space='" + space + "'"
        first = request('POST', '/api/context/query', {'sql': sql}, token)
        assert first['rows'] == [[0]] and not first['truncated']
        old = first['snapshot']['generation']
        assert old and first['snapshot']['rows'] > 0 and first['snapshot']['diskBytes'] > 0
        status = request('GET', '/api/context/snapshot', token=token)
        assert status['generation'] == old
        request('POST', '/api/collections/pages/records', {'space': space, 'slug': 'new-evidence', 'kind': 'concept'}, token)
        # Either complete generation is legal during refresh; no partial copy is.
        available = request('POST', '/api/context/query', {'sql': sql, 'consistency': 'available', 'atLeast': old}, token)
        assert available['rows'] in ([[0]], [[1]]) and not available['truncated']
        fresh = request('POST', '/api/context/query', {'sql': sql, 'consistency': 'fresh', 'atLeast': old}, token)
        assert fresh['rows'] == [[1]] and fresh['snapshot']['generation'] != old
        conflict = request('POST', '/api/context/query', {'sql': sql, 'expectedGeneration': old}, token, 409)
        assert conflict['code'] == 'snapshot_generation_conflict'

        request('POST', '/api/collections/users/records', {'email': 'other@example.com', 'name': 'Other synthetic reader', 'password': 'SyntheticOtherPassword123!', 'passwordConfirm': 'SyntheticOtherPassword123!'}, admin)
        other = request('POST', '/api/collections/users/auth-with-password', {'identity': 'other@example.com', 'password': 'SyntheticOtherPassword123!'})['token']
        hidden = request('POST', '/api/context/query', {'sql': sql}, other)
        assert hidden['rows'] == [[0]] and hidden['snapshot']['generation'] != fresh['snapshot']['generation']
        foreign = request('POST', '/api/context/query', {'sql': sql, 'atLeast': fresh['snapshot']['generation']}, other, 409)
        assert foreign['code'] == 'snapshot_generation_conflict'
        # Snapshot access still authenticates disabled accounts immediately.
        request('PATCH', '/api/collections/users/records/' + user['id'], {'disabled': True}, admin)
        request('GET', '/api/context/snapshot', token=token, expected=(401, 403))
        request('POST', '/api/context/query', {'sql': sql, 'consistency': 'available'}, token, (401, 403))
    print('PASS: available complete copies, fresh write barrier, requester-bound generations, exact conflict and disabled-account denial')


if __name__ == '__main__':
    main()
