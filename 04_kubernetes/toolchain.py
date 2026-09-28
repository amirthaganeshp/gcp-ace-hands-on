"""Find kubectl, kind and docker, wherever they actually live.

On Linux and macOS they are on PATH and this module is a thin wrapper. On
Windows they are usually inside WSL, and the repository's Python is not -
so every call has to cross that boundary.

THE RULE THAT MAKES THIS SAFE: never let a shell parse the command. Nested
quoting through PowerShell into wsl into bash collapses in ways that are
genuinely hard to debug - a `$` disappears, a quote closes early, and bash
reports a syntax error in a line you did not write.

AND AN ARGV LIST IS NOT ENOUGH ON ITS OWN. `wsl -- <command>` hands the
command line to the DEFAULT SHELL, which re-parses it. Passing a clean
Python list still fails:

    docker ps --format {{.Names}}|{{.Image}}
    -> /bin/bash: line 1: {{.Image}}: command not found

because bash saw the pipe. `wsl --exec <command>` executes directly with no
shell, and the same list works. That one flag is the difference between a
wrapper that is safe and one that merely looks safe, so it is used
everywhere below.

The single deliberate exception is resolving the tool paths in the first
place, which NEEDS a login shell to pick up ~/.local/bin. That is one
fixed command with nothing interpolated into it.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TOOLS = ("kubectl", "kind", "docker")


class ToolchainError(RuntimeError):
    pass


@dataclass
class Toolchain:
    """How to invoke kubectl / kind / docker from here."""
    # e.g. ["wsl", "-d", "Ubuntu-24.04", "--exec"] - see the module docstring
    # for why it is --exec and never --
    prefix: list[str] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)
    where: str = "native"
    distro: str | None = None

    # ---------------------------------------------------------- discovery
    @classmethod
    def discover(cls) -> "Toolchain":
        native = {t: shutil.which(t) for t in TOOLS}
        if all(native.values()) and _works([native["kubectl"], "version",
                                            "--client", "-o", "json"]):
            return cls(prefix=[], paths={t: native[t] for t in TOOLS},
                       where="native")

        if sys.platform != "win32" or not shutil.which("wsl"):
            missing = [t for t, p in native.items() if not p]
            raise ToolchainError(
                f"not found: {', '.join(missing) or 'a working kubectl'}.\n"
                "    See 04_kubernetes/setup/README.md.")

        for distro in _wsl_distros():
            found = _resolve_in_wsl(distro)
            if found:
                return cls(prefix=["wsl", "-d", distro, "--exec"], paths=found,
                           where=f"wsl:{distro}", distro=distro)

        raise ToolchainError(
            "kubectl/kind/docker are not on PATH here, and no WSL distro has\n"
            "    all three. See 04_kubernetes/setup/README.md - there is an\n"
            "    install script for exactly this.")

    # ------------------------------------------------------------- calls
    def run(self, tool: str, *args: str, check: bool = True,
            timeout: int = 180, stdin: str | None = None
            ) -> subprocess.CompletedProcess:
        cmd = [*self.prefix, self.paths[tool], *args]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, input=stdin,
                              encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise ToolchainError(
                f"{tool} {' '.join(args[:4])} failed ({proc.returncode})\n"
                f"    {(proc.stderr or proc.stdout).strip()[:400]}")
        return proc

    def out(self, tool: str, *args: str, **kw) -> str:
        return self.run(tool, *args, **kw).stdout.strip()

    def json(self, tool: str, *args: str, **kw) -> dict:
        text = self.out(tool, *args, **kw)
        return json.loads(text) if text else {}

    def kubectl_ok(self, *args: str, timeout: int = 60) -> bool:
        return self.run("kubectl", *args, check=False,
                        timeout=timeout).returncode == 0

    # ------------------------------------------------------------- paths
    def path_for(self, p: Path) -> str:
        """A path this toolchain can open.

        A Windows path means nothing to a binary running inside WSL, so
        translate it rather than hoping. `wslpath` is the supported way;
        the manual fallback covers the ordinary drive-letter case.
        """
        if not self.distro:
            return str(p)
        win = str(p.resolve())
        try:
            conv = subprocess.run([*self.prefix, "wslpath", "-u", win],
                                  capture_output=True, text=True, timeout=30)
            if conv.returncode == 0 and conv.stdout.strip():
                return conv.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        drive, _, rest = win.partition(":")
        return f"/mnt/{drive.lower()}{rest}".replace("\\", "/")

    @contextlib.contextmanager
    def held_open(self, seconds: int = 3600):
        """Keep the WSL distro alive for the duration of the block.

        WSL shuts a distro down once it has no processes left. Driving it
        from Windows, that means the distro dies IN THE GAPS BETWEEN YOUR
        COMMANDS - and a kind cluster dies with it, because its nodes are
        containers on a docker daemon that just stopped.

        It is a genuinely confusing failure: every individual command works,
        and the script fails anyway, at whichever step happened to follow a
        pause. A plain `time.sleep(25)` was enough to lose the cluster
        mid-run.

        So: hold one process open. `sleep` costs nothing and pins the distro
        up until the block exits.
        """
        if not self.distro:
            yield None
            return
        proc = subprocess.Popen(
            [*self.prefix, "sleep", str(seconds)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            yield proc
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()

    def describe(self) -> str:
        if self.where == "native":
            return f"native ({self.paths['kubectl']})"
        return f"{self.where}  kubectl={self.paths['kubectl']}"


# ------------------------------------------------------------- internals
def _works(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _wsl_distros() -> list[str]:
    try:
        # wsl --list emits UTF-16 on Windows; decode explicitly rather than
        # letting text=True guess and hand back a string full of NULs.
        proc = subprocess.run(["wsl", "--list", "--quiet"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    raw = proc.stdout
    for enc in ("utf-16-le", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []
    return [d.strip() for d in text.replace("\x00", "").splitlines() if d.strip()]


def _resolve_in_wsl(distro: str) -> dict[str, str] | None:
    """Ask a LOGIN shell where the tools are, so ~/.local/bin is on PATH.

    This is the one place a command string is used. It is fixed text with
    nothing interpolated into it, which is what makes it safe.
    """
    try:
        proc = subprocess.run(
            ["wsl", "-d", distro, "--", "bash", "-lc",
             "command -v kubectl kind docker"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    found: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        for tool in TOOLS:
            if line.endswith("/" + tool):
                found.setdefault(tool, line)
    return found if len(found) == len(TOOLS) else None
