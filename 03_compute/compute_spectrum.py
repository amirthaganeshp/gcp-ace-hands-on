"""Compute: the spectrum from bare metal to scale-to-zero, and what each step costs.

"Compute" on Google Cloud is not one product, it is a LADDER. Every rung
hands one more responsibility to Google and takes one more piece of control
away from you. Picking the right rung is most of ACE domain 2 (~30%), and
almost every exam scenario is really asking "which rung".

  1. The ladder, and what you stop managing at each step
  2. Machine families, and the vCPU:memory ratio that decides the shape
  3. Predefined vs custom machine types - the cost of rounding up
  4. Spot VMs: the discount, and what it actually costs you    [simulated]
  5. Autoscaling a managed instance group                      [simulated]
  6. Scale to zero: where Cloud Run stops being cheaper        [modelled]
  7. Disks, images and the instance lifecycle
  8. Sole-tenant and Bare Metal Solution - the bottom rung

SECTIONS 2, 3 AND 6 ARE ARITHMETIC and exact given their inputs.
SECTIONS 4 AND 5 ARE SEEDED SIMULATIONS of a model that is stated in full
before it runs - they are labelled, and the model is the thing to argue
with, not the numbers.
SECTIONS 1, 7 AND 8 ARE DOCUMENTED - there is no local proxy for a Google
hypervisor.

PRICES ARE A REPRESENTATIVE MODEL. They are roughly us-central1 on-demand
list, they are not a quote, and they move. They are here so the SHAPE of a
crossover is visible; for a real figure use the pricing calculator.

Run:
    python 03_compute/compute_spectrum.py

Concept reference: ACE domain 2 (~30%) - planning and implementing.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"
SEED = 7

# ---------------------------------------------------------------------------
# REPRESENTATIVE PRICES - a model, not a quote. See the docstring.
# ---------------------------------------------------------------------------
VCPU_HOUR = 0.031611          # general-purpose vCPU, on-demand
GB_HOUR = 0.004237            # general-purpose memory, on-demand
SPOT_MULTIPLIER = 0.30        # Spot runs 60-91% below on-demand; 70% off here
RUN_VCPU_SEC = 0.000024       # Cloud Run, per vCPU-second while serving
RUN_GIB_SEC = 0.0000025       # Cloud Run, per GiB-second while serving
RUN_PER_REQUEST = 0.40 / 1e6  # Cloud Run, per request

# vCPU:memory ratios. These ARE the machine type families.
RATIOS = {"highcpu": 1.0, "standard": 4.0, "highmem": 8.0}


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def vm_hourly(vcpu: float, gb: float, spot: bool = False) -> float:
    """On-demand hourly cost of a shape, before any discount programme."""
    price = vcpu * VCPU_HOUR + gb * GB_HOUR
    return price * (SPOT_MULTIPLIER if spot else 1.0)


def custom_shape(vcpu: int, gb: float) -> tuple[int, float, str]:
    """The smallest LEGAL custom machine type for a requirement.

    Custom types are not free-form. The rules that bite:
      - vCPU count must be 1, or an EVEN number.
      - Memory must be a multiple of 256 MB.
      - Memory must be between 0.5 GB and 8 GB PER vCPU. Going above the
        8 GB/vCPU ceiling is "extended memory", which is allowed but priced
        separately - so in practice you add vCPUs you do not need instead.
      - Only some series offer custom at all (E2, N1, N2, N2D). The
        compute- and accelerator-optimised families do not.
    """
    cores = vcpu if vcpu == 1 else vcpu + (vcpu % 2)
    note = ""
    ceiling = cores * 8.0
    if gb > ceiling:
        needed = math.ceil(gb / 8.0)
        cores = needed if needed == 1 else needed + (needed % 2)
        note = f"+{cores - vcpu}v for the 8GB/vCPU ceiling"
    mem = math.ceil(gb * 4) / 4          # round up to a 256 MB multiple
    return cores, mem, note


# ---------------------------------------------------------------------------
# 4. Spot preemption model
# ---------------------------------------------------------------------------
@dataclass
class SpotResult:
    finished: bool
    wall_hours: float
    machine_hours: float
    preemptions: int
    wasted_hours: float


def run_spot_job(rng: random.Random, work_hours: float, mtbp_hours: float,
                 checkpoint_minutes: float | None, restart_minutes: float,
                 give_up_hours: float) -> SpotResult:
    """One batch job on a Spot VM, under an EXPLICIT model.

    THE MODEL, which is the part worth arguing with:
      - Preemption arrives as a Poisson process with mean time `mtbp_hours`.
        Real Spot reclamation is driven by Google's capacity, not by a clock,
        so this is a stand-in for "it happens, unpredictably".
      - On preemption the instance dies. Restarting costs `restart_minutes`.
      - With checkpointing, work resumes from the last checkpoint, so at most
        one checkpoint interval is lost. Without it, the job restarts from
        zero.
      - Checkpoint writes themselves are assumed free. They are not, but they
        are small next to the loss they prevent.
    """
    done = 0.0            # work completed and durably checkpointed
    progress = 0.0        # work completed since the last checkpoint
    wall = 0.0
    machine = 0.0
    preemptions = 0
    wasted = 0.0

    while done + progress < work_hours and wall < give_up_hours:
        remaining = work_hours - done - progress
        time_to_preempt = rng.expovariate(1.0 / mtbp_hours)

        if time_to_preempt >= remaining:          # the job finishes first
            wall += remaining
            machine += remaining
            progress += remaining
            break

        # preempted mid-flight
        wall += time_to_preempt
        machine += time_to_preempt
        progress += time_to_preempt
        preemptions += 1

        if checkpoint_minutes is None:
            wasted += progress                    # everything since the start
            progress = 0.0
        else:
            interval = checkpoint_minutes / 60.0
            kept = math.floor(progress / interval) * interval
            wasted += progress - kept
            done += kept
            progress = 0.0

        wall += restart_minutes / 60.0            # waiting for capacity again

    finished = done + progress >= work_hours - 1e-9
    return SpotResult(finished, wall, machine, preemptions, wasted)


# ---------------------------------------------------------------------------
# 5. Managed instance group autoscaler model
# ---------------------------------------------------------------------------
SPIKE_START_MIN = 14 * 60          # 14:00
SPIKE_LENGTH_MIN = 25
SPIKE_MULTIPLIER = 4.0


def diurnal_load(minute: int, spike: bool = False) -> float:
    """Requests per second across a day. Quiet night, two daytime humps.

    With `spike`, a flash event lands at 14:00 - the marketing email, the
    front page, the thing nobody told operations about.
    """
    hour = minute / 60.0
    base = 40.0
    morning = 260.0 * math.exp(-((hour - 10.5) ** 2) / 6.0)
    evening = 200.0 * math.exp(-((hour - 19.0) ** 2) / 5.0)
    load = base + morning + evening
    if spike and SPIKE_START_MIN <= minute < SPIKE_START_MIN + SPIKE_LENGTH_MIN:
        load *= SPIKE_MULTIPLIER
    return load


def simulate_autoscaler(rps_per_instance: float, target_util: float,
                        boot_minutes: int, scale_down_stabilise: int,
                        minutes: int = 1440, min_instances: int = 1,
                        spike: bool = False) -> dict:
    """A MIG autoscaler, per minute, under an EXPLICIT model.

    THE MODEL:
      - An instance can physically serve `rps_per_instance`. The autoscaler
        SIZES for `target_util` of that, so a target of 0.6 deliberately
        leaves 40% headroom on every instance.
      - A new instance takes `boot_minutes` to become healthy and serve, and
        is BILLED from the moment it is created. That lag is the point of
        the section.
      - Scale-DOWN waits `scale_down_stabilise` minutes before removing
        anything. Google's real stabilisation window is 10 minutes and the
        asymmetry is deliberate: scaling up fast is cheap insurance,
        scaling down fast causes flapping.
      - Requests above real serving capacity are counted as SHED. A real
        system queues some of them, so this is the pessimistic reading.
    """
    serving = min_instances
    pending: list[int] = []          # boot-completion minutes
    below_since: int | None = None
    trace_load, trace_serving, trace_target = [], [], []
    shed = 0.0
    offered = 0.0
    instance_minutes = 0

    for m in range(minutes):
        # 1. instances that finished booting are now serving
        matured = [t for t in pending if t <= m]
        serving += len(matured)
        pending = [t for t in pending if t > m]

        # 2. what actually happened to this minute's traffic
        load = diurnal_load(m, spike)
        capacity = serving * rps_per_instance         # REAL capacity, not target
        offered += load * 60
        if load > capacity:
            shed += (load - capacity) * 60

        # 3. what the autoscaler wants, sized to the target utilisation
        desired = max(min_instances,
                      math.ceil(load / (rps_per_instance * target_util)))
        in_flight = serving + len(pending)

        if desired > in_flight:
            for _ in range(desired - in_flight):
                pending.append(m + boot_minutes)
            below_since = None
        elif desired < in_flight:
            if below_since is None:
                below_since = m
            elif m - below_since >= scale_down_stabilise:
                serving = max(desired, min_instances)
                pending = []
                below_since = None
        else:
            below_since = None

        # 4. you are billed for booting instances too
        instance_minutes += serving + len(pending)
        trace_load.append(load)
        trace_serving.append(serving)
        trace_target.append(desired)

    peak = max(trace_target)
    return {
        "instance_hours": instance_minutes / 60.0,
        "fixed_instance_hours": peak * minutes / 60.0,
        "peak": peak,
        "shed": shed,
        "offered": offered,
        "load": trace_load,
        "serving": trace_serving,
        "desired": trace_target,
    }


def main() -> None:
    print("COMPUTE - FROM BARE METAL TO SCALE TO ZERO")

    # ---------------------------------------------------------- 1. the ladder
    rule("1. THE LADDER   [documented]")
    print("""  Every rung hands one more responsibility to Google. Reading it
  downward is "more control"; reading it upward is "less to run".

    rung                     you still manage          Google manages
    --------------------------------------------------------------------
    Bare Metal Solution      the OS, everything on     the rack, power,
                             it, and the licensing     the network
    Sole-tenant nodes        the OS, the VM, WHICH     the physical host
                             physical host it uses
    Compute Engine           the OS, patching, the     the hypervisor,
                             image, scaling policy     live migration
    Managed instance group   the image and the         creating, healing
                             scaling policy            and replacing VMs
    GKE Standard             the node pools, the       the control plane
                             Kubernetes objects
    GKE Autopilot            the Kubernetes objects    the nodes as well
    Cloud Run                a container image and     everything else,
                             a concurrency setting     including zero
    Cloud Run functions      a FUNCTION                the container too
    App Engine standard      code in a supported       the runtime
                             runtime

  TWO THINGS ARE TRUE ALL THE WAY DOWN:
    - What you manage, you can break, tune and be billed for while idle.
    - What Google manages, you cannot inspect when it misbehaves.

  THE DECIDING QUESTIONS, in the order that actually resolves scenarios:
    1. Does it need a specific OS, a kernel module, a licence tied to a
       host, or a GPU you pick?          -> Compute Engine (or lower)
    2. Is it a container, and does the team already run Kubernetes
       objects and need that control?    -> GKE
    3. Is it a container, stateless, HTTP or event driven?  -> Cloud Run
    4. Is it a single function reacting to one event?   -> Run functions
    5. Is it a legacy app in a supported runtime?       -> App Engine

  "LIFT AND SHIFT" IN A QUESTION ALWAYS MEANS COMPUTE ENGINE. The phrase
  exists to tell you the application cannot be rewritten.""")

    # ------------------------------------------------- 2. families and ratios
    rule("2. MACHINE FAMILIES, AND THE RATIO THAT DECIDES THE SHAPE")
    print("  A machine type is a FAMILY, a SERIES and a SHAPE:\n")
    print("      e2 - standard - 4")
    print("      |    |          |")
    print("      |    |          vCPU count")
    print("      |    the vCPU:memory RATIO")
    print("      the series\n")
    print(f"  {'series':<12} {'GB per vCPU':>12}   an 8-vCPU machine gets")
    print("  " + "-" * 52)
    for name, gb in RATIOS.items():
        print(f"  {name:<12} {gb:>12.0f}   {8 * gb:>5.0f} GB")

    print("""
  THE FAMILIES, and the one word that picks each:

    E2      cheapest general purpose. No local SSD, no GPUs.
    N2/N2D  balanced general purpose. N2D is AMD.
    N4/C4   the current general-purpose and balanced generations.
    C2/C3   COMPUTE optimised - high sustained clock. Gaming servers,
            single-threaded HPC, ad serving.
    M1/M2/M3 MEMORY optimised - hundreds of GB to TBs. The word in the
            question is usually SAP HANA or "in-memory database".
    A2/A3/G2 ACCELERATOR optimised - GPUs are attached, not added.
    T2D/T2A scale-OUT. T2A is Arm, which means recompiling.

  Shared-core (e2-micro, e2-small, e2-medium) share a physical core and
  BURST. Fine for a jump host, wrong for anything with a latency target.""")

    # ------------------------------------------------ 3. custom machine types
    rule("3. PREDEFINED vs CUSTOM - the cost of rounding up")
    workloads = [
        ("web frontend",     2, 4),
        ("app server",       4, 16),
        ("analytics worker", 6, 40),
        ("cache node",       4, 48),
        ("batch cruncher",  16, 16),
    ]
    print(f"  {'workload':<18} {'needs':>11}   {'smallest predefined':<20} "
          f"{'$/hr':>8}   {'custom':<13} {'$/hr':>8}")
    print("  " + "-" * 88)
    waste_rows = []
    notes = []
    for name, vcpu, gb in workloads:
        # smallest predefined shape that fits BOTH dimensions
        best = None
        for series, ratio in RATIOS.items():
            cores = max(vcpu, math.ceil(gb / ratio))
            cores = 2 ** math.ceil(math.log2(max(cores, 1)))  # shapes go 1,2,4,8..
            shape_gb = cores * ratio
            cost = vm_hourly(cores, shape_gb)
            if best is None or cost < best[0]:
                best = (cost, f"n2-{series}-{cores}", cores, shape_gb)
        pre_cost, label, cores, shape_gb = best
        c_cpu, c_gb, note = custom_shape(vcpu, gb)
        cus_cost = vm_hourly(c_cpu, c_gb)
        waste_rows.append((name, cus_cost, pre_cost))
        if note:
            notes.append((name, note))
        print(f"  {name:<18} {vcpu:>3}v{gb:>5.0f}GB   {label:<20} "
              f"${pre_cost:>7.4f}   {f'{c_cpu}v {c_gb:.0f}GB':<13} ${cus_cost:>7.4f}"
              f"{'  <<' if note else ''}")

    tot_pre = sum(c for _, _, c in waste_rows)
    tot_cus = sum(c for _, c, _ in waste_rows)
    print(f"\n  predefined total  ${tot_pre:.4f}/hr   ${tot_pre * 730:>9.2f}/month")
    print(f"  custom total      ${tot_cus:.4f}/hr   ${tot_cus * 730:>9.2f}/month")
    print(f"  difference        {(tot_pre - tot_cus) / tot_pre * 100:>5.1f}%"
          f"          ${(tot_pre - tot_cus) * 730:>9.2f}/month\n")
    for name, note in notes:
        print(f"  <<  {name}: {note}")
    if notes:
        print("\n  THAT ROW IS THE POINT. A custom machine type is not free-form:")
        print("  memory must sit between 0.5 and 8 GB PER vCPU. Asking for")
        print("  48 GB on 4 vCPU is 12 GB/vCPU, which is over the ceiling, so")
        print("  you either pay for EXTENDED MEMORY or buy vCPUs you will")
        print("  never use. Custom removes the ratio STEPS, not the ratio.")
    print("\n  Two more constraints worth knowing: vCPU must be 1 or an EVEN")
    print("  number, memory must be a multiple of 256 MB, and custom types")
    print("  exist only on E2/N1/N2/N2D - not on the compute- or")
    print("  accelerator-optimised families.")
    print("\n  CAVEAT ON THAT PERCENTAGE: this model prices vCPU and memory")
    print("  linearly, so it ignores any premium Google charges for a custom")
    print("  shape over the equivalent predefined one. Treat the saving as an")
    print("  UPPER BOUND and check the calculator before promising it.")
    print("\n  The exam framing is simpler than the maths: RIGHT-SIZE FIRST,")
    print("  then commit. Committing to an oversized shape buys a discount on")
    print("  waste. Recommender surfaces the right-size suggestions for you.")

    # ------------------------------------------------------------- 4. Spot
    rule("4. SPOT VMs - the discount, and what it actually costs   [simulated]")
    print("  THE FACTS FIRST, which are not simulated:")
    print("    - Spot VMs run 60-91% below on-demand.")
    print("    - They can be reclaimed AT ANY TIME, with a 30-second")
    print("      termination notice, when Google wants the capacity.")
    print("    - They carry NO SLA and cannot be live-migrated.")
    print("    - PREEMPTIBLE VMs are the older model and are always stopped")
    print("      within 24 HOURS. SPOT VMs have no such limit - that pair is")
    print("      a favourite exam distinction.\n")

    work = 10.0            # hours of actual computation
    mtbp = 4.0             # mean time between preemptions, MODELLED
    trials = 2000
    print(f"  MODEL: a {work:.0f}-hour batch job, preemption as a Poisson process")
    print(f"  with a mean of {mtbp:.0f} hours, 5 minutes to restart, {trials} trials,")
    print(f"  seed {SEED}. Give up after 48 hours.\n")

    scenarios = [
        ("no checkpointing", None),
        ("checkpoint / 60 min", 60.0),
        ("checkpoint / 15 min", 15.0),
    ]
    on_demand_cost = vm_hourly(8, 32) * work
    print(f"  {'strategy':<22} {'finished':>9} {'median wall':>12} "
          f"{'machine-hrs':>12} {'cost':>9} {'vs on-demand':>13}")
    print("  " + "-" * 82)
    spot_rows = []
    for label, ckpt in scenarios:
        rng = random.Random(SEED)
        results = [run_spot_job(rng, work, mtbp, ckpt, 5.0, 48.0)
                   for _ in range(trials)]
        ok = [r for r in results if r.finished]
        rate = len(ok) / trials * 100
        walls = sorted(r.wall_hours for r in ok) or [float("nan")]
        median = walls[len(walls) // 2]
        mh = sum(r.machine_hours for r in ok) / max(len(ok), 1)
        cost = vm_hourly(8, 32, spot=True) * mh
        spot_rows.append((label, rate, median, mh, cost))
        print(f"  {label:<22} {rate:>8.1f}% {median:>11.1f}h {mh:>12.1f} "
              f"${cost:>8.2f} {cost / on_demand_cost * 100:>12.0f}%")
    print(f"  {'on-demand, no Spot':<22} {100.0:>8.1f}% {work:>11.1f}h "
          f"{work:>12.1f} ${on_demand_cost:>8.2f} {100:>12.0f}%")

    nockpt = spot_rows[0]
    best = spot_rows[-1]
    print(f"\n  WITHOUT CHECKPOINTING, {nockpt[1]:.1f}% of runs finished inside 48")
    print("  hours - the job kept losing everything and starting again. The")
    print("  discount was never the problem; the ARCHITECTURE was.")
    print(f"\n  WITH 15-MINUTE CHECKPOINTS, {best[1]:.1f}% finished, at "
          f"{best[4] / on_demand_cost * 100:.0f}% of the")
    print("  on-demand cost. That is the whole Spot proposition: it is a")
    print("  discount you unlock by making the work RESUMABLE.")
    print("\n  Which is why the exam answer is never just 'use Spot to save")
    print("  money'. It is Spot FOR fault-tolerant batch, rendering, CI, and")
    print("  never for a database, a stateful server, or anything with an SLA.")

    # ------------------------------------------------------ 5. autoscaling
    rule("5. AUTOSCALING A MANAGED INSTANCE GROUP   [simulated]")
    print("  A MIG is the unit of everything operational on Compute Engine:")
    print("  autoscaling, autohealing, rolling updates, and the backend of a")
    print("  load balancer. A bare VM has none of that.\n")
    print("  MODEL: an instance serves 100 rps flat out; the autoscaler sizes")
    print("  to a TARGET UTILISATION of that; 3 minutes to boot and pass a")
    print("  health check, billed from creation; a 10-minute scale-down")
    print("  stabilisation window; a 24-hour diurnal load curve. Requests")
    print("  above real capacity are counted as shed.\n")
    sim = simulate_autoscaler(rps_per_instance=100.0, target_util=0.6,
                              boot_minutes=3, scale_down_stabilise=10)
    saving = 1 - sim["instance_hours"] / sim["fixed_instance_hours"]
    print(f"  peak instances needed        {sim['peak']:>8}")
    print(f"  autoscaled instance-hours    {sim['instance_hours']:>8.1f}")
    print(f"  fixed-at-peak instance-hours {sim['fixed_instance_hours']:>8.1f}")
    print(f"  saving                       {saving * 100:>7.1f}%")
    print(f"  requests shed during ramps   {sim['shed']:>8,.0f} "
          f"({sim['shed'] / sim['offered'] * 100:.3f}% of offered)\n")
    print(f"  AUTOSCALING SAVED {saving * 100:.0f}% AND SHED "
          f"{sim['shed'] / sim['offered'] * 100:.3f}% OF REQUESTS.")
    print("\n  ZERO SHED WAS NOT THE EXPECTED RESULT, and it is the finding.")
    print("  A DIURNAL CURVE DOES NOT STRESS AN AUTOSCALER. Load that takes")
    print("  hours to double moves less in 3 minutes than the 40% headroom a")
    print("  60% utilisation target already leaves on every instance. The")
    print("  autoscaler was late all day and it never mattered.")

    # --------------------------------- 5b. what actually breaks an autoscaler
    print(f"\n  What breaks it is a SPIKE. Same day, same autoscaler, but at")
    print(f"  {SPIKE_START_MIN // 60}:00 traffic jumps {SPIKE_MULTIPLIER:.0f}x for "
          f"{SPIKE_LENGTH_MIN} minutes - the marketing")
    print("  email, the front page, the thing nobody told operations about:\n")
    spiked = simulate_autoscaler(100.0, 0.6, 3, 10, spike=True)
    print(f"  {'':<14} {'instance-hrs':>13} {'shed':>12} {'% of offered':>13}")
    print("  " + "-" * 56)
    print(f"  {'smooth day':<14} {sim['instance_hours']:>13.1f} "
          f"{sim['shed']:>12,.0f} {sim['shed'] / sim['offered'] * 100:>12.3f}%")
    print(f"  {'with a spike':<14} {spiked['instance_hours']:>13.1f} "
          f"{spiked['shed']:>12,.0f} "
          f"{spiked['shed'] / spiked['offered'] * 100:>12.3f}%")
    print(f"\n  {spiked['shed']:,.0f} requests shed, all of them inside a "
          f"{SPIKE_LENGTH_MIN}-minute window.")
    print("  The autoscaler did react - it just reacted 3 minutes after the")
    print("  damage started, which is exactly as fast as an instance boots.")

    # --------------------------- 5c. the utilisation target is a risk dial
    print("\n  Now raise the utilisation target, which is the knob everyone")
    print("  reaches for when the instance bill arrives:\n")
    print(f"  {'target util':>11} {'instance-hrs':>13} {'vs 60%':>8} "
          f"{'shed on spike':>15} {'% of offered':>13}")
    print("  " + "-" * 65)
    util_rows = []
    for target in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        s = simulate_autoscaler(100.0, target, 3, 10, spike=True)
        pct = s["shed"] / s["offered"] * 100
        util_rows.append((target, s["instance_hours"], pct))
        print(f"  {target:>10.0%} {s['instance_hours']:>13.1f} "
              f"{s['instance_hours'] / spiked['instance_hours'] - 1:>+7.1%} "
              f"{s['shed']:>15,.0f} {pct:>12.3f}%")
    cheap = util_rows[-1]
    safe = util_rows[0]
    print(f"\n  From 50% to 95% target: {(1 - cheap[1] / safe[1]) * 100:.0f}% fewer "
          f"instance-hours, and")
    if cheap[2] > 0 and safe[2] > 0:
        print(f"  {cheap[2] / safe[2]:.1f}x the shed requests.")
    else:
        print(f"  shed went from {safe[2]:.3f}% to {cheap[2]:.3f}% of offered.")
    print("\n  TARGET UTILISATION IS NOT AN EFFICIENCY DIAL, IT IS A RISK DIAL.")
    print("  Every point you claw back off the instance bill is headroom you")
    print("  no longer have when the spike arrives. Nothing in the smooth-day")
    print("  numbers would have told you that.")
    print("\n  THE LEVERS THAT ACTUALLY HELP, and none of them is 'scale faster':")
    print("    - a smaller boot: a baked image (Packer / custom image) rather")
    print("      than a startup script that installs packages")
    print("    - MIN INSTANCES above the trough, so the first ramp starts")
    print("      from somewhere")
    print("    - scheduled scaling when the curve is known in advance, which")
    print("      on a diurnal shape like this one it is")
    print("    - scale on a metric that LEADS demand rather than CPU, which")
    print("      lags it")
    print("\n  Scale-down is deliberately slower than scale-up. That asymmetry")
    print("  is not a bug to tune out; removing capacity you are about to")
    print("  need again is how you get flapping.")
    print("\n  Regional (multi-zone) MIGs spread instances across zones and")
    print("  are the default answer to 'survive a zone failure'. A zonal MIG")
    print("  does not.")

    # ------------------------------------------------------ 6. scale to zero
    rule("6. SCALE TO ZERO - where Cloud Run stops being cheaper   [modelled]")
    print("  MODEL: a request uses 200 ms of 1 vCPU and 512 MiB. Cloud Run is")
    print("  billed per vCPU-second, per GiB-second and per request while")
    print("  SERVING. The VM is a 2-vCPU/8 GB instance billed every hour of")
    print("  the month whether or not anyone calls it. Free tiers ignored.\n")

    per_request = (0.2 * RUN_VCPU_SEC) + (0.2 * 0.5 * RUN_GIB_SEC) + RUN_PER_REQUEST
    vm_month = vm_hourly(2, 8) * 730
    print(f"  Cloud Run, per request   ${per_request:.8f}")
    print(f"  one always-on VM, month  ${vm_month:.2f}\n")

    rates = [0.1, 0.5, 1, 3, 5, 10, 25, 50, 100]
    print(f"  {'req/sec':>8} {'req/month':>12} {'Cloud Run':>11} {'the VM':>9}  cheaper")
    print("  " + "-" * 56)
    run_costs, vm_costs = [], []
    crossover = None
    for r in rates:
        n = r * 3600 * 730
        run_cost = n * per_request
        run_costs.append(run_cost)
        vm_costs.append(vm_month)
        if crossover is None and run_cost > vm_month:
            crossover = r
        print(f"  {r:>8} {n:>12,.0f} ${run_cost:>10,.2f} ${vm_month:>8.2f}  "
              f"{'the VM' if run_cost > vm_month else 'Cloud Run'}")

    exact = vm_month / (per_request * 3600 * 730)
    print(f"\n  The curves cross at {exact:.2f} requests/second sustained,")
    print(f"  or {exact * 3600 * 730:,.0f} requests a month.\n")
    print("  AND THAT NUMBER IS A TRAP IF YOU STOP THERE. Three corrections,")
    print("  all of which push the real crossover HIGHER:")
    print("\n    - SUSTAINED is doing the work. A service at 20 rps for 8")
    print("      hours and nothing for 16 averages under 7 rps, and Cloud Run")
    print("      bills only the 8. The VM bills all 24.")
    print("    - ONE VM IS NOT A DEPLOYMENT. It has no redundancy, no health")
    print("      check, no rolling update. Compare against a MIG of at least")
    print("      two across zones, and the VM line doubles.")
    print("    - THE VM BILL IS NOT THE COST. Someone patches that OS.")
    print("      Cloud Run has no OS you can patch.")
    print("\n  So: bursty, spiky or unknown traffic -> Cloud Run, and the")
    print("  scale-to-zero is worth more than the unit price. Steady high")
    print("  throughput you can keep genuinely busy -> instances, with a")
    print("  committed use discount on top. See 08_billing_cost.")
    print("\n  Cloud Run's own levers: CONCURRENCY (how many requests one")
    print("  container handles at once - the single biggest cost knob, and")
    print("  the one people leave at the default), min instances to buy away")
    print("  cold starts, and max instances to cap a runaway bill.")

    # ------------------------------------------------ 7. disks and lifecycle
    rule("7. DISKS, IMAGES AND THE INSTANCE LIFECYCLE   [documented]")
    print("""    BOOT DISK        by default DELETED WITH THE INSTANCE. The
                     checkbox that saves people is "keep disk".

    pd-standard      HDD. Cheap, sequential, archival.
    pd-balanced      SSD, the sane default.
    pd-ssd           higher IOPS per GB.
    pd-extreme /     provisioned IOPS, for databases that need a floor.
      hyperdisk
    LOCAL SSD        physically attached, fastest, and EPHEMERAL - the
                     data is gone when the instance stops. Scratch and
                     caches only. This is an exam favourite.

    Persistent disk performance SCALES WITH SIZE. "The disk is slow" is
    often "the disk is small"; resizing up is online, shrinking is not
    possible.

    SNAPSHOT         incremental, of a disk. For backup and restore.
    MACHINE IMAGE    the whole instance - disks, metadata, config. For
                     cloning a VM.
    CUSTOM IMAGE     a boot disk to launch new instances from. This is
                     the one that shortens the boot in section 5.

    LIVE MIGRATION   Google moves a running VM off a host it needs to
                     service, with no reboot. It is ON by default, and
                     it is NOT available for Spot VMs, or for instances
                     with GPUs attached.

    STOPPED instances are not billed for vCPU or memory, but ARE billed
    for their disks and any reserved static IP.

    METADATA and STARTUP SCRIPTS configure a VM at boot; the metadata
    server is also how an instance gets its service account token,
    which is the mechanism behind "attach a service account instead of
    downloading a key" in 02_iam.""")

    # -------------------------------------------------- 8. the bottom rung
    rule("8. SOLE-TENANT AND BARE METAL   [documented]")
    print("""    SOLE-TENANT NODES    your VMs, alone on a physical host nobody
                         else shares. Two reasons, and they are the two
                         the exam uses:
                           - LICENSING that is counted per physical core
                             or is bring-your-own
                           - a compliance rule about physical isolation
                         You still get a hypervisor and normal VMs; you
                         are paying for the host, not the instances.

    BARE METAL SOLUTION  actual physical servers in a Google facility,
                         connected to your VPC at low latency. It exists
                         mainly for workloads that cannot be virtualised
                         at all - classically Oracle. Not a general
                         answer to "we want more performance".

    CONFIDENTIAL VMs are a different axis entirely: memory encrypted in
    use, so the hypervisor cannot read it. That is about confidentiality,
    not tenancy - do not confuse it with sole-tenant.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    labels = [s[0] for s in spot_rows] + ["on-demand"]
    costs = [s[4] for s in spot_rows] + [on_demand_cost]
    finished = [s[1] for s in spot_rows] + [100.0]
    bars = ax1.bar(range(len(labels)), costs,
                   color=[PALETTE["vermillion"] if f < 95 else PALETTE["green"]
                          for f in finished])
    ax1.set_xticks(range(len(labels)))
    ax1.set_xticklabels([l.replace(" / ", "\n") for l in labels],
                        rotation=20, ha="right", fontsize=8)
    ax1.set_ylabel("cost of a 10-hour job ($)")
    ax1.set_title("Spot: red = often never finished", loc="left")
    for b, f in zip(bars, finished):
        ax1.text(b.get_x() + b.get_width() / 2, b.get_height(),
                 f"{f:.0f}%", ha="center", va="bottom", fontsize=8)

    hours = [m / 60 for m in range(len(spiked["load"]))]
    ax3b = ax2.twinx()
    ax2.plot(hours, spiked["load"], color=PALETTE["grey"], lw=1.2,
             label="load (rps)")
    ax2.set_ylabel("requests/sec")
    ax3b.step(hours, spiked["desired"], color=PALETTE["orange"], lw=1.4,
              label="wanted")
    ax3b.step(hours, spiked["serving"], color=PALETTE["blue"], lw=1.8,
              label="serving")
    ax3b.set_ylabel("instances")
    ax3b.grid(False)
    ax2.set_xlabel("hour of day")
    ax2.set_title("Late all day; it only cost at 14:00", loc="left")
    ax3b.legend(loc="upper left", fontsize=8)

    ax3.plot(rates, run_costs, "o-", color=PALETTE["blue"], label="Cloud Run")
    ax3.plot(rates, vm_costs, "--", color=PALETTE["vermillion"],
             label="one always-on VM")
    ax3.axvline(exact, color=PALETTE["grey"], lw=1, ls=":")
    ax3.set_xscale("log")
    ax3.set_yscale("log")
    ax3.set_xlabel("sustained requests/sec")
    ax3.set_ylabel("$ per month")
    ax3.set_title(f"Crossover at {exact:.1f} rps", loc="left")
    ax3.legend(fontsize=8)
    save_figure(fig, OUT / "compute_spectrum.png")
    print(f"\n  figure -> {OUT / 'compute_spectrum.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "lift and shift", "cannot be               COMPUTE ENGINE
   rewritten", "needs a specific OS"
  "containers, and the team wants            GKE (Autopilot unless they
   Kubernetes"                               ask to manage nodes)
  "stateless container, HTTP, traffic        CLOUD RUN
   is spiky / unpredictable"
  "run code when a file lands in a           CLOUD RUN FUNCTIONS
   bucket"
  "fault-tolerant batch, cost is the         SPOT VMs, with checkpointing
   priority"
  "must run for exactly 24 hours"            NOT preemptible - those are
                                             stopped within 24h
  "survive a zone failure"                   REGIONAL managed instance
                                             group
  "licence counted per physical core"        SOLE-TENANT NODES
  "memory must be encrypted in use"          CONFIDENTIAL VM
  "fastest possible scratch disk"            LOCAL SSD - and accept that
                                             it is ephemeral
  "the instance is gone but we need          only if "keep boot disk" was
   the data"                                 set. Otherwise it is gone
  "scaling is too slow"                      a BAKED IMAGE and min
                                             instances, not a faster
                                             autoscaler""")


if __name__ == "__main__":
    main()
