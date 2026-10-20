# Team commits and scope

Each member's branch contains their two scoped commits and is pushed using their own GitHub account. Members can run their own package, or one authorized operator can use the five account owners' tokens on the same Mac. Author names alone do not establish which GitHub account pushed a branch.

The repository owner must first add the four other GitHub accounts as collaborators, and each member must accept the invitation. Each listed commit email must be added and verified on its owner's GitHub account. Do not share passwords or access tokens.

## Ownership and branches

| Member | GitHub | Branch | Scope |
| --- | --- | --- | --- |
| Tejas Pant | tejaspant09 | feature/tejas/link-ui | Page layouts, navigation, CSS, creation wizard and frontend validation |
| Charchit Pant | CPTECH47 | feature/charchit/auth-crud | Models, migrations, login, workspace isolation and link/group management |
| Pulkit Joshi | pulkitjoshi987 | feature/pulkit/redirects | Redirect admission, expiry/caps, password gates, validation and security controls |
| Jaanvi Kandpal | jaanvikandpal170-jpg | feature/jaanvi/analytics | Event capture/enrichment, retry/retention, stored-event reports and dashboard charts |
| Mansi Nagarkoti | mansinagarkoti | feature/mansi/qr-csv-deploy | QR/CSV/bio sharing, runtime wiring, deployment, documentation and integration tests |

`team-scopes.json` is the exact file-to-commit assignment. Every application file belongs to one member and one patch. Views, forms and admin registrations are split into feature modules so branches do not compete for a shared implementation file. Package initializers and project URL wiring belong to Mansi's integration scope. Existing imports such as `links.forms.LinkForm` remain available in the integrated application.

## Dates and meaningful commits

Both author and committer timestamps use the requested historical schedule in IST (`+05:30`). These dates are Git metadata; GitHub receives the actual pushes when members execute them. The packages do not claim that pushes happened on those earlier dates.

| Member | Commit 1 | Commit 2 |
| --- | --- | --- |
| Charchit | October 19, 2026, 09:15 | October 20, 2026, 09:30 |
| Pulkit | October 19, 2026, 10:30 | October 20, 2026, 10:45 |
| Jaanvi | October 19, 2026, 11:45 | October 20, 2026, 12:00 |
| Tejas | October 19, 2026, 13:00 | October 20, 2026, 13:15 |
| Mansi | October 19, 2026, 14:15 | October 20, 2026, 14:30 |

Each patch has a descriptive `feat:` or `chore:` message. The two patches separate real deliverables rather than duplicating or padding commits. Later changes should be committed when the member completes another meaningful change.

## Build the five handoff packages

From the complete project checkout, run this with an output directory that does not already exist:

```sh
python3 tools/build_team_handoff.py --output artifacts/team-handoff
```

This produces five individual ZIPs and `linkpulse-team-handoff.zip` inside the ignored `artifacts/team-handoff` directory. Send each member only their own individual ZIP. The builder checks scope coverage, rejects em dashes, verifies that all ten patches apply together and compares every reconstructed file with the source. It creates no commits, pushes nothing and leaves this repository's Git metadata alone.

## Each member runs their own package

Install Git, Python 3 and GitHub CLI from https://cli.github.com. Extract the package outside a fresh clone. The package's README contains commands customized for the member. For example, Tejas runs:

```sh
git clone https://github.com/CPTECH47/MindForge-linkpulse.git linkpulse-tejas
cd linkpulse-tejas
gh auth login --hostname github.com --git-protocol https --web
python3 /absolute/path/to/tejas/commit_and_push.py --check
python3 /absolute/path/to/tejas/commit_and_push.py
git log -2 --format=fuller
git diff --stat c50f0d0d8f6451fd228ab4b9d893f159e09f7cb5..HEAD
python3 /absolute/path/to/tejas/commit_and_push.py --push
```

Replace the script path with the extracted package's actual path. The first command with `--check` creates no commits. The next invocation verifies the signed-in GitHub username and creates the member's two commits. After reviewing them, `--push` checks and reuses those commits, checks the GitHub account again and pushes only the member's branch. A mismatched account, dirty checkout, tampered patch, unrelated file or unexpected existing commit stops the helper. It never force-pushes or pushes `main`.

The helper checks the active account but cannot prove who is operating the computer. Members can execute their individual packages themselves; the authorized same-computer workflow below is also available. GitHub email attribution depends on each member verifying the specified email in their account settings.

## Push all five branches from the current Mac

With each account owner's authorization, use their personal access token for their own branch. Token authentication identifies the GitHub account, not the person physically operating the computer. GitHub email attribution still requires each member to verify the supplied email in their account settings.

From the complete project folder, run:

```sh
python3 tools/push_team.py --store-tokens
python3 tools/push_team.py --check-auth
python3 tools/push_team.py --push
```

`--store-tokens` prompts for each token with Terminal echo disabled, verifies the GitHub username and repository push access, and stores the token in macOS Keychain, keyed by repository path and username. Tokens are never accepted as command-line arguments or saved in the project, environment files or handoff archives. No GitHub CLI installation is required for Keychain mode.

`--check-auth` verifies saved credentials without commits or pushes. `--push` validates all five accounts before creating commits, uses a separate checkout under the ignored `artifacts/team-push` folder, and pushes each feature branch with the matching account. It keeps the requested author/committer names, emails and historical timestamps. It never pushes `main` or force-pushes. It can resume its own unchanged commits after an interrupted run.

To replace just one account's token, use `python3 tools/push_team.py --store-tokens --member tejas`, substituting the member's lowercase first name.

Each token must permit writing repository contents, and the account must have accepted its collaborator invitation. Mansi's token also needs permission to write workflows because her package includes `.github/workflows/test.yml`. For classic tokens on this public repository, use `public_repo`, plus `workflow` for Mansi. If using a fine-grained token, grant access to this repository with Contents read/write and Workflows read/write for Mansi, subject to GitHub's account eligibility restrictions.

References: [GitHub multi-account authentication](https://docs.github.com/en/account-and-profile/how-tos/account-management/managing-multiple-accounts), [macOS Keychain credentials](https://docs.github.com/en/get-started/git-basics/updating-credentials-from-the-macos-keychain).

## Integrate all five branches

All branches start from the repository's existing initial commit, `c50f0d0d8f6451fd228ab4b9d893f159e09f7cb5`. Each branch contains only that owner's feature files and has dependencies on the other members' modules. Individual branches are not standalone applications. Run the full application tests on their combined result.

After every member has pushed, a maintainer can create a local integration branch and merge the five branches:

```sh
git fetch origin
git switch --create feature/mansi/team-integration origin/main
git merge --no-ff origin/feature/charchit/auth-crud
git merge --no-ff origin/feature/pulkit/redirects
git merge --no-ff origin/feature/jaanvi/analytics
git merge --no-ff origin/feature/tejas/link-ui
git merge --no-ff origin/feature/mansi/qr-csv-deploy
```

Use the verification commands in README.md with PostgreSQL, then merge the integration branch into `main` through the team's review process. Keep the original feature commits: use merge commits, not squash merging, if both commits per member must remain in the final history. A maintainer's integration merge records combining reviewed work and does not replace the members' own feature commits.

The full application CI runs on `main`, the combined `feature/mansi/team-integration` branch, and pull requests targeting `main`. Individual member branches depend on each other and should be integrated together before opening the application integration pull request.
