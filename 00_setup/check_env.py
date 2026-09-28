"""Environment check: what you have, what it unlocks, and what still works.

THIS SCRIPT IMPORTS NOTHING OUTSIDE THE STANDARD LIBRARY, on purpose. It is
the one thing in the repository that has to run BEFORE you have installed
anything, so it cannot need matplotlib to tell you that matplotlib is
missing. It is also the only part with no figure, for the same reason.

It checks:
  1. the Python you are running, and whether it is a virtual environment
  2. the two packages every other part needs
  3. optional command-line tools, and exactly what each one unlocks
  4. a part-by-part readiness table for this repository

Exit code 0 if every part that is built can run, 1 otherwise - so it is
usable as a CI gate as well as a thing to read.

Run:
    python 00_setup/check_env.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)

# package -> why this repository wants it
PACKAGES = {
    "matplotlib": "every figure in every part",
    "numpy": "a few numeric helpers; matplotlib pulls it in anyway",
}

# tool -> (what it unlocks, what still works without it)
TOOLS = {
    "gcloud": ("talking to a real Google Cloud project",
               "EVERYTHING here - no part needs it"),
    "kubectl": ("driving the local cluster in 04_kubernetes",
                "every other part"),
    "kind": ("creating the local cluster in 04_kubernetes",
             "every other part"),
    "docker": ("the container runtime kind runs its nodes in",
               "every other part"),
    "terraform": ("nothing in this repository",
                  "09_iac implements the planner itself, deliberately"),
    "git": ("cloning and history", "everything, if you downloaded a zip"),
}

# part -> (packages, tools, one-line description)
PARTS: list[tuple[str, list[str], list[str], str]] = [
    ("00_setup", [], [], "this check"),
    ("01_resource_hierarchy", ["matplotlib"], [],
     "blast radius, Org Policy, quotas"),
    ("02_iam", ["matplotlib"], [], "inheritance, deny, blast radius"),
    ("03_compute", ["matplotlib"], [], "the ladder, Spot, autoscaling"),
    ("04_kubernetes", ["matplotlib"], ["kind", "kubectl", "docker"],
     "a REAL local cluster"),
    ("05_storage", ["matplotlib"], [], "classes, lifecycle, databases"),
    ("06_networking", ["matplotlib"], [], "CIDR, peering, firewall"),
    ("07_operations", ["matplotlib"], [], "log router, alerting"),
    ("08_billing_cost", ["matplotlib"], [], "SUD, CUD, budgets"),
    ("09_iac", ["matplotlib"], [], "graph, plan, cascades"),
    ("10_capstone_summary", ["matplotlib"], [], "end to end, plus the cheat sheet"),
]


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def have_package(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# kubectl has no --version - that is `version --client`. And on Windows the
# `kubectl` on PATH may be a WRAPPER shipped by the container runtime (Rancher
# Desktop ships a kubectl.EXE that rejects --client), so fall back to plain
# `version`. The timeout covers real kubectl, which contacts the cluster for
# that form and can hang when there isn't one.
VERSION_ARGS: dict[str, list[list[str]]] = {
    "kubectl": [["version", "--client"], ["version"]],
    "gcloud": [["--version"]],
}
DEFAULT_VERSION_ARGS = [["--version"], ["version"]]


def tool_version(exe: str, path: str) -> str:
    """Best-effort version string. Never raises, never hangs for long.

    Invokes the RESOLVED PATH rather than the bare name: on Windows the bare
    name may resolve to a shim that produces nothing on stdout.
    """
    for args in VERSION_ARGS.get(exe, DEFAULT_VERSION_ARGS):
        try:
            out = subprocess.run([path, *args], capture_output=True,
                                 text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        text = (out.stdout or out.stderr or "").strip()
        if text and "unknown flag" not in text.lower():
            return text.splitlines()[0][:52]
    return "(installed; version not reported)"


def in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def main() -> int:
    print("ACE REPOSITORY - ENVIRONMENT CHECK")
    problems: list[str] = []

    # ------------------------------------------------------------- python
    rule("1. PYTHON")
    v = sys.version_info
    ok_version = (v.major, v.minor) >= MIN_PYTHON
    print(f"  interpreter   {sys.executable}")
    print(f"  version       {v.major}.{v.minor}.{v.micro}"
          f"   {'ok' if ok_version else f'NEEDS >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}'}")
    venv = in_virtualenv()
    print(f"  virtualenv    {'yes - ' + sys.prefix if venv else 'NO'}")
    if not ok_version:
        problems.append(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")
    if not venv:
        print("\n  You are running the SYSTEM Python. Nothing will break, but")
        print("  installing this repository's requirements into it puts them")
        print("  on every other project on this machine. See 00_setup/README.")

    # ----------------------------------------------------------- packages
    rule("2. PACKAGES")
    print(f"  {'package':<14} {'state':<9} why it is here")
    print("  " + "-" * 66)
    missing_pkgs = []
    for name, why in PACKAGES.items():
        present = have_package(name)
        if not present:
            missing_pkgs.append(name)
        print(f"  {name:<14} {'ok' if present else 'MISSING':<9} {why}")
    if missing_pkgs:
        problems.append(f"missing package(s): {', '.join(missing_pkgs)}")
        print(f"\n  Install them:  pip install -r requirements.txt")

    # -------------------------------------------------------------- tools
    rule("3. COMMAND-LINE TOOLS")
    print("  None of these is needed for the parts that are built today")
    print("  except where the last column says otherwise.\n")
    print(f"  {'tool':<11} {'state':<9} unlocks")
    print("  " + "-" * 66)
    # kubectl/kind/docker commonly live inside WSL while this Python does
    # not. Reporting them "missing" because they are not on the WINDOWS PATH
    # is a false negative - 04_kubernetes reaches them through
    # 04_kubernetes/toolchain.py, which is stdlib-only and safe to reuse here.
    in_wsl: dict[str, str] = {}
    try:
        sys.path.insert(0, str(ROOT / "04_kubernetes"))
        from toolchain import Toolchain  # noqa: PLC0415
        tc = Toolchain.discover()
        if tc.distro:
            in_wsl = dict(tc.paths)
    except Exception:            # noqa: BLE001 - absent, or no WSL; both fine
        pass

    found_tools: dict[str, str] = {}
    for exe, (unlocks, _) in TOOLS.items():
        path = shutil.which(exe)
        state = "found"
        if not path and exe in in_wsl:
            path = in_wsl[exe]
            state = "in WSL"
        if path:
            found_tools[exe] = path
        print(f"  {exe:<11} {(state if path else '-'):<9} {unlocks}")
    if in_wsl:
        print(f"\n  'in WSL' means 04_kubernetes can reach it even though it is")
        print("  not on this PATH. See 04_kubernetes/toolchain.py.")

    native_found = {e: p for e, p in found_tools.items() if e not in in_wsl
                    or shutil.which(e)}
    if native_found:
        print(f"\n  {'tool':<11} version")
        print("  " + "-" * 66)
        for exe, path in sorted(native_found.items()):
            print(f"  {exe:<11} {tool_version(exe, path)}")
    wsl_only = {e: p for e, p in found_tools.items() if e not in native_found}
    if wsl_only:
        # Do not try to RUN a WSL path from here - it is not executable on
        # this side, and probing it would print a misleading failure.
        print(f"\n  {'tool':<11} path inside WSL")
        print("  " + "-" * 66)
        for exe, path in sorted(wsl_only.items()):
            print(f"  {exe:<11} {path}")

    print("\n  NOTE ON terraform: 09_iac does NOT use it. The planner in that")
    print("  part implements the documented graph, three-way-diff and")
    print("  force-new rules itself, so the section runs on a machine with")
    print("  no Terraform and no credentials. That is deliberate.")
    print("\n  NOTE ON gcloud: no part of this repository calls it. Every")
    print("  result here is computed locally. gcloud is for when you want to")
    print("  try something against a real project of your own.")

    # ---------------------------------------------------------- readiness
    rule("4. WHAT CAN RUN RIGHT NOW")
    print(f"  {'part':<24} {'built':<7} {'runnable':<10} needs")
    print("  " + "-" * 70)
    blocked_built = 0
    for name, pkgs, tools, _desc in PARTS:
        built = (ROOT / name).is_dir() and any(
            (ROOT / name).glob("*.py"))
        need_pkg = [p for p in pkgs if not have_package(p)]
        need_tool = [t for t in tools if t not in found_tools]
        missing = need_pkg + need_tool
        if not built:
            state = "-"
        elif missing:
            state = "blocked"
            blocked_built += 1
        else:
            state = "yes"
        need = ", ".join(missing) if missing else ""
        print(f"  {name:<24} {'yes' if built else 'not yet':<7} "
              f"{state:<10} {need}")

    if blocked_built:
        problems.append(f"{blocked_built} built part(s) cannot run")

    # ------------------------------------------------------------ verdict
    rule("VERDICT")
    if problems:
        for p in problems:
            print(f"  - {p}")
        print("\n  See 00_setup/README.md for the two commands that fix this.")
        return 1
    print("  Everything that is built can run. Start here:\n")
    print("      python 02_iam/iam_hierarchy.py")
    print("\n  Or read 99_reference/CLI_REFERENCE.md, which needs nothing at")
    print("  all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
