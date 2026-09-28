"""Operations: logs go to every sink that matches, and alerts fire on duration.

Domain 3 of the ACE exam (~27%) is "ensuring successful operation", and it
is mostly Cloud Logging and Cloud Monitoring. Two mechanisms inside it are
routinely got wrong, and both are testable here:

  - THE LOG ROUTER IS NOT FIRST-MATCH. Every sink is evaluated
    independently, so one log entry can land in four places at once. This
    is the opposite of the firewall in 06_networking, and the difference
    shows up as a bill.
  - AN ALERT CONDITION IS A DURATION, NOT A THRESHOLD. "CPU above 80%"
    almost never means what people think it means.

  1. The four audit log types
  2. The log router - a real sink evaluator            [runnable]
  3. What that routing costs                           [arithmetic]
  4. Metrics: free from the hypervisor vs the Ops Agent
  5. Alerting policies - a real evaluator              [simulated]
  6. Uptime checks, and what an availability target costs [arithmetic]
  7. The rest of the suite

SECTIONS 2, 3, 5 AND 6 RUN. Section 5's metric series is seeded and its
model is printed before the numbers. Sections 1, 4 and 7 are documented.

PRICES ARE A REPRESENTATIVE MODEL. The FREE ALLOWANCES and the RETENTION
defaults are the durable, examinable numbers.

Run:
    python 07_operations/operations.py

Concept reference: ACE domain 3 (~27%) - ensuring successful operation.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"
SEED = 11

SEVERITIES = ["DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL"]

# Representative prices. The FREE ALLOWANCE is the number to remember.
LOG_INGEST_PER_GIB = 0.50          # into a Cloud Logging bucket
LOG_FREE_GIB = 50.0                # per project per month, _Required is free
GCS_PER_GIB_MONTH = 0.020
BQ_STORAGE_PER_GIB_MONTH = 0.020


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------------------
# 2. The log router.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LogEntry:
    log_name: str
    resource_type: str
    severity: str
    gib: float


@dataclass
class Filter:
    """A cut-down version of the real filter language, enough to route."""
    log_name_contains: str | None = None
    resource_type: str | None = None
    min_severity: str | None = None

    def matches(self, e: LogEntry) -> bool:
        if self.log_name_contains and self.log_name_contains not in e.log_name:
            return False
        if self.resource_type and self.resource_type != e.resource_type:
            return False
        if self.min_severity:
            if SEVERITIES.index(e.severity) < SEVERITIES.index(self.min_severity):
                return False
        return True

    def describe(self) -> str:
        bits = []
        if self.log_name_contains:
            bits.append(f'logName~"{self.log_name_contains}"')
        if self.resource_type:
            bits.append(f'resource.type="{self.resource_type}"')
        if self.min_severity:
            bits.append(f"severity>={self.min_severity}")
        return " AND ".join(bits) if bits else "(everything)"


@dataclass
class Sink:
    name: str
    destination: str            # "logbucket" | "gcs" | "bigquery" | "pubsub"
    inclusion: Filter = field(default_factory=Filter)
    exclusions: list[Filter] = field(default_factory=list)
    locked: bool = False        # _Required cannot be modified or disabled

    def accepts(self, e: LogEntry) -> bool:
        if not self.inclusion.matches(e):
            return False
        if self.locked:
            # Exclusions CANNOT be applied to _Required. Adding one to the
            # config changes nothing, which is the point of the sink.
            return True
        return not any(x.matches(e) for x in self.exclusions)


def route(entry: LogEntry, sinks: list[Sink]) -> list[str]:
    """Every sink is evaluated INDEPENDENTLY. There is no ordering, no
    precedence and no first-match. A log entry goes to EVERY sink whose
    inclusion filter matches and whose exclusions do not.

    This is the single most important operational difference between the
    Log Router and every other rule engine in this repository.
    """
    return [s.name for s in sinks if s.accepts(entry)]


# ---------------------------------------------------------------------------
# 5. Alerting.
# ---------------------------------------------------------------------------
def build_series(rng: random.Random, minutes: int) -> tuple[list[float],
                                                            tuple[int, int]]:
    """A CPU utilisation series with noise, brief spikes, and ONE real
    incident. The incident window is returned so we can check whether an
    alerting policy actually caught the thing that mattered.
    """
    series = [38.0 + rng.gauss(0, 6) for _ in range(minutes)]
    # short spikes: a batch job, a deploy, a garbage collection pause
    for start in (40, 95, 160, 205, 260):
        for i in range(start, min(start + rng.randint(1, 3), minutes)):
            series[i] += 55
    # the real incident: sustained, 22 minutes
    incident = (300, 322)
    for i in range(*incident):
        series[i] = 88 + rng.gauss(0, 3)
    return [max(0.0, min(100.0, v)) for v in series], incident


def evaluate_alert(series: list[float], threshold: float,
                   duration_min: int) -> list[tuple[int, int]]:
    """A Monitoring alerting condition, implemented.

    The condition is NOT "a point crossed the threshold". It is "every
    aligned point in a window of `duration_min` was above the threshold".
    The alert opens at the END of the first such window - which is also
    why the duration is the floor on your time to detect.
    """
    firing = []
    run = 0
    open_at = None
    for i, v in enumerate(series):
        if v > threshold:
            run += 1
            if run >= max(duration_min, 1) and open_at is None:
                open_at = i
        else:
            if open_at is not None:
                firing.append((open_at, i))
                open_at = None
            run = 0
    if open_at is not None:
        firing.append((open_at, len(series)))
    return firing


def main() -> None:
    print("OPERATIONS - EVERY SINK THAT MATCHES, AND DURATION NOT THRESHOLD")

    # ------------------------------------------------------ 1. audit logs
    rule("1. THE FOUR AUDIT LOG TYPES   [documented]")
    print("""  These four come up in every ACE exam, and the distinctions are
  always the same three: is it ON by default, can you turn it OFF,
  and does it cost anything.

    ADMIN ACTIVITY    "who changed the configuration" - creating a VM,
                      changing an IAM policy, deleting a bucket.
                      ALWAYS ON. CANNOT be disabled. FREE.
                      Retained 400 days in _Required.

    DATA ACCESS       "who read or wrote the data" - reading an object,
                      running a query.
                      OFF BY DEFAULT (except BigQuery, which is on).
                      You enable it per service, and it is CHARGEABLE
                      and very high volume. This is the one that
                      surprises people on the bill.
                      Retained 30 days in _Default.

    SYSTEM EVENT      Google's own automated actions - a live migration,
                      an instance preempted.
                      ALWAYS ON. CANNOT be disabled. FREE.

    POLICY DENIED     a request refused by a security policy, such as
                      VPC Service Controls.
                      ALWAYS ON. CHARGEABLE.

  THE EXAM PATTERN: "we need to know who deleted the instance" is ADMIN
  ACTIVITY and it is already there. "We need to know who READ the
  customer table" is DATA ACCESS and it is NOT - somebody has to turn
  it on first, and it was not on last month, so the answer to "who read
  it in March" may simply be that nobody knows.""")

    # ------------------------------------------------------ 2. the router
    rule("2. THE LOG ROUTER - a real sink evaluator")

    sinks = [
        Sink("_Required", "logbucket",
             Filter(log_name_contains="cloudaudit.googleapis.com/activity"),
             locked=True),
        Sink("_Default", "logbucket", Filter(),
             exclusions=[Filter(resource_type="gce_instance",
                                min_severity=None)]),
        Sink("security-archive", "gcs",
             Filter(log_name_contains="cloudaudit.googleapis.com")),
        Sink("analytics", "bigquery",
             Filter(resource_type="gce_instance")),
        Sink("pager", "pubsub", Filter(min_severity="ERROR")),
    ]
    # The _Default exclusion above is deliberately broad - see the result.
    sinks[1].exclusions = [Filter(resource_type="gce_instance",
                                  min_severity="DEBUG")]

    print("  The sinks in this project:\n")
    print(f"  {'sink':<18} {'destination':<11} inclusion filter")
    print("  " + "-" * 72)
    for s in sinks:
        lock = " [LOCKED]" if s.locked else ""
        print(f"  {s.name:<18} {s.destination:<11} {s.inclusion.describe()}{lock}")
        for x in s.exclusions:
            print(f"  {'':<30} exclude: {x.describe()}")

    # GiB per month, for a moderately busy project. Data Access dominates,
    # which is exactly what happens the month somebody enables it.
    entries = [
        LogEntry("cloudaudit.googleapis.com/activity", "gce_instance",
                 "NOTICE", 2.0),
        LogEntry("cloudaudit.googleapis.com/data_access", "bigquery_resource",
                 "INFO", 300.0),
        LogEntry("compute.googleapis.com/serial_port", "gce_instance",
                 "INFO", 90.0),
        LogEntry("run.googleapis.com/stderr", "cloud_run_revision",
                 "ERROR", 25.0),
        LogEntry("compute.googleapis.com/app", "gce_instance",
                 "CRITICAL", 4.0),
    ]

    print(f"\n  {'log entry':<44} goes to")
    print("  " + "-" * 76)
    fan = []
    for e in entries:
        dests = route(e, sinks)
        fan.append(len(dests))
        label = f"{e.log_name.split('/')[-1]} / {e.resource_type} / {e.severity}"
        print(f"  {label:<44} {', '.join(dests) if dests else '(dropped)'}")

    print(f"\n  AVERAGE FAN-OUT: {sum(fan) / len(fan):.1f} destinations per entry "
          f"(max {max(fan)}).")
    print("\n  NO SINK STOPPED ANOTHER ONE. There is no ordering, no")
    print("  precedence and no first-match here - every sink is evaluated")
    print("  independently against every entry. Compare 06_networking, where")
    print("  the first matching firewall rule ends evaluation, and 02_iam,")
    print("  where only a Deny policy subtracts. The Log Router is the only")
    print("  engine in this repository that MULTIPLIES.")

    excluded = [e for e in entries if e.resource_type == "gce_instance"]
    still = [e for e in excluded if route(e, sinks)]
    print(f"\n  Note the _Default exclusion on gce_instance: "
          f"{len(excluded)} entries were excluded")
    print(f"  from _Default, and {len(still)} of them are still being stored "
          f"somewhere else.")
    print("  AN EXCLUSION IS PER SINK, NOT A GLOBAL MUTE. 'We excluded those")
    print("  logs and the bill did not move' is this, every time.")

    print("\n  And _Required: it is LOCKED. You cannot add an exclusion to it,")
    print("  you cannot disable it, and you cannot change its 400-day")
    print("  retention. That is deliberate - it is the sink that guarantees")
    print("  an audit trail exists even if someone reconfigures everything")
    print("  else.")

    # ------------------------------------------------------- 3. what it costs
    rule("3. WHAT THAT ROUTING COSTS   [arithmetic]")
    print("  Monthly volume per entry type, routed as above.\n")
    dest_gib: dict[str, float] = {}
    for e in entries:
        for name in route(e, sinks):
            dest_gib[name] = dest_gib.get(name, 0.0) + e.gib

    total_generated = sum(e.gib for e in entries)
    total_stored = sum(dest_gib.values())
    print(f"  {'sink':<18} {'destination':<11} {'GiB/month':>10} {'$/month':>9}  note")
    print("  " + "-" * 72)
    bill = 0.0
    for s in sinks:
        g = dest_gib.get(s.name, 0.0)
        if s.name == "_Required":
            cost, note = 0.0, "free, always, cannot be disabled"
        elif s.destination == "logbucket":
            billable = max(0.0, g - LOG_FREE_GIB)
            cost = billable * LOG_INGEST_PER_GIB
            note = f"first {LOG_FREE_GIB:.0f} GiB free -> {billable:.1f} billable"
        elif s.destination == "gcs":
            cost, note = g * GCS_PER_GIB_MONTH, "routing free, you pay GCS"
        elif s.destination == "bigquery":
            cost, note = g * BQ_STORAGE_PER_GIB_MONTH, "routing free, you pay BQ"
        else:
            cost, note = 0.0, "routing free, you pay whoever consumes it"
        bill += cost
        print(f"  {s.name:<18} {s.destination:<11} {g:>10.1f} {cost:>9.2f}  {note}")

    print(f"\n  generated {total_generated:.1f} GiB, stored "
          f"{total_stored:.1f} GiB -> {total_stored / total_generated:.1f}x "
          f"duplication")
    print(f"  total ${bill:.2f}/month")

    # What the exclusion on _Default is actually worth, measured both ways.
    def default_bill(with_exclusion: bool) -> tuple[float, float]:
        d = Sink("_Default", "logbucket", Filter(),
                 exclusions=list(sinks[1].exclusions) if with_exclusion else [])
        g = sum(e.gib for e in entries if d.accepts(e))
        return g, max(0.0, g - LOG_FREE_GIB) * LOG_INGEST_PER_GIB

    g_off, c_off = default_bill(False)
    g_on, c_on = default_bill(True)
    print(f"\n  What the one exclusion on _Default is worth:")
    print(f"    without it   {g_off:>6.1f} GiB ingested   ${c_off:>7.2f}/month")
    print(f"    with it      {g_on:>6.1f} GiB ingested   ${c_on:>7.2f}/month")
    print(f"    saved        {g_off - g_on:>6.1f} GiB             "
          f"${c_off - c_on:>7.2f}/month\n")
    print("  TWO RULES:")
    print("    - ROUTING to GCS / BigQuery / Pub/Sub costs nothing for the")
    print("      routing itself. You pay the DESTINATION. Ingestion into a")
    print("      Cloud LOGGING bucket is the charge, and the first 50 GiB")
    print("      per project per month is free.")
    print("    - To reduce the LOGGING bill you must EXCLUDE AT INGESTION,")
    print("      which is what the two lines above measure. Routing the same")
    print("      logs somewhere cheaper ADDS a copy; it never removes one -")
    print(f"      which is why {total_stored / total_generated:.1f}x more data "
          f"is stored than was generated.")
    print("\n  And note WHICH entry dominates: the Data Access audit log, at")
    print(f"  {max(entries, key=lambda e: e.gib).gib:.0f} of {total_generated:.0f} "
          f"GiB. That is the log type section 1 said was off by")
    print("  default. Somebody turned it on, and this is the month after.")
    print("\n  Retention: _Required is 400 days and fixed. _Default is 30 days")
    print("  and CAN be changed - custom log buckets go up to 3650 days, and")
    print("  retention beyond the default is chargeable.")
    print("\n  An AGGREGATED SINK at a folder or organization, with")
    print("  includeChildren, captures logs from every project beneath it.")
    print("  That is the answer to 'centralise logs from all projects' - one")
    print("  sink above them, not one sink configured in each.")

    # ----------------------------------------------------------- 4. metrics
    rule("4. METRICS: FREE FROM THE HYPERVISOR vs THE OPS AGENT   [documented]")
    print("""  Google can see a VM from the outside without any cooperation
  from it. It cannot see INSIDE it.

    FREE, no agent, from the hypervisor:
      CPU utilisation, network bytes in/out, disk read/write bytes
      and operations, uptime.

    REQUIRES THE OPS AGENT, installed in the guest:
      MEMORY UTILISATION, DISK SPACE USED / FREE, swap, per-process
      metrics, and ALL application and syslog LOGS from the VM.

  MEMORY AND DISK USAGE ARE THE TWO THAT ARE ALWAYS IN THE QUESTION.
  "We want to alert when a VM runs out of memory" ALWAYS requires
  installing the Ops Agent first. There is no way to get it from the
  outside, and a dashboard with no memory metric is this, not a bug.

  The Ops Agent replaced the older separate Monitoring and Logging
  agents; it does both.

  CUSTOM METRICS are for anything the platform does not emit - queue
  depth, orders per minute. Write them from your code, then alert on
  them like any other. Log-based metrics are the other route: count
  log entries matching a filter and turn that count into a metric.""")

    # -------------------------------------------------------- 5. alerting
    rule("5. ALERTING POLICIES - a real evaluator   [simulated]")
    rng = random.Random(SEED)
    minutes = 360
    series, incident = build_series(rng, minutes)
    threshold = 80.0
    print(f"  MODEL: {minutes} minutes of CPU utilisation, seed {SEED}. Noise")
    print("  around 38%, five BRIEF spikes of 1-3 minutes (a deploy, a GC")
    print(f"  pause, a batch job), and ONE REAL INCIDENT of "
          f"{incident[1] - incident[0]} minutes at ~88%")
    print(f"  starting at minute {incident[0]}. Threshold {threshold:.0f}%.\n")

    above = sum(1 for v in series if v > threshold)
    print(f"  minutes above {threshold:.0f}%: {above} of {minutes}\n")
    print(f"  {'duration setting':>17} {'alerts fired':>13} "
          f"{'real incident caught':>21} {'time to alert':>14}")
    print("  " + "-" * 70)
    sweep = []
    for dur in (1, 2, 3, 5, 10, 15, 25):
        fires = evaluate_alert(series, threshold, dur)
        caught = [f for f in fires
                  if f[0] >= incident[0] and f[0] <= incident[1]]
        ttd = (caught[0][0] - incident[0]) if caught else None
        sweep.append((dur, len(fires), bool(caught), ttd))
        print(f"  {f'{dur} min':>17} {len(fires):>13} "
              f"{str(bool(caught)):>21} "
              f"{(f'{ttd} min' if ttd is not None else 'never'):>14}")

    noisy = sweep[0]
    quiet = [s for s in sweep if s[1] == 1 and s[2]]
    missed = [s for s in sweep if not s[2]]
    print(f"\n  AT A 1-MINUTE DURATION THE POLICY FIRED {noisy[1]} TIMES and only")
    print("  one of those was real. That is not a sensitive alert, it is an")
    print("  alert nobody reads by Thursday.")
    if quiet:
        print(f"\n  The first setting that fires ONCE and still catches the")
        print(f"  incident is {quiet[0][0]} MINUTES, at a cost of "
              f"{quiet[0][3]} minutes of detection delay.")
    if missed:
        print(f"\n  At {missed[0][0]} minutes and above the policy MISSES THE "
              f"INCIDENT ENTIRELY.")
        print(f"  The outage lasted {incident[1] - incident[0]} minutes; the "
              f"window never completed.")
    print("\n  THE DURATION IS NOT A SENSITIVITY KNOB, IT IS A BET ON HOW LONG")
    print("  YOUR INCIDENTS LAST. Too short and you train people to ignore")
    print("  the pager; too long and you cannot detect anything shorter than")
    print("  the window. And the duration is a FLOOR on time-to-detect - you")
    print("  can never be told faster than you asked to wait.")
    print("\n  The other parts of an alerting policy, which the exam names:")
    print("    CONDITION         the metric, the threshold, the duration,")
    print("                      and the aligner (how raw points are")
    print("                      reduced to one value per period)")
    print("    NOTIFICATION      email, SMS, Pub/Sub, Slack, PagerDuty,")
    print("      CHANNEL         webhook. Configured SEPARATELY and attached")
    print("                      - a policy with no channel fires silently")
    print("    AUTO-CLOSE        how long after the condition clears the")
    print("                      incident closes")

    # ----------------------------------------------- 6. uptime and targets
    rule("6. UPTIME CHECKS, AND WHAT AN AVAILABILITY TARGET COSTS")
    print("""  An UPTIME CHECK polls a public endpoint - a URL, a VM, a load
  balancer - from MULTIPLE GLOBAL LOCATIONS, and alerts when enough
  of them fail. It needs the endpoint to be reachable from the
  internet; a private service needs a different approach.

  Two things it gives you that a metric does not: it tests from
  OUTSIDE your project, so it catches a broken load balancer or DNS,
  and it distinguishes "down for everyone" from "down from Europe".\n""")
    print(f"  {'target':>10} {'per day':>12} {'per month':>13} {'per year':>13}")
    print("  " + "-" * 52)
    targets = [99.0, 99.5, 99.9, 99.95, 99.99, 99.999]
    for t in targets:
        un = (100 - t) / 100
        day = un * 24 * 60
        month = un * 30 * 24 * 60
        year = un * 365 * 24 * 60
        def fmt(m: float) -> str:
            if m < 60:
                return f"{m:.1f} min"
            if m < 1440:
                return f"{m / 60:.1f} hr"
            return f"{m / 1440:.1f} days"
        print(f"  {t:>9.3f}% {fmt(day):>12} {fmt(month):>13} {fmt(year):>13}")

    budget_999 = 0.001 * 30 * 24 * 60
    if quiet:
        detect = quiet[0][3]
        print(f"\n  READ THE 99.9% ROW AGAINST SECTION 5. A 99.9% monthly target")
        print(f"  allows {budget_999:.1f} minutes of downtime. The alerting policy that")
        print(f"  fired exactly once took {detect} minutes to notice - "
              f"{detect / budget_999 * 100:.0f}% of the")
        print("  whole month's budget, spent before anyone starts working.")
        print(f"  The incident itself ran {incident[1] - incident[0]} minutes, "
              f"which is "
              f"{(incident[1] - incident[0]) / budget_999 * 100:.0f}% of the budget")
        print("  in a single event.")
    print("\n  Which is why the useful question is never 'what uptime do we")
    print("  want' - everyone wants five nines - but 'how long may one")
    print("  incident last', and that number has to cover detect, page,")
    print("  wake up, diagnose and fix.")

    # ------------------------------------------------------- 7. the rest
    rule("7. THE REST OF THE SUITE   [documented]")
    print("""    CLOUD MONITORING   metrics, dashboards, alerting, uptime checks.
                       A metrics SCOPE can span several projects, which
                       is how you get one dashboard for an environment
                       spread over many projects.
    CLOUD LOGGING      ingestion, the Log Router, log buckets, the Logs
                       Explorer, log-based metrics.
    ERROR REPORTING    groups identical stack traces into one issue and
                       counts them. Free, on by default for several
                       runtimes, and the fastest way to see "what is
                       broken right now".
    CLOUD TRACE        latency, distributed across services. The answer
                       to "which call in the chain is slow".
    CLOUD PROFILER     continuous CPU and memory profiling in
                       production, at very low overhead. The answer to
                       "which function is expensive".

  THE DISTINCTION THE EXAM USES: TRACE tells you WHICH SERVICE is
  slow; PROFILER tells you WHICH CODE is slow; ERROR REPORTING tells
  you WHAT IS FAILING; LOGGING tells you WHAT HAPPENED; MONITORING
  tells you WHETHER IT IS STILL HAPPENING.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    snames = [s.name for s in sinks]
    vals = [dest_gib.get(n, 0.0) for n in snames]
    cols = [PALETTE["grey"] if n == "_Required" else PALETTE["blue"]
            for n in snames]
    ax1.barh(snames[::-1], vals[::-1], color=cols[::-1])
    ax1.axvline(total_generated, color=PALETTE["vermillion"], ls=":", lw=1.5)
    ax1.set_xlabel("GiB/month stored (dotted = GiB generated)")
    ax1.set_title("Every sink that matches", loc="left")

    ax2.plot(range(minutes), series, lw=0.9, color=PALETTE["grey"])
    ax2.axhline(threshold, color=PALETTE["vermillion"], ls="--", lw=1.2)
    ax2.axvspan(*incident, color=PALETTE["orange"], alpha=0.25)
    for a, b in evaluate_alert(series, threshold, 5):
        ax2.axvspan(a, b, color=PALETTE["blue"], alpha=0.45)
    ax2.set_xlabel("minute")
    ax2.set_ylabel("CPU %")
    ax2.set_title("Orange = incident, blue = 5-min alert", loc="left")

    durs = [s[0] for s in sweep]
    fired = [s[1] for s in sweep]
    ax3.plot(durs, fired, "o-", color=PALETTE["blue"], label="alerts fired")
    for d, f, c, _ in sweep:
        if not c:
            ax3.plot([d], [f], "x", color=PALETTE["vermillion"], markersize=11)
    ax3.axhline(1, color=PALETTE["grey"], ls=":", lw=1)
    ax3.set_xlabel("duration setting (minutes)")
    ax3.set_ylabel("alerts fired in 6 hours")
    ax3.set_title("x = missed the real incident", loc="left")
    ax3.legend(fontsize=8)
    save_figure(fig, OUT / "operations.png")
    print(f"\n  figure -> {OUT / 'operations.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "who deleted the instance"                 ADMIN ACTIVITY audit log -
                                             already on, cannot be off
  "who READ the customer table"              DATA ACCESS audit log - and
                                             it must be ENABLED first
  "keep audit logs 7 years"                  a SINK to Cloud Storage
                                             (or a bucket with long
                                             retention). _Required is
                                             400 days and fixed
  "centralise logs from every project"       an AGGREGATED SINK at the
                                             folder or org, with
                                             includeChildren
  "our logging bill is too high"             EXCLUDE at ingestion.
                                             Routing elsewhere adds a
                                             copy, it does not remove one
  "alert when a VM runs out of memory"       install the OPS AGENT first
  "alert on queue depth"                     a CUSTOM or LOG-BASED metric
  "we get paged constantly"                  raise the DURATION, not the
                                             threshold
  "is the site up for users in Asia"         an UPTIME CHECK
  "which microservice is slow"               CLOUD TRACE
  "which function is burning CPU"            CLOUD PROFILER
  "one dashboard across our projects"        a metrics SCOPE""")


if __name__ == "__main__":
    main()
