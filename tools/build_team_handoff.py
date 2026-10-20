"""Build five scoped patch packages without creating commits or modifying this repo's Git metadata."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def run(*args, cwd, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = options.output.resolve()
    manifest = json.loads((root / "docs/team-scopes.json").read_text())
    candidates = set(
        run("git", "ls-files", "--cached", "--others", "--exclude-standard", cwd=root).splitlines()
    )
    scoped = [path for owner in manifest["owners"] for commit in owner["commits"] for path in commit["files"]]
    if len(scoped) != len(set(scoped)) or set(scoped) != candidates:
        raise SystemExit(
            f"Scope coverage mismatch. Missing: {sorted(candidates - set(scoped))}; "
            f"extra: {sorted(set(scoped) - candidates)}. Each file must have one owner."
        )
    for filename in scoped:
        try:
            content = (root / filename).read_text()
        except UnicodeDecodeError:
            continue
        if "\u2014" in content:
            raise SystemExit(f"Replace the em dash in {filename} before building.")
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="linkpulse-handoff-build-") as directory:
        scratch = Path(directory) / "repository"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(root), str(scratch)],
            check=True,
        )
        for filename in scoped:
            target = scratch / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / filename, target)
        package_names = []
        for owner in manifest["owners"]:
            package = output / owner["key"]
            package.mkdir()
            data = {**owner, "repository": manifest["repository"], "base": manifest["base"]}
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / (owner["key"] + ".index"))}
            run("git", "read-tree", manifest["base"], cwd=scratch, env=env)
            previous = manifest["base"]
            for number, commit in enumerate(data["commits"], 1):
                run("git", "add", "--", *commit["files"], cwd=scratch, env=env)
                actual = set(
                    run("git", "diff", "--cached", "--name-only", previous, cwd=scratch, env=env).splitlines()
                )
                if actual != set(commit["files"]):
                    raise SystemExit(f"Unchanged or unexpected files in {owner['key']} commit {number}.")
                patch = subprocess.check_output(
                    ["git", "diff", "--cached", "--binary", "--full-index", "--no-renames", previous],
                    cwd=scratch,
                    env=env,
                )
                commit["patch"] = f"{number:02d}.patch"
                commit["sha256"] = hashlib.sha256(patch).hexdigest()
                commit["tree"] = run("git", "write-tree", cwd=scratch, env=env)
                (package / commit["patch"]).write_bytes(patch)
                previous = commit["tree"]
            (package / "metadata.json").write_text(json.dumps(data, indent=2) + "\n")
            shutil.copy2(root / "tools/team_commit.py", package / "commit_and_push.py")
            (package / "README.md").write_text(
                f"# {owner['name']} - LinkPulse handoff\n\n"
                f"GitHub account: `{owner['username']}`\n\n"
                f"Commit email: `{owner['email']}`. Add and verify this email on your own GitHub account.\n\n"
                "Install Git, Python 3 and GitHub CLI (https://cli.github.com). "
                "The repository owner must give your account collaborator access before pushing.\n\n"
                "Extract this folder outside the repository. In a fresh clone, run:\n\n"
                "```sh\n"
                f"git clone {manifest['repository']} linkpulse-{owner['key']}\n"
                f"cd linkpulse-{owner['key']}\n"
                "gh auth login --hostname github.com --git-protocol https --web\n"
                f"python3 /absolute/path/to/{owner['key']}/commit_and_push.py --check\n"
                f"python3 /absolute/path/to/{owner['key']}/commit_and_push.py\n"
                "git log -2 --format=fuller\n"
                f"git diff --stat {manifest['base']}..HEAD\n"
                f"python3 /absolute/path/to/{owner['key']}/commit_and_push.py --push\n"
                "```\n\n"
                "Replace the absolute script path with your extracted folder's actual path. "
                "Run only your own package. The helper checks the active GitHub username, "
                "patch checksums, staged file scope and both commit identities and timestamps. "
                "It never force-pushes or pushes main. It can reuse its own two existing commits.\n\n"
                "On a Mac, authorized operators can instead run `--store-token` to enter this account's "
                "token through a hidden Terminal prompt, then use `--keychain` when committing or "
                "`--keychain --push` when pushing. This mode uses macOS Keychain and does not need "
                "GitHub CLI. Never put a token in chat, a command argument or a project file. "
                "For all five accounts from one Mac, see docs/CONTRIBUTIONS.md in the complete project.\n\n"
                "## Scheduled metadata\n\n"
                + "\n".join(f"- `{commit['date']}`: `{commit['message']}`" for commit in data["commits"])
                + "\n\nThe supplied historical dates set Git metadata only; GitHub receives the push when you run it. "
                "This feature branch depends on the other four packages. Integrate all five before deploying.\n"
            )
            package_names.append(owner["key"])
            with zipfile.ZipFile(output / (owner["key"] + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(package.iterdir()):
                    archive.write(path, path.relative_to(output))
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "integration.index")}
        run("git", "read-tree", manifest["base"], cwd=scratch, env=env)
        for owner in manifest["owners"]:
            for commit in owner["commits"]:
                run(
                    "git",
                    "apply",
                    "--cached",
                    "--whitespace=error-all",
                    str(output / owner["key"] / commit["patch"]),
                    cwd=scratch,
                    env=env,
                )
        run("git", "diff", "--cached", "--check", cwd=scratch, env=env)
        for filename in scoped:
            expected = run("git", "hash-object", str(root / filename), cwd=scratch)
            actual = run("git", "rev-parse", ":" + filename, cwd=scratch, env=env)
            if expected != actual:
                raise SystemExit(f"Reconstruction differs from source: {filename}")
        report = {
            "files": len(scoped),
            "owners": len(package_names),
            "patches": 10,
            "integrated_tree": run("git", "write-tree", cwd=scratch, env=env),
            "commits_created": 0,
            "pushes": 0,
        }
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    with zipfile.ZipFile(output / "linkpulse-team-handoff.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for key in package_names:
            for path in sorted((output / key).iterdir()):
                archive.write(path, path.relative_to(output))
        archive.write(output / "verification.json", "verification.json")
    print(json.dumps({"output": str(output), **report}, indent=2))


if __name__ == "__main__":
    main()
