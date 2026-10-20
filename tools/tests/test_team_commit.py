"""Exercise scope, identity and restart checks in disposable repositories with synthetic identities."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[1] / "team_commit.py"
SPEC = importlib.util.spec_from_file_location("team_commit", HELPER)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


class TeamHandoffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="linkpulse-handoff-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        self.package = self.root / "package"
        self.package.mkdir()
        original = Path.cwd()
        os.chdir(self.repository)
        self.addCleanup(os.chdir, original)
        handoff.git("init", "--initial-branch=main")
        handoff.git("config", "user.name", "Synthetic Test Member")
        handoff.git("config", "user.email", "test-member@example.invalid")
        handoff.git("config", "commit.gpgsign", "false")
        handoff.git("remote", "add", "origin", "https://github.com/example/test.git")
        Path("README.md").write_text("Fixture baseline.\n")
        handoff.git("add", "README.md")
        handoff.git("commit", "-m", "test: create fixture baseline")
        base = handoff.git("rev-parse", "HEAD")
        self.data = {
            "key": "fixture",
            "name": "Synthetic Test Member",
            "username": "test-member",
            "email": "test-member@example.invalid",
            "branch": "feature/fixture/scoped-changes",
            "repository": "https://github.com/example/test.git",
            "base": base,
            "commits": [],
        }
        previous = base
        for number in (1, 2):
            filename = f"feature-{number}.txt"
            Path(filename).write_text(f"Scoped fixture change {number}.\n")
            handoff.git("add", filename)
            content = subprocess.check_output(
                ["git", "diff", "--cached", "--binary", "--full-index", previous]
            )
            tree = handoff.git("write-tree")
            name = f"{number:02d}.patch"
            (self.package / name).write_bytes(content)
            self.data["commits"].append(
                {
                    "files": [filename],
                    "patch": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "tree": tree,
                    "date": f"2026-10-{18 + number}T12:00:00+05:30",
                    "message": f"feat: add scoped fixture {number}",
                }
            )
            previous = tree
        handoff.git("read-tree", base)
        Path("feature-1.txt").unlink()
        Path("feature-2.txt").unlink()
        (self.package / "metadata.json").write_text(json.dumps(self.data))

    def test_two_scoped_commits_keep_dates_and_can_resume(self):
        data = handoff.load_package(self.package)
        handoff.check_repository(data)
        handoff.validate_patches(self.package, data)
        with contextlib.redirect_stdout(io.StringIO()):
            handoff.create_commits(self.package, data)
            handoff.create_commits(self.package, data)
        commits, exists = handoff.existing_commits(data)
        self.assertTrue(exists)
        self.assertEqual(len(commits), 2)
        self.assertEqual(handoff.git("status", "--porcelain"), "")

    def test_modified_patch_is_rejected(self):
        with (self.package / "01.patch").open("ab") as stream:
            stream.write(b"tampered\n")
        with self.assertRaisesRegex(handoff.HandoffError, "modified"):
            handoff.load_package(self.package)

    def test_patch_cannot_add_another_owners_file(self):
        self.data["commits"][0]["files"] = ["unrelated.txt"]
        with self.assertRaisesRegex(handoff.HandoffError, "declared scope"):
            handoff.validate_patches(self.package, self.data)
        self.assertEqual(handoff.git("status", "--porcelain"), "")

    def test_dirty_checkout_is_rejected_before_commits(self):
        Path("unrelated.txt").write_text("Existing user work.\n")
        with self.assertRaisesRegex(handoff.HandoffError, "fresh clone"):
            handoff.check_repository(self.data)
        self.assertEqual(handoff.git("rev-parse", "HEAD"), self.data["base"])

    def test_wrong_github_account_is_rejected(self):
        response = subprocess.CompletedProcess([], 0, stdout="another-member\n", stderr="")
        with (
            patch.object(handoff.shutil, "which", return_value="gh"),
            patch.object(handoff.subprocess, "run", return_value=response),
            self.assertRaisesRegex(handoff.HandoffError, "belongs to test-member"),
        ):
            handoff.verify_account("test-member")

    def test_unrelated_extra_commit_blocks_resume_and_push(self):
        with contextlib.redirect_stdout(io.StringIO()):
            handoff.create_commits(self.package, self.data)
        Path("unrelated.txt").write_text("Outside scope.\n")
        handoff.git("add", "unrelated.txt")
        handoff.git("commit", "-m", "test: inject unrelated fixture commit")
        with self.assertRaisesRegex(handoff.HandoffError, "extra commits"):
            handoff.existing_commits(self.data)

    def test_token_owner_must_match_member(self):
        with (
            patch.object(handoff, "github_request", return_value=({"login": "another-member"}, {})),
            self.assertRaisesRegex(handoff.HandoffError, "does not belong"),
        ):
            handoff.verify_token(self.data, "synthetic-token-value")

    def test_token_requires_repository_push_access(self):
        responses = [({"login": "test-member"}, {}), ({"permissions": {"push": False}}, {})]
        with (
            patch.object(handoff, "github_request", side_effect=responses),
            self.assertRaisesRegex(handoff.HandoffError, "no repository push access"),
        ):
            handoff.verify_token(self.data, "synthetic-token-value")

    def test_matching_token_and_write_access_pass(self):
        responses = [({"login": "TEST-MEMBER"}, {}), ({"permissions": {"push": True}}, {})]
        with patch.object(handoff, "github_request", side_effect=responses):
            handoff.verify_token(self.data, "synthetic-token-value")

    def test_workflow_package_requires_classic_workflow_scope(self):
        self.data["commits"][0]["files"].append(".github/workflows/test.yml")
        responses = [
            ({"login": "test-member"}, {"X-OAuth-Scopes": "public_repo"}),
            ({"permissions": {"push": True}}, {}),
        ]
        with (
            patch.object(handoff, "github_request", side_effect=responses),
            self.assertRaisesRegex(handoff.HandoffError, "workflow scope"),
        ):
            handoff.verify_token(self.data, "synthetic-token-value")

    def test_keychain_stores_token_via_stdin_not_process_arguments(self):
        response = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with (
            patch.object(handoff.sys, "platform", "darwin"),
            patch.object(handoff.subprocess, "run", return_value=response) as command,
        ):
            handoff.keychain_credential(self.data, "synthetic-token-value")
        args, kwargs = command.call_args
        self.assertNotIn("synthetic-token-value", " ".join(args[0]))
        self.assertIn("username=test-member\n", kwargs["input"])
        self.assertIn("path=example/test.git\n", kwargs["input"])
        self.assertIn("password=synthetic-token-value\n", kwargs["input"])

    def test_keychain_cannot_return_another_accounts_credential(self):
        response = subprocess.CompletedProcess(
            [], 0, stdout="username=another-member\npassword=synthetic-token-value\n", stderr=""
        )
        with (
            patch.object(handoff.sys, "platform", "darwin"),
            patch.object(handoff.subprocess, "run", return_value=response),
            self.assertRaisesRegex(handoff.HandoffError, "no matching token"),
        ):
            handoff.keychain_credential(self.data)

    def test_token_prompt_rejects_noninteractive_input(self):
        with (
            patch.object(handoff.sys.stdin, "isatty", return_value=False),
            self.assertRaisesRegex(handoff.HandoffError, "interactive local Terminal"),
        ):
            handoff.store_token(self.data)

    def test_keychain_push_targets_only_the_matching_members_branch(self):
        with (
            patch.object(handoff, "verify_keychain") as verify,
            patch.object(handoff, "git") as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            handoff.push_branch(self.data, keychain=True)
        verify.assert_called_once_with(self.data)
        args = command.call_args.args
        self.assertIn("credential.helper=osxkeychain", args)
        self.assertIn("credential.useHttpPath=true", args)
        self.assertIn("https://test-member@github.com/example/test.git", args)
        self.assertEqual(args[-1], "feature/fixture/scoped-changes:refs/heads/feature/fixture/scoped-changes")
        self.assertNotIn("--force", args)
        self.assertNotIn("refs/heads/main", args)


if __name__ == "__main__":
    unittest.main()
