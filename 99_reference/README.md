# Reference

Four documents and a checker that keeps them honest.

```bash
python 99_reference/check_reference.py     # stdlib only, no setup needed
```

---

| | |
|---|---|
| **[CLI_REFERENCE.md](CLI_REFERENCE.md)** | **233 documented commands**, organised by exam domain, plus the patterns that generalise: the verb set, the zonal/regional/global split, and `--format`/`--filter`. **A primary deliverable of this repo** — ACE is the most command-line-heavy of the three certifications |
| **[DECISIONS.md](DECISIONS.md)** | every *"the scenario says → the answer"* table from all nine parts, in one place, each linked back to where it is demonstrated |
| **[FINDINGS.md](FINDINGS.md)** | what the runs actually showed. Every number was **printed by a script here**, not looked up — including the ones that contradicted what I expected |
| **[SERVICE_NAMES.md](SERVICE_NAMES.md)** | old name → current name, the complete load-balancer renaming, what is being retired, and the pairs that *sound* like renames and are different products |

## Why there is a checker

A reference section rots faster than anything else in a repository. Parts get built, sections get
renamed, and the index quietly stops describing what is there.

`check_reference.py` verifies that every built part is covered by CLI_REFERENCE and DECISIONS, that
every relative link resolves, that every documented `gcloud` line has a recognisable verb, and that
each exam domain has something behind it. **Standard library only** — like
[`00_setup/check_env.py`](../00_setup/README.md), it runs before anything is installed, and it has
no figure for the same reason. Exit 0 or 1, so it sits in CI next to the other two checks.

```
  0. the toolchain             00_setup
  1. setting up (23%)          01_resource_hierarchy, 08_billing_cost
  2. planning (30%)            03_compute, 05_storage, 06_networking
  3. operating (27%)           07_operations, 09_iac
  4. access and security (20%) 02_iam
```

**Domain 2 is short one part** — `04_kubernetes`, which is the only thing in the repository that
needs a container runtime.

### It caught itself first

On its first run the checker flagged 13 `gcloud` lines as having no recognised verb. **Eleven were
false positives**: my verb list held bare words (`add`, `set`, `get`) and gcloud's real verbs are
frequently hyphenated compounds — `add-iam-policy-binding`, `set-machine-type`, `get-credentials`,
`expand-ip-range`. The rule is now a **prefix** rule, which is what the naming convention actually
is.

The other two were a schematic in an untagged fence. It now reads only **language-tagged** blocks
and skips lines containing `<` placeholders, on the basis that an untagged fence in this repository
is sample output or a diagram, not something anyone should paste.

*The reference was right and the checker was wrong — which is the failure mode worth designing
against, because a checker that cries wolf gets switched off.*

## Where to start

- Sitting the exam soon → **[DECISIONS.md](DECISIONS.md)**, then the parts behind any row you cannot
  justify.
- Working in a terminal → **[CLI_REFERENCE.md](CLI_REFERENCE.md)**, especially *Format and filter*
  and *Commands that are one-way*.
- Reading old material or blog posts → **[SERVICE_NAMES.md](SERVICE_NAMES.md)** first.
- Wondering whether any of this was measured → **[FINDINGS.md](FINDINGS.md)**.
