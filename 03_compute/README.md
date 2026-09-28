# Compute — from bare metal to scale-to-zero

> **ACE domain 2 (~30%)** — planning and implementing a cloud solution
> **Runtime:** ~5 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 03_compute/compute_spectrum.py
```

"Compute" is not one product, it is a **ladder**. Every rung hands one more responsibility to
Google and takes one more piece of control away from you. Almost every exam scenario is really
asking *which rung*.

**§2, §3 and §6 are arithmetic** — exact given their inputs. **§4 and §5 are seeded simulations**
of a model stated in full before it runs; the model is the thing to argue with, not the numbers.
**§1, §7 and §8 are documented** 📝 — there is no local proxy for a Google hypervisor.

> ⚠️ **Prices are a representative model.** Roughly `us-central1` on-demand list, not a quote, and
> they move. They exist so the *shape* of a crossover is visible.

---

## 1. The ladder 📝

| rung | you still manage | Google manages |
|---|---|---|
| **Bare Metal Solution** | the OS, everything on it, the licensing | the rack, power, network |
| **Sole-tenant nodes** | the OS, the VM, *which physical host* | the physical host |
| **Compute Engine** | the OS, patching, the image, the scaling policy | the hypervisor, live migration |
| **Managed instance group** | the image and the scaling policy | creating, healing, replacing VMs |
| **GKE Standard** | node pools, Kubernetes objects | the control plane |
| **GKE Autopilot** | Kubernetes objects | the nodes as well |
| **Cloud Run** | a container image, a concurrency setting | everything else, including zero |
| **Cloud Run functions** | a *function* | the container too |
| **App Engine standard** | code in a supported runtime | the runtime |

Two things are true all the way down:

- **What you manage, you can break, tune, and be billed for while idle.**
- **What Google manages, you cannot inspect when it misbehaves.**

The deciding questions, in the order that actually resolves scenarios:

1. Needs a specific OS, a kernel module, a host-locked licence, a GPU you pick? → **Compute Engine**
2. A container, and the team needs Kubernetes objects and that control? → **GKE**
3. A container, stateless, HTTP or event-driven? → **Cloud Run**
4. A single function reacting to one event? → **Cloud Run functions**
5. A legacy app in a supported runtime? → **App Engine**

> **"Lift and shift" in a question always means Compute Engine.** The phrase exists to tell you the
> application cannot be rewritten.

## 1b. Deploying each rung, for real

The ladder above is concepts; this is the commands. **Kept here rather than as separate
subfolders** — every other rung in `03_compute` is arithmetic or a labelled simulation with a
single script behind it, and App Engine, Cloud Run and Cloud Run functions have no honest local
proxy any more than Compute Engine's hypervisor does. Splitting them into empty subfolders would
suggest they run; they don't. The commands below are real and checked; the full set, with every
flag this repo uses, lives in
[`99_reference/CLI_REFERENCE.md` §4](../99_reference/CLI_REFERENCE.md#4-compute--03_compute).

**Compute Engine** — you build the image, you run `create`:

```bash
gcloud compute instances create web-1 --zone=us-central1-a --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud
```

**Cloud Run** — you hand over a container, Google decides how many and where:

```bash
gcloud run deploy web --source=. --region=us-central1 \
  --allow-unauthenticated --concurrency=80 --min-instances=0
```

`--source=.` builds the image for you via Cloud Build and pushes it to Artifact Registry — one
command instead of build, tag, push, deploy. `--min-instances=0` is what makes it scale to zero;
see §6 for what that trades away.

**Cloud Run functions** — one function, one trigger, nothing else to name:

```bash
gcloud run deploy hello-fn --source=. --function=handler \
  --trigger-http --region=us-central1
```

**App Engine standard** — no container at all, just `app.yaml` and your code:

```yaml
# app.yaml
runtime: python312
instance_class: F2
automatic_scaling:
  min_instances: 0
  max_instances: 10
```

```bash
gcloud app deploy app.yaml --version=v2         # NEW version, old one keeps serving
gcloud app services set-traffic default --splits=v2=0.1,v1=0.9   # canary
gcloud app services set-traffic default --splits=v2=1            # promote
gcloud app versions list
gcloud app versions delete v1                   # only after nothing points at it
```

**The versions-and-traffic-split model is App Engine's whole story**, and it is the answer
whenever a scenario says *"gradually shift traffic to a new version with no new infrastructure"* —
Cloud Run has an equivalent (`gcloud run services update-traffic`), but App Engine is where the
exam introduced the idea and still tests it most directly.

**GKE** has no `deploy` command of its own here — see [`04_kubernetes`](../04_kubernetes/README.md),
which runs a real cluster rather than documenting one.

## 2. Machine families and the ratio that decides the shape

```
e2 - standard - 4
|    |          |
|    |          vCPU count
|    the vCPU:memory RATIO
the series
```

| series | GB per vCPU | an 8-vCPU machine gets |
|---|---|---|
| `highcpu` | 1 | 8 GB |
| `standard` | 4 | 32 GB |
| `highmem` | 8 | 64 GB |

| family | the one word that picks it |
|---|---|
| **E2** | cheapest general purpose. No local SSD, no GPUs |
| **N2/N2D** | balanced general purpose (N2D is AMD) |
| **N4/C4** | the current generations |
| **C2/C3** | **compute** optimised — high sustained clock |
| **M1/M2/M3** | **memory** optimised — the question usually says *SAP HANA* or *in-memory* |
| **A2/A3/G2** | **accelerator** optimised — GPUs are attached, not added |
| **T2D/T2A** | scale-**out**. T2A is Arm, which means recompiling |

Shared-core (`e2-micro`, `e2-small`, `e2-medium`) share a physical core and **burst** — fine for a
jump host, wrong for anything with a latency target.

## 3. Predefined vs custom — the cost of rounding up

```
workload                 needs   smallest predefined      $/hr   custom            $/hr
----------------------------------------------------------------------------------------
web frontend         2v    4GB   n2-standard-2        $ 0.0971   2v 4GB        $ 0.0802
app server           4v   16GB   n2-standard-4        $ 0.1942   4v 16GB       $ 0.1942
analytics worker     6v   40GB   n2-highmem-8         $ 0.5241   6v 40GB       $ 0.3591
cache node           4v   48GB   n2-highmem-8         $ 0.5241   6v 48GB       $ 0.3930  <<
batch cruncher      16v   16GB   n2-highcpu-16        $ 0.5736   16v 16GB      $ 0.5736

predefined total  $1.9130/hr   $  1396.51/month
custom total      $1.6002/hr   $  1168.12/month
difference         16.4%          $   228.40/month
```

**The `cache node` row is the point.** A custom machine type is **not free-form**: memory must sit
between **0.5 and 8 GB per vCPU**. Asking for 48 GB on 4 vCPU is 12 GB/vCPU, over the ceiling — so
you either pay for **extended memory** or buy vCPUs you will never use. The script bumps it to 6.

> **Custom removes the ratio *steps*, not the ratio.**

Also: vCPU must be **1 or an even number**, memory a multiple of **256 MB**, and custom types exist
only on **E2/N1/N2/N2D** — not on the compute- or accelerator-optimised families.

⚠️ **Caveat on that 16.4%:** the model prices vCPU and memory linearly, so it ignores any premium
Google charges for a custom shape. Treat it as an **upper bound**.

The exam framing is simpler than the maths: **right-size first, then commit.** Committing to an
oversized shape buys a discount on waste.

## 4. Spot VMs 🔬

**The facts, which are not simulated:**

- Spot runs **60–91% below on-demand**.
- Reclaimed **at any time**, with a **30-second** termination notice.
- **No SLA**, and **cannot be live-migrated**.
- **Preemptible** VMs are the older model and are **always stopped within 24 hours**. **Spot VMs
  have no such limit** — that pair is a favourite exam distinction.

**The model:** a 10-hour batch job; preemption as a Poisson process with a mean of 4 hours; 5
minutes to restart; 2000 trials; seed 7; give up after 48 hours.

| strategy | finished | median wall | machine-hrs | cost | vs on-demand |
|---|---|---|---|---|---|
| **no checkpointing** | **74.2%** | 25.2 h | 26.7 | $3.11 | 80% |
| checkpoint / 60 min | 100.0% | 11.4 h | 11.4 | $1.32 | 34% |
| **checkpoint / 15 min** | **100.0%** | 10.5 h | 10.3 | **$1.20** | **31%** |
| on-demand, no Spot | 100.0% | 10.0 h | 10.0 | $3.88 | 100% |

**Without checkpointing, a quarter of runs never finished inside 48 hours** — and the ones that did
cost 80% of on-demand anyway, having thrown away most of the discount in repeated restarts. The
discount was never the problem; the **architecture** was.

> Spot is **a discount you unlock by making the work resumable.** Which is why the answer is never
> "use Spot to save money" — it is Spot **for** fault-tolerant batch, rendering and CI, and **never**
> for a database, a stateful server, or anything with an SLA.

## 5. Autoscaling a managed instance group 🔬

A MIG is the unit of everything operational on Compute Engine: autoscaling, autohealing, rolling
updates, and the backend of a load balancer. **A bare VM has none of that.**

**The model:** an instance serves 100 rps flat out; the autoscaler sizes to a *target utilisation*
of that; 3 minutes to boot and pass a health check, **billed from creation**; a 10-minute
scale-down stabilisation window; a 24-hour diurnal curve. Requests above real capacity are **shed**.

```
peak instances needed               6
autoscaled instance-hours        59.2
fixed-at-peak instance-hours    144.0
saving                          58.9%
requests shed during ramps          0 (0.000% of offered)
```

### Zero shed was not the expected result, and it is the finding

**A diurnal curve does not stress an autoscaler.** Load that takes hours to double moves less in 3
minutes than the 40% headroom a 60% target already leaves on every instance. The autoscaler was
late all day and it never mattered.

What breaks it is a **spike** — same day, same autoscaler, traffic ×4 for 25 minutes at 14:00:

| | instance-hrs | shed | % of offered |
|---|---|---|---|
| smooth day | 59.2 | 0 | 0.000% |
| **with a spike** | 61.1 | **17,638** | 0.165% |

All of it inside a 25-minute window. The autoscaler *did* react — 3 minutes after the damage
started, which is exactly as fast as an instance boots.

### Target utilisation is a risk dial, not an efficiency dial

| target util | instance-hrs | vs 60% | shed on spike |
|---|---|---|---|
| 50% | 71.5 | +17.0% | 17,638 |
| **60%** | 61.1 | — | 17,638 |
| 70% | 55.3 | −9.5% | 17,638 |
| 80% | 49.2 | −19.5% | 17,638 |
| **90%** | 45.9 | −24.9% | **35,638** |
| 95% | 44.7 | −26.8% | 35,638 |

From 50% → 95%: **37% fewer instance-hours and 2.0× the shed requests.** Every point you claw off
the instance bill is headroom you no longer have when the spike arrives — and **nothing in the
smooth-day numbers would have told you that.**

**The levers that actually help,** and none of them is "scale faster":

- **a smaller boot** — a baked custom image rather than a startup script that installs packages
- **min instances** above the trough, so the first ramp starts from somewhere
- **scheduled scaling** when the curve is known in advance, which on a diurnal shape it is
- scale on a metric that **leads** demand rather than CPU, which lags it

Scale-down is deliberately slower than scale-up. That asymmetry is not a bug to tune out; removing
capacity you are about to need again is how you get flapping.

**Regional (multi-zone) MIGs** spread instances across zones and are the default answer to *"survive
a zone failure"*. A zonal MIG does not.

## 6. Scale to zero — where Cloud Run stops being cheaper

**The model:** a request uses 200 ms of 1 vCPU and 512 MiB. Cloud Run bills per vCPU-second, per
GiB-second and per request **while serving**. The VM is 2 vCPU / 8 GB, billed **every hour of the
month whether or not anyone calls it**. Free tiers ignored.

| req/sec | req/month | Cloud Run | the VM | cheaper |
|---|---|---|---|---|
| 0.1 | 262,800 | $1.43 | $70.90 | Cloud Run |
| 1 | 2,628,000 | $14.32 | $70.90 | Cloud Run |
| 3 | 7,884,000 | $42.97 | $70.90 | Cloud Run |
| **5** | 13,140,000 | **$71.61** | $70.90 | **the VM** |
| 25 | 65,700,000 | $358.07 | $70.90 | the VM |
| 100 | 262,800,000 | $1,432.26 | $70.90 | the VM |

**The curves cross at 4.95 requests/second sustained** — about 13.0 million requests a month.

> **And that number is a trap if you stop there.** Three corrections, all pushing the real crossover
> *higher*:
>
> - **"Sustained" is doing the work.** A service at 20 rps for 8 hours and nothing for 16 averages
>   under 7 rps — Cloud Run bills only the 8, the VM bills all 24.
> - **One VM is not a deployment.** No redundancy, no health check, no rolling update. Compare
>   against a MIG of at least two across zones and the VM line doubles.
> - **The VM bill is not the cost.** Someone patches that OS. Cloud Run has no OS you can patch.

So: **bursty, spiky or unknown traffic → Cloud Run**, where scale-to-zero is worth more than the
unit price. **Steady high throughput you can keep genuinely busy → instances**, with a committed use
discount on top (see `08_billing_cost`).

Cloud Run's own levers: **concurrency** (how many requests one container handles at once — the
biggest cost knob, and the one people leave at the default), **min instances** to buy away cold
starts, **max instances** to cap a runaway bill.

## 7. Disks, images and the instance lifecycle 📝

**The boot disk is deleted with the instance by default.** The checkbox that saves people is *keep
disk*.

| | |
|---|---|
| `pd-standard` | HDD. Cheap, sequential, archival |
| `pd-balanced` | SSD, the sane default |
| `pd-ssd` | higher IOPS per GB |
| `pd-extreme` / Hyperdisk | provisioned IOPS, for databases that need a floor |
| **Local SSD** | physically attached, fastest, and **ephemeral** — gone when the instance stops. Scratch and caches only. **Exam favourite** |

**Persistent disk performance scales with size.** "The disk is slow" is often "the disk is small";
resizing up is online, shrinking is not possible.

| | |
|---|---|
| **Snapshot** | incremental, of a disk. Backup and restore |
| **Machine image** | the whole instance — disks, metadata, config. Cloning a VM |
| **Custom image** | a boot disk to launch new instances from — the one that shortens the boot in §5 |

**Live migration** moves a running VM off a host Google needs to service, with no reboot. On by
default, and **not available for Spot VMs or instances with GPUs**.

**Stopped instances** are not billed for vCPU or memory, but **are** billed for their disks and any
reserved static IP.

**Metadata and startup scripts** configure a VM at boot; the metadata server is also how an instance
gets its service account token — the mechanism behind *"attach a service account instead of
downloading a key"* in [`02_iam`](../02_iam/README.md).

## 8. Sole-tenant and Bare Metal 📝

| | |
|---|---|
| **Sole-tenant nodes** | your VMs alone on a physical host nobody else shares. Two reasons, and they are the two the exam uses: **licensing counted per physical core**, or a **compliance rule about physical isolation**. You are paying for the host, not the instances |
| **Bare Metal Solution** | actual physical servers in a Google facility, connected to your VPC. It exists for workloads that cannot be virtualised at all — classically Oracle. **Not** a general answer to "we want more performance" |

**Confidential VMs** are a different axis entirely: memory encrypted **in use**, so the hypervisor
cannot read it. That is confidentiality, not tenancy — do not confuse the two.

## The exam angle

| the scenario says | the answer |
|---|---|
| "lift and shift", "cannot be rewritten", "needs a specific OS" | **Compute Engine** |
| "containers, and the team wants Kubernetes" | **GKE** (Autopilot unless they ask to manage nodes) |
| "stateless container, HTTP, spiky traffic" | **Cloud Run** |
| "run code when a file lands in a bucket" | **Cloud Run functions** |
| "fault-tolerant batch, cost is the priority" | **Spot VMs**, with checkpointing |
| "must run for exactly 24 hours" | **not preemptible** — those are stopped within 24 h |
| "survive a zone failure" | **regional** managed instance group |
| "licence counted per physical core" | **sole-tenant nodes** |
| "memory must be encrypted in use" | **Confidential VM** |
| "fastest possible scratch disk" | **Local SSD** — and accept that it is ephemeral |
| "the instance is gone but we need the data" | only if **keep boot disk** was set. Otherwise it is gone |
| "scaling is too slow" | a **baked image** and **min instances**, not a faster autoscaler |

## Things to try

- Set `mtbp` in §4 to 1.0 hour — shorter than the checkpoint benefit — and watch even the
  15-minute strategy start failing. There is a preemption rate above which Spot is not a discount
  at any architecture.
- Set `SPIKE_MULTIPLIER` to 2.0 and find the multiplier at which shed first appears. That number is
  your real headroom, expressed in traffic rather than percent.
- Give `simulate_autoscaler` a `min_instances` above the trough and re-read both columns. It costs
  money every hour of the night and it is often still the right call.

## What is not demonstrated here

Not simulated, and not claimed: real VM provisioning or boot, actual preemption behaviour, real CPU
or disk performance, GKE scheduling, Cloud Run cold-start latency, or any real billing. The
arithmetic in §2, §3 and §6 is exact given its inputs; §4 and §5 are models whose assumptions are
printed before the numbers; §1, §7 and §8 are documented.
