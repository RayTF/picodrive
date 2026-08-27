"""Packaged GUI entry point."""

from vectorforge.gui import run_gui
from vectorforge.paths import AppPaths


if __name__ == "__main__":
    raise SystemExit(run_gui(AppPaths.default().ensure()))
