"""Keep the reference honest as the repository grows.

A reference section rots faster than anything else in a repository: parts get
built, sections get renamed, and the index quietly stops describing what is
there. This script checks that it still does.

It verifies:
  1. every built part is covered by CLI_REFERENCE.md and DECISIONS.md
  2. every relative link in 99_reference resolves
  3. every fenced command block uses a command this repository claims to
     document, and every gcloud command has a recognisable verb
  4. coverage per exam domain

STANDARD LIBRARY ONLY, like 00_setup/check_env.py, so it runs before
anything is installed. No figure, for the same reason.

Exit code 0 if the reference is consistent, 1 otherwise - so it can sit in
CI next to check_env.py and check_links.py.

Run:
    python 99_reference/check_reference.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DOCS = ["CLI_REFERENCE.md", "DECISIONS.md", "FINDINGS.md", "SERVICE_NAMES.md"]

# part -> exam domain, for the coverage table at the end
DOMAINS = {
    "00_setup": "0. the toolchain",
    "01_resource_hierarchy": "1. setting up (23%)",
    "08_billing_cost": "1. setting up (23%)",
    "03_compute": "2. planning (30%)",
    "04_kubernetes": "2. planning (30%)",
    "05_storage": "2. planning (30%)",
    "06_networking": "2. planning (30%)",
    "07_operations": "3. operating (27%)",
    "09_iac": "3. operating (27%)",
    "02_iam": "4. access and security (20%)",
    "10_capstone_summary": "all four (capstone)",
}

# Parts that do not have to appear in CLI_REFERENCE.md, and why.
NO_COMMANDS_OF_ITS_OWN = {
    "99_reference": "it IS the reference",
    "10_capstone_summary": "composes the other parts; introduces no commands",
}

# Commands this repository documents. Anything else in a fenced block is
# either prose that looks like a command or something we forgot to list.
KNOWN_CLIS = {"gcloud", "gsutil", "bq", "kubectl", "terraform", "python",
              "pip", "kind", "docker"}

GCLOUD_VERBS = {
    "create", "delete", "describe", "list", "update", "patch", "get",
    "set", "add", "remove", "enable", "disable", "init", "info",
    "version", "login", "revoke", "activate", "deactivate", "install",
    "read", "cp", "mv", "rm", "ls", "rsync", "link", "unlink", "move",
    "resize", "start", "stop", "reset", "ssh", "scp", "snapshot",
    "undelete", "connect", "expose", "run", "help", "unset", "restart",
    "components", "auth", "config", "deploy", "submit", "browse", "tail",
    "log", "apply", "approve", "push", "build",
}

# gcloud's verbs are frequently HYPHENATED verb-noun compounds -
# add-iam-policy-binding, set-machine-type, get-credentials,
# expand-ip-range. An earlier version of this script listed only the bare
# verbs and flagged eleven perfectly good lines, so the rule is now a
# prefix rule, which is what the naming convention actually is.
VERB_PREFIXES = {
    "add", "remove", "get", "set", "list", "create", "start", "stop",
    "print", "expand", "activate", "deactivate", "update", "delete",
    "describe", "sign", "rolling", "associated", "enable", "disable",
}


def looks_like_verb(token: str) -> bool:
    if token in GCLOUD_VERBS:
        return True
    return "-" in token and token.split("-", 1)[0] in VERB_PREFIXES


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def built_parts() -> list[str]:
    out = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or not re.match(r"^\d\d_", d.name):
            continue
        if any(d.glob("*.py")) or (d / "README.md").exists():
            out.append(d.name)
    return out


def fenced_blocks(text: str) -> list[str]:
    """Only LANGUAGE-TAGGED blocks. An untagged fence in this repository is a
    schematic or a sample of output, not something anyone should paste."""
    return re.findall(r"```(?:bash|sh|console)\n(.*?)```", text, re.S)


def main() -> int:
    print("99_reference - CONSISTENCY CHECK")
    problems: list[str] = []
    texts = {}
    for name in DOCS:
        p = HERE / name
        if not p.exists():
            problems.append(f"{name} is missing")
            continue
        texts[name] = p.read_text(encoding="utf-8")

    # ------------------------------------------------------ 1. coverage
    rule("1. PART COVERAGE")
    parts = built_parts()
    print(f"  {'part':<24} {'CLI_REFERENCE':>14} {'DECISIONS':>11} "
          f"{'FINDINGS':>10}")
    print("  " + "-" * 64)
    for part in parts:
        if part == "99_reference":
            continue          # the reference does not index itself
        in_cli = part in texts.get("CLI_REFERENCE.md", "")
        in_dec = part in texts.get("DECISIONS.md", "")
        in_fnd = part in texts.get("FINDINGS.md", "")
        exempt = part in NO_COMMANDS_OF_ITS_OWN
        if not in_cli and not exempt:
            problems.append(f"{part} not mentioned in CLI_REFERENCE.md")
        if not in_dec:
            problems.append(f"{part} not mentioned in DECISIONS.md")
        cli_col = "yes" if in_cli else ("n/a" if exempt else "NO")
        print(f"  {part:<24} {cli_col:>14} "
              f"{'yes' if in_dec else 'NO':>11} "
              f"{'yes' if in_fnd else '-':>10}")

    for part, why in sorted(NO_COMMANDS_OF_ITS_OWN.items()):
        if part in parts:
            print(f"\n  n/a  {part}: {why}")
    print(f"\n  {len(parts)} built part(s). FINDINGS is allowed to be partial -")
    print("  not every part produced a result worth recording.")

    # --------------------------------------------------------- 2. links
    rule("2. RELATIVE LINKS")
    checked = broken = 0
    for name, text in texts.items():
        for target in re.findall(r"\]\((\.\.?/[^)#]+)", text):
            checked += 1
            if not (HERE / target).resolve().exists():
                broken += 1
                problems.append(f"{name}: dead link -> {target}")
                print(f"  BROKEN  {name} -> {target}")
    print(f"  checked {checked} relative link(s), {broken} broken")

    # ------------------------------------------------------ 3. commands
    rule("3. COMMAND BLOCKS")
    counts: dict[str, int] = {}
    suspicious: list[str] = []
    for line in "\n".join(fenced_blocks(texts.get("CLI_REFERENCE.md", ""))
                          ).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        if "<" in line:            # a placeholder schematic, not a command
            continue
        head = line.split()[0]
        if head not in KNOWN_CLIS:
            continue
        counts[head] = counts.get(head, 0) + 1
        if head == "gcloud":
            tokens = [t for t in line.split()[1:] if not t.startswith("-")]
            if tokens and not any(looks_like_verb(t) for t in tokens):
                suspicious.append(line[:66])

    print(f"  {'cli':<12} documented commands")
    print("  " + "-" * 36)
    for cli, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {cli:<12} {n}")
    print(f"\n  {sum(counts.values())} command line(s) in CLI_REFERENCE.md")

    if suspicious:
        print(f"\n  {len(suspicious)} gcloud line(s) with no recognised verb -")
        print("  either a new verb to add to this script, or a typo:")
        for s in suspicious:
            print(f"    {s}")
        problems.append(f"{len(suspicious)} gcloud line(s) with no known verb")

    # -------------------------------------------------------- 4. domains
    rule("4. COVERAGE BY EXAM DOMAIN")
    by_domain: dict[str, list[str]] = {}
    for part in parts:
        if part == "99_reference":
            continue
        by_domain.setdefault(DOMAINS.get(part, "(unmapped)"), []).append(part)
    for domain in sorted(by_domain):
        names = ", ".join(by_domain[domain])
        print(f"  {domain:<28} {names}")
    missing_domains = set(DOMAINS.values()) - set(by_domain)
    for d in sorted(missing_domains):
        wanted = [p for p, dom in DOMAINS.items() if dom == d]
        print(f"  {d:<28} NOTHING BUILT ({', '.join(wanted)})")

    # ------------------------------------------------------------ verdict
    rule("VERDICT")
    if problems:
        for p in problems:
            print(f"  - {p}")
        return 1
    print("  The reference describes what is actually here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
