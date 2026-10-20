"""Store authorized tokens locally, then commit and push each member's scoped branch from one Mac."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from team_commit import (
    HandoffError,
    check_repository,
    create_commits,
    existing_commits,
    git,
    load_package,
    push_branch,
    store_token,
    validate_patches,
    verify_keychain,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--store-tokens", action="store_true", help="Prompt for tokens and store in Keychain.")
    modes.add_argument(
        "--check-auth", action="store_true", help="Verify all five saved accounts without commits."
    )
    modes.add_argument(
        "--push", action="store_true", help="Create the ten commits and push the five branches."
    )
    parser.add_argument("--member", help="Limit credential setup or authentication checks to one member.")
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    packages = root / "artifacts/team-handoff"
    manifest = json.loads((root / "docs/team-scopes.json").read_text())
    try:
        if options.push and options.member:
            raise HandoffError("Use --member for token setup/checks; --push validates and handles all five.")
        owners = manifest["owners"]
        if options.member:
            owners = [owner for owner in owners if owner["key"] == options.member]
            if not owners:
                raise HandoffError("Unknown member. Use tejas, charchit, pulkit, jaanvi or mansi.")
        data = [load_package(packages / owner["key"]) for owner in owners]
        if options.store_tokens:
            for owner in data:
                store_token(owner)
            print("Token setup complete. No commits or pushes made.")
            return
        for owner in data:
            verify_keychain(owner)
            print(f"Verified repository access for {owner['username']}.")
        if options.check_auth:
            print("All selected accounts verified. No commits or pushes made.")
            return
        workspace = root / "artifacts/team-push"
        if not workspace.exists():
            subprocess.run(
                ["git", "clone", "--quiet", "--no-hardlinks", str(root), str(workspace)], check=True
            )
            os.chdir(workspace)
            git("remote", "set-url", "origin", manifest["repository"])
        else:
            os.chdir(workspace)
        # Preflight every patch before creating any member's commits.
        for owner in data:
            check_repository(owner)
            validate_patches(packages / owner["key"], owner)
            existing_commits(owner)
        for owner in data:
            check_repository(owner)
            verify_keychain(owner)
            create_commits(packages / owner["key"], owner)
            push_branch(owner, keychain=True)
        print("Pushed five scoped branches with two commits each. main was not pushed.")
    except (HandoffError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Team push stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
