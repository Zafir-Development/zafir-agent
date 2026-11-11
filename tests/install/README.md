# Install and Update E2E Tests

These tests answer one question: can a user on a released version get to this commit?

Each leg installs a released version and updates it through the real user
surface: the installer one-liner and the updater CLI, against the selected
checkout revision. The harness can use a mock LLM provider for interaction. It
does not substitute a mock installer or updater for either real entry point.

## The layers

The test family has four layers. Each layer has one job.

1. `scripts/sandbox/generate-e2e-matrix.mjs` declares the support matrix. It lists every {os, install-method, update-method} pair. It expands the pairs against the sampled release tags. It knows nothing about which pairs CI can run.
2. `.github/workflows/install-e2e.yml` is the primary workflow. It picks the release tags, runs the generator, and fans out one matrix job per OS. It also writes the plan chart and the result chart on the run summary.
3. The run workflows own the capability knowledge. `install-e2e-run.yml` serves linux and macos (`install-e2e-macos-run.yml` is the macOS entry that delegates to it). `install-e2e-windows-run.yml` serves windows. Job-level `if:` gates select the supported pairs. All other pairs skip natively and show as grey.
4. The drivers do the work. `tests/install/installer-script-e2e.sh` handles POSIX installs, and `tests/install/windows-e2e.ps1` handles Windows installs. Install and update methods are separate axes, subject to each workflow's capability gates.

To declare a new method, edit the generator. To implement a method, flip the gate in the run workflow and extend a driver.

## The isolation trick

Source drivers redirect canonical Hermes Git URLs to a local bare clone at
`serve.git`, using a driver-owned `GIT_CONFIG_GLOBAL` rewrite. This controls
the source install/update boundary, not all network access: tool/dependency
downloads can still use the network.

The driver parks the `main` branch of `serve.git` at the old release. The installer runs and lands on the old release. Then the driver moves `main` to HEAD. An update becomes available in the same way that it does for a real user.

For script-install legs, the installer comes from the old Git ref. A
script-reinstall update uses the target revision's script. A `hermes-update`
leg starts the old release's updater. These paths are intentionally different.

### The HEAD -> NEXT column

Every combination also runs from HEAD itself. The driver installs HEAD, then mints NEXT: a synthetic child of HEAD that adds one marker file (`.hermes-e2e-next`). NEXT exists only in the object store, with no ref, and the bare clone carries it into `serve.git`. The driver then moves `main` to NEXT and applies the update method.

This column tests two things that no tag leg tests:

- HEAD's installer on an empty machine. Tag legs run an old installer, or run HEAD's installer over an existing install.
- HEAD's own updater. Tag legs start the old release's updater.

On Windows, the HEAD leg also takes every `git.exe` directory off PATH and installs no `remote get-url` shim. `install.ps1` uses any git that it finds on PATH, so without this step pinned-git staging never runs. The driver's own git plumbing uses the git path that it captured before the strip. The drivers take NEXT as `--update-ref NEXT` (Windows: `-UpdateRef NEXT`). The run workflows take it as the `update-ref` input.

## What one leg does

Each leg with the script drivers has these phases:

1. Stage: make the bare clone, park `main` at the old release.
2. Install: run the old release's own installer script. Make sure that the checkout is at the old commit and that `hermes --version` works.
3. Update: move `main` to HEAD. Apply one update method. The update must produce a new successful receipt or result file; a changed checkout alone is not completion.
4. Verify the installed command and products before running `hermes --version`. Select the command under the installation's `.hermes/bin`; use the old venv only for a source tree without PM. Check PM currency and compiler receipts where supported. Preserve the no-desktop scenario for a plain install. Do not rebuild, remove dependencies, or force-stop an updater during verification. Historical installs without these receipts get artifact-presence checks, not a freshness claim.

The cheap fixture checks are `tests/scripts/test_source_driver.py` and `tests-js/source-update-observer.test.mjs`. They do not run installers or prove a native update. The observer does not change source files, products, dependency selections, or facts.

## Old versions

A leg can install a release from months back. The driver must not assume that the old version has today's CLI surface. The rule: probe, do not assume.

- For the installer, read the flag from the old ref's own script text.
- For the installed CLI, ask the binary with `--help`.
- If a flag is not found, omit the flag. This is not an error.

## The install methods

- `installer-script`: the platform's one-liner (`curl | bash` on linux and macos, `irm | iex` on windows). It is the only install method; the GUI installer and the packaged desktop artifact went with the desktop packaging removal.

The update axis is `installer-script` (re-run the one-liner) or `hermes-update`
(the CLI updater).

## Skips

A grey leg is normal. A method pair that is declared in the generator but has no
driver arm yet skips natively; the gate in the run workflow lists the pairs that
run.

The result chart on the run summary shows each leg as passed, failed, or skipped. [Confirmed historical upgrade limitations](KNOWN_FAILURES.md) records failures that cannot be fixed in the update target, with exact release commits and CI evidence. These are not blanket skips: the original paths still run. Exact signature matches are non-red, counted separately as known failures, and linked to footnotes at the bottom of the result chart. An unrelated error on the same tag still fails.

## Triggers and cost

The matrix runs on release builds only. It never runs on pull requests, pushes to main, or a schedule: one leg installs real toolchains and takes more than 10 minutes. The triggers are:

- A reusable workflow call from the stable release gate (`route=all`).
- Manual dispatch. You can select the route and the tag count:

```
gh workflow run install-e2e.yml --ref <branch> -f route=all -f tag-count=2
```

The generator's output is the leg-count authority. Read the workflow's plan
chart before dispatching a large run. Scheduled/tag runs default to two sampled
tags; manual dispatch defaults to three. `tag-count` accepts 1–10.

`all` selects every source OS. `both`, `update`, and `installer` select Linux
source legs, not Windows plus macOS. `install-ref` selects one exact source
baseline. Stable release calls also exclude the candidate tag so it cannot serve
as its own old version.

Per-leg timeouts and GitHub's matrix limits remain workflow constraints, not
proof that every declared combination ran.

Running the drivers locally: don't, except in a disposable VM. Both drivers
run the real installer and updater against a fixture HOME and PUT gates on a
machine with a real Hermes install.

## Plugin upgrade preservation

Every upgrade leg also carries a plugin-survival contract: a tagged upgrade
must not delete or modify anything under the active home's `plugins/**` tree
or any profile's `profiles/<name>/plugins/**` tree. Destructive flows
(explicit uninstall, plugin removal, profile or user deletion) are out of
contract and not exercised.

- `e2e-assets/verify-plugin-preservation.py` is the shared, stdlib-only,
  read-only verifier. `snapshot` records every entry (kind, byte size +
  sha256, link targets, and a recursive fingerprint of a symlink's external
  target) across all plugin roots, including empty directories and the roots
  themselves; `verify` diffs the live tree against that snapshot and fails
  on any deletion or modification. Unreadable paths are hard errors; an
  empty snapshot is refused as inconclusive rather than claimed as a pass.
- `e2e-assets/preserve-plugins.sh` is the POSIX/macOS hook pair: after the
  install phase it seeds controlled, non-dependency directory fixtures (a
  `mnemosyne-wrapper` plugin with its marker, a symlinked runtime, a second
  profile plugin tree, and the externally-owned sidecar witness outside the
  home — no pyproject anywhere in the scanned root, nothing downloaded) and
  snapshots; after the update lands it verifies and fails the leg on any
  violation. Both shell and Windows hooks call the same Python `seed`
  command. Existing fixtures or snapshots abort rather than masking damage
  by reseeding. Windows uses a junction without requiring symlink privilege.
- Unit tests live at `tests/scripts/test_verify_plugin_preservation.py` and
  exercise the verifier against a real temp filesystem (real files, real
  symlinks; junction fallback on Windows).
- Stable-to-stable: the drivers accept `--update-ref REF` (Windows:
  `-UpdateRef`), defaulting to HEAD. Pass the next release tag to target a
  stable→stable upgrade through the same serve.git staging; only label a leg
  stable-to-stable when BOTH the install ref and the target ref are release
  tags. `NEXT` is reserved for the HEAD -> NEXT column (see above).

## Manual update rehearsals

There is no `manual/` directory in this repo. The rehearsal scripts — `pre`
(back up the whole `HERMES_HOME`, the
`hermes` shims on PATH and the global git config, then point the install's
update source at a custom repo + ref) and `post` (undo all of it and report how
exact the restore was) — are a hand-off kit for someone with a *real* install,
kept outside this checkout on purpose: they are not part of the repo and not
wired into any lane here.

What *is* in the repo is the assertion layer they exist to demonstrate. The
user-state preservation checks below run on every upgrade leg; the manual kit
only reproduces the same upgrade on a machine you care about, where a backup
and a restore are the only honest way to do it.

## User-state preservation

Alongside the plugin-tree contract below, every upgrade leg also carries a
**user-state** contract: an upgrade may add state, may rewrite `config.yaml`
(additive config migration) and the bundled `skills/` tree (the product
re-syncs it), but it may not delete or modify the user's own durable state —
`.env`, `auth.json`, `state.db`, `gateway_state.json`, `memories/`, `cron/`,
`sessions/`, `profiles/`, `photon/`, `desktop-plugins/`, `tui-widgets/`,
`skins/`, `pets/`, `skills/.archive/` — and `state.db` may not lose rows.

- `e2e-assets/verify-user-state.py` is the shared, stdlib-only, read-only
  verifier. It records row counts for `state.db` rather than bytes (a live
  SQLite file changes for benign reasons), and it has **no** `seed` mode on
  purpose: the state it defends must be produced by the product through the
  ordinary user path, never hand-written by the harness.
- `e2e-assets/user-state-actions.sh` produces that state with real commands —
  `hermes chat -q` (a real turn → `sessions/` + `state.db` rows),
  `hermes auth add` (→ `auth.json`), `hermes profile create`
  (→ `profiles/<name>/`) — after probing `--help` for each flag, per the
  harness's "probe, do not assume" rule. Each action asserts it actually landed,
  so a leg can never "pass" while testing nothing.
- `e2e-assets/preserve-user-state.sh` is the POSIX/macOS hook pair
  (snapshot before the upgrade, verify after). Windows calls the same Python
  `snapshot`/`verify` from `windows-e2e.ps1`'s phases, alongside its existing
  plugin hooks.
- Two more invariants ride along: the redirect must stay transport-level
  (`config --get remote.origin.url` stays official while `remote get-url` is
  rewritten), and the user-visible launcher must still exist and run after the
  upgrade.
- Unit tests live at `tests/scripts/test_verify_user_state.py` and exercise the
  verifier against a real temp filesystem with real sqlite databases.

## Artifacts

Each leg uploads its logs as an artifact. Every leg also records the screen for its whole run: the composite action `.github/actions/e2e-screen-record` records with the OS's capture backend (x11grab on linux, gdigrab on windows, avfoundation on macos), and fails the leg if the recording is missing or has zero frames. ffmpeg itself comes from the PM toolchain — jobs pass `packages: ffmpeg` to `actions/setup-pm`, which installs the locked, sha256-pinned build (native per-OS, including win32-arm64) and puts it on `PATH`; the action only verifies it is there. Linux runners have no display, so the action starts `Xvfb :99` first and exports `DISPLAY` for every later step. Get a leg's artifacts with `gh run download <run-id>`.
