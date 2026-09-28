"""Billing: four discounts with four different conditions, and a budget that
does not stop anything.

Cost is examined in domain 1 (~23%) and it is the part of the exam most
likely to be wrong in your head, because the discounts sound
interchangeable and are not. Each one buys a price cut in exchange for a
DIFFERENT promise:

    SUD   you promise nothing. It is automatic, and it rewards leaving a
          machine ON.
    CUD   you promise to PAY for a year or three, used or not.
    SPOT  you promise to TOLERATE being interrupted.
    right-sizing   you promise nothing and it beats all three, which is
          why 03_compute puts it first.

  1. Where the money is actually decided
  2. Sustained use discounts - the tiered model        [arithmetic]
  3. Committed use discounts - the break-even          [arithmetic]
  4. All four levers against one workload              [arithmetic]
  5. Budgets and alerts - and what they do NOT do      [simulated]
  6. Finding the money: export, labels, attribution
  7. The things that quietly cost money

SECTIONS 2, 3 AND 4 ARE ARITHMETIC and exact given the discount model.
SECTION 5 IS A SIMULATION with the model printed first.
SECTIONS 1, 6 AND 7 ARE DOCUMENTED.

DISCOUNT RATES ARE A REPRESENTATIVE MODEL. The TIER STRUCTURE of SUD and
the "you pay whether you use it" property of CUD are the durable,
examinable facts; the exact percentages move and vary by family and
region.

Run:
    python 08_billing_cost/billing_and_cost.py

Concept reference: ACE domain 1 (~23%) - setting up the environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"

# ---------------------------------------------------------------------------
# The discount model. Representative - see the docstring.
# ---------------------------------------------------------------------------
# Sustained use, the classic N1 structure: the month is split into quarters
# and each quarter of USAGE is discounted more than the last. Running the
# whole month nets 30% off. Note E2 machine types get NO sustained use
# discount - their list price is already low.
SUD_TIERS = [(0.25, 1.00),   # first 25% of the month: full price
             (0.50, 0.80),   # 25-50%: 20% off
             (0.75, 0.60),   # 50-75%: 40% off
             (1.00, 0.40)]   # 75-100%: 60% off

CUD_1YR = 0.37               # ~37% off, resource-based, 1 year
CUD_3YR = 0.55               # ~55% off, resource-based, 3 years
SPOT = 0.70                  # ~70% off, interruptible - see 03_compute

LIST_PER_MONTH = 500.0       # on-demand list price for the fleet, per month


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def sud_paid_fraction(uptime: float) -> float:
    """Fraction of LIST price paid, after sustained use discounts.

    The discount is INCREMENTAL, not a single rate applied to the whole
    bill. That is the entire reason the net discount curve bends.
    """
    paid = 0.0
    lower = 0.0
    for upper, rate in SUD_TIERS:
        if uptime <= lower:
            break
        span = min(uptime, upper) - lower
        paid += span * rate
        lower = upper
    return paid


def cost_on_demand(uptime: float) -> float:
    return LIST_PER_MONTH * uptime


def cost_sud(uptime: float) -> float:
    return LIST_PER_MONTH * sud_paid_fraction(uptime)


def cost_cud(uptime: float, discount: float) -> float:
    """A commitment is billed in full every month, whatever you run."""
    del uptime
    return LIST_PER_MONTH * (1 - discount)


def cost_spot(uptime: float) -> float:
    return LIST_PER_MONTH * uptime * (1 - SPOT)


def solve_breakeven(discount: float) -> float | None:
    """The uptime at which a commitment starts beating on-demand+SUD."""
    target = 1 - discount
    lo, hi = 0.0, 1.0
    if sud_paid_fraction(hi) < target:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if sud_paid_fraction(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# 5. Budgets.
# ---------------------------------------------------------------------------
def simulate_budget(budget: float, days: int, normal_per_day: float,
                    runaway_day: int, runaway_per_day: float,
                    thresholds: list[float]) -> dict:
    """A month of spend against a budget, and when each alert fires.

    THE MODEL, and the one thing it is built to show:
      - spend accrues daily; on `runaway_day` somebody leaves something
        large running and the daily rate jumps
      - an ACTUAL-spend alert fires the first day cumulative spend crosses
        each threshold
      - a FORECAST alert fires the first day the run-rate projects to
        exceed the budget by month end
      - NOTHING IN THIS FUNCTION STOPS THE SPEND, because nothing in a
        Google Cloud budget does either
    """
    cum = 0.0
    daily, cumulative = [], []
    fired: dict[str, int] = {}
    for day in range(1, days + 1):
        rate = runaway_per_day if day >= runaway_day else normal_per_day
        cum += rate
        daily.append(rate)
        cumulative.append(cum)
        for t in thresholds:
            key = f"actual {t:.0%}"
            if key not in fired and cum >= budget * t:
                fired[key] = day
        forecast = cum / day * days
        if "forecast 100%" not in fired and forecast > budget:
            fired["forecast 100%"] = day
    return {"cumulative": cumulative, "daily": daily, "fired": fired,
            "final": cum, "budget": budget}


def main() -> None:
    print("BILLING - FOUR DISCOUNTS, FOUR PROMISES, AND A BUDGET THAT WATCHES")

    # ----------------------------------------------------- 1. the framing
    rule("1. WHERE THE MONEY IS ACTUALLY DECIDED   [documented]")
    print("""  In rough order of how much they save, which is NOT the order
  people try them in:

    1. NOT RUNNING IT           delete it, or schedule it off. Nothing
                                beats zero, and most environments have
                                something running that nobody uses.
    2. RIGHT-SIZING             03_compute section 3. A commitment on an
                                oversized machine buys a discount on
                                waste, which is why this comes FIRST.
    3. THE RIGHT PRODUCT        Cloud Run instead of an idle VM
                                (03_compute section 6); the right storage
                                class (05_storage section 4).
    4. DISCOUNT PROGRAMMES      sections 2-4 below. Real, automatic in
                                one case, and the LAST thing to reach for
                                rather than the first.

  THE ORDER MATTERS BECAUSE THE DISCOUNTS COMPOUND THE MISTAKE. A
  three-year commitment on a fleet that is twice the size it needs to
  be locks in the wrong number for three years at 55% off.""")

    # ---------------------------------------------------------- 2. SUD
    rule("2. SUSTAINED USE DISCOUNTS - automatic, and non-linear")
    print("  [representative tiers - the STRUCTURE is the examinable part]\n")
    print("  The month is split into quarters. Each quarter of USAGE is")
    print("  discounted more than the last:\n")
    lower = 0.0
    for upper, rate in SUD_TIERS:
        print(f"    {lower:>5.0%} - {upper:<5.0%} of the month   "
              f"pay {rate:>4.0%} of list   ({1 - rate:>3.0%} off)")
        lower = upper

    print(f"\n  {'uptime':>8} {'paid':>8} {'net discount':>14} {'$ / month':>11}")
    print("  " + "-" * 46)
    uptimes = [0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90, 1.00]
    sud_curve = []
    for u in uptimes:
        paid = sud_paid_fraction(u)
        net = 1 - paid / u if u else 0.0
        sud_curve.append((u, net))
        print(f"  {u:>8.0%} {paid:>8.3f} {net:>13.1%} "
              f"{LIST_PER_MONTH * paid:>11.2f}")

    half = 1 - sud_paid_fraction(0.5) / 0.5
    full = 1 - sud_paid_fraction(1.0)
    print(f"\n  RUNNING ALL MONTH NETS {full:.0%} OFF. RUNNING HALF THE MONTH "
          f"NETS {half:.0%},")
    print(f"  not {full / 2:.0%}. The discount is INCREMENTAL - the first quarter of")
    print("  the month is always full price - so the curve bends, and every")
    print("  hour you switch a machine off costs you discount on the hours")
    print("  you kept.")
    print("\n  THAT IS AN UNCOMFORTABLE INCENTIVE and it is worth naming:")
    print("  sustained use discounts reward LEAVING THINGS ON. They are")
    print("  automatic, you cannot decline them, and they will never be the")
    print("  reason to run something you do not need. Compare lever 1.")
    print("\n  You apply for nothing and sign nothing. SUD is calculated per")
    print("  month, per region, and Google aggregates usage across instances")
    print("  of the same type to maximise it for you. Note E2 machine types")
    print("  are NOT eligible - their list price is already low.")

    # ---------------------------------------------------------- 3. CUD
    rule("3. COMMITTED USE DISCOUNTS - the break-even")
    print("  A commitment is a promise to PAY for a fixed amount of vCPU and")
    print("  memory in a region for 1 or 3 years. You are billed for it every")
    print("  month WHETHER OR NOT YOU USE IT. It cannot be cancelled.\n")
    print(f"    1 year   ~{CUD_1YR:.0%} off")
    print(f"    3 years  ~{CUD_3YR:.0%} off\n")
    print("  So the question is never 'is 55% good'. It is: at what UPTIME")
    print("  does paying all the time beat paying only when you run, with")
    print("  sustained use discounts already applied?\n")

    be1 = solve_breakeven(CUD_1YR)
    be3 = solve_breakeven(CUD_3YR)
    print(f"  {'commitment':<12} {'you pay':>9} {'break-even uptime':>19}")
    print("  " + "-" * 44)
    print(f"  {'1 year':<12} {1 - CUD_1YR:>8.0%} {be1:>18.1%}")
    print(f"  {'3 years':<12} {1 - CUD_3YR:>8.0%} {be3:>18.1%}")

    print(f"\n  A ONE-YEAR COMMITMENT NEEDS ABOUT {be1:.0%} UPTIME TO PAY OFF.")
    print(f"  A THREE-YEAR ONE NEEDS ABOUT {be3:.0%}.")
    print("\n  Read that carefully, because it is the opposite of the")
    print("  intuition: the LONGER, DEEPER commitment is the EASIER one to")
    print("  justify on utilisation.")
    print("\n  And that is STRUCTURAL, not an artefact of the rates chosen")
    print("  here. A deeper discount means a lower bill every month, which")
    print("  means it overtakes sustained use sooner - so the break-even")
    print("  falls monotonically as the discount rises:\n")
    print(f"    {'discount':>9} {'break-even uptime':>19}")
    print("    " + "-" * 30)
    for d in (0.20, 0.30, 0.37, 0.45, 0.55, 0.70):
        be = solve_breakeven(d)
        shown = f"{be:.1%}" if be is not None else "never pays off"
        tag = "  <- 1 year" if abs(d - CUD_1YR) < 1e-9 else (
              "  <- 3 years" if abs(d - CUD_3YR) < 1e-9 else "")
        print(f"    {d:>9.0%} {shown:>19}{tag}")
    print("\n  There is no pair of real commitment rates where the 3-year")
    print("  option needs MORE uptime than the 1-year one. So the break-even")
    print("  is never the reason to prefer 1 year.")
    print("\n  WHAT MAKES THREE YEARS HARD IS NOT THE ARITHMETIC, IT IS THE")
    print("  FORECAST. You are asserting a workload will still exist, at")
    print("  roughly this size, in this region, in three years. The")
    print("  break-even is certain; that sentence is not.")
    print("\n  Note also the top row: below about a 30% discount a commitment")
    print("  never pays off at any uptime, because sustained use already")
    print("  gets you 30% for free.")
    print("\n  WHAT A COMMITMENT DOES NOT DO:")
    print("    - it does not reserve capacity. A commitment is a BILLING")
    print("      construct. If you need capacity guaranteed, that is a")
    print("      RESERVATION, which is a separate thing you can buy with it")
    print("    - it does not follow you to another region")
    print("    - it cannot be cancelled, and the exam likes this fact")
    print("\n  Resource-based commitments are vCPU and memory. SPEND-BASED")
    print("  (flexible) commitments are a dollar-per-hour promise that")
    print("  covers several services including Cloud Run - more flexible,")
    print("  a smaller discount.")

    # -------------------------------------------- 4. all four levers
    rule("4. ALL FOUR LEVERS, ONE WORKLOAD")
    print(f"  A fleet whose on-demand LIST price is ${LIST_PER_MONTH:.0f}/month at "
          f"100% uptime.\n")
    print(f"  {'uptime':>8} {'on-demand':>11} {'+ SUD':>9} {'CUD 1yr':>9} "
          f"{'CUD 3yr':>9} {'Spot':>8}   {'cheapest':<10} cheapest if it")
    print(f"  {'':>8} {'':>11} {'':>9} {'':>9} {'':>9} {'':>8}   {'':<10} "
          f"must not be interrupted")
    print("  " + "-" * 98)
    curves = {"on-demand": [], "+ SUD": [], "CUD 1yr": [], "CUD 3yr": [],
              "Spot": []}
    grid = [0.10, 0.25, 0.50, 0.60, 0.75, 0.90, 1.00]
    for u in grid:
        row = {
            "on-demand": cost_on_demand(u),
            "+ SUD": cost_sud(u),
            "CUD 1yr": cost_cud(u, CUD_1YR),
            "CUD 3yr": cost_cud(u, CUD_3YR),
            "Spot": cost_spot(u),
        }
        for k, v in row.items():
            curves[k].append(v)
        best = min(row, key=row.get)
        no_spot = {k: v for k, v in row.items() if k != "Spot"}
        best_ns = min(no_spot, key=no_spot.get)
        print(f"  {u:>8.0%} {row['on-demand']:>11.2f} {row['+ SUD']:>9.2f} "
              f"{row['CUD 1yr']:>9.2f} {row['CUD 3yr']:>9.2f} "
              f"{row['Spot']:>8.2f}   {best:<10} {best_ns}")

    # Does plain on-demand-with-SUD ever win, once Spot is off the table?
    sud_wins = [u for u in grid
                if min({"on-demand": cost_on_demand(u), "+ SUD": cost_sud(u),
                        "CUD 1yr": cost_cud(u, CUD_1YR),
                        "CUD 3yr": cost_cud(u, CUD_3YR)}.items(),
                       key=lambda kv: kv[1])[0] == "+ SUD"]

    print("\n  SPOT WINS EVERY ROW ON PRICE, AND THAT IS WHY PRICE IS THE")
    print("  WRONG COLUMN TO READ. Read the LAST column instead - it is the")
    print("  one most production workloads actually face.")
    print(f"\n  AND IN THAT COLUMN, SUSTAINED USE WINS {len(sud_wins)} OF "
          f"{len(grid)} ROWS. Below the")
    print("  break-even, plain on-demand is cheaper because SUD has barely")
    print("  started; above it, the three-year commitment is cheaper because")
    print("  55% beats 30%.")

    # THE GRID ABOVE IS TOO COARSE, and 10_capstone_summary found that out by
    # landing an autoscaled workload at 42% uptime, where SUD does win. Solve
    # for the window instead of sampling it.
    window = [i / 1000 for i in range(1, 1000)
              if min({"on-demand": i / 1000,
                      "+ SUD": sud_paid_fraction(i / 1000),
                      "CUD 1yr": 1 - CUD_1YR,
                      "CUD 3yr": 1 - CUD_3YR}.items(),
                     key=lambda kv: kv[1])[0] == "+ SUD"]
    print(f"\n  BUT THAT ROW COUNT IS AN ARTEFACT OF THE GRID. Solved rather")
    print("  than sampled, sustained use IS the cheapest option between")
    print(f"  {min(window):.0%} AND {max(window):.0%} UPTIME - above 25% it beats "
          f"on-demand, and")
    print("  below the three-year break-even it beats a commitment. The grid")
    print(f"  above samples {min(window):.0%} and {max(window):.0%}, the two "
          f"ENDPOINTS, and steps over")
    print("  the interior.")
    print("\n  A COARSE GRID CAN HIDE A WHOLE REGIME, and it is harder to")
    print("  notice than an arithmetic error because every printed row is")
    print("  true. An autoscaled tier lives in exactly that window -")
    print("  10_capstone_summary lands at 42% and picks SUD.")
    print("\n  So the honest version: SUD is what you get when you decline to")
    print("  choose, AND there is a real band where declining is correct.")
    print("\n  The caveat that keeps this honest: CUD 3yr wins its rows only")
    print("  if the workload really is still there in three years. The")
    print("  arithmetic is certain and the forecast is not.")
    print("\n  Each lever costs you something that does not appear here:")
    print("\n    on-demand  nothing. Full flexibility, full price.")
    print("    + SUD      nothing. Automatic. Just do not switch things off")
    print("               to chase it.")
    print("    CUD        a 1 or 3 year bill you cannot cancel, in one")
    print("               region, for a workload you have to forecast.")
    print("    Spot       interruption at any time with 30 seconds' notice,")
    print("               no SLA, and an architecture that must be resumable")
    print("               - 03_compute measured a 10-hour job that finished")
    print("               only 74% of the time without checkpointing.")
    print("\n  AND THEY COMBINE. A steady baseline on a commitment, the")
    print("  variable peak on-demand, and batch on Spot is the normal shape")
    print("  of a mature bill - not one lever for everything.")

    # ------------------------------------------------------- 5. budgets
    rule("5. BUDGETS AND ALERTS - and what they do NOT do   [simulated]")
    budget, days = 2000.0, 30
    sim = simulate_budget(budget, days, normal_per_day=40.0, runaway_day=12,
                          runaway_per_day=300.0,
                          thresholds=[0.5, 0.9, 1.0])
    print(f"  MODEL: a ${budget:.0f}/month budget with alert thresholds at 50%,")
    print("  90% and 100% of ACTUAL spend, plus a FORECAST alert. Normal")
    print("  burn $40/day; on day 12 somebody leaves a large job running")
    print("  and it becomes $300/day.\n")
    print(f"  {'alert':<18} fired on")
    print("  " + "-" * 34)
    for key in sorted(sim["fired"], key=lambda k: sim["fired"][k]):
        print(f"  {key:<18} day {sim['fired'][key]}")

    over = sim["final"] - budget
    print(f"\n  budget            ${budget:>9,.2f}")
    print(f"  actual spend      ${sim['final']:>9,.2f}")
    print(f"  overrun           ${over:>9,.2f}  "
          f"({sim['final'] / budget - 1:+.0%})")

    forecast_day = sim["fired"].get("forecast 100%")
    actual_day = sim["fired"].get("actual 100%")
    if forecast_day and actual_day:
        spend_at_forecast = sim["cumulative"][forecast_day - 1]
        print(f"\n  THE FORECAST ALERT FIRED ON DAY {forecast_day}, when only "
              f"${spend_at_forecast:,.0f} had")
        print(f"  been spent - {actual_day - forecast_day} days before the "
              f"budget was actually breached.")
        print("  That is the alert worth configuring, and it is the one")
        print("  people leave off because it fires when nothing looks wrong.")

    print(f"\n  AND THE BUDGET STOPPED NOTHING. {len(sim['fired'])} alerts fired and")
    print(f"  ${sim['final']:,.0f} went out of the door anyway.")
    print("\n  A GOOGLE CLOUD BUDGET IS A NOTIFICATION, NOT A CAP. This is")
    print("  the single most commonly misunderstood thing in the domain and")
    print("  it is a favourite exam question. There is no 'stop at $2000'")
    print("  setting.")
    print("\n  To actually stop spending you have to build it: the budget")
    print("  publishes to a PUB/SUB topic, a Cloud Run function subscribes,")
    print("  and that function DISABLES BILLING on the project. Which is")
    print("  brutal - everything in the project stops, including the")
    print("  database - so it belongs on a sandbox, not on production.")
    print("\n  Budgets are set on a BILLING ACCOUNT and can be scoped to")
    print("  projects, services or LABELS. They can also be set as a")
    print("  percentage of LAST month's spend rather than a fixed figure,")
    print("  which is the one that survives a growing environment.")

    # ------------------------------------------------- 6. finding the money
    rule("6. FINDING THE MONEY   [documented]")
    print("""    BILLING EXPORT TO BIGQUERY   the answer to almost every
                                 "analyse our spend" question. The
                                 console reports are fixed views; the
                                 export is the data, with labels and
                                 SKU detail. TURN IT ON BEFORE YOU
                                 NEED IT - it is NOT retroactive, and
                                 the month you want to investigate is
                                 always the month before you enabled
                                 it.

    LABELS                       how cost gets attributed to a team,
                                 an environment or a cost centre. They
                                 flow into the export. No labels means
                                 no answer to "whose is this" that
                                 does not involve guessing from
                                 project names. See 01_resource_
                                 hierarchy section 7 - and note LABELS,
                                 not tags, for cost.

    RECOMMENDER                  surfaces idle VMs, oversized machines,
                                 idle disks and idle addresses, and
                                 also COMMITMENT recommendations based
                                 on your actual usage. It is doing
                                 section 3's arithmetic against real
                                 data - use it before you compute a
                                 break-even by hand.

    PRICING CALCULATOR           before you build. The only place any
                                 number in this file should have come
                                 from if it mattered.

    COST TABLE / REPORTS         in the console, grouped by project,
                                 service or SKU. Enough for "what
                                 changed this month"; not enough for
                                 anything with a join in it.""")

    # ------------------------------------------ 7. the quiet costs
    rule("7. THE THINGS THAT QUIETLY COST MONEY   [documented]")
    print("""  None of these show up as "compute" and all of them show up on
  the bill. Every one is something somebody created and forgot.

    STATIC IP, RESERVED AND UNUSED   Google charges MORE for a
                                     reserved address doing nothing
                                     than for one attached to a running
                                     instance. It is a deliberate
                                     nudge, and it surprises people.
    UNATTACHED PERSISTENT DISKS      a deleted VM whose disk had "keep
                                     disk" ticked. Billed in full,
                                     forever. See 03_compute section 7.
    SNAPSHOTS AND OLD IMAGES         incremental, so cheap each, and
                                     nobody ever deletes them.
    STOPPED INSTANCES                no vCPU or memory charge, but the
                                     DISKS still bill.
    EGRESS                           cross-region, cross-continent and
                                     internet traffic. Same-region is
                                     free. "Why is the bill so high" is
                                     more often egress than storage -
                                     see 05_storage section 6.
    CLOUD NAT AND LOAD BALANCERS     hourly charges plus data
                                     processed, whether or not anyone
                                     used them.
    LOG INGESTION                    07_operations measured one
                                     exclusion worth $48/month, and a
                                     Data Access audit log that was 300
                                     of 421 GiB.
    IDLE GKE CLUSTERS                the control plane bills per hour
                                     on Standard whether or not any
                                     workload runs.

  THE PATTERN: nearly all of it is things that were created for a
  reason that has since expired. That is why lever 1 in section 1 is
  lever 1, and why RECOMMENDER finds more money than any discount
  programme in this file.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    fine = [i / 100 for i in range(1, 101)]
    ax1.plot([u * 100 for u in fine],
             [(1 - sud_paid_fraction(u) / u) * 100 for u in fine],
             color=PALETTE["blue"], lw=2)
    ax1.plot([50], [half * 100], "o", color=PALETTE["vermillion"])
    ax1.plot([100], [full * 100], "o", color=PALETTE["vermillion"])
    ax1.set_xlabel("uptime in the month (%)")
    ax1.set_ylabel("net sustained use discount (%)")
    ax1.set_title("SUD bends; half is not half", loc="left")

    for label, style in (("on-demand", "-"), ("+ SUD", "-"),
                         ("CUD 1yr", "--"), ("CUD 3yr", "--"), ("Spot", ":")):
        ax2.plot([u * 100 for u in grid], curves[label], style,
                 marker="o", markersize=3, label=label)
    for be, name in ((be1, "1yr"), (be3, "3yr")):
        if be:
            ax2.axvline(be * 100, color=PALETTE["grey"], ls=":", lw=1)
    ax2.set_xlabel("uptime in the month (%)")
    ax2.set_ylabel("$ / month")
    ax2.set_title("Break-even at the dotted lines", loc="left")
    ax2.legend(fontsize=7)

    dd = list(range(1, days + 1))
    ax3.plot(dd, sim["cumulative"], color=PALETTE["blue"], lw=2,
             label="cumulative spend")
    ax3.axhline(budget, color=PALETTE["black"], lw=1.2, label="budget")
    for t, colour in ((0.5, PALETTE["green"]), (0.9, PALETTE["orange"]),
                      (1.0, PALETTE["vermillion"])):
        ax3.axhline(budget * t, color=colour, ls=":", lw=1)
    for key, day in sim["fired"].items():
        ax3.plot([day], [sim["cumulative"][day - 1]], "v",
                 color=PALETTE["vermillion"], markersize=7)
    ax3.set_xlabel("day of month")
    ax3.set_ylabel("$")
    ax3.set_title("4 alerts, nothing stopped", loc="left")
    ax3.legend(fontsize=8)
    save_figure(fig, OUT / "billing_and_cost.png")
    print(f"\n  figure -> {OUT / 'billing_and_cost.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "stop spending when we hit the budget"     YOU CANNOT with a budget
                                             alone. Budget -> Pub/Sub ->
                                             function that DISABLES
                                             BILLING
  "warn us before we overspend"              a FORECASTED-spend budget
                                             alert
  "steady workload running 24/7"             COMMITTED USE DISCOUNT
  "we already run it all month, what do      nothing - SUSTAINED USE is
   we apply for"                             automatic
  "fault-tolerant batch, cheapest"           SPOT VMs
  "guarantee we can get the capacity"        a RESERVATION. A commitment
                                             is billing, not capacity
  "which team spent this"                    LABELS + billing export to
                                             BigQuery
  "find waste for us"                        RECOMMENDER
  "estimate before we build"                 the PRICING CALCULATOR
  "the bill is high and compute looks        check EGRESS, idle static
   normal"                                   IPs, unattached disks, log
                                             ingestion
  "cancel our 3-year commitment"             you cannot
  "one budget for the whole organisation"    budgets are on the BILLING
                                             ACCOUNT, scoped by project,
                                             service or label""")


if __name__ == "__main__":
    main()
