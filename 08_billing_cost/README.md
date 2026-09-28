# Billing — four discounts with four different promises, and a budget that watches

> **ACE domain 1 (~23%)** — setting up a cloud solution environment
> **Runtime:** ~2 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 08_billing_cost/billing_and_cost.py
```

The discounts sound interchangeable and are not. Each buys a price cut in exchange for a
**different promise**:

| | you promise |
|---|---|
| **SUD** | nothing. Automatic, and it rewards leaving a machine **on** |
| **CUD** | to **pay** for a year or three, used or not |
| **Spot** | to **tolerate** being interrupted |
| **right-sizing** | nothing — and it beats all three, which is why [`03_compute`](../03_compute/README.md) puts it first |

**§2, §3 and §4 are arithmetic**, exact given the discount model. **§5 is a simulation** with its
model printed first. §1, §6 and §7 are documented 📝.

> ⚠️ Discount rates are a representative model. The **tier structure** of SUD and the **"you pay
> whether you use it"** property of CUD are the durable, examinable facts; the percentages move by
> family and region.

---

## 1. Where the money is actually decided 📝

In rough order of how much they save — which is **not** the order people try them in:

1. **Not running it.** Delete it, or schedule it off. Nothing beats zero.
2. **Right-sizing.** A commitment on an oversized machine buys a discount on waste.
3. **The right product.** Cloud Run instead of an idle VM; the right storage class.
4. **Discount programmes.** §2–§4. The **last** thing to reach for, not the first.

> **The order matters because the discounts compound the mistake.** A three-year commitment on a
> fleet twice the size it needs to be locks in the wrong number for three years at 55% off.

## 2. Sustained use discounts — automatic, and non-linear

The month splits into quarters. Each quarter of **usage** is discounted more than the last:

| of the month | you pay | off |
|---|---|---|
| 0–25% | 100% of list | 0% |
| 25–50% | 80% | 20% |
| 50–75% | 60% | 40% |
| 75–100% | 40% | **60%** |

| uptime | paid | **net discount** | $/month |
|---|---|---|---|
| 10% | 0.100 | 0.0% | 50.00 |
| 25% | 0.250 | 0.0% | 125.00 |
| 40% | 0.370 | 7.5% | 185.00 |
| **50%** | 0.450 | **10.0%** | 225.00 |
| 75% | 0.600 | 20.0% | 300.00 |
| 90% | 0.660 | 26.7% | 330.00 |
| **100%** | 0.700 | **30.0%** | 350.00 |

**Running all month nets 30% off. Running half the month nets 10% — not 15%.** The discount is
**incremental**, and the first quarter of the month is always full price, so the curve bends. Every
hour you switch a machine off costs you discount on the hours you kept.

> **That is an uncomfortable incentive and it is worth naming:** sustained use discounts reward
> **leaving things on**. They are automatic, you cannot decline them, and they will never be the
> reason to run something you don't need.

You apply for nothing and sign nothing. SUD is calculated per month, per region, and Google
aggregates usage across instances of the same type to maximise it for you. **E2 machine types are
not eligible** — their list price is already low.

## 3. Committed use discounts — the break-even

A commitment is a promise to **pay** for a fixed amount of vCPU and memory in a region for 1 or 3
years. **You are billed every month whether or not you use it, and it cannot be cancelled.**

So the question is never *"is 55% good"*. It is: **at what uptime does paying all the time beat
paying only when you run, with SUD already applied?**

| commitment | you pay | **break-even uptime** |
|---|---|---|
| **1 year** (~37% off) | 63% | **82.5%** |
| **3 years** (~55% off) | 45% | **50.0%** |

> **Read that carefully, because it is the opposite of the intuition.** The **longer, deeper**
> commitment is the **easier** one to justify on utilisation.

And that is **structural, not an artefact of the rates chosen here.** A deeper discount means a
lower bill every month, so it overtakes sustained use sooner — the break-even falls **monotonically**
as the discount rises:

| discount | break-even uptime | |
|---|---|---|
| 20% | **never pays off** | |
| 30% | 100.0% | |
| 37% | 82.5% | ← 1 year |
| 45% | 66.7% | |
| 55% | 50.0% | ← 3 years |
| 70% | 31.2% | |

**There is no pair of real commitment rates where the 3-year option needs more uptime than the
1-year one.** So the break-even is never the reason to prefer 1 year.

> **What makes three years hard is not the arithmetic, it is the forecast.** You are asserting a
> workload will still exist, at roughly this size, in this region, in three years. The break-even is
> certain; that sentence is not.

Note the top row: **below about a 30% discount a commitment never pays off at any uptime**, because
sustained use already gets you 30% for free.

**What a commitment does *not* do:**

- **It does not reserve capacity.** A commitment is a *billing* construct. Guaranteed capacity is a
  **reservation**, a separate thing you can buy alongside it.
- It does not follow you to another region.
- **It cannot be cancelled**, and the exam likes this fact.

Resource-based commitments are vCPU and memory. **Spend-based (flexible)** commitments are a
dollar-per-hour promise covering several services including Cloud Run — more flexible, smaller
discount.

## 4. All four levers, one workload

A fleet whose on-demand list price is $500/month at 100% uptime:

| uptime | on-demand | + SUD | CUD 1yr | CUD 3yr | Spot | cheapest | cheapest if it **must not be interrupted** |
|---|---|---|---|---|---|---|---|
| 10% | 50.00 | 50.00 | 315.00 | 225.00 | **15.00** | Spot | **on-demand** |
| 25% | 125.00 | 125.00 | 315.00 | 225.00 | **37.50** | Spot | **on-demand** |
| **50%** | 250.00 | **225.00** | 315.00 | **225.00** | 75.00 | Spot | **CUD 3yr** *(exact tie — the break-even)* |
| 75% | 375.00 | 300.00 | 315.00 | **225.00** | 112.50 | Spot | CUD 3yr |
| 90% | 450.00 | 330.00 | 315.00 | **225.00** | 135.00 | Spot | CUD 3yr |
| 100% | 500.00 | 350.00 | 315.00 | **225.00** | 150.00 | Spot | CUD 3yr |

**Spot wins every row on price, and that is why price is the wrong column to read.** Read the last
column — the one most production workloads actually face.

**Sustained use wins 0 of 7 rows.** Below the break-even, plain on-demand is cheaper because SUD has
barely started; above it, the three-year commitment is cheaper because 55% beats 30%.

> ⚠️ **That row count is an artefact of the grid, and the capstone caught it.** Solved rather than
> sampled, **sustained use is genuinely the cheapest option between 25% and 50% uptime** — above 25%
> it beats on-demand, below the three-year break-even it beats a commitment. The grid above samples
> **25% and 50%, the two endpoints**, and steps straight over the interior.
>
> **A coarse grid can hide a whole regime**, and it is harder to notice than an arithmetic error
> because every printed row is true. An autoscaled tier lives in exactly that window —
> [`10_capstone_summary`](../10_capstone_summary/README.md) lands at **42% and picks SUD**.
>
> So the honest version: **SUD is what you get when you decline to choose, and there is a real band
> where declining is correct.**

The caveat that keeps the rest honest: CUD 3yr wins its rows **only if the workload really is still
there in three years.** The arithmetic is certain and the forecast is not.

Each lever costs you something absent from the table:

| | the real price |
|---|---|
| on-demand | nothing. Full flexibility, full price |
| + SUD | nothing. Just don't switch things off to chase it |
| CUD | a 1- or 3-year bill you cannot cancel, in one region, for a workload you must forecast |
| Spot | interruption at any time with 30 s notice, no SLA, and an architecture that must be resumable — `03_compute` measured a 10-hour job that finished only **74%** of the time without checkpointing |

**And they combine.** A steady baseline on a commitment, the variable peak on-demand, and batch on
Spot is the normal shape of a mature bill — not one lever for everything.

## 5. Budgets and alerts — and what they do *not* do 🔬

**The model:** a $2,000/month budget with alerts at 50%, 90% and 100% of **actual** spend plus a
**forecast** alert. Normal burn $40/day; on **day 12** somebody leaves a large job running and it
becomes $300/day.

| alert | fired on |
|---|---|
| actual 50% | day 13 |
| **forecast 100%** | **day 13** |
| actual 90% | day 16 |
| actual 100% | day 17 |

```
budget            $ 2,000.00
actual spend      $ 6,140.00
overrun           $ 4,140.00  (+207%)
```

**The forecast alert fired on day 13, when only $1,040 had been spent** — four days before the
budget was actually breached. That is the alert worth configuring, and it is the one people leave
off because it fires when nothing looks wrong.

> **And the budget stopped nothing.** 4 alerts fired and **$6,140 went out of the door anyway.**
>
> **A Google Cloud budget is a notification, not a cap.** This is the single most commonly
> misunderstood thing in the domain and a favourite exam question. **There is no "stop at $2,000"
> setting.**

To actually stop spending you have to build it: the budget publishes to a **Pub/Sub** topic, a
**Cloud Run function** subscribes, and that function **disables billing** on the project. Which is
brutal — everything in the project stops, including the database — so it belongs on a sandbox, not
on production.

Budgets are set on a **billing account** and can be scoped to projects, services or **labels**. They
can also be a percentage of **last month's** spend rather than a fixed figure, which is the one that
survives a growing environment.

## 6. Finding the money 📝

| | |
|---|---|
| **Billing export to BigQuery** | the answer to almost every *"analyse our spend"* question. The console reports are fixed views; the export is the data, with labels and SKU detail. **Turn it on before you need it — it is not retroactive**, and the month you want to investigate is always the month before you enabled it |
| **Labels** | how cost is attributed to a team, environment or cost centre. They flow into the export. No labels means no answer to *"whose is this"* that doesn't involve guessing from project names. **Labels, not tags** — see [`01_resource_hierarchy` §7](../01_resource_hierarchy/README.md) |
| **Recommender** | surfaces idle VMs, oversized machines, idle disks and addresses, **and commitment recommendations from your actual usage**. It does §3's arithmetic against real data — use it before computing a break-even by hand |
| **Pricing calculator** | before you build. The only place any number in this file should have come from if it mattered |
| **Cost table / reports** | enough for *"what changed this month"*; not enough for anything with a join in it |

## 7. The things that quietly cost money 📝

None of these show up as "compute" and all of them show up on the bill.

| | |
|---|---|
| **Static IP, reserved and unused** | Google charges **more** for a reserved address doing nothing than for one attached to a running instance. A deliberate nudge, and it surprises people |
| **Unattached persistent disks** | a deleted VM whose disk had *keep disk* ticked. Billed in full, forever |
| **Snapshots and old images** | incremental, so cheap each, and nobody ever deletes them |
| **Stopped instances** | no vCPU or memory charge, but the **disks** still bill |
| **Egress** | cross-region, cross-continent and internet. Same-region is free. *"Why is the bill so high"* is more often egress than storage |
| **Cloud NAT and load balancers** | hourly charges plus data processed, used or not |
| **Log ingestion** | [`07_operations`](../07_operations/README.md) measured one exclusion worth **$48/month**, and a Data Access audit log that was **300 of 421 GiB** |
| **Idle GKE clusters** | the control plane bills per hour on Standard whether or not any workload runs |

> **The pattern:** nearly all of it is things created for a reason that has since expired. That is
> why lever 1 is lever 1, and why **Recommender finds more money than any discount programme in this
> file.**

## The exam angle

| the scenario says | the answer |
|---|---|
| "stop spending when we hit the budget" | **you cannot with a budget alone.** Budget → Pub/Sub → function that **disables billing** |
| "warn us before we overspend" | a **forecasted-spend** budget alert |
| "steady workload running 24/7" | **committed use discount** |
| "we already run it all month — what do we apply for" | **nothing.** Sustained use is automatic |
| "fault-tolerant batch, cheapest" | **Spot VMs** |
| "guarantee we can get the capacity" | a **reservation**. A commitment is billing, not capacity |
| "which team spent this" | **labels** + billing export to BigQuery |
| "find waste for us" | **Recommender** |
| "estimate before we build" | the **pricing calculator** |
| "the bill is high and compute looks normal" | check **egress**, idle static IPs, unattached disks, log ingestion |
| "cancel our 3-year commitment" | **you cannot** |
| "one budget for the whole organisation" | budgets are on the **billing account**, scoped by project, service or label |

## Things to try

- Set `CUD_3YR` to `0.30` and re-solve. The break-even goes to **100%** — the commitment only pays
  off if you never switch the machine off for a second, because sustained use already gives 30% for
  nothing. Below 30% there is no uptime at which it wins. **A commitment has to beat the free
  discount before it beats anything**, and that floor is invisible unless you model SUD first.
- Change `runaway_day` in §5 to 28. The forecast alert has almost no runway left, and the overrun
  lands in next month's bill instead. **A budget's usefulness depends on how early in the cycle
  things go wrong**, which is not something you control.
- Add a `cost_cud_partial` that bills the commitment *plus* on-demand for usage above it. That is
  how real commitments behave when you under-commit, and it is the safer way to buy one.

## What is not demonstrated here

Not simulated, and not claimed: real prices, real SUD tiering for any family other than the classic
N1 structure, spend-based commitment maths, marketplace or support charges, taxes, sustained-use
aggregation across instance types, or any real billing account. §2–§4 are exact given the stated
discount model; §5's model prints before its numbers.
