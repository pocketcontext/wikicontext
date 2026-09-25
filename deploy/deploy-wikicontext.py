#!/usr/bin/python3 -I
"""Root-owned, fixed-target ONCE update with a single SQLite/Litestream writer."""
from contextlib import contextmanager
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile

HOST = "wiki.pocketcontext.com"
IMAGE = "ghcr.io/pocketcontext/wikicontext:latest"
ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root"}


def run(*args, capture=False):
    result = subprocess.run(args, env=ENV, text=True, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        # Captured Docker metadata may contain credentials: never include its output.
        raise RuntimeError(f"{args[0]} {args[1]} failed (exit {result.returncode})")
    return result.stdout if capture else ""


# Optional stdin is only registry authentication, never a deployment target or command.
MAX_CREDENTIAL_BYTES = 16384


def read_credentials(stream):
    raw = stream.read(MAX_CREDENTIAL_BYTES + 1)
    if len(raw) > MAX_CREDENTIAL_BYTES:
        raise RuntimeError("Registry credential input exceeds limit")
    if not raw.strip():
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"username", "token"}:
            raise ValueError()
        username, token = value["username"], value["token"]
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\[\]-]{0,99}", username):
            raise ValueError()
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{16,12000}", token):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError):
        raise RuntimeError("Invalid registry credential input") from None


@contextmanager
def registry_auth(credentials):
    # The job token exists only in this process and a private temporary Docker config.
    # ONCE v0.3.3 consults this Docker keychain. No sibling or persistent login changes.
    old_env = ENV.copy()
    try:
        with tempfile.TemporaryDirectory(prefix="wikicontext-registry-") as directory:
            os.chmod(directory, 0o700)
            ENV["DOCKER_CONFIG"] = directory
            if credentials:
                result = subprocess.run(
                    ["docker", "login", "ghcr.io", "--username", credentials["username"], "--password-stdin"],
                    input=credentials["token"] + "\n", env=ENV, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode:
                    raise RuntimeError("Registry authentication failed")
            yield
    finally:
        ENV.clear()
        ENV.update(old_env)


def task_containers():
    ids = run("docker", "ps", "--all", "--filter", "label=once", "--format", "{{.ID}}", capture=True).split()
    containers = json.loads(run("docker", "inspect", *ids, capture=True)) if ids else []
    matches = [c for c in containers
               if json.loads(c.get("Config", {}).get("Labels", {}).get("once", "{}")).get("host") == HOST]
    return matches


def deploy():
    matches = task_containers()
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one WikiContext container; refusing an ambiguous update")
    container = matches[0]
    if container["Config"]["Image"] != IMAGE and not re.fullmatch(
            r"ghcr\.io/pocketcontext/wikicontext@sha256:[0-9a-f]{64}", container["Config"]["Image"]):
        raise RuntimeError("WikiContext image does not match the fixed deployment target")
    run("docker", "pull", IMAGE)
    try:
        run("docker", "stop", "--time", "60", container["Id"])
        state = json.loads(run("docker", "inspect", "--format", "{{json .State}}", container["Id"], capture=True))
        if state["Running"] or state["ExitCode"] != 0 or state.get("OOMKilled"):
            raise RuntimeError("WikiContext did not stop gracefully; refusing to replace it")
        run("once", "update", HOST, "--image", IMAGE, "--auto-update=false")
    except Exception:
        # ONCE retains the old stopped container when replacement fails to become healthy.
        # Recover service, but still fail the deployment so CI reports the failed update.
        try:
            remaining = task_containers()
            if len(remaining) != 1 or remaining[0]["Id"] != container["Id"]:
                raise RuntimeError("Recovery container is ambiguous; refusing to start another writer")
            run("docker", "start", container["Id"])
        except Exception:
            print("WikiContext recovery failed; operator intervention required", file=sys.stderr)
        raise


DEPLOYMENT_CONFIGURED = False  # Enable only after the deployment target is approved.


def main():
    if not DEPLOYMENT_CONFIGURED:
        raise RuntimeError("WikiContext deployment is not configured or approved")
    if len(sys.argv) != 1:
        raise RuntimeError("This deployment command accepts no arguments")
    if os.geteuid() != 0:
        raise RuntimeError("This deployment command must run as root")
    with open("/run/lock/deploy-wikicontext.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        credentials = read_credentials(sys.stdin.buffer)
        with registry_auth(credentials):
            deploy()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exceptions never include captured metadata or configuration values.
        print(f"Deployment failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
