"""Source orchestration uses real node-deps/pnpm in an isolated checkout.

Only PM's tool acquisition (and its installed-node record) is substituted with the host's node/pnpm. Small
workspace scripts stand in for the expensive UI compilers; subprocess failures,
locked dependency selection, environment propagation and publication are real.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import pm
from pm.package import Runner


def use_host_node_as_pm_node(monkeypatch):
    """Freshness reads run only under PM's recorded Node; stand the host's node in for it."""
    node, real = Path(shutil.which("node")), pm.installed_package
    monkeypatch.setattr(pm, "installed_package", lambda name, **kwargs: (
        SimpleNamespace(binary=node) if name == "node" else real(name, **kwargs)))


def copy_freshness_scripts(root):
    repository = Path(__file__).resolve().parents[2]
    scripts = root / "scripts/build"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("freshness.mjs", "frontend-common.mjs"):
        shutil.copy2(repository / "scripts/build" / name, scripts / name)


def stamp_product(root, product, out):
    script = (root / "scripts/build/freshness.mjs").as_uri()
    subprocess.run([shutil.which("node"), "--input-type=module", "-e",
                    f"import {{recordProduct, buildInputs}} from {json.dumps(script)};"
                    "const [source, product, out] = process.argv.slice(1);"
                    "recordProduct({source, product, out, inputs: buildInputs(source, product)});",
                    str(root), product, str(out)], check=True)


def test_source_build_uses_selected_python_for_isolated_icon_child(tmp_path, monkeypatch):
    from hermes_cli.source_build import source_build_env
    from pm import paths
    from pm.environments import site_packages, venv_python

    root = tmp_path / "source"
    root.mkdir()
    venv = root / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    selected = site_packages(venv)
    (selected / "icon_dependency.py").write_text("ready = True\n", encoding="utf-8")
    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setattr(pm, "ensure", lambda name, **kwargs: Runner(name, kwargs["base_env"]))
    monkeypatch.syspath_prepend(str(selected))

    env = source_build_env()
    assert env["HERMES_PYTHON"] == str(venv_python(venv))
    subprocess.run([env["HERMES_PYTHON"], "-I", "-c",
                    "import icon_dependency; assert icon_dependency.ready"], check=True)


def test_automatic_build_preserves_pm_admission_intent(monkeypatch):
    from hermes_cli.source_build import source_build_env

    intent = []
    def acquire(name, *, base_env, explicit, verify=True):
        intent.append(explicit)
        return Runner(name, base_env)
    monkeypatch.setattr(pm, "ensure", acquire)
    source_build_env()
    assert intent == [False]


def test_installed_pnpm_does_not_authorize_missing_workspace_dependencies(source_checkout, monkeypatch):
    from hermes_cli.source_build import prepare_source_dependencies, source_build_env

    root, _ = source_checkout
    env = source_build_env()
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    with pytest.raises(subprocess.CalledProcessError):
        prepare_source_dependencies(root, ("ui-tui", "web"), env=env)
    assert _events(root) == []
    prepare_source_dependencies(root, ("ui-tui", "web"), env=env, explicit=True)
    events = _events(root)
    prepare_source_dependencies(root, ("ui-tui", "web"), env=env)
    assert _events(root) == events


@pytest.fixture
def source_checkout(tmp_path, monkeypatch):
    node, pnpm = shutil.which("node"), shutil.which("pnpm")
    assert node and pnpm, "source-build integration requires node and pnpm"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "tools"))
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "0")
    monkeypatch.setenv("ESBUILD_BINARY_PATH", "/wrong/esbuild")
    monkeypatch.setenv("HERMES_PYTHON", "/wrong/python")
    (home / "npmrc").write_text(
        "fund=false\nnode-get-windows-binary-host-mirror=https://mirror.invalid/get-windows/\n"
        "//registry.invalid/:_authToken=npmrc-secret\nelectron-mirror=${MIRROR_BASE}/electron/\n"
        "@scope:registry=https://registry.invalid/\nca[]=npmrc-array\nnodedir=${UNSET_NPMRC_VAR}\n",
        encoding="utf-8")
    monkeypatch.setenv("MIRROR_BASE", "https://mirror.invalid")
    monkeypatch.delenv("UNSET_NPMRC_VAR", raising=False)
    monkeypatch.delenv("NPM_CONFIG_USERCONFIG", raising=False)
    acquired = []

    def acquire(name, *, base_env=None, explicit=False, verify=True):
        acquired.append(name)
        assert name == "pnpm"

        return Runner(name, {**(base_env or os.environ), "PATH": os.pathsep.join(
            [str(Path(pnpm).parent), str(Path(node).parent), os.environ["PATH"]])})

    monkeypatch.setattr(pm, "ensure", acquire)
    use_host_node_as_pm_node(monkeypatch)
    root = tmp_path / "source with spaces"
    root.mkdir()
    workspaces = ["ui-tui", "web", "apps/desktop", "unrelated"]
    manifest = {"name": "build-fixture", "private": True, "version": "1.0.0",
                "scripts": {"postinstall": "node log.mjs deps"}}
    (root / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    # verifyDepsBeforeRun mirrors the repository's: `pnpm run` never installs. It precedes the
    # package list, which tests extend by appending.
    (root / "pnpm-workspace.yaml").write_text(
        "verifyDepsBeforeRun: false\npackages:\n" + "".join(f"  - {workspace}\n" for workspace in workspaces),
        encoding="utf-8")
    # A local package stands in for registry dependencies: pnpm links it into every installed
    # workspace's node_modules, offline.
    (root / "fixture-dep").mkdir()
    (root / "fixture-dep/package.json").write_text('{"name": "fixture-dep", "version": "1.0.0"}', encoding="utf-8")
    for workspace in workspaces:
        directory = root / workspace
        directory.mkdir(parents=True)
        (directory / "package.json").write_text(json.dumps({
            "name": workspace.replace("/", "-"), "version": "1.0.0",
            "dependencies": {"fixture-dep": f"file:{os.path.relpath(root / 'fixture-dep', directory)}"},
            "scripts": {"build": "node ../../scripts/build/build-desktop.mjs",
                        "builder": "node ../../scripts/build/package-desktop.mjs"}
            if workspace == "apps/desktop" else {},
        }), encoding="utf-8")
    (root / "log.mjs").write_text(
        "import { appendFileSync } from 'node:fs';\n"
        "appendFileSync('events.jsonl', JSON.stringify({step: process.argv[2], "
        "python: process.env.HERMES_PYTHON, ci: process.env.CI, "
        "esbuild: process.env.ESBUILD_BINARY_PATH, "
        "npmrc: process.env.NPM_CONFIG_USERCONFIG, store: process.env.pnpm_config_store_dir, "
        "mirror: process.env.npm_config_node_get_windows_binary_host_mirror, "
        "electron: process.env.npm_config_electron_mirror, "
        "skipped: Object.keys(process.env).filter(key => /^npm_config_(@.*|ca(\\[\\])?|nodedir)$/i.test(key)), "
        "leaked: Object.values(process.env).some(value => value.includes('npmrc-secret'))}) + '\\n');\n",
        encoding="utf-8",
    )
    subprocess.run([pnpm, "install", "--lockfile-only", "--ignore-scripts", "--offline"], cwd=root, check=True,
                   env={**os.environ, **{f"pnpm_config_{name}_dir": str(tmp_path / "pnpm" / name)
                                         for name in ("store", "cache", "state")}})
    scripts = root / "scripts" / "build"
    scripts.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[2]
    for name in ("node-deps.mjs", "freshness.mjs", "frontend-common.mjs", "pnpm-lock.mjs"):
        shutil.copy2(repository / "scripts/build" / name, scripts / name)
    (root / ".gitignore").write_text("node_modules/\n**/dist/\n", encoding="utf-8")
    # node-deps requires PM's pnpm pin: pin the pnpm this test runs.
    (root / "pm").mkdir()
    version = subprocess.run([pnpm, "--version"], capture_output=True, text=True, encoding="utf-8",
                             timeout=60, check=True).stdout.strip()
    (root / "pm/lock.json").write_text(json.dumps({"packages": {"pnpm": {"version": version}}}), encoding="utf-8")
    return root, acquired


@pytest.fixture
def source_products(source_checkout):
    root, acquired = source_checkout
    (root / "product.mjs").write_text(
        "import { appendFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';\n"
        "import { dirname, join } from 'node:path';\n"
        "import { fileURLToPath } from 'node:url';\n"
        "import { recordProduct, buildInputs } from './scripts/build/freshness.mjs';\n"
        "const root = dirname(fileURLToPath(import.meta.url));\n"
        "export function build(step, output) {\n"
        "  appendFileSync(join(root, 'events.jsonl'), JSON.stringify({step}) + '\\n');\n"
        "  if (existsSync(join(root, 'fail-' + step))) throw new Error('fixture ' + step + ' failure');\n"
        "  if (step === 'web' && !existsSync(join(root, 'web/public/favicon.ico'))) throw new Error('icons missing');\n"
        "  const path = join(root, output); mkdirSync(dirname(path), { recursive: true });\n"
        "  writeFileSync(path, step);\n"
        "  if (step !== 'icons') {\n"
        "    let out = dirname(path);\n"
        "    if (step === 'desktop') { out = join(out, 'resources/app.asar.unpacked/dist');\n"
        "      mkdirSync(out, {recursive: true}); writeFileSync(join(out, 'index.html'), 'renderer'); }\n"
        "    recordProduct({source: root, product: step, out, inputs: buildInputs(root, step)});\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    for script, step, output in [
        ("generate-icons.mjs", "icons", "never-rendered-at-install"),
        ("build/tui.mjs", "tui", "ui-tui/dist/entry.js"),
        ("build/web.mjs", "web", "hermes_cli/web_dist/index.html"),
    ]:
        relative = "../../" if script.startswith("build/") else "../"
        (root / "scripts" / script).write_text(
            f"import {{ build }} from '{relative}product.mjs'; build({step!r}, {output!r});\n",
            encoding="utf-8",
        )
    (root / "scripts/build/package-desktop.mjs").write_text(
        "import { relative } from 'node:path';\n"
        "import { build } from '../../product.mjs';\n"
        "const flag = '-c.directories.output=';\n"
        "const staging = process.argv.find(arg => arg.startsWith(flag)).slice(flag.length);\n"
        "build('desktop', relative('../..', staging) + '/linux-unpacked/hermes');\n",
        encoding="utf-8",
    )
    (root / "scripts/build/build-desktop.mjs").write_text(
        "if (!process.argv.includes('--icons')) await import('../generate-icons.mjs');\n",
        encoding="utf-8",
    )
    # Default-brand icons are committed; updates consume them without rendering.
    (root / "web/public").mkdir(parents=True, exist_ok=True)
    (root / "web/public/favicon.ico").write_bytes(b"committed icon")
    return root, acquired


def _events(root):
    path = root / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.platforms("posix")
def test_preparation_reuses_only_the_exact_completed_workspace_union(source_checkout):
    from hermes_cli.source_build import prepare_source_dependencies, source_build_env

    root, acquired = source_checkout
    before = (root / "pnpm-lock.yaml").read_bytes()
    env = source_build_env()
    prepare_source_dependencies(root, ("ui-tui", "web"), env=env)
    first = _events(root)
    assert [event["step"] for event in first] == ["deps"]
    assert first[0]["python"] == env["HERMES_PYTHON"]
    assert first[0]["ci"] == "1"
    assert "esbuild" not in first[0]
    assert first[0]["npmrc"] == str(Path(os.environ["HERMES_HOME"]) / "npmrc")
    # npmrc settings reach install scripts as npm did it (node-pre-gyp mirrors); credentials never do.
    assert first[0]["mirror"] == "https://mirror.invalid/get-windows/"
    assert first[0]["electron"] == "https://mirror.invalid/electron/"
    assert first[0]["skipped"] == []
    assert first[0]["leaked"] is False
    # pnpm's store lives under the Hermes root, never the user's XDG data dir.
    assert first[0]["store"] == str(Path(os.environ["HERMES_HOME"]) / "cache/pnpm/store")
    assert (Path(os.environ["HERMES_HOME"]) / "cache/pnpm/store").is_dir()
    assert (root / "ui-tui/node_modules/fixture-dep").exists()
    assert (root / "web/node_modules/fixture-dep").exists()
    assert not (root / "apps/desktop/node_modules").exists()
    assert not (root / "unrelated/node_modules").exists()

    prepare_source_dependencies(root, ("ui-tui", "web"), env=env)
    assert _events(root) == first
    prepare_source_dependencies(root, ("ui-tui", "web", "apps/desktop"), env=env)
    assert len(_events(root)) == 2
    assert (root / "apps/desktop/node_modules/fixture-dep").exists()
    assert not (root / "unrelated/node_modules").exists()
    assert (root / "pnpm-lock.yaml").read_bytes() == before
    assert acquired == ["pnpm"]

    # A lock failure must not fall back to an unlocked install that rewrites the lock.
    (root / "pnpm-lock.yaml").write_text("not yaml", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError):
        prepare_source_dependencies(root, ("ui-tui", "web"), env=env)
    assert (root / "pnpm-lock.yaml").read_text() == "not yaml"
    assert len(_events(root)) == 2
    assert acquired == ["pnpm"]

    # Exercise PM rather than hiding a provisioning error behind system pnpm.
    from unittest.mock import patch
    with patch.object(pm, "ensure", side_effect=pm.InstallError("pnpm", "unavailable")):
        with pytest.raises(pm.InstallError, match="unavailable"):
            source_build_env()
    assert len(_events(root)) == 2


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("desktop", [False, True])
def test_update_builds_selected_products_after_one_union_preparation(source_products, desktop):
    from hermes_cli.source_build import build_update_products
    from hermes_cli.main_web_build import _web_ui_build_needed

    root, acquired = source_products
    app = root / "apps/desktop/release/linux-unpacked/hermes"
    app.parent.mkdir(parents=True)
    app.write_text("previous app")
    build_update_products(root, desktop=desktop)
    steps = [event["step"] for event in _events(root)]
    assert steps == ["deps", "tui", "web"]
    assert acquired == ["pnpm"]
    assert (root / "ui-tui/dist/entry.js").read_text() == "tui"
    assert (root / "hermes_cli/web_dist/index.html").read_text() == "web"
    assert not _web_ui_build_needed(root / "web")
    assert not (root / "apps/desktop/node_modules").exists()
    assert not (root / "unrelated/node_modules").exists()
    assert app.read_text() == "previous app"
    assert not list((root / "apps/desktop").glob(".staging-*"))


@pytest.mark.platforms("linux")
def test_update_recompiles_only_products_whose_inputs_changed(source_products):
    from hermes_cli.source_build import build_update_products

    root, _ = source_products

    def products():
        return [event["step"] for event in _events(root) if event["step"] != "deps"]

    build_update_products(root, desktop=True)
    (root / "events.jsonl").unlink()
    build_update_products(root, desktop=True)
    assert products() == []

    (root / "events.jsonl").unlink()
    (root / "web/src").mkdir(parents=True, exist_ok=True)
    (root / "web/src/changed.ts").write_text("export {}\n", encoding="utf-8")
    build_update_products(root, desktop=False)
    assert products() == ["web"]


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("step", ["tui", "web"])
def test_update_failure_raises_without_retries_or_replacing_live_app(source_products, step):
    from hermes_cli.source_build import ProductBuildError, build_update_products

    root, acquired = source_products
    app = root / "apps/desktop/release/linux-unpacked/hermes"
    app.parent.mkdir(parents=True)
    app.write_text("previous app")
    (root / f"fail-{step}").touch()
    with pytest.raises(ProductBuildError) as failure:
        build_update_products(root, desktop=True)
    # The failure is still raised, naming the one product that failed (no retries) ...
    assert len(failure.value.failures) == 1
    assert isinstance(failure.value.failures[0][1], subprocess.CalledProcessError)
    # ... but it no longer skips the independent products after it (was order[:index + 1]).
    assert [event["step"] for event in _events(root)] == ["deps", "tui", "web"]
    assert acquired == ["pnpm"]
    assert app.read_text() == "previous app"
    assert not list((root / "apps/desktop").glob(".staging-*"))
@pytest.mark.platforms("linux")
@pytest.mark.parametrize("desktop", [False, True])
def test_module_cli_builds_the_requested_products(source_products, desktop, monkeypatch):
    import runpy

    root, acquired = source_products
    monkeypatch.setattr(sys, "argv", ["source_build", "--source", str(root)] + (["--desktop"] if desktop else []))
    # run_module exercises __main__ while substituting only tool acquisition.
    monkeypatch.delitem(sys.modules, "hermes_cli.source_build", raising=False)
    runpy.run_module("hermes_cli.source_build", run_name="__main__")
    assert acquired == ["pnpm"]
    assert (root / "hermes_cli/web_dist/index.html").is_file()
    assert not (root / "apps/desktop/release/linux-unpacked/hermes").exists()
