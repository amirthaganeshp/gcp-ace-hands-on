# Associate Cloud Engineer, hands on

A runnable companion for the Google Cloud **Associate Cloud Engineer** exam, built on the same
conventions as the companion [`gcp-pde-hands-on`](https://github.com/amirthaganeshp/gcp-pde-hands-on) and [`gcp-ml-hands-on`](https://github.com/amirthaganeshp/gcp-ml-hands-on) repositories: every
claim is either **measured on your machine** or **labelled as documented**, and nothing is
simulated to look like something it is not.

```bash
python -m venv .venv
.venv/Scripts/activate                # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt

python 00_setup/check_env.py          # what you have, and what it unlocks
python 02_iam/iam_hierarchy.py        # start here - 20% of the exam, and pure logic
```

**No Google Cloud account, no credentials, no billing, no Terraform, no Docker.** Every result is
computed on your machine. `check_env.py` imports only the standard library, so it runs before you
have installed anything and exits non-zero if a built part cannot run — see
[`00_setup`](00_setup/README.md).

---

## Why this repo is shaped differently from the other two

The PDE and PMLE repos work because **the technology under those exams is open source.** Dataflow
*is* Apache Beam, Managed Spark *is* Spark, Composer *is* Airflow, and scikit-learn/Keras/PyTorch
are the same libraries Google runs. The exam content already ran on a laptop; Google was providing
the *hosting*.

**ACE examines the hosting itself** — provisioning VMs, wiring VPCs, binding IAM roles, configuring
load balancers. There is no "Compute Engine library" to import and no VPC emulator.

So this repo splits differently:

| | |
|---|---|
| ✅ **Runnable** | anything that is **logic or arithmetic**: IAM resolution, CIDR planning, billing maths, alerting conditions — plus **Kubernetes**, via a real local cluster |
| 📝 **Documented** | anything that *is* Google's infrastructure: VM provisioning, VPC wiring, load balancers, managed services |

**Kubernetes is the one exception that behaves like the other repos**, because GKE is *managed
Kubernetes* and Kubernetes is open source. `kind` runs a real cluster in containers on your laptop,
which is the same "the technology runs locally, only the hosting differs" pattern.

## Exam domains

| domain | weight | where |
|---|---|---|
| 1. Setting up a cloud solution environment | 23% | `01_resource_hierarchy`, `08_billing_cost` |
| 2. Planning and implementing a cloud solution | **30%** | `03_compute`, `04_kubernetes`, `05_storage`, `06_networking` |
| 3. Ensuring successful operation | 27% | `07_operations`, `09_iac` |
| 4. Configuring access and security | 20% | **`02_iam`** |

Passing is ~70% (700/1000), 50–60 questions in 2 hours, valid 36 months.

## Repository map

```
00_setup/              environment check, gcloud configurations, what runs with no project
01_resource_hierarchy/ org -> folder -> project -> resource; quotas; billing links; labels
02_iam/                principals, roles, INHERITANCE, deny policies, service accounts   [runnable]
03_compute/            the compute spectrum, machine families, Spot, instance groups     [runnable]
04_kubernetes/         GKE anatomy, Autopilot vs Standard, workloads, scaling            [runnable, kind]
05_storage/            GCS classes and lifecycle, PD, Filestore; the database decision   [runnable]
06_networking/         VPC, subnets, firewall, Cloud NAT, the load balancer matrix       [runnable]
07_operations/         Monitoring, Logging, audit log types, alerting, uptime checks     [runnable]
08_billing_cost/       billing accounts, budgets, CUD vs SUD vs Spot, quotas             [runnable]
09_iac/                Deployment Manager vs Terraform                                   [runnable]
10_capstone_summary/   one environment end to end, plus the visual cheat sheet           [runnable]
99_reference/          CLI_REFERENCE.md (central here), decisions, glossary, renames
```

**`99_reference/CLI_REFERENCE.md` is a primary deliverable in this repo**, not a footnote. ACE is
the most command-line-heavy of the three exams.

## Conventions

Inherited from the companion repositories:

- **Every script runs standalone**, seeded, on a laptop CPU, with no project and no billing.
- **Narration is derived from measurement.** If a script prints a number, the sentence beside it
  was written from that number — not the other way round.
- **Honest negatives are kept**, not tuned away.
- Labels: ✅ runs locally · 🔬 labelled model or simulation · 📝 documented, no local proxy.

## Status

**Complete.** All twelve parts build, run and are checked in CI.

| part | state |
|---|---|
| `00_setup` | ✅ stdlib-only environment check, gcloud reference |
| `01_resource_hierarchy` | ✅ blast radius, an Org Policy evaluator, the quota planner |
| `02_iam` | ✅ IAM resolver, deny policies, blast radius |
| `03_compute` | ✅ the ladder, machine shapes, Spot, autoscaling, the Cloud Run crossover |
| `04_kubernetes` | ✅ **a real local cluster** via kind ([needs a container runtime](04_kubernetes/setup/README.md)) |
| `05_storage` | ✅ class crossovers, the minimum-duration cliff, a lifecycle engine, the database resolver |
| `06_networking` | ✅ CIDR planner, VPC peering overlap, firewall priority evaluator |
| `07_operations` | ✅ the log router, audit log types, alerting duration, availability targets |
| `08_billing_cost` | ✅ SUD tiers, the CUD break-even, and a budget that stops nothing |
| `09_iac` | ✅ a dependency graph, the three-way plan, replacement cascades |
| `10_capstone_summary` | ✅ one environment through all nine engines, plus the cheat sheet |
| `99_reference` | ✅ CLI_REFERENCE (233 commands), DECISIONS, FINDINGS, SERVICE_NAMES |

**`04_kubernetes` is the only part that needs anything beyond `pip install`** — a container
runtime, because it runs a genuine Kubernetes cluster rather than modelling one.

Last full run: **13 of 13 passed in 2.7 minutes**, the cluster build being 134 s of that.

## Licence

MIT — see [LICENSE](LICENSE), which also records what is fetched at runtime and under whose terms
(kind, kubectl, Docker Engine, the `kindest/node` and `nginx` images), and states plainly that
**no dataset is downloaded, `gcloud` is never called, and every price, quota and permission count
here is a labelled representative model rather than a quote.**
