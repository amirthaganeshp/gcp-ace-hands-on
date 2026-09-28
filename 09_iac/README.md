# Infrastructure as code — a plan is a three-way diff, and one rename destroys four things

> **ACE domain 3 (~27%)** — ensuring successful operation
> **Runtime:** ~2 s on a laptop CPU · **Needs:** nothing — **no Terraform binary, no credentials**

```bash
python 09_iac/iac_and_state.py
```

Two mechanisms here are almost universally misunderstood, and both are implementable:

- **A plan is not a diff between your code and the cloud.** It is a **three-way** comparison of
  **config**, **state** and **reality**, and the five combinations behave differently.
- **Some attributes cannot be changed in place.** Changing one forces a replacement, and
  replacement **cascades** to everything referencing it through another force-new attribute.

**§1–§4 run.** The planner is a real (small) implementation of the rules Terraform documents, not a
description of them. §5 and §6 are documented 📝.

> ⚠️ The resource types and their force-new attributes are **modelled** on the real Google provider
> — close enough to be instructive, not a substitute for reading the resource docs.

---

## 1. Why IaC at all, and what idempotent means

| | |
|---|---|
| **Console** | fine to learn with, impossible to review, repeat or hand over. **Nothing records why** |
| **gcloud** | repeatable if you remember the flags. Still **imperative**: you say what to *do*, not what should *exist* |
| **A shell script** | repeatable and in git — but **not idempotent**. Run it twice and it either fails on "already exists" or creates a second one |
| **IaC** | you declare the **desired state**. The tool works out the difference and does only that |

```
apply #1 against an empty project: 6 to create
apply #2, nothing else changed:    0 to change, 6 unchanged
```

**That second line is idempotence**, and it is why a plan is safe to run in CI on every commit. A
shell script cannot give it to you without writing the "does it already exist" check by hand, for
every resource, correctly.

## 2. The dependency graph, and what can run at once

**You never declare the edges.** They fall out of the **references** — writing
`${google_compute_network.vpc.id}` as the subnet's network *is* the dependency.

```
level 0  (3 in parallel)
  network.vpc
  sql_database_instance.db
  storage_bucket.assets
level 1  (1 in parallel)
  subnetwork.web  <- network.vpc
level 2  (2 in parallel)
  instance.app  <- subnetwork.web
  instance.web  <- subnetwork.web
```

Everything inside one level is independent, so the tool creates them **concurrently** — that is what
`-parallelism` acts on. **Destroys run in reverse order**, which is why a subnet is never torn out
from under a running instance.

The database and the bucket sit at level 0 with the VPC: they reference nothing, so nothing waits
for them. **An unconnected resource is free concurrency.**

A cycle is refused, not worked around:

```
unorderable - cycle among ['instance.app', 'network.vpc', 'subnetwork.web'];
also blocked: ['instance.web']
```

## 3. The plan is a three-way diff

| | |
|---|---|
| **CONFIG** | what you wrote |
| **STATE** | what the tool believes it made last time |
| **REALITY** | what is actually there now |

Most people picture *config vs reality*. **The tool cannot do that** — it only manages what is in
**state**, and finds drift by refreshing state against reality first.

| resource | C | S | R | action | why |
|---|---|---|---|---|---|
| `instance.app` | – | y | y | **destroy** | removed from config |
| `instance.jump` | y | – | y | **create (WILL FAIL)** | exists but is not in state — needs **import** |
| `instance.someones_test` | – | – | y | *(ignored)* | not managed by this configuration |
| `instance.web` | y | y | y | no change | |
| `network.vpc` | y | y | y | no change | |
| `subnetwork.web` | y | y | y | no change | |
| `sql_database_instance.db` | y | y | y | **update in place** | tier — **[DRIFT]** |
| `storage_bucket.assets` | y | y | – | **create** | deleted outside the tool — recreate |

**Drift (db)** — somebody resized it in the console. The plan wants to put it **back**. IaC does not
record your change, it **reverts** it, and it will do so at 3am in CI without asking. That is the
deal, and it is why a managed resource must not be touched by hand.

**Deleted (bucket)** — the plan recreates it. Note what does **not** come back: the objects that
were in it. **IaC restores the resource, never the data** — see
[`05_storage` §8](../05_storage/README.md) on what is not a backup.

**Not in state (jump)** — someone built it by hand, then wrote matching config. The plan says
*create* and the apply **fails on "already exists"**. The fix is **`terraform import`**, which
adopts the existing resource into state. The most common first-week error there is.

**Removed from config (app)** — deleting the block does not orphan it, it **destroys** it. To stop
managing something, that is **`terraform state rm`**, not a delete key.

And `someones_test` is simply **invisible**: not in config, not in state. IaC has no opinion about
resources it doesn't manage — which is why *"we use Terraform"* is never the same sentence as
*"everything is in Terraform"*.

## 4. Replacement cascades

| you change | replaced | updated | what gets replaced |
|---|---|---|---|
| **rename the VPC** | **4** | 0 | `instance.app`, `instance.web`, `network.vpc`, `subnetwork.web` |
| move the subnet to another region | **3** | 0 | `instance.app`, `instance.web`, `subnetwork.web` |
| **grow the subnet range** | 0 | 1 | – |
| resize the app instance | 0 | 1 | – |
| change the database version | 1 | 0 | `sql_database_instance.db` |
| change the bucket storage class | 0 | 1 | – |

> **Renaming the VPC replaces 4 resources.** One string, in one line, and the network, the subnet
> and *both* instances are destroyed and rebuilt — because the subnet's `network` is force-new and
> the instances' `subnetwork` is force-new, so the replacement **walks straight down the graph from
> §2**.

**The database and the bucket survive**, and not because they are important — **because they
reference nothing**. Blast radius here is a property of the **graph**, exactly as it was in
[`01_resource_hierarchy`](../01_resource_hierarchy/README.md), and **it is visible before you
apply**.

Contrast the rows that cost nothing. Resizing an instance and changing a bucket's storage class are
in-place updates — and so is **growing the subnet range**, which is the same asymmetry
[`06_networking`](../06_networking/README.md) measured (*expand yes, shrink never*) showing up here
as ForceNew or not.

> **Which is the whole argument for `terraform plan`:** it tells you this **before** the apply, in a
> review, with a diff, and the word to search for is **REPLACE**. `gcloud` and the console will not
> warn you, because they do not know what else you built.

## 5. State: where it lives, and what breaks it 📝

State maps your config to real resource ids. It is not a cache and not optional — without it the
tool cannot tell *"create this"* from *"I already made this"*.

| | |
|---|---|
| **Where it goes** | a **GCS bucket, with object versioning on**. **Never in git** — it contains resource ids and often **secrets in plain text**, and two people on two laptops will overwrite each other |
| **Locking** | a remote backend takes a lock during apply so two applies cannot run at once. A stale lock after a crashed run is a normal operational event |
| **Drift** | any change made outside the tool. §3 showed what happens. The defence is not vigilance, it is **not granting humans write access to what the pipeline owns** — `02_iam` and `01_resource_hierarchy` are the actual controls |
| **`import`** | adopts an existing resource into state |
| **`state rm`** | stop managing something **without destroying it** |
| **Workspaces / separate state** | the cleaner pattern is separate state **and a separate project** per environment, so a bad apply in dev cannot reach prod |
| **Modules** | reusable groups with inputs and outputs — the unit of *"every team gets the same VPC shape"* |

> **If state is lost** and the resources still exist, the tool will try to **create all of them
> again** and fail on the ones that exist. Recovery is a restore from the bucket's object versions —
> which is why versioning on the state bucket is not optional.

## 6. Deployment Manager vs Terraform vs the rest 📝

| | |
|---|---|
| **Terraform** | the industry default, multi-cloud, huge provider ecosystem, HCL. If a question names a tool, this is usually it |
| **Infrastructure Manager** | Google's **managed Terraform** — runs it for you, keeps state in Google Cloud, integrates with IAM. The current Google-native answer |
| **Deployment Manager** | Google's **original** native IaC — YAML with Jinja/Python templates, Google only. Google has announced its **deprecation** in favour of Infrastructure Manager. Exam blueprints lag announcements, so know what it *is* and expect it to appear, but don't start anything new on it — **check the current status rather than trusting this line** |
| **Config Connector** | manage Google Cloud resources as **Kubernetes objects**, reconciled by a controller in your cluster |
| **gcloud / client libraries** | imperative. Right for one-off investigation and things IaC genuinely can't express |

> *"Repeatable"*, *"version controlled"*, *"review the change before it happens"*, *"identical
> environments"* ⇒ **IaC** rather than gcloud. *"Multi-cloud"* or a named tool ⇒ **Terraform**.
> *"Managed, in Google Cloud, with IAM"* ⇒ **Infrastructure Manager**. *"As Kubernetes resources"* ⇒
> **Config Connector**.

## 6b. Where Cloud Build fits 📝

**Cloud Build is not a fifth item for the table above.** Everything in §6 answers *"what decides
the desired state"*. Cloud Build answers a different question: *"what runs the commands"* — and one
of the commands it can run is `terraform apply`.

```
                 DECIDES the desired state          RUNS the commands
                 ---------------------------         ------------------
Terraform /      write the config, hold state         (you type
Infra Manager                                          terraform apply)
                                                    ↓
Cloud Build      -                                  a TRIGGER fires on a
                                                     git push, runs terraform
                                                     apply inside a build step
```

**A build is a sequence of containers, run in order, nothing more exotic than that.** Each `step`
in `cloudbuild.yaml` is an image and an argv; the official builders (`docker`, `gcloud`,
`hashicorp/terraform`, `kubectl`) are just containers someone published. That is *why* it can build
an image, run `terraform apply`, and deploy to Cloud Run inside the same pipeline — they are three
steps, not three products.

**A trigger connects a build to a repo event** — push to a branch, a tag, a pull request. *"Build
and deploy automatically on every push to main"* is a Cloud Build trigger; the exam distinguishes
this from *"review the change before it happens"* in §3, which is `terraform plan` read by a human,
run **before** merge — a trigger firing **on** merge is the step after that review, not a
replacement for it.

**Cloud Build vs Cloud Deploy** is the pairing worth fixing in memory: **Build produces the
artifact once** (an image, pushed to Artifact Registry); **Deploy promotes that same artifact**
through environments — dev → staging → prod — with approval gates in between. A pipeline that
rebuilds the image for every environment is the anti-pattern Cloud Deploy exists to prevent: you
want to know the exact bytes that passed staging are the exact bytes that reach production.

**Where the state lives is unaffected either way.** A build running `terraform apply` still reads
and writes the same GCS-backed state from §5 — Cloud Build supplies the compute and the trigger,
not a different backend. If a build's service account can write that state bucket, it can change
production; that permission is the real security boundary, and it is an IAM question
([`02_iam`](../02_iam/README.md)), not an IaC one.

## The exam angle

| the scenario says | the answer |
|---|---|
| "identical dev, staging and prod" | IaC, one configuration, separate state and separate **projects** |
| "review infrastructure changes before they happen" | **`terraform plan`** in a pull request |
| "multi-cloud", or names Terraform | **Terraform** |
| "managed Terraform inside Google Cloud" | **Infrastructure Manager** |
| "Google's original YAML/Jinja IaC" | **Deployment Manager** (being retired) |
| "manage cloud resources with kubectl" | **Config Connector** |
| "we built it by hand, now put it in code" | **`terraform import`** |
| "stop managing this without deleting it" | **`terraform state rm`** |
| "where does state go" | a **versioned GCS bucket**. Never git |
| "two engineers applied at once" | remote backend **locking** |
| "someone changed it in the console" | the next apply **reverts** it |
| "why is it destroying my instance" | a **force-new** attribute changed, or something it depends on was replaced |
| "build and deploy automatically on every push" | a **Cloud Build trigger** |
| "promote the same image through dev, staging, prod with approval" | **Cloud Deploy** |
| "run `terraform apply` from CI, not a laptop" | **Cloud Build**, calling Terraform as a build step |
| "who can change production infrastructure" | whoever the build's **service account** can write the **state bucket** as — an IAM question |

## Things to try

- Add `"ip_cidr_range"` to `FORCE_NEW["google_compute_subnetwork"]` and re-run §4. *Growing the
  subnet* jumps from 0 replaced to 3 — the same edit, the same graph, a different provider
  decision. **The blast radius is not a property of your code; it is a property of the provider's
  schema**, which is why reading the resource docs is the real skill.
- Point `google_sql_database_instance.db` at the subnet by adding a reference, then rename the VPC.
  The database joins the cascade. **Connecting a resource to the graph is what puts it at risk**,
  and it is usually done for an unrelated reason.
- Delete a resource from `state` only (not config, not reality) and re-plan. You get the *"exists
  but is not in state"* row — the same situation as a hand-built resource, reached from the
  opposite direction.

## What is not demonstrated here

Not run, and not claimed: real Terraform, real HCL parsing, real providers or provider versioning,
`terraform` CLI behaviour, remote backends, locking, modules, or any Google Cloud API call. The
planner implements the documented *rules* for graph ordering, three-way diffing and force-new
cascades against a modelled schema — it will not tell you whether a particular real attribute is
ForceNew.
