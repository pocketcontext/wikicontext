#!/usr/bin/env python3
"""Exercise deployment orchestration without Docker, root, network or credentials."""
import importlib.util
import io
import os
from types import SimpleNamespace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load("hook", "deploy-wikicontext.py")
installer = load("installer", "install.py")


class DeploymentTests(unittest.TestCase):
    def run_hook(self, fail=None, killed=False, count=1, recovery_count=None, image=None):
        calls = []
        inspections = 0
        def command(*args, capture=False):
            nonlocal inspections
            calls.append(args)
            if args[:2] == fail:
                raise RuntimeError("stub failure")
            if args[:2] == ("docker", "ps"):
                return "old"
            if args[:2] == ("docker", "inspect"):
                if "--format" in args:
                    return json.dumps({"Running": False, "ExitCode": 137 if killed else 0})
                inspections += 1
                size = recovery_count if inspections > 1 and recovery_count is not None else count
                return json.dumps([{"Id": "old", "Config": {"Image": image or hook.IMAGE, "Labels": {
                    "once": json.dumps({"host": hook.HOST, "env": {"SECRET": "never print"}})}}}] * size)
            return ""
        with patch.object(hook, "run", side_effect=command):
            if fail or killed or count != 1 or image == "ghcr.io/pocketcontext/dealcontext:latest":
                with self.assertRaises(RuntimeError):
                    hook.deploy()
            else:
                hook.deploy()
        return calls

    def test_unconfigured_entrypoints_never_mutate(self):
        for module in (hook, installer):
            self.assertFalse(module.DEPLOYMENT_CONFIGURED)
            with patch.object(module.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "not configured or approved"):
                    module.main()
                run.assert_not_called()

    def test_order(self):
        calls = self.run_hook()
        self.assertEqual([c[:2] for c in calls], [
            ("docker", "ps"), ("docker", "inspect"), ("docker", "pull"),
            ("docker", "stop"), ("docker", "inspect"), ("once", "update")])
        self.assertEqual(calls[3], ("docker", "stop", "--time", "60", "old"))
        self.assertEqual(calls[-1], ("once", "update", hook.HOST, "--image", hook.IMAGE, "--auto-update=false"))

    def test_adopts_initial_pinned_wikicontext_image(self):
        calls = self.run_hook(image="ghcr.io/pocketcontext/wikicontext@sha256:" + "a" * 64)
        self.assertEqual(calls[-1], ("once", "update", hook.HOST, "--image", hook.IMAGE, "--auto-update=false"))

    def test_wrong_application_image_never_mutates(self):
        self.assertEqual(len(self.run_hook(image="ghcr.io/pocketcontext/dealcontext:latest")), 2)

    def test_pull_failure_does_not_stop(self):
        calls = self.run_hook(fail=("docker", "pull"))
        self.assertNotIn(("docker", "stop"), [c[:2] for c in calls])
        self.assertNotIn(("once", "start"), [c[:2] for c in calls])

    def test_update_failure_recovers_and_fails(self):
        self.assertEqual(self.run_hook(fail=("once", "update"))[-1], ("docker", "start", "old"))

    def test_stop_failure_recovers_without_update(self):
        calls = self.run_hook(fail=("docker", "stop"))
        self.assertEqual(calls[-1], ("docker", "start", "old"))
        self.assertNotIn(("once", "update"), [c[:2] for c in calls])

    def test_forced_stop_does_not_update(self):
        calls = self.run_hook(killed=True)
        self.assertEqual(calls[-1], ("docker", "start", "old"))
        self.assertNotIn(("once", "update"), [c[:2] for c in calls])

    def test_ambiguous_containers_never_mutate(self):
        self.assertEqual(len(self.run_hook(count=2)), 2)

    def test_ambiguous_recovery_never_starts_another_writer(self):
        calls = self.run_hook(fail=("once", "update"), recovery_count=2)
        self.assertNotIn(("docker", "start"), [c[:2] for c in calls])

    def test_missing_old_container_never_starts_another_writer(self):
        calls = self.run_hook(fail=("once", "update"), recovery_count=0)
        self.assertNotIn(("docker", "start"), [c[:2] for c in calls])

    def test_arguments_rejected_before_commands(self):
        with patch.object(hook, "DEPLOYMENT_CONFIGURED", True), patch.object(sys, "argv", ["deploy-wikicontext", "other-host"]), patch.object(hook, "run") as run:
            with self.assertRaises(RuntimeError):
                hook.main()
            run.assert_not_called()

    def test_installer_preserves_other_keys_and_restrictions(self):
        website = 'restrict,command="/usr/local/bin/deploy www.pocketcontext.com" ssh-ed25519 AAA website\n'
        crm = f'no-port-forwarding,no-pty,{installer.OLD} ssh-ed25519 BBB crm\n'
        result = installer.rewrite_keys(website + crm + crm)
        self.assertEqual(result, website + (crm.replace(installer.OLD, installer.NEW) * 2))
        self.assertEqual(installer.rewrite_keys(result), result)
        with self.assertRaises(RuntimeError):
            installer.rewrite_keys(website)

    def test_registry_stdin_empty_is_anonymous(self):
        self.assertIsNone(hook.read_credentials(io.BytesIO(b'')))

    def test_registry_stdin_valid_is_bounded(self):
        value = {'username': 'github-actions[bot]', 'token': 'header.payload-with_dash.signature_' + 'A' * 30}
        self.assertEqual(hook.read_credentials(io.BytesIO(json.dumps(value).encode())), value)
        with self.assertRaisesRegex(RuntimeError, 'exceeds limit'):
            hook.read_credentials(io.BytesIO(b'A' * (hook.MAX_CREDENTIAL_BYTES + 1)))

    def test_registry_stdin_rejects_malformed_values_without_echo(self):
        secret = 'SECRET_MUST_NOT_APPEAR'
        cases = [secret, json.dumps({'token': secret}), json.dumps({'username': '--bad', 'token': secret}),
                 json.dumps({'username': 'user', 'token': secret, 'host': 'other-host'}),
                 json.dumps({'username': 'user', 'token': secret + '\n'}), '[]', 'null']
        for value in cases:
            with self.assertRaises(RuntimeError) as raised:
                hook.read_credentials(io.BytesIO(value.encode()))
            self.assertNotIn(secret, str(raised.exception))

    def test_registry_config_private_and_removed_after_success(self):
        original = hook.ENV.copy()
        credentials = {'username': 'user', 'token': 'ghs_' + 'A' * 30}
        config = None
        def login(args, **kwargs):
            self.assertEqual(args, ['docker', 'login', 'ghcr.io', '--username', 'user', '--password-stdin'])
            self.assertNotIn(credentials['token'], str(args))
            self.assertEqual(kwargs['input'], credentials['token'] + '\n')
            self.assertEqual(kwargs['stdout'], hook.subprocess.PIPE)
            self.assertEqual(kwargs['stderr'], hook.subprocess.PIPE)
            self.assertEqual(os.stat(kwargs['env']['DOCKER_CONFIG']).st_mode & 0o777, 0o700)
            return SimpleNamespace(returncode=0)
        with patch.object(hook.subprocess, 'run', side_effect=login):
            with hook.registry_auth(credentials):
                config = Path(hook.ENV['DOCKER_CONFIG'])
                self.assertTrue(config.is_dir())
        self.assertFalse(config.exists())
        self.assertEqual(hook.ENV, original)

    def test_registry_login_failure_is_redacted_and_config_removed(self):
        original = hook.ENV.copy()
        seen = []
        def login(args, **kwargs):
            seen.append(Path(kwargs['env']['DOCKER_CONFIG']))
            return SimpleNamespace(returncode=1, stdout='SYNTHETIC_SECRET', stderr='SYNTHETIC_SECRET')
        with patch.object(hook.subprocess, 'run', side_effect=login):
            with self.assertRaisesRegex(RuntimeError, '^Registry authentication failed$'):
                with hook.registry_auth({'username': 'user', 'token': 'SYNTHETIC_SECRET'}):
                    self.fail('deploy must not run after failed authentication')
        self.assertFalse(seen[0].exists())
        self.assertEqual(hook.ENV, original)

    def test_registry_config_removed_on_deploy_failure_and_anonymous_isolated(self):
        original = hook.ENV.copy()
        with patch.object(hook.subprocess, 'run') as login:
            with self.assertRaises(RuntimeError):
                with hook.registry_auth(None):
                    config = Path(hook.ENV['DOCKER_CONFIG'])
                    self.assertTrue(config.is_dir())
                    raise RuntimeError('synthetic deployment failure')
            login.assert_not_called()
        self.assertFalse(config.exists())
        self.assertEqual(hook.ENV, original)


if __name__ == "__main__":
    unittest.main()
