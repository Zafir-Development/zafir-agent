"""
setup.py — wheel/sdist build guard.

pip/PyPI and Homebrew are no longer supported distribution methods for
Hermes Agent (see website/docs/getting-started/platform-support.md). The
wheel would ship without bundled assets (locales, skills, optional-mcps,
tui_dist, plugin manifests) since those are resolved at runtime
via env-var overrides set by packaged builds or the source-checkout layout.

This file overrides the ``bdist_wheel`` and ``sdist`` setuptools commands
to raise an error. The PEP 517
``build_wheel`` / ``build_sdist`` hooks in
``setuptools.build_meta`` call these commands internally, so the guard
fires for ``uv build``, ``pip wheel``, ``python -m build``, and direct
``setup.py`` invocations alike.

Editable installs (``uv sync``, ``pip install -e .``)
use ``build_editable``, which does NOT call ``bdist_wheel`` — it calls
``build_ext`` in editable mode. So the guard does not affect development.
"""

import os

from setuptools import setup
from setuptools.command.sdist import sdist

_ROOT = os.path.dirname(os.path.abspath(__file__))

_BLOCK_MESSAGE = (
    "Building wheels or sdists for hermes-agent is not supported.\n"
    "Hermes is distributed via the shell installer or Docker image.\n"
    "See: https://hermes-agent.nousresearch.com/docs/getting-started/installation\n"
    "\n"
    "If you are developing, use an editable install instead:\n"
    "  source ./activate  # PowerShell: . .\\activate.ps1\n"
    "\n"
)


class _GuardedSdist(sdist):
    def run(self, *args, **kwargs):
        raise RuntimeError(_BLOCK_MESSAGE)


cmdclass = {"sdist": _GuardedSdist}

# bdist_wheel is only available when the `wheel` package is installed.
# setuptools.build_meta.build_wheel() calls it internally, so the guard
# fires for all PEP 517 wheel build paths. Define the subclass only when
# the import succeeds — otherwise a None base class raises TypeError at
# class-definition time, before the cmdclass guard can run.
try:
    from setuptools.command.bdist_wheel import bdist_wheel

    class _GuardedBdistWheel(bdist_wheel):
        def run(self, *args, **kwargs):
            raise RuntimeError(_BLOCK_MESSAGE)

    cmdclass["bdist_wheel"] = _GuardedBdistWheel
except ImportError:
    pass

# Root single-file modules (``run_agent``, ``hermes_state``, ``toolsets``...)
# are invisible to ``packages.find``: that finder sees only directories with an
# ``__init__.py``. The wheel build needs them on ``py_modules``, so derive the
# list from the source tree at build time. A static list in ``pyproject.toml``
# drifted each time the tree layout changed (missing modules broke installed
# wheels with ``ModuleNotFoundError``), so there is no list to maintain here.
# ``setup()`` kwargs merge with ``pyproject.toml``, and this file is the only
# legitimate wheel/sdist builder, so the derived value is the single source.
# Editable installs do not read it: ``build_editable`` never runs
# ``bdist_wheel``. The build sees the same root modules as the source tree.
def _root_py_modules():
    try:
        names = os.listdir(_ROOT)
    except OSError:
        return []
    return sorted(
        name[:-3]
        for name in names
        if name.endswith(".py") and name != "setup.py"
    )


setup(cmdclass=cmdclass, py_modules=_root_py_modules())
