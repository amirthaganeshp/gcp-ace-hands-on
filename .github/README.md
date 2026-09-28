# CI

Three jobs, split because they fail for different reasons and you want to know which one broke.

| job | what it proves | needs |
|---|---|---|
| **checks** | the repo describes itself accurately — every relative link resolves, and every built part is covered by the reference | nothing. Both scripts are **stdlib-only** and run before `pip install` |
| **parts** | every part that needs no cluster actually runs, and produces its figure | `pip install -r requirements.txt` |
| **kubernetes** | a **real kind cluster** comes up and `04_kubernetes` passes against it | Docker, which GitHub's `ubuntu-latest` runners have |

Figures from the `parts` job are uploaded as an artifact, so you can look at what a run produced
without cloning.

## Why `kubernetes` is a separate job

It creates a Kubernetes cluster from scratch, so it is the slow one and the one most likely to be
flaky. Kept separate, a transient failure there cannot hide a genuine failure in `parts`.

It installs kind with **the same script a human runs** —
[`04_kubernetes/setup/install_kind.sh`](../04_kubernetes/setup/install_kind.sh). If that script
rots, CI notices before a reader does. Versions are resolved at run time, so it also catches
upstream moving.

## Running the same checks by hand

No CI needed — this is the whole thing:

```bash
python .github/scripts/check_links.py      # no dependencies
python 99_reference/check_reference.py     # no dependencies
python 00_setup/check_env.py               # what you have, what it unlocks
```

Then any part: `python 02_iam/iam_hierarchy.py`.

## Verified from a clean clone

On Linux, fresh clone into a Linux filesystem, fresh venv, nothing else:

```
shell scripts executable?  -rwxr-xr-x
line endings:              LF
check_env before install:  exit 1, names every blocked part
check_env after install:   exit 0

all 10 parts:              ok, including 04_kubernetes on a real cluster
74 relative links:         resolve
reference check:           OK
```

`04_kubernetes` there used the **native** toolchain path — no WSL bridge — which is exactly what a
CI runner does.
