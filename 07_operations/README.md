# Operations — logs go to every sink that matches, and alerts fire on duration

> **ACE domain 3 (~27%)** — ensuring successful operation
> **Runtime:** ~3 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 07_operations/operations.py
```

Two mechanisms in this domain are routinely got wrong, and both are testable here:

- **The Log Router is not first-match.** Every sink is evaluated independently, so one log entry
  lands in four places at once. This is the *opposite* of the firewall in
  [`06_networking`](../06_networking/README.md), and the difference shows up as a bill.
- **An alert condition is a duration, not a threshold.** *"CPU above 80%"* almost never means what
  people think it means.

**§2, §3, §5 and §6 run.** §5's metric series is seeded and its model is printed before the numbers.
§1, §4 and §7 are documented 📝.

> ⚠️ Prices are a representative model. The **free allowances** and the **retention defaults** are
> the durable, examinable numbers.

---

## 1. The four audit log types 📝

The distinctions are always the same three: **on by default? can you turn it off? does it cost?**

| | on by default | can disable | cost | retention |
|---|---|---|---|---|
| **Admin Activity** — *who changed the config* | ✅ always | ❌ never | free | 400 d (`_Required`) |
| **Data Access** — *who read or wrote the data* | ❌ **off** (except BigQuery) | ✅ | **chargeable, high volume** | 30 d (`_Default`) |
| **System Event** — *Google's own actions* | ✅ always | ❌ never | free | 400 d |
| **Policy Denied** — *refused by a security policy* | ✅ always | ❌ | chargeable | 30 d |

> **The exam pattern:** *"we need to know who deleted the instance"* is **Admin Activity** and it is
> already there. *"We need to know who **read** the customer table"* is **Data Access** and it is
> **not** — somebody has to turn it on first. And it wasn't on last month, so the answer to "who
> read it in March" may simply be **that nobody knows**.

## 2. The log router — a real sink evaluator

```
sink               destination inclusion filter
_Required          logbucket   logName~"cloudaudit.googleapis.com/activity" [LOCKED]
_Default           logbucket   (everything)
                               exclude: resource.type="gce_instance"
security-archive   gcs         logName~"cloudaudit.googleapis.com"
analytics          bigquery    resource.type="gce_instance"
pager              pubsub      severity>=ERROR
```

| log entry | goes to |
|---|---|
| activity / gce_instance / NOTICE | `_Required`, `security-archive`, `analytics` |
| data_access / bigquery_resource / INFO | `_Default`, `security-archive` |
| serial_port / gce_instance / INFO | `analytics` |
| stderr / cloud_run_revision / ERROR | `_Default`, `pager` |
| app / gce_instance / CRITICAL | `analytics`, `pager` |

**Average fan-out: 2.0 destinations per entry (max 3).**

> **No sink stopped another one.** There is no ordering, no precedence and no first-match — every
> sink is evaluated independently against every entry. Compare `06_networking`, where the first
> matching firewall rule *ends* evaluation, and `02_iam`, where only a Deny policy subtracts. **The
> Log Router is the only engine in this repository that multiplies.**

**3 entries were excluded from `_Default`, and all 3 are still being stored somewhere else.** An
exclusion is **per sink, not a global mute** — *"we excluded those logs and the bill didn't move"*
is this, every time.

And `_Required` is **locked**: you cannot add an exclusion, disable it, or change its 400-day
retention. That is deliberate — it is the sink that guarantees an audit trail exists even if someone
reconfigures everything else.

## 3. What that routing costs

| sink | destination | GiB/month | $/month | note |
|---|---|---|---|---|
| `_Required` | logbucket | 2.0 | **0.00** | free, always, cannot be disabled |
| `_Default` | logbucket | 325.0 | **137.50** | first 50 GiB free → 275.0 billable |
| `security-archive` | gcs | 302.0 | 6.04 | routing free, you pay GCS |
| `analytics` | bigquery | 96.0 | 1.92 | routing free, you pay BQ |
| `pager` | pubsub | 29.0 | 0.00 | routing free, you pay whoever consumes it |

```
generated 421.0 GiB, stored 754.0 GiB -> 1.8x duplication
total $145.46/month
```

What the **one** exclusion on `_Default` is worth, measured both ways:

| | GiB ingested | $/month |
|---|---|---|
| without it | 421.0 | $185.50 |
| with it | 325.0 | $137.50 |
| **saved** | **96.0** | **$48.00** |

**Two rules:**

- **Routing** to GCS / BigQuery / Pub/Sub costs nothing *for the routing itself*. You pay the
  **destination**. Ingestion into a Cloud **Logging** bucket is the charge, and the **first 50 GiB
  per project per month is free**.
- To reduce the **Logging** bill you must **exclude at ingestion** — which is what those two lines
  measure. Routing the same logs somewhere cheaper **adds** a copy; it never removes one, which is
  why 1.8× more data is stored than was generated.

**Note which entry dominates: the Data Access audit log, at 300 of 421 GiB.** That is the log type
§1 said was off by default. Somebody turned it on, and this is the month after.

**Retention:** `_Required` is 400 days and fixed. `_Default` is 30 days and **can** be changed —
custom log buckets go up to **3650 days**, and retention beyond the default is chargeable.

An **aggregated sink** at a folder or organization with `includeChildren` captures logs from every
project beneath it. That is the answer to *"centralise logs from all projects"* — **one sink above
them**, not one sink configured in each.

## 4. Metrics: free from the hypervisor vs the Ops Agent 📝

Google can see a VM from the outside without any cooperation from it. **It cannot see inside it.**

| free, no agent | requires the **Ops Agent** in the guest |
|---|---|
| CPU utilisation, network bytes in/out, disk read/write bytes and operations, uptime | **memory utilisation**, **disk space used/free**, swap, per-process metrics, and **all application and syslog logs from the VM** |

> **Memory and disk usage are the two that are always in the question.** *"Alert when a VM runs out
> of memory"* **always** requires installing the Ops Agent first. There is no way to get it from
> outside, and a dashboard with no memory metric is this, not a bug.

The Ops Agent replaced the older separate Monitoring and Logging agents; it does both.

**Custom metrics** are for anything the platform doesn't emit — queue depth, orders per minute.
**Log-based metrics** are the other route: count log entries matching a filter, turn that count into
a metric.

## 5. Alerting policies — a real evaluator 🔬

**The model:** 360 minutes of CPU, seed 11. Noise around 38%, **five brief spikes of 1–3 minutes** (a
deploy, a GC pause, a batch job), and **one real incident of 22 minutes at ~88%** starting at minute
300. Threshold 80%.

**32 of 360 minutes are above 80%.**

| duration setting | alerts fired | real incident caught | time to alert |
|---|---|---|---|
| 1 min | **6** | True | 0 min |
| 2 min | 4 | True | 1 min |
| 3 min | 3 | True | 2 min |
| **5 min** | **1** | **True** | **4 min** |
| 10 min | 1 | True | 9 min |
| 15 min | 1 | True | 14 min |
| **25 min** | **0** | **False** | **never** |

**At a 1-minute duration the policy fired 6 times and only one was real.** That is not a sensitive
alert, it is an alert nobody reads by Thursday.

The first setting that fires **once** and still catches the incident is **5 minutes**, at a cost of
**4 minutes of detection delay**. At **25 minutes** the policy **misses the incident entirely** —
the outage lasted 22 minutes, so the window never completed.

> **The duration is not a sensitivity knob, it is a bet on how long your incidents last.** Too short
> and you train people to ignore the pager; too long and you cannot detect anything shorter than the
> window. And the duration is a **floor on time-to-detect** — you can never be told faster than you
> asked to wait.

The other parts of a policy, which the exam names by name:

| | |
|---|---|
| **Condition** | the metric, threshold, **duration**, and the **aligner** (how raw points reduce to one value per period) |
| **Notification channel** | email, SMS, Pub/Sub, Slack, PagerDuty, webhook. Configured **separately** and attached — **a policy with no channel fires silently** |
| **Auto-close** | how long after the condition clears the incident closes |

## 6. Uptime checks, and what an availability target costs

An **uptime check** polls a public endpoint from **multiple global locations**. Two things it gives
you that a metric does not: it tests from **outside your project**, so it catches a broken load
balancer or DNS, and it distinguishes *"down for everyone"* from *"down from Europe"*.

| target | per day | per month | per year |
|---|---|---|---|
| 99.0% | 14.4 min | 7.2 hr | 3.6 days |
| 99.5% | 7.2 min | 3.6 hr | 1.8 days |
| **99.9%** | 1.4 min | **43.2 min** | 8.8 hr |
| 99.95% | 0.7 min | 21.6 min | 4.4 hr |
| 99.99% | 0.1 min | 4.3 min | 52.6 min |
| 99.999% | 0.0 min | 0.4 min | 5.3 min |

**Read the 99.9% row against §5.** That target allows 43.2 minutes a month. The alerting policy that
fired exactly once took **4 minutes to notice — 9% of the whole month's budget, spent before anyone
starts working.** The incident itself ran 22 minutes: **51% of the budget in a single event.**

> So the useful question is never *"what uptime do we want"* — everyone wants five nines — but
> **"how long may one incident last"**, and that number has to cover detect, page, wake up, diagnose
> and fix.

## 7. The rest of the suite 📝

| | |
|---|---|
| **Cloud Monitoring** | metrics, dashboards, alerting, uptime checks. A **metrics scope** can span several projects — one dashboard for an environment spread over many |
| **Cloud Logging** | ingestion, the Log Router, log buckets, Logs Explorer, log-based metrics |
| **Error Reporting** | groups identical stack traces into one issue and counts them. Free, on by default for several runtimes |
| **Cloud Trace** | latency, distributed across services |
| **Cloud Profiler** | continuous CPU and memory profiling in production, very low overhead |

> **Trace** tells you *which service* is slow; **Profiler** tells you *which code* is slow; **Error
> Reporting** tells you *what is failing*; **Logging** tells you *what happened*; **Monitoring**
> tells you *whether it is still happening*.

## The exam angle

| the scenario says | the answer |
|---|---|
| "who deleted the instance" | **Admin Activity** audit log — already on, cannot be off |
| "who **read** the customer table" | **Data Access** audit log — and it must be **enabled** first |
| "keep audit logs 7 years" | a **sink** to Cloud Storage. `_Required` is 400 days and fixed |
| "centralise logs from every project" | an **aggregated sink** at the folder/org with `includeChildren` |
| "our logging bill is too high" | **exclude at ingestion.** Routing elsewhere adds a copy |
| "alert when a VM runs out of memory" | install the **Ops Agent** first |
| "alert on queue depth" | a **custom** or **log-based** metric |
| "we get paged constantly" | raise the **duration**, not the threshold |
| "is the site up for users in Asia" | an **uptime check** |
| "which microservice is slow" | **Cloud Trace** |
| "which function is burning CPU" | **Cloud Profiler** |
| "one dashboard across our projects" | a **metrics scope** |

## Things to try

- Change the incident length in `build_series` from 22 minutes to 8 and re-run the sweep. The
  setting that "fires once and catches it" moves, and the settings that miss it move with it.
  **There is no duration that is correct independent of your incidents.**
- Add a sixth sink routing `severity>=WARNING` to a log bucket and re-read §3. The duplication
  factor rises and the Logging bill rises with it — the only destination type where an extra copy
  costs you on the Logging line.
- Remove the `_Default` exclusion and confirm the $48/month reappears. Then try to achieve the same
  saving by routing those logs to GCS instead, and watch it not work.

## What is not demonstrated here

Not simulated, and not claimed: real log ingestion, the actual filter language (the evaluator
implements a cut-down subset — enough to route, not enough to lint your filters), real metric
collection, the Ops Agent, real alerting latency, notification delivery, MQL/PromQL, or Cloud Trace
and Profiler. The routing rules in §2 and the arithmetic in §3 and §6 are exact given their inputs;
§5 is a model whose assumptions print before the numbers.
