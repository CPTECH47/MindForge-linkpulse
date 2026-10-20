"""Apply one member's two scoped patches and commit through their own GitHub identity."""

import argparse
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class HandoffError(Exception):
    pass


def git(*args, env=None):
    result = subprocess.run(["git", *args], text=True, capture_output=True, env=env, check=False)
    if result.returncode:
        raise HandoffError(result.stderr.strip() or result.stdout.strip() or "Git command failed.")
    return result.stdout.strip()


def verify_account(username):
    if not shutil.which("gh"):
        raise HandoffError("Install GitHub CLI, then run: gh auth login --hostname github.com")
    result = subprocess.run(
        ["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise HandoffError("GitHub authentication failed. Run: gh auth login --hostname github.com")
    actual = result.stdout.strip()
    if actual.casefold() != username.casefold():
        raise HandoffError(
            f"Signed in as {actual}; this package belongs to {username}. "
            f"Run: gh auth switch --hostname github.com --user {username}"
        )


def credential_input(data, token=None):
    location = urlsplit(data["repository"])
    if location.scheme != "https" or location.hostname != "github.com":
        raise HandoffError("Token authentication is restricted to github.com over HTTPS.")
    fields = {
        "protocol": "https",
        "host": "github.com",
        "path": location.path.lstrip("/"),
        "username": data["username"],
    }
    if token is not None:
        fields["password"] = token
    if any("\n" in value or "\r" in value for value in fields.values()):
        raise HandoffError("Invalid credential field.")
    return "".join(f"{key}={value}\n" for key, value in fields.items()) + "\n"


def keychain_credential(data, token=None):
    if sys.platform != "darwin":
        raise HandoffError("Keychain mode requires macOS. Use GitHub CLI mode on other systems.")
    result = subprocess.run(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=osxkeychain",
            "-c",
            "credential.useHttpPath=true",
            "credential",
            "approve" if token else "fill",
        ],
        input=credential_input(data, token),
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "never",
            "GIT_ASKPASS": "/usr/bin/false",
        },
    )
    if result.returncode:
        raise HandoffError(
            f"No usable Keychain token for {data['username']}. Store it locally with --store-token."
        )
    if token is not None:
        return None
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    value = fields.get("password", "")
    if not value or fields.get("username", "").casefold() != data["username"].casefold():
        raise HandoffError(f"Keychain returned no matching token for {data['username']}.")
    return value


def github_request(path, token):
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "LinkPulse-team-push",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response), response.headers
    except urllib.error.HTTPError as error:
        raise HandoffError(f"GitHub credential or permission check failed (HTTP {error.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise HandoffError("Could not reach GitHub to verify this token. Retry when connected.") from None


def verify_token(data, token):
    account, headers = github_request("/user", token)
    if str(account.get("login", "")).casefold() != data["username"].casefold():
        raise HandoffError(f"This token does not belong to {data['username']}. Nothing was committed.")
    repository = urlsplit(data["repository"]).path.removesuffix(".git")
    details, _ = github_request("/repos" + repository, token)
    if not details.get("permissions", {}).get("push"):
        raise HandoffError(
            f"{data['username']} has no repository push access. Accept the collaborator invitation "
            "and grant the token access to MindForge-linkpulse."
        )
    scopes = headers.get("X-OAuth-Scopes", "")
    owns_workflows = any(
        path.startswith(".github/workflows/") for commit in data["commits"] for path in commit["files"]
    )
    if owns_workflows and scopes and "workflow" not in {part.strip() for part in scopes.split(",")}:
        raise HandoffError("This package adds CI workflows; its classic token also needs workflow scope.")


def verify_keychain(data):
    token = keychain_credential(data)
    verify_token(data, token)


def store_token(data):
    if not sys.stdin.isatty():
        raise HandoffError("Enter tokens only through an interactive local Terminal, not chat or a file.")
    token = getpass.getpass(f"GitHub token for {data['username']} (hidden): ").strip()
    if not token:
        raise HandoffError("No token entered.")
    credential_input(data, token)
    verify_token(data, token)
    keychain_credential(data, token)
    print(f"Verified {data['username']} and saved its repository token in macOS Keychain.")


def push_branch(data, keychain=False):
    if keychain:
        verify_keychain(data)
        location = urlsplit(data["repository"])
        remote = f"https://{data['username']}@github.com{location.path}"
        git(
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=osxkeychain",
            "-c",
            "credential.useHttpPath=true",
            "push",
            "--set-upstream",
            remote,
            data["branch"] + ":refs/heads/" + data["branch"],
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false"},
        )
    else:
        verify_account(data["username"])
        git(
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
            "push",
            "--set-upstream",
            data["repository"],
            data["branch"] + ":refs/heads/" + data["branch"],
        )
    print(f"Pushed {data['branch']} using GitHub account {data['username']}.")


def load_package(package):
    data = json.loads((package / "metadata.json").read_text())
    claimed = set()
    for commit in data["commits"]:
        if not commit["files"] or claimed.intersection(commit["files"]):
            raise HandoffError("Each patch must have its own nonempty, disjoint file scope.")
        claimed.update(commit["files"])
        for filename in commit["files"]:
            path = Path(filename)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
                raise HandoffError(f"Invalid scoped path: {filename}")
        patch = package / commit["patch"]
        if patch.parent != package or hashlib.sha256(patch.read_bytes()).hexdigest() != commit["sha256"]:
            raise HandoffError("A patch was modified or is missing. Obtain the original package.")
    return data


def check_repository(data):
    if git("rev-parse", "--is-inside-work-tree") != "true":
        raise HandoffError("Run this script from a clean clone of MindForge-linkpulse.")
    root = Path(git("rev-parse", "--show-toplevel"))
    os.chdir(root)
    remote = git("remote", "get-url", "origin").removesuffix(".git").rstrip("/")
    expected = data["repository"].removesuffix(".git")
    ssh_remote = "git@github.com:" + expected.removeprefix("https://github.com/")
    if remote.casefold() not in {expected.casefold(), ssh_remote.casefold()}:
        raise HandoffError("Origin does not point to the expected GitHub repository.")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise HandoffError(
            "This checkout has changes. Use a fresh clone and keep the handoff folder outside it."
        )
    git("cat-file", "-e", data["base"] + "^{commit}")


def validate_patches(package, data):
    with tempfile.TemporaryDirectory(prefix="linkpulse-scope-index-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", data["base"], env=env)
        previous = data["base"]
        for commit in data["commits"]:
            git("apply", "--cached", "--whitespace=error-all", str(package / commit["patch"]), env=env)
            changed = set(git("diff", "--cached", "--name-only", previous, env=env).splitlines())
            tree = git("write-tree", env=env)
            if changed != set(commit["files"]) or tree != commit["tree"]:
                raise HandoffError("Patch contents do not match this member's declared scope.")
            previous = tree


def existing_commits(data):
    ref = "refs/heads/" + data["branch"]
    exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", ref], check=False).returncode == 0
    if not exists:
        return [], False
    git("merge-base", "--is-ancestor", data["base"], ref)
    commits = git("rev-list", "--reverse", data["base"] + ".." + ref).splitlines()
    if len(commits) > len(data["commits"]):
        raise HandoffError("This branch has extra commits. Use a fresh clone for this handoff.")
    parent = data["base"]
    for oid, expected in zip(commits, data["commits"]):
        actual = git(
            "show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce%x00%aI%x00%cI%x00%T%x00%P%x00%B", oid
        ).split("\0")
        wanted = [
            data["name"],
            data["email"],
            data["name"],
            data["email"],
            expected["date"],
            expected["date"],
            expected["tree"],
            parent,
            expected["message"],
        ]
        if actual != wanted:
            raise HandoffError("Existing branch commits differ from this handoff. Use a fresh clone.")
        parent = oid
    return commits, True


def create_commits(package, data):
    commits, exists = existing_commits(data)
    if exists:
        git("switch", data["branch"])
    else:
        git("switch", "--create", data["branch"], data["base"])
    for commit in data["commits"][len(commits) :]:
        git("apply", "--index", "--whitespace=error-all", str(package / commit["patch"]))
        changed = set(git("diff", "--cached", "--name-only").splitlines())
        if changed != set(commit["files"]) or git("write-tree") != commit["tree"]:
            raise HandoffError("Staged files differ from the declared scope. Nothing was committed.")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": data["name"],
            "GIT_AUTHOR_EMAIL": data["email"],
            "GIT_COMMITTER_NAME": data["name"],
            "GIT_COMMITTER_EMAIL": data["email"],
            "GIT_AUTHOR_DATE": commit["date"],
            "GIT_COMMITTER_DATE": commit["date"],
        }
        git("commit", "-m", commit["message"], env=env)
        print(git("log", "-1", "--format=%h %s"))
    existing_commits(data)
    if git("status", "--porcelain", "--untracked-files=all"):
        raise HandoffError("Unexpected changes remain after committing. Inspect before pushing.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check", action="store_true", help="Validate patches without commits or login.")
    parser.add_argument("--push", action="store_true", help="Also push the member's branch after checks.")
    parser.add_argument("--keychain", action="store_true", help="Use this member's saved macOS token.")
    parser.add_argument(
        "--store-token", action="store_true", help="Prompt locally and save a verified token."
    )
    options = parser.parse_args()
    if options.check and options.push:
        parser.error("Choose --check or --push, not both.")
    if options.store_token and (options.check or options.push):
        parser.error("Store a token separately from checking, committing or pushing.")
    package = options.package.resolve()
    try:
        data = load_package(package)
        if options.store_token:
            store_token(data)
            return
        check_repository(data)
        validate_patches(package, data)
        if options.check:
            print(f"Scope and patch checks passed for {data['name']}. No commits or pushes made.")
            return
        if options.keychain:
            verify_keychain(data)
        else:
            verify_account(data["username"])
        create_commits(package, data)
        print(f"Two scoped commits ready on {data['branch']}.")
        if options.push:
            push_branch(data, keychain=options.keychain)
        else:
            print("Review: git log -2 --format=fuller && git diff --stat " + data["base"] + "..HEAD")
            print("To push, rerun this script with --push. Existing commits will be checked and reused.")
    except (HandoffError, OSError, ValueError, KeyError) as error:
        print(f"Handoff stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
