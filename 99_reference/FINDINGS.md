# Findings — what the runs actually showed

Every number here was **printed by a script in this repository**, not looked up. Several contradicted
what I expected before running, and those are the ones worth reading.

Re-running any part reproduces its numbers: everything is seeded or arithmetic.

---

## 1. Binding a weaker role weakens nothing → [`02_iam`](../02_iam/README.md)

```
bob has roles/editor at the ORGANIZATION      30 permissions
prod team binds roles/viewer at the PROJECT   30 permissions  (+0)
can bob still delete compute instances?       True

then an IAM DENY policy at the project        30 -> 28
can bob still delete compute instances?       False
```

**Allow policies only ever add.** Deny is the only thing that subtracts, and it is a separate policy
type rather than a binding.

*A draft of that section claimed Alice had "more on prod than dev" while printing 12 and 12 —
`dataViewer` was a strict subset of org-level `viewer`. Fixing the example rather than the sentence
produced the better lesson: **overlapping grants are normal, so counting roles tells you nothing
about access.***

## 2. The densest address plan is the wrong one → [`06_networking`](../06_networking/README.md)

Packing subnets to demand produced a valid, minimal plan — and wedged `europe-west1` between two
`us-central1` subnets:

| region | subnets | summarised as |
|---|---|---|
| us-central1 | 3 | **3 CIDRs** — any single CIDR also swallows 2 foreign subnets |

Per-region `/20` blocks cost **11,536 addresses (18% of the /16)** and buy one route/firewall
range per region plus room to expand in place. **The trade is not about addresses** — private space
is free.

## 3. A firewall deny is not a guardrail → [`06_networking`](../06_networking/README.md)

| traffic | blanket deny at 900 | same rule re-declared at priority 100 |
|---|---|---|
| IAP tunnel → :22 | deny | **allow** |

**Priority is an explicit lever.** Anyone with `compute.securityAdmin` writes 100 and walks past it.
Real guardrails live *above* the project — which is [`01_resource_hierarchy`](../01_resource_hierarchy/README.md) §4.

## 4. Spot without checkpointing costs 80% of on-demand → [`03_compute`](../03_compute/README.md)

A 10-hour job, preemption modelled as Poisson with a 4-hour mean, 2000 trials:

| strategy | finished | machine-hrs | cost | vs on-demand |
|---|---|---|---|---|
| **no checkpointing** | **74.2%** | 26.7 | $3.11 | **80%** |
| checkpoint / 15 min | 100.0% | 10.3 | $1.20 | **31%** |

**The discount was never the problem; the architecture was.** A quarter of runs never finished, and
the ones that did threw the discount away in restarts.

## 5. A diurnal curve does not stress an autoscaler → [`03_compute`](../03_compute/README.md)

With a correct simulator, shed went to **exactly zero at every utilisation target**. Load that takes
hours to double moves less in 3 minutes than the headroom a 60% target already leaves. What breaks
an autoscaler is a **spike**:

| target util | instance-hrs | shed on a 4× spike |
|---|---|---|
| 50% | 71.5 | 17,638 |
| 90% | 45.9 | **35,638** |

50% → 95%: **37% fewer instance-hours and 2.0× the shed requests.** **Target utilisation is a risk
dial, not an efficiency dial** — and nothing in the smooth-day numbers would have told you.

## 6. Archive is the easiest class to lose money on → [`05_storage`](../05_storage/README.md)

```
NEARLINE  beats STANDARD below  12.0 reads per GB per year
COLDLINE  beats STANDARD below   9.6 reads per GB per year
ARCHIVE   beats STANDARD below   4.5 reads per GB per year
```

And the cliff: **a one-day-old object in Archive costs 22× what it costs in Standard**, because the
365-day minimum is billed either way.

The "aggressive" lifecycle policy — coldest class fast, delete early — had **genuinely the lowest
storage line of four** and cost **2.8× the do-nothing policy**. *It optimised the one column it
could see.*

**It also wins at exactly one read a year and loses at two.** A policy tuned that finely is one
behaviour change from being your most expensive option.

## 7. The log router is the only engine here that multiplies → [`07_operations`](../07_operations/README.md)

```
average fan-out: 2.0 destinations per entry (max 3)
generated 421.0 GiB, stored 754.0 GiB -> 1.8x duplication
```

Every sink is evaluated **independently** — the opposite of the firewall, where the first match ends
evaluation, and of IAM, where only Deny subtracts. **An exclusion is per sink, not a global mute**:
3 entries were excluded from `_Default` and all 3 were still stored elsewhere.

One exclusion was worth **$48/month**. And **Data Access alone was 300 of the 421 GiB** — the log
type that is off by default.

## 8. The alert duration is a bet on how long your incidents last → [`07_operations`](../07_operations/README.md)

Five brief spikes and one 22-minute incident:

```
 1 min  ->  6 alerts, 1 of them real
 5 min  ->  1 alert,  caught it, 4 min to detect
25 min  ->  0 alerts, MISSED the incident entirely
```

Against a 99.9% target (43.2 min/month): **4 minutes of detection is 9% of the budget**, and the
incident itself is **51% of it in one event**.

## 9. Sustained use wins in a window a coarse grid stepped over → [`08_billing_cost`](../08_billing_cost/README.md)

In the "cheapest if it must not be interrupted" column, **SUD won 0 of 7 rows**, and I concluded it
*"is not a strategy"*.

**The capstone corrected that.** An autoscaled web tier lands at **42% uptime**, and SUD is the
cheapest option there. Solved rather than sampled, **SUD is genuinely cheapest between 25% and 50%
uptime** — above 25% it beats on-demand, below the 3-year break-even it beats a commitment. The grid
sampled **25% and 50%, the two endpoints**, and stepped straight over the interior.

> **A coarse grid can hide a whole regime**, and it is harder to catch than an arithmetic error
> because every printed row is true. This is the only finding here that a *later* part overturned,
> which is the argument for the capstone importing the real engines rather than restating results.

Break-even against on-demand-plus-SUD: **1 year needs 82.5% uptime, 3 years needs 50.0%.** And that
ordering is **structural**, not a property of the rates chosen — break-even falls monotonically with
the discount, so a 3-year option can never need *more* uptime than a 1-year one.

Also from the sweep: **below about a 30% discount a commitment never pays off at any uptime**,
because sustained use already gives 30% free.

## 10. A budget stops nothing → [`08_billing_cost`](../08_billing_cost/README.md)

```
budget            $ 2,000.00
actual spend      $ 6,140.00   (+207%)
alerts fired      4
```

**A Google Cloud budget is a notification, not a cap.** The forecast alert fired on day 13 with only
$1,040 spent — four days before the breach, and it is the one people leave off because it fires when
nothing looks wrong.

## 11. One rename destroys four things → [`09_iac`](../09_iac/README.md)

| you change | replaced |
|---|---|
| **rename the VPC** | **4** — network, subnet, *and both instances* |
| grow the subnet range | 0 |
| resize an instance | 0 |

The subnet's `network` and the instances' `subnetwork` are both force-new, so replacement walks down
the graph. **The database and bucket survive because they reference nothing** — blast radius is a
property of the graph, and it is visible *before* you apply.

Marking `ip_cidr_range` force-new takes *"grow the subnet"* from 0 replaced to 3: **blast radius
belongs to the provider schema, not to your code.**

## 12. Sustained-use-style incentives are not always aligned → [`08_billing_cost`](../08_billing_cost/README.md)

Running all month nets **30% off**. Running **half** the month nets **10%, not 15%** — the first
quarter is always full price, so the curve bends. **Sustained use discounts reward leaving machines
on**, which is worth naming rather than discovering.

---

## Bugs the runs caught in my own work

Kept because the class of error matters more than the instance.

| | |
|---|---|
| **Autoscaler shed 54.88% of requests** | the pending-instance list dropped boots on the minute they completed, so `serving` never grew. A number too extreme to be true, and it was |
| **"Largest fleet that fits: 8"** printed under a table showing 8 is blocked | the search started at the requested size and only grew. The answer was 6 |
| **Headroom of exactly 0 counted as blocking** | a quota is a ceiling you may *sit on* |
| **Custom machine type quoted as 4 vCPU / 48 GB** | 12 GB/vCPU, over the 8 GB/vCPU ceiling. Implementing the real constraints turned that row into the section's lesson |
| **Cost table printed $0.00** while the prose claimed excluding at ingestion was the only lever | the volumes all fell under the 50 GiB free tier |
| **Lifecycle policies B and D scored identically** | both acted on day 365 with a 365-day horizon, so the comparison proved nothing |
| **Cycle detector named four resources** | my test was "has an unresolved dependency", which is not cycle membership. Three were in the cycle; one was merely blocked |
| **"Read the four that are not no-change"** above a table with five | counted by hand instead of derived |
| **Claimed policy C wins at 2 reads/year** | swept it: C wins at exactly 1 and loses at 2 |
| **Claimed a 45% 3-year rate would invert the break-even ordering** | it cannot — break-even falls monotonically with the discount |
| **gcloud reported no version** | version probes invoked bare names rather than resolved paths |

**The pattern:** almost every one was caught by *reading the output against the sentence next to it*.
A number that contradicts its own caption is the cheapest bug detector there is.
