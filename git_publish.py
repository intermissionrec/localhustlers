#!/usr/bin/env python3
"""
Thin wrapper around the `git` CLI used by editor_app.py to publish
changes straight to the GitHub repo backing GitHub Pages.

Two ways to authenticate, auto-detected:

1. Local machine, no token: relies on whatever git credentials are
   already configured on this machine (SSH key, cached HTTPS
   credential helper) — the same as pushing by hand. This is the
   default when no token is supplied.

2. Headless / VM, with a GitHub Personal Access Token: set the
   GITHUB_TOKEN environment variable (a fine-grained PAT scoped to
   just this repo, with "Contents: Read and write" permission is
   enough) and every git operation here authenticates with it
   instead. The token is passed to git via GIT_ASKPASS + a short-lived
   temp script, so it never appears in argv (visible to `ps`) or gets
   written into .git/config — it only lives in an environment
   variable for the lifetime of that one git subprocess.

Either way, this module just shells out to `git` — it doesn't touch
your credentials directly.
"""
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

TOKEN_ENV_VAR = "GITHUB_TOKEN"


def _run(root: Path, *args, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    # never let git fall back to an interactive prompt and hang
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=full_env,
    )


def _parse_owner_repo(url: str):
    """Pull owner/repo out of an https:// or git@ GitHub remote URL."""
    match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _token_push_url(remote: str, token: str):
    parsed = _parse_owner_repo(remote)
    if not parsed:
        return None
    owner, repo = parsed
    return f"https://x-access-token@github.com/{owner}/{repo}.git"


class _Askpass:
    """Temp helper script that hands git a token via GIT_ASKPASS, so the
    token never appears on the command line or in a git config file."""

    def __init__(self, token: str):
        self.token = token
        self.path = None

    def __enter__(self):
        fd, path = tempfile.mkstemp(prefix="lh_askpass_", suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write('#!/bin/sh\necho "$LH_GIT_TOKEN"\n')
        os.chmod(path, stat.S_IRWXU)
        self.path = path
        return {"GIT_ASKPASS": path, "LH_GIT_TOKEN": self.token, "GIT_TERMINAL_PROMPT": "0"}

    def __exit__(self, *exc):
        if self.path and os.path.exists(self.path):
            os.remove(self.path)


def token_configured() -> bool:
    return bool(os.environ.get(TOKEN_ENV_VAR))


def is_git_repo(root: Path) -> bool:
    return _run(root, "rev-parse", "--is-inside-work-tree").returncode == 0


def current_branch(root: Path):
    result = _run(root, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def remote_url(root: Path, name="origin"):
    result = _run(root, "remote", "get-url", name)
    return result.stdout.strip() if result.returncode == 0 else None


def status_lines(root: Path):
    """Uncommitted changes, porcelain-style, one entry per line."""
    result = _run(root, "status", "--porcelain")
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


class _null_ctx:
    """No-op context manager used when there's no token — keeps the
    `with` block in publish() the same shape either way."""

    def __enter__(self):
        return {}

    def __exit__(self, *exc):
        return False


def publish(root: Path, commit_message: str, pull_first: bool = True, token: str = None):
    """
    Stage everything under `root`, commit, and push to origin/<branch>.

    If `token` is given (or GITHUB_TOKEN is set in the environment and
    `token` is left as None), pull/push authenticate with that PAT
    instead of your locally configured git credentials — this is what
    makes it work unattended on a VM.

    Returns (ok: bool, steps: list[(label, subprocess.CompletedProcess)])
    so the caller can show exactly what happened at each step.
    """
    steps = []
    token = token or os.environ.get(TOKEN_ENV_VAR)

    branch = current_branch(root)
    if not branch:
        fake = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
            returncode=1,
            stdout="",
            stderr="Could not determine the current git branch. Is this folder a git repo?",
        )
        return False, [("branch", fake)]

    push_target = "origin"
    askpass_env = {}
    if token:
        origin = remote_url(root)
        token_url = _token_push_url(origin, token) if origin else None
        if not token_url:
            fake = subprocess.CompletedProcess(
                args=["git", "remote", "get-url", "origin"],
                returncode=1,
                stdout="",
                stderr=(
                    "GITHUB_TOKEN is set, but I couldn't figure out the "
                    "owner/repo from the 'origin' remote URL to build an "
                    "authenticated push URL."
                ),
            )
            return False, [("token setup", fake)]
        push_target = token_url

    with _Askpass(token) if token else _null_ctx() as askpass_env:
        if pull_first:
            pull_source = push_target if token else "origin"
            r = _run(root, "pull", "--rebase", pull_source, branch, env=askpass_env)
            steps.append((f"pull --rebase {'<token>' if token else 'origin'} {branch}", r))
            if r.returncode != 0:
                return False, steps

        r = _run(root, "add", ".")
        steps.append(("add .", r))
        if r.returncode != 0:
            return False, steps

        r = _run(root, "commit", "-m", commit_message)
        steps.append(("commit", r))
        nothing_to_commit = r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr).lower()
        if r.returncode != 0 and not nothing_to_commit:
            return False, steps

        r = _run(root, "push", push_target, branch, env=askpass_env)
        steps.append((f"push {'<token>' if token else 'origin'} {branch}", r))
        if r.returncode != 0:
            return False, steps

    return True, steps
