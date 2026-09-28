# Capstone — one environment, built end to end with the other nine parts

> **All four ACE domains** · **Runtime:** ~6 s on a laptop CPU · **Needs:** nothing beyond
> `pip install -r requirements.txt`

```bash
python 10_capstone_summary/capstone.py
```

This script **imports the engines from the other parts** and runs one coherent scenario through all
of them. Nothing is reimplemented — the IAM resolver, the Org Policy evaluator, the CIDR planner,
the firewall evaluator, the storage arithmetic, the log router, the discount model and the IaC
planner are the same objects those parts demonstrate.

That makes it an **integration test** as well as a revision aid: if any part changes its API, this
breaks. And it means a result here can **contradict** a result there — which is exactly what
happened (§7).

---

## The brief

> Acme is launching a product in the EU.
> - data must stay in the EU
> - no VM may have a public IP
> - the network team owns the network; the product team owns the app
> - a web tier behind a load balancer, an analytics worker, an orders database, an assets bucket
>
> **Build it. Then find what is wrong with it.**

## 1. Hierarchy and guardrails

Three org-level policies, one line of intent each:

```
gcp.resourceLocations                 allow [europe-west1, europe-west4]
compute.vmExternalIpAccess            allow []   (no public IPs)
iam.disableServiceAccountKeyCreation  enforced   (no downloadable keys)
```

| project | europe-west1 | europe-west4 | us-central1 | asia-east1 |
|---|---|---|---|---|
| `shop-eu-prod` | yes | yes | **NO** | **NO** |
| `shop-eu-dev` | yes | yes | **NO** | **NO** |

Three lines at the org, **3 projects covered, no exceptions**. Data residency is not a policy
document here — it is the API refusing.

## 2. Access

| principal | binding | permissions |
|---|---|---|
| net-team | `roles/compute.instanceAdmin` | 5 |
| app-team | `roles/storage.objectViewer` | 2 |
| web-sa | `roles/storage.admin` | 6 |

**The shortcut nobody took:** `roles/editor` is 30 permissions across 6 services. The network team
has **5, in 1** — a **6.0× reduction in blast radius** for one extra minute of thinking.

## 3. The network

> **The web tier autoscales to a maximum of 10, though today's curve only needs 6. Size the subnet
> from the maximum** — the addresses have to exist on the worst day, and a subnet can be grown but
> **never shrunk**.

| subnet | region | want | CIDR | usable |
|---|---|---|---|---|
| web-ew1 | europe-west1 | 10 | `10.20.0.0/28` | 12 |
| app-ew1 | europe-west1 | 12 | `10.20.0.16/28` | 12 |
| data-ew4 | europe-west4 | 6 | `10.20.0.32/28` | 12 |

| traffic | verdict | matched |
|---|---|---|
| health checker → :80 | allow | `allow-health` (800) |
| IAP SSH → :22 | allow | `allow-iap-ssh` (700) |
| internet → :443 | **deny** | `deny-public` (900) |
| VM → Google API :443 | allow | `implied-allow-egress` |

Public ingress is denied and the two paths we need survive, **because both were written below
900**. That ordering is the design, not an accident.

No VM has an external IP, so outbound needs **Cloud NAT** and Google APIs need **Private Google
Access**. The egress row was allowed by the *implied* rule — which permits nothing on its own
without a path.

## 4. The compute

```
peak instances the curve needs          6
autoscaled instance-hours/day        61.1
fixed at peak, instance-hours       144.0
saving from autoscaling             57.6%
shed on the 4x spike               17,638 (0.165%)
```

The analytics worker at **6 vCPU / 40 GB** is a legal custom shape and fits **no** predefined one.

## 5. The data

**Orders → Cloud SQL (PostgreSQL)**, regional, in europe-west1. Not Spanner — the brief never asked
for global consistency.

**Assets bucket at ~6 reads per GB per year:**

| class | $/GB-year |
|---|---|
| Standard | 0.2400 |
| Nearline | 0.1800 |
| **Coldline** | **0.1680** |
| Archive | 0.3144 |

> **Archive — the "obvious" cheap answer — costs 1.9× the right one**, because of retrieval. The
> class is a bet on the access pattern, not a property of the data.

## 6. Operating it

```
generated 303 GiB, stored 349 GiB -> 1.2x
_Default ingests 303 GiB; 253 billable -> $126.50/month

alerting: threshold 80%, duration 5 min -> one alert, 4 minutes to detect
```

Against a 99.9% target (43.2 min/month), **4 minutes of detection is 9% of the monthly error budget
spent noticing.**

## 7. What it costs — and the correction

| lever | $/month | condition |
|---|---|---|
| on-demand | 360.98 | none |
| **+ SUD** | **331.32** | automatic |
| CUD 1yr | 535.97 | pay all year; break-even 82% |
| CUD 3yr | 382.84 | pay 3 years; break-even 50% |

Uptime is **42%**, below the 3-year break-even of 50%, so a commitment would be paying for capacity
the autoscaler deliberately switches off. **Autoscaling and committing pull in opposite directions**
— commit the baseline, autoscale the peak.

> ### This corrects something `08_billing_cost` said
>
> That part reported sustained use winning **zero of seven rows** and concluded it *"is not a
> strategy"*. **It wins here.**
>
> Solved rather than sampled, **SUD is genuinely cheapest between 25% and 50% uptime** — above 25%
> it beats on-demand, below the 3-year break-even it beats a commitment. The grid in that section
> sampled **25% and 50%, the two endpoints**, and stepped straight over the interior.
>
> **A coarse grid can hide a whole regime.** The arithmetic was right and the sampling was wrong,
> which is harder to notice than an arithmetic error **because every printed row is true.**
>
> `08_billing_cost` now solves for the window and says so.

## 8. Building it repeatably

```
5 resources, 3 dependency levels, widest 3
  level 0: network.vpc, sql_database_instance.orders, storage_bucket.assets
  level 1: subnetwork.web
  level 2: instance.web

Renaming the VPC would REPLACE 3 of 5:
  instance.web, network.vpc, subnetwork.web
```

The database and the bucket survive **because they reference nothing** — and that is visible in
`plan`, before anything happens.

## 9. The scorecard

| area | verdict | detail |
|---|---|---|
| guardrails | **OK** | 3 org policies, 3 projects, no exceptions yet |
| least privilege | **OK** | predefined roles; 6.0× smaller than Editor |
| network | **OK** | no public ingress; IAP and health checks outrank the deny |
| compute | **RISK** | 0.165% shed on a spike; **min instances not set** |
| storage class | **OK** | Coldline chosen on measured access, not list price |
| operations | **RISK** | log duplication 1.2×; **no exclusion set** |
| cost | **RISK** | uptime 42% vs 3yr break-even 50% |
| repeatability | **OK** | 5 resources in code; rename blast radius 3 |

**5 OK, 3 RISK.**

> **The three risks are all the same shape: a default that was never revisited.** No min instances
> on the MIG, no exclusion on `_Default`, no decision about committing the baseline. None is a
> mistake exactly — each is a thing **nobody chose**.
>
> And note what is *not* on the list. Nothing is broken by a wrong answer; the environment is
> correct. Everything that showed up is an **unexamined default**, which is what real review finds —
> and it is why the guardrails in §1 matter more than any single resource in the build.

## 10. The cheat sheet

One page: domain weights and which part covers them, the four rule engines side by side, the storage
crossovers, this environment's cost levers, the numbers worth memorising, and the decision spine.

**If a row on it is not obvious, the part it came from is the one to re-read.**

## Things to try

- Change `MIG_MAX` to 60 and re-run. The subnet jumps a prefix size and the cost table moves, but
  the *scorecard* does not — **capacity is not the risk; the unexamined defaults are.**
- Set `target_util` to 0.9 in §4. Shed doubles, the cost falls, and the compute row stays RISK for a
  different reason than before.
- Give the web tier `min_instances=2`. Uptime rises toward the break-even, and at some point the
  cost section's recommendation flips from SUD to a commitment. **That is the trade in one edit.**

## What is not demonstrated here

Not run, and not claimed: any Google Cloud API, any real resource, any real bill. Every number comes
from the other parts' models, with their stated assumptions — this part composes them, it does not
add new measurement. The value is in the composition: results that are individually true and
jointly reveal something neither part could, as §7 shows.
