"""Fail if any relative markdown link in the repo does not resolve.

Cheap, and it catches the documentation rot that a repo of ~50 cross-linked
READMEs otherwise accumulates silently.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\(([^)]+)\)")

bad: list[str] = []
checked = 0

for md in sorted(ROOT.rglob("*.md")):
    if ".git" in md.parts:
        continue
    text = md.read_text(encoding="utf-8", errors="replace")
    for m in LINK.finditer(text):
        target = m.group(1).split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        checked += 1
        if not (md.parent / target).exists():
            bad.append(f"{md.relative_to(ROOT)} -> {target}")

print(f"checked {checked} relative links across the repository")
if bad:
    print(f"\nBROKEN ({len(bad)}):")
    for b in bad:
        print(f"  {b}")
    sys.exit(1)
print("all resolve")
