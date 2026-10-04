#!/usr/bin/env python3
"""Exercise a copied uv launcher against the package being released."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT.name
source = ROOT / 'skills' / APP / APP
text = source.read_text()
assert re.search(r'rev = "[0-9a-f]{40}"', text), 'Launcher must pin a full commit'
with tempfile.TemporaryDirectory(prefix=APP + '-launcher-') as tmp:
    target = Path(tmp) / APP
    # Validate the unreleased working tree with the exact launcher. Release checks
    # additionally run the unchanged launcher after its package commit is pushed.
    target.write_text(re.sub(r'\{ git = "[^"]+", rev = "[0-9a-f]{40}" \}',
                             '{ path = "' + str(ROOT) + '" }', text))
    target.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(APP.upper() + '_')}
    env['XDG_CACHE_HOME'] = str(Path(tmp) / 'private-cache')
    for args, expected in [(['--help'], 0), (['whoami'], 2)]:
        result = subprocess.run([shutil.which('uv') or 'uv', 'run', '--script', str(target), *args],
                                cwd=tmp, env=env, text=True, capture_output=True)
        assert result.returncode == expected, (args, result.returncode, result.stderr)
    assert 'usage:' in subprocess.check_output(['uv', 'run', '--script', str(target), '--help'],
                                               cwd=tmp, env=env, text=True)
print('PASS copied uv launcher, package resolution, help and configuration exit status')
