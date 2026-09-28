# Setup — two commands, and what each optional tool actually unlocks

> **Runtime:** ~5 s · **Needs:** nothing at all — `check_env.py` imports **only the standard
> library**, on purpose

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python 00_setup/check_env.py
```

That is the whole setup. **No Google Cloud account, no credentials, no billing, no Terraform, no
Docker** — every result in the other nine parts is computed on your machine.

---

## Why `check_env.py` has no figure

Every other part of this repository ends by saving a figure. This one does not, and it is the only
script here that imports nothing outside the standard library.

**It has to run before you have installed anything.** A checker that needs matplotlib in order to
tell you matplotlib is missing is not a checker. So it is stdlib-only, it has no figure, and it
exits **0** when every built part can run and **1** when it cannot — which makes it usable as a CI
gate as well as something to read.

## What the check tells you

```
  part                     built   runnable   needs
  ----------------------------------------------------------------------
  00_setup                 yes     yes
  01_resource_hierarchy    yes     yes
  02_iam                   yes     yes
  03_compute               yes     yes
  04_kubernetes            not yet -          kind
  05_storage               yes     yes
  ...
```

**Exactly one part needs anything beyond `pip install`,** and that is `04_kubernetes` — because GKE
is *managed Kubernetes* and Kubernetes is open source, so it can run for real. Everything else is
logic and arithmetic.

## The tools, and what each is actually for

| tool | unlocks | without it |
|---|---|---|
| **gcloud** | talking to a **real** project of your own | **everything here** — no part calls it |
| **kind** + **kubectl** + a container runtime | the real local cluster in `04_kubernetes` | every other part |
| **terraform** | **nothing in this repository** | `09_iac` implements the planner itself, deliberately |
| **git** | cloning and history | everything, if you downloaded a zip |

Two of those deserve a sentence each, because they look like they should be required and are not:

- **`09_iac` does not use Terraform.** It implements the documented graph-ordering, three-way-diff
  and force-new-cascade rules directly, so the section runs on a machine with no Terraform binary
  and no credentials.
- **No part calls `gcloud`.** Every number is computed locally. `gcloud` is for when you want to try
  something against a project of your own — which you should, but not to read this repository.

### A Windows gotcha the check surfaced

On this machine `kubectl` on `PATH` is not kubectl:

```
kubectl     kuberlr version: 0.7.0
```

Rancher Desktop ships **`kuberlr`**, a version-switching wrapper that downloads and delegates to the
real kubectl matching whatever cluster you are pointed at. It is fine — better than fine, it avoids
client/server skew — but it **rejects flags real kubectl accepts** (`kubectl version --client`
errors with *unknown flag*), so a script that shells out to `kubectl` can fail in ways that have
nothing to do with your cluster. Worth knowing before `04_kubernetes`.

## Use a virtual environment

The check warns if you are not in one:

> You are running the **system** Python. Nothing will break, but installing this repository's
> requirements into it puts them on every other project on this machine.

It is a warning and not an error — it is your machine. But `python -m venv .venv` costs three
seconds and the alternative is a dependency conflict six months from now on an unrelated project.

## Setting up gcloud — for your own project, not for this repo 📝

You do not need any of this to run the repository. You **do** need it for the exam, and every
command below is examinable.

### Install and initialise

| | |
|---|---|
| `gcloud init` | interactive: log in, pick a project, pick a default region/zone. The one to run first |
| `gcloud components update` | update the SDK. **Not `apt`/`brew`** if you installed via the archive |
| `gcloud components install <x>` | e.g. `kubectl`, `beta`, `alpha` |
| `gcloud info` | where everything is, which config is active, which account |
| `gcloud version` | SDK and component versions |

### Configurations — the part people miss

A **configuration** is a named bundle of account + project + region + zone. Switching between a work
project and a personal one is one command, not four.

| | |
|---|---|
| `gcloud config configurations create dev` | make one |
| `gcloud config configurations list` | see them all, and which is ACTIVE |
| `gcloud config configurations activate dev` | switch |
| `gcloud config set project my-project-id` | set a value in the active config |
| `gcloud config set compute/region us-central1` | region and zone live under `compute/` |
| `gcloud config list` | what the active config holds |

**Precedence, highest first:** the `--project` flag on the command → the `CLOUDSDK_CORE_PROJECT`
environment variable → the active configuration. *"It ran against the wrong project"* is almost
always the active configuration being different from what you assumed — `gcloud config list` before
anything destructive.

### The three kinds of auth, which are not interchangeable

| | |
|---|---|
| `gcloud auth login` | authenticates **you**, for `gcloud` commands |
| `gcloud auth application-default login` | writes **Application Default Credentials** for *client libraries and Terraform* — a different credential store, and the reason your Python script gets a permission error when `gcloud` works fine |
| `gcloud auth list` | which accounts are available, and which is active |
| `--impersonate-service-account=<sa>` | act as a service account **without downloading a key**. The mechanism [`02_iam`](../02_iam/README.md) argues for |

> **`gcloud auth login` and `gcloud auth application-default login` are separate.** Doing one does
> not do the other. This is the single most common "but I *am* logged in" confusion.

### Cloud Shell

A browser terminal with the SDK, `kubectl`, Docker, Python, Go and an editor pre-installed, 5 GB of
persistent `$HOME`, and **already authenticated as you**. No install, nothing to configure.

**The catch:** the VM is ephemeral. `$HOME` persists; anything installed outside it does not survive
a restart, and the session times out when idle.

### The four ways in, and when each is right

| | |
|---|---|
| **Console** | exploring, and seeing what a thing *is*. Not repeatable, not reviewable |
| **gcloud / gsutil / bq** | one-off work and scripting. `gsutil` is being folded into `gcloud storage`, which is also faster |
| **Client libraries** | inside an application. Use **Application Default Credentials**, never a downloaded key |
| **REST / gRPC** | what everything above actually calls. `--log-http` on any gcloud command shows you |

**`alpha` and `beta`** are separate component groups: `gcloud beta compute ...`. Beta is feature-
complete but may change; alpha may vanish. If a command "doesn't exist", check whether it lives
under one of those.

## The exam angle

| the scenario says | the answer |
|---|---|
| "switch between two projects constantly" | **`gcloud config configurations`** |
| "my script can't authenticate but gcloud works" | **`gcloud auth application-default login`** |
| "run one command against a different project" | the **`--project`** flag |
| "no local install, already authenticated" | **Cloud Shell** |
| "act as a service account without a key" | **`--impersonate-service-account`** |
| "the command doesn't exist" | try **`gcloud beta`** / **`alpha`**, or `gcloud components install` |
| "what account and project am I using" | **`gcloud config list`** / `gcloud info` |
| "files installed in Cloud Shell vanished" | only **`$HOME`** persists |

## Things to try

- Run `python 00_setup/check_env.py` **before** creating the venv. It exits **1** and names every
  blocked part — which is what it looks like to someone who just cloned this.
- Run it again after `pip install -r requirements.txt`. Eight parts flip from `blocked` to `yes` and
  the exit code goes to 0.
- `gcloud config configurations create scratch`, set a project, then `gcloud config list` in each
  configuration. Switching context is one command, and knowing that is worth more in the exam than
  it looks.

## What is not demonstrated here

Not done, and not claimed: installing the SDK, authenticating, or touching any Google Cloud API.
`check_env.py` inspects your machine and reports; it changes nothing, downloads nothing and sends
nothing anywhere. The gcloud sections above are documented reference, not executed.
