"""The one-use initializer cannot target a sibling or accept caller settings."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap', Path(__file__).resolve().parents[1] / 'deploy/bootstrap-wikicontext.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        settings = {'WIKICONTEXT_' + k: 'synthetic' for k in ('SUPERUSER_EMAIL', 'SUPERUSER_PASSWORD', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_WORKSPACE_DOMAIN', 'TRUSTED_PROXY_HEADER')}
        settings.update({'LITESTREAM_' + k: 'synthetic' for k in ('BUCKET', 'PATH', 'REGION', 'ENDPOINT', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY')})
        settings.update(LITESTREAM_BUCKET='wikicontext-backup', LITESTREAM_PATH='once-pocketcontext/wikicontext')
        self.payload = {'image': 'ghcr.io/pocketcontext/wikicontext@sha256:' + 'a' * 64, 'settings': settings}
        self.credential = {'username': 'synthetic', 'token': 'header.payload-with_dash.signature_' + 'x' * 40}

    def test_unconfigured_bootstrap_never_mutates(self):
        self.assertFalse(bootstrap.DEPLOYMENT_CONFIGURED)
        with patch.object(bootstrap, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'not configured or approved'):
                bootstrap.main()
            run.assert_not_called()

    def test_valid_pinned_target(self):
        self.assertEqual(bootstrap.validate(self.payload, self.credential), self.payload['settings'])

    def test_no_sibling_image_or_backup(self):
        with self.assertRaises(ValueError):
            bootstrap.validate(dict(self.payload, image=self.payload['image'].replace('wikicontext', 'dealcontext')), self.credential)
        self.payload['settings']['LITESTREAM_BUCKET'] = 'sibling'
        with self.assertRaises(ValueError):
            bootstrap.validate(self.payload, self.credential)

    def test_no_arbitrary_runtime_environment(self):
        self.payload['settings']['LITESTREAM_DISABLED'] = 'true'
        with self.assertRaises(ValueError):
            bootstrap.validate(self.payload, self.credential)

    def test_no_arbitrary_credential_payload(self):
        for credential in ({'username': 'name', 'token': 'x' * 40, 'settings': {}}, {'username': 'x\n', 'token': 'x' * 40}, {'username': 'name', 'token': 'short'}):
            with self.assertRaises(ValueError):
                bootstrap.validate(self.payload, credential)


if __name__ == '__main__':
    unittest.main()
