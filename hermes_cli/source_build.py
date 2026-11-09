"""Source launch/update composition over the shared JavaScript builders."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def source_product_current(project_root: Path, product: str, out: Path) -> bool:
    """Read the compiler's receipt without acquiring tools or dependencies."""
    from pm import env_for, installed_package

    installed = installed_package("node")
    if installed is None or installed.binary is None:
        return False  # Only PM's Node may run the receipt reader; never the user's PATH copy.
    node, env = str(installed.binary), env_for("node")
    try:
        result = subprocess.run(
            [node, str(project_root / "scripts/build/freshness.mjs"),
             "--source", str(project_root), "--product", product, "--out", str(out)],
            cwd=project_root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        )
        return result.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def source_build_env(base_env: dict | None = None, *, explicit: bool = False, verify: bool = True) -> dict[str, str]:
    from pm import ensure
    from pm.environments import project_python, running_from_selected_environment
    from pm.packages import pnpm_env
    from pm.index_config import hermes_npmrc, user_npmrc
    from pm.paths import repo_root

    # The historical update runs on store Python with the selected environment
    # activated in-process. Icon generation starts an isolated child, which needs
    # the selected venv executable rather than the store interpreter.
    root = repo_root()
    python = str(project_python(root)) if running_from_selected_environment(root) else sys.executable
    env = {**os.environ, **(base_env or {}), "CI": "1", "HERMES_PYTHON": python,
           "PYTHON": python}
    env.pop("ESBUILD_BINARY_PATH", None)
    npmrc = user_npmrc(env)
    if npmrc == hermes_npmrc():
        env.setdefault("NPM_CONFIG_USERCONFIG", str(npmrc))
    # pnpm reads the npmrc that user_npmrc selects (an explicit userconfig, else Hermes's, else
    # ~/.npmrc) only for its registry and auth. npm also handed every other key to the processes it
    # spawned as npm_config_<key>; keep doing that, since it is how node-pre-gyp (run by
    # stage-native-deps.mjs) finds a binary mirror (node_get_windows_binary_host_mirror).
    inherited = {name.upper() for name in env}
    for key, value in _npmrc_script_settings(npmrc, env):
        name = f"npm_config_{key.replace('-', '_').lower()}"
        if name.upper() not in inherited:  # an explicit setting wins, in any case
            env[name] = value
    return ensure("pnpm", base_env=pnpm_env(env), explicit=explicit, verify=verify).env


_NPMRC_SETTING = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
# A one-time password and the deprecated inline client TLS key and certificate are credentials,
# whatever npm itself exported.
_NPMRC_SECRETS = frozenset({"otp", "key", "cert"})


def _npmrc_script_settings(npmrc: Path, env: dict) -> list[tuple[str, str]]:
    """The npmrc's plain settings (``pm.index_config.read_npmrc``) that may reach install
    scripts. Skipped: credentials (``//host/:_authToken``, ``_auth``, ``otp``, ``key``,
    ``cert``) and scoped registries (``@scope:registry``)."""
    from pm.index_config import read_npmrc

    settings = read_npmrc(npmrc, env)
    return [(key, value) for key, value in settings.items()
            if _NPMRC_SETTING.fullmatch(key) and key.lower() not in _NPMRC_SECRETS]


def run_in_custody(project_root: Path, command: list, label: str, **kwargs):
    """``pm.progress.run_contained`` for a build command that writes the checkout (node, pnpm):
    it and everything it starts stay in the update's custody (POSIX: the checkout lock fd, the
    caller's process group, and every descendant killed when it exits; Windows: the owner's
    kill-on-close job), so the checkout is never handed to a contender while one of them still
    writes. Outside an update it is ``run_contained`` as is."""
    from pm.progress import run_contained
    from hermes_cli.update_custody import contained_command

    with contained_command(command, root=project_root) as (argv, custody):
        return run_contained(argv, label, **kwargs, **custody)


def run_source_script(project_root: Path, script: str, *args: str, env: dict, label: str) -> None:
    command = [shutil.which("node", path=env["PATH"]), str(project_root / script), *args]
    run_in_custody(project_root, command, label, indent="  ", cwd=project_root, env=env)


def _install_args(explicit: bool) -> tuple[str, ...]:
    from pm import lazy_installs_allowed

    return () if explicit or lazy_installs_allowed() else ("--no-install",)


def prepare_source_dependencies(project_root: Path, workspaces: tuple[str, ...], *, env: dict,
                                explicit: bool = False) -> None:
    run_source_script(
        project_root, "scripts/build/node-deps.mjs", "--source", str(project_root), "--reuse",
        *_install_args(explicit),
        *(arg for workspace in workspaces for arg in ("--workspace", workspace)), env=env,
        label="Preparing Node dependencies",
    )


def prepare_launch_dependencies(project_root: Path, *, env: dict) -> None:
    """A launch rebuild must not prune another installed source frontend."""
    prepare_source_dependencies(project_root, ("ui-tui", "web"), env=env)


def build_source_tui(project_root: Path, *, env: dict) -> None:
    run_source_script(project_root, "scripts/build/tui.mjs", env=env, label="Building the TUI")


def build_source_web(project_root: Path, *, env: dict, icons: Path | None = None) -> None:
    # Bounded build (#63338): the Vite/Rolldown dashboard build saturates small
    # hosts; cap the V8 heap and the native bundler's rayon thread pool.
    from hermes_cli.web_build_limits import apply_web_build_limits

    apply_web_build_limits(env)
    # Default-brand icons are committed; installs never render them.
    icons = icons or project_root
    run_source_script(project_root, "scripts/build/web.mjs", "--source", str(project_root),
                      "--icons", str(icons), "--out", str(project_root / "hermes_cli/web_dist"), env=env,
                      label="Building the web UI")


def source_frontends(project_root: Path) -> tuple[str, ...]:
    """The frontend workspaces this checkout carries. A source slice without them
    (python-only installs, the installer's acceptance fixture) has no products
    to build; it still publishes commands and runs the maintenance tail."""
    return tuple(name for name in ("ui-tui", "web") if (project_root / name / "package.json").is_file())


class ProductBuildError(RuntimeError):
    """One or more products failed; every independent product was still attempted."""

    def __init__(self, failures: list[tuple[str, BaseException]]):
        self.failures = failures
        super().__init__("; ".join(f"{name}: {_failure_text(exc)}" for name, exc in failures))


def _failure_text(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return f"{' '.join(map(str, exc.cmd)) if isinstance(exc.cmd, (list, tuple)) else exc.cmd} exited {exc.returncode}"
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def build_update_products(project_root: Path, *, desktop: bool, after_dependencies=None) -> None:
    """Prepare the selected union once, attempting every independent product.

    A failed product never skips the next one; the failures are raised together at the end as
    ``ProductBuildError``.
    ``after_dependencies`` (it must not raise) runs once the Python and Node dependencies are
    prepared, whether or not they succeeded, and before the first product build.
    """
    # Both current updates and historical takeover reach this in a fresh target
    # interpreter, never in the updater's pre-sync import graph.
    from hermes_cli.main_install_repair import _install_configured_features_missing_deps
    from hermes_cli.update_stage import publish_stage

    failures: list[tuple[str, BaseException]] = []
    publish_stage("Building the apps")

    def attempt(name: str, step) -> bool:
        try:
            step()
            return True
        except Exception as exc:  # health: allow BLE001 -- collected and raised after the independent steps
            print(f"  ⚠ {name} failed: {_failure_text(exc)}")
            failures.append((name, exc))
            return False

    attempt("feature dependencies", lambda: _install_configured_features_missing_deps(project_root))
    frontends = source_frontends(project_root)
    if not frontends and after_dependencies is not None:
        after_dependencies()
    if frontends:
        env: dict = {}
        workspaces = frontends
        publish_stage("Updating Node dependencies")

        def node_dependencies(selected: tuple[str, ...]) -> None:
            # Acquiring pnpm is part of this step: its failure must be reported like the install's.
            # A recorded install is trusted as at startup (re-hashing the toolchain costs seconds per
            # tail); a missing one is still installed explicitly.
            env.update(source_build_env(explicit=True, verify=False))
            prepare_source_dependencies(project_root, selected, env=env, explicit=True)

        # Every product compiles from these node_modules: without them there is nothing to build.
        prepared = attempt("Node dependencies", lambda: node_dependencies(workspaces))
        if after_dependencies is not None:
            after_dependencies()
        if prepared:
            # An update that changed no TUI/web input reuses the receipted output, as the
            # launch path already does; recompiling it produces the same bytes.
            if "ui-tui" in frontends:
                if source_product_current(project_root, "tui", project_root / "ui-tui/dist"):
                    print("  ✓ TUI is up to date")
                else:
                    publish_stage("Building the TUI")
                    attempt("TUI build", lambda: build_source_tui(project_root, env=env))
            if "web" in frontends:
                if source_product_current(project_root, "web", project_root / "hermes_cli/web_dist"):
                    print("  ✓ Web UI is up to date")
                else:
                    publish_stage("Building the web UI")
                    attempt("web UI build", lambda: build_source_web(project_root, env=env))
    # A configured memory provider that no longer ships in core is installed from the
    # catalog for every profile home sharing this venv (config, data and tool names
    # unchanged). The update must finish even if the migration blows up.
    try:
        from hermes_cli.memory_provider_migration import migrate_all_homes

        migrate_all_homes()
    except Exception as exc:  # health: allow BLE001 -- post-commit boundary: printed as ⚠, never fails the committed update; every later update/tail re-runs it
        print(f"  ⚠ Memory provider migration skipped: {exc}")
    # Same for a gateway platform / toolset that left core (Home Assistant): every home that used
    # it gets its catalog plugin (hermes_cli/left_core_migration.py).
    try:
        from hermes_cli.left_core_migration import migrate_all_homes as migrate_left_core

        migrate_left_core()
    except Exception as exc:  # health: allow BLE001 -- post-commit boundary: printed as ⚠, never fails the committed update; every later update/tail re-runs it
        print(f"  ⚠ Plugin migration skipped: {exc}")
    if failures:
        raise ProductBuildError(failures)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build source-install frontends")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    build_update_products(args.source.resolve(), desktop=args.desktop)
