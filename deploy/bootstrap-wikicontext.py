#!/usr/bin/python3 -I
"""One-use fixed-target bootstrap, installed temporarily by a trusted operator.

The root-owned payload pins the approved image and private application settings.
CI supplies only its short-lived registry authentication on stdin. The operator
replaces this key's forced command with the regular update wrapper afterward.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

HOST = 'wiki.pocketcontext.com'
PAYLOAD = Path('/etc/wikicontext-bootstrap.json')


def validate(payload, credential):
    if not re.fullmatch(r'ghcr\.io/pocketcontext/wikicontext@sha256:[a-f0-9]{64}', payload.get('image', '')):
        raise ValueError('Invalid pinned application image')
    settings = payload.get('settings')
    allowed = {'WIKICONTEXT_' + key for key in ('SUPERUSER_EMAIL', 'SUPERUSER_PASSWORD', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_WORKSPACE_DOMAIN', 'TRUSTED_PROXY_HEADER')}
    allowed |= {'LITESTREAM_' + key for key in ('BUCKET', 'PATH', 'REGION', 'ENDPOINT', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY')}
    if not isinstance(settings, dict) or set(settings) != allowed or not all(isinstance(v, str) and v for v in settings.values()):
        raise ValueError('Invalid bootstrap configuration')
    if settings['LITESTREAM_BUCKET'] != 'wikicontext-backup' or settings['LITESTREAM_PATH'] != 'once-pocketcontext/wikicontext':
        raise ValueError('Invalid backup target')
    if not isinstance(credential, dict) or set(credential) != {'username', 'token'}:
        raise ValueError('Invalid registry authentication')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', credential['username']) or not re.fullmatch(r'[A-Za-z0-9_.-]{20,2048}', credential['token']):
        raise ValueError('Invalid registry authentication')
    return settings


def run(args, env, data=None):
    result = subprocess.run(args, env=env, input=data, capture_output=True, text=True)
    if result.returncode:
        # ONCE/Docker errors may contain credentials or settings. Never echo them.
        raise RuntimeError('Bootstrap command failed: ' + args[0])
    return result.stdout


DEPLOYMENT_CONFIGURED = False  # Enable only after the deployment target is approved.


def main():
    if not DEPLOYMENT_CONFIGURED:
        raise RuntimeError("WikiContext deployment is not configured or approved")
    if len(sys.argv) != 1 or os.geteuid() != 0:
        raise ValueError('Run as root with no arguments')
    info = PAYLOAD.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Bootstrap payload must be a root-owned regular file, mode 0600')
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise ValueError('Registry authentication too large')
    payload = json.loads(PAYLOAD.read_text())
    credential = json.loads(raw)
    settings = validate(payload, credential)
    with open('/run/lock/deploy-wikicontext.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='wikicontext-registry-') as temp:
            os.chmod(temp, 0o700)
            env = dict(os.environ, DOCKER_CONFIG=temp)
            if HOST in run(['once', 'list'], env):
                raise RuntimeError('Application already exists; refusing bootstrap')
            run(['docker', 'login', 'ghcr.io', '--username', credential['username'], '--password-stdin'], env, credential['token'])
            run(['docker', 'pull', payload['image']], env)
            args = ['once', 'deploy', payload['image'], '--host', HOST, '--auto-update=false', '--cpus', '1', '--memory', '512']
            for key, value in settings.items():
                args += ['--env', key + '=' + value]
            run(args, env)
            PAYLOAD.unlink()
    print('WikiContext initial deployment completed; private bootstrap payload removed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('WikiContext bootstrap failed (' + type(error).__name__ + '); no details logged.', file=sys.stderr)
        sys.exit(1)
