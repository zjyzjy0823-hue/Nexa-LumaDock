# Validation workflow

Start with the local diff, detect its boundaries, consult the physical validation
baseline, run targeted checks, then commit/push and verify that commit's GitHub CI.
Release publication is a separate step.

```text
git diff → Change Impact → Validation Baseline → Targeted Tests → GitHub CI → Release
```

```console
python scripts/detect-change-impact.py
python scripts/detect-change-impact.py --base <commit> --head HEAD --json
python scripts/detect-change-impact.py --base f59b60de688a5a5b35471e2a47a4a31dd1baaabf --include-worktree
python scripts/validate-release.py --include-worktree --run-local --evidence .git/v061-local-validation.json
```

The default impact input includes staged, unstaged and non-ignored untracked
files. Explicit `--base`/`--head` compares commits; `--include-worktree` adds local
changes, and requires the current HEAD. Renames inspect both the old and new
paths. Inheritance always compares the baseline with the selected HEAD (plus
the working tree when requested), so a narrow range cannot hide earlier changes.

- **PASS**: the check actually ran successfully, or the release owner recorded
  a physical PASS in `.validation-baseline.json`.
- **REUSED**: the previous physical PASS still protects unchanged boundaries.
  This does not claim a new physical test run.
- **INVALIDATED**: a protected boundary changed, or the prior result was not
  PASS. The corresponding physical check needs fresh evidence.

Rules in `scripts/change_impact.py` distinguish presentation, services, sync,
conflicts, identity, connection, migrations, sidecar and platform packaging.
Unknown paths conservatively invalidate protected boundaries. Pure product
version changes do not invalidate physical results; dependency or other edits
in those same metadata files do. CI changes outside its existing Windows
packaging job preserve the Desktop baseline. Tests themselves do not change
product boundaries. Extend explicit path rules when adding new infrastructure.

The release report always analyzes the cumulative baseline diff. `--run-local`
executes the supported targeted commands and builds for the current tree.
Physical checks and packaged smoke are deliberately **NOT_RUN** if required:
they need the relevant platform/environment and must not be invented by a script.
The local runner is a small starting point; inspect its command mapping when
introducing a new service. CI continues to run all existing jobs.

Evidence files are trusted local command records, not signed attestations. They
are only reusable while the cumulative changed file contents match. After
committing/pushing, verify the exact commit's run:

```console
python scripts/validate-release.py --evidence .git/v061-local-validation.json --ci-run <run-id>
```

CI is **NOT_RUN** without a supplied run, **PENDING** while running, and **PASS**
only for a successful run whose commit matches the report HEAD and whose jobs
all succeeded. `RELEASE_READY=YES` requires a clean tree, required checks PASS,
and verified CI PASS. It does not create a tag, merge or publish anything.
Exit 0 means reporting succeeded (even if checks are pending); invalid input,
stale evidence, failed executed checks or failed verified CI return nonzero.

Settings → About includes **Nexa Diagnostics**, Refresh and Copy Diagnostics.
The authenticated read-only snapshot shows backend/database health, local/Core
workspace and client presence, queue counts, last sync success, protocol
compatibility and actual automation task status. An older Core without the new
client diagnostics endpoint remains connected with protocol/runtime **unknown**.
Local automation remains OFF. A failed API request is displayed as unavailable;
the UI never copies raw request errors. Database/auth failure can prevent the
snapshot itself from being returned, so use `/api/health` to distinguish backend
availability. No queue seeding, mutation, migration or sync cycle is triggered.
Core probing uses existing credentials/transport and only projects safe fields;
tokens, login data, response bodies and exception messages are excluded.
