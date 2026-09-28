"""Capstone: one environment, built end to end with the other nine parts.

This script IMPORTS THE ENGINES FROM THE OTHER PARTS and runs a single
coherent scenario through all of them. Nothing here is reimplemented - the
IAM resolver, the Org Policy evaluator, the CIDR planner, the firewall
evaluator, the storage arithmetic, the log router, the discount model and
the IaC planner are the same objects those parts demonstrate.

That makes this an integration test as well as a revision aid: if any part
changes its API, this breaks.

  THE BRIEF
  Acme is launching a product in the EU. Data must stay in the EU, no VM
  may have a public IP, one team runs the network, one runs the product.
  Build the environment, then find what is wrong with it.

  1. Hierarchy and guardrails      (01_resource_hierarchy)
  2. Access                        (02_iam)
  3. The network                   (06_networking)
  4. The compute                   (03_compute)
  5. The data                      (05_storage)
  6. Operating it                  (07_operations)
  7. What it costs                 (08_billing_cost)
  8. Building it repeatably        (09_iac)
  9. The scorecard
 10. The cheat sheet

Run:
    python 10_capstone_summary/capstone.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"


def load(part: str, module: str):
    """Import a sibling part by path.

    The directories start with digits, so they are not importable as
    packages. Registering the module in sys.modules before executing it is
    not optional: dataclasses resolves its type hints through
    sys.modules[cls.__module__], and without this the first @dataclass in
    the file raises.
    """
    path = ROOT / part / f"{module}.py"
    spec = importlib.util.spec_from_file_location(module, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module] = mod
    spec.loader.exec_module(mod)
    return mod


HIER = load("01_resource_hierarchy", "hierarchy_and_policy")
IAM = load("02_iam", "iam_hierarchy")
COMPUTE = load("03_compute", "compute_spectrum")
STORAGE = load("05_storage", "storage_and_databases")
NET = load("06_networking", "vpc_and_firewall")
OPS = load("07_operations", "operations")
BILL = load("08_billing_cost", "billing_and_cost")
IAC = load("09_iac", "iac_and_state")


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:
    print("CAPSTONE - ONE ENVIRONMENT, END TO END")
    print("""
  THE BRIEF
    Acme is launching a product in the EU.
      - data must stay in the EU
      - no VM may have a public IP
      - the network team owns the network; the product team owns the app
      - a web tier behind a load balancer, an analytics worker, an
        orders database, and an assets bucket
    Build it. Then find what is wrong with it.""")
    scorecard: list[tuple[str, str, str]] = []

    # The autoscaler is modelled first, because the NETWORK has to be sized
    # from what it can grow to - not from what it runs today. See section 3.
    MIG_MAX = 10
    sim = COMPUTE.simulate_autoscaler(rps_per_instance=100.0, target_util=0.6,
                                      boot_minutes=3, scale_down_stabilise=10,
                                      spike=True)

    # =============================================== 1. hierarchy + policy
    rule("1. HIERARCHY AND GUARDRAILS   (01_resource_hierarchy)")
    org = HIER.Node("acme.com", "organization")
    platform = org.add(HIER.Node("platform", "folder"))
    platform.add(HIER.Node("net-hub", "project"))
    product = org.add(HIER.Node("product-eu", "folder"))
    prod = product.add(HIER.Node("shop-eu-prod", "project"))
    dev = product.add(HIER.Node("shop-eu-dev", "project"))

    LOC = "constraints/gcp.resourceLocations"
    EXTIP = "constraints/compute.vmExternalIpAccess"
    SAKEY = "constraints/iam.disableServiceAccountKeyCreation"

    org.list_policies[LOC] = HIER.ListPolicy(
        allowed={"europe-west1", "europe-west4"})
    org.list_policies[EXTIP] = HIER.ListPolicy(allowed=set())
    org.bool_policies[SAKEY] = True

    print("  Three org-level policies, one line of intent each:\n")
    print(f"    {LOC.split('/')[1]:<34} allow [europe-west1, europe-west4]")
    print(f"    {EXTIP.split('/')[1]:<34} allow []   (no public IPs)")
    print(f"    {SAKEY.split('/')[1]:<34} enforced   (no downloadable keys)\n")

    regions = ["europe-west1", "europe-west4", "us-central1", "asia-east1"]
    print(f"  {'project':<16}", end="")
    for r in regions:
        print(f" {r:>13}", end="")
    print()
    print("  " + "-" * 72)
    for node in (prod, dev):
        print(f"  {node.name:<16}", end="")
        for r in regions:
            print(f" {'yes' if HIER.value_permitted(node, LOC, r) else 'NO':>13}",
                  end="")
        print()

    reach = len(org.projects())
    enforced, where = HIER.effective_bool_policy(prod, SAKEY)
    print(f"\n  reach of a policy at the org: {reach} project(s)")
    print(f"  service-account keys on prod: enforced={enforced}, set at {where}")
    scorecard.append(("guardrails", "OK",
                      f"3 org policies, {reach} projects, no exceptions yet"))

    # ===================================================== 2. access
    rule("2. ACCESS   (02_iam)")
    iam_org = IAM.Node("acme.com", "organization")
    iam_prod = IAM.Node("shop-eu-prod", "project", parent=iam_org)

    iam_prod.bind("net-team@acme.com", "roles/compute.instanceAdmin")
    iam_prod.bind("app-team@acme.com", "roles/storage.objectViewer")
    sa = "web-sa@shop-eu-prod.iam.gserviceaccount.com"
    iam_prod.bind(sa, "roles/storage.admin")

    print(f"  {'principal':<24} {'binding':<34} perms")
    print("  " + "-" * 70)
    for who, role in (("net-team@acme.com", "roles/compute.instanceAdmin"),
                      ("app-team@acme.com", "roles/storage.objectViewer"),
                      (sa, "roles/storage.admin")):
        n = len(IAM.effective_permissions(iam_prod, who))
        print(f"  {who.split('@')[0]:<24} {role:<34} {n}")

    # what the "just make them Editor" alternative would have cost
    editor = len(IAM.ROLES["roles/editor"])
    net_team = len(IAM.effective_permissions(iam_prod, "net-team@acme.com"))
    svcs = len({p.split(".")[0] for p in IAM.ROLES["roles/editor"]})
    print(f"\n  The shortcut nobody took: roles/editor is {editor} permissions")
    print(f"  across {svcs} services. The network team has {net_team}, in 1.")
    print(f"  Least privilege here is a {editor / net_team:.1f}x reduction in blast")
    print("  radius, and it cost one extra minute of thinking.")
    scorecard.append(("least privilege", "OK",
                      f"predefined roles; {editor / net_team:.1f}x smaller than Editor"))

    # ==================================================== 3. the network
    rule("3. THE NETWORK   (06_networking)")
    demand = [("web-ew1", "europe-west1", MIG_MAX),
              ("app-ew1", "europe-west1", 12),
              ("data-ew4", "europe-west4", 6)]
    print(f"  The web tier autoscales to a MAXIMUM of {MIG_MAX}, though today's")
    print(f"  curve only needs {sim['peak']}. SIZE THE SUBNET FROM THE MAXIMUM -")
    print("  the addresses have to exist on the worst day, and a subnet can")
    print("  be grown but never shrunk.\n")
    print(f"  {'subnet':<12} {'region':<14} {'want':>5} {'cidr':<16} "
          f"{'usable':>7}")
    print("  " + "-" * 60)
    import ipaddress
    cursor = int(ipaddress.ip_network("10.20.0.0/16").network_address)
    BLOCK = 20
    plan_rows = []
    for i, (name, region, hosts) in enumerate(demand):
        p = NET.prefix_for(hosts)
        size = 2 ** (32 - p)
        cursor = (cursor + size - 1) // size * size
        net = ipaddress.ip_network((cursor, p))
        cursor += size
        plan_rows.append((name, region, hosts, net))
        print(f"  {name:<12} {region:<14} {hosts:>5} {str(net):<16} "
              f"{NET.usable(net):>7}")

    print("\n  Firewall, with the health-check rule ABOVE the lockdown:")
    web = {"web"}
    rules = [
        NET.FirewallRule("allow-health", 800, "INGRESS", "allow",
                         ["35.191.0.0/16", "130.211.0.0/22"], ports={80},
                         targets=web),
        NET.FirewallRule("deny-public", 900, "INGRESS", "deny", ["0.0.0.0/0"]),
        NET.FirewallRule("allow-iap-ssh", 700, "INGRESS", "allow",
                         ["35.235.240.0/20"], ports={22}, targets=web),
    ]
    traffic = [("health checker -> :80", NET.Connection("35.191.2.7", 80,
                                                        "INGRESS", web)),
               ("IAP SSH        -> :22", NET.Connection("35.235.240.5", 22,
                                                        "INGRESS", web)),
               ("internet       -> :443", NET.Connection("203.0.113.9", 443,
                                                         "INGRESS", web)),
               ("VM -> Google API :443", NET.Connection("142.250.1.1", 443,
                                                        "EGRESS", web))]
    print(f"  {'traffic':<26} {'verdict':<7} matched")
    print("  " + "-" * 62)
    for label, conn in traffic:
        verdict, why = NET.evaluate(rules, conn)
        print(f"  {label:<26} {verdict:<7} {why}")
    print("\n  Public ingress is denied and the two paths we need survive,")
    print("  because both were written BELOW 900. That ordering is the")
    print("  design, not an accident.")
    print("\n  No VM has an external IP (the org policy forbids it), so")
    print("  outbound needs CLOUD NAT and Google APIs need PRIVATE GOOGLE")
    print("  ACCESS. The egress row above was allowed by the implied rule -")
    print("  which permits nothing on its own without a path.")
    scorecard.append(("network", "OK",
                      "no public ingress; IAP and health checks outrank the deny"))

    # ==================================================== 4. the compute
    rule("4. THE COMPUTE   (03_compute)")
    vcpu, gb = 4, 16
    hourly = COMPUTE.vm_hourly(vcpu, gb)
    print(f"  web tier: a REGIONAL managed instance group, n2-standard-{vcpu}")
    print(f"            ({vcpu} vCPU / {gb} GB), autoscaled 60% target\n")
    print(f"  peak instances the curve needs   {sim['peak']:>8}")
    print(f"  autoscaled instance-hours/day    {sim['instance_hours']:>8.1f}")
    print(f"  fixed at peak, instance-hours    {sim['fixed_instance_hours']:>8.1f}")
    saving = 1 - sim["instance_hours"] / sim["fixed_instance_hours"]
    print(f"  saving from autoscaling          {saving * 100:>7.1f}%")
    shed_pct = sim["shed"] / sim["offered"] * 100
    print(f"  shed on the 4x spike             {sim['shed']:>8,.0f} "
          f"({shed_pct:.3f}%)")

    c_cpu, c_gb, note = COMPUTE.custom_shape(6, 40)
    print(f"\n  analytics worker: 6 vCPU / 40 GB is a legal CUSTOM shape")
    print(f"  ({c_cpu}v {c_gb:.0f}GB{', ' + note if note else ''}) and fits no predefined one.")
    scorecard.append(("compute", "RISK",
                      f"{shed_pct:.3f}% shed on a spike; min instances not set"))

    # ====================================================== 5. the data
    rule("5. THE DATA   (05_storage)")
    db_choice, db_why = STORAGE.choose_database(
        STORAGE.Need(sql_engine="postgres"))
    print(f"  orders database   {db_choice:<22} {db_why.split(' - ')[0]}")
    print("                    regional, in europe-west1, not global - the")
    print("                    brief never asked for global consistency.\n")

    reads_per_year = 6
    print(f"  assets bucket: about {reads_per_year} reads per GB per year.\n")
    print(f"  {'class':<10} {'$/GB-year':>11}")
    print("  " + "-" * 24)
    best, best_cost = None, None
    for name in STORAGE.ORDER:
        c = STORAGE.CLASSES[name]
        total = (STORAGE.storage_cost(c, 1.0, 365)
                 + reads_per_year * c.retrieval_per_gb)
        if best_cost is None or total < best_cost:
            best, best_cost = name, total
        print(f"  {name:<10} {total:>11.4f}")
    print(f"\n  cheapest at that access rate: {best}")
    archive = (STORAGE.storage_cost(STORAGE.CLASSES['ARCHIVE'], 1.0, 365)
               + reads_per_year * STORAGE.CLASSES['ARCHIVE'].retrieval_per_gb)
    print(f"  ARCHIVE, the 'obvious' cheap answer, would cost "
          f"${archive:.4f} -")
    print(f"  {archive / best_cost:.1f}x the right one, because of retrieval.")
    scorecard.append(("storage class", "OK",
                      f"{best} chosen on measured access, not on list price"))

    # ==================================================== 6. operating it
    rule("6. OPERATING IT   (07_operations)")
    sinks = [
        OPS.Sink("_Required", "logbucket",
                 OPS.Filter(log_name_contains="cloudaudit.googleapis.com/activity"),
                 locked=True),
        OPS.Sink("_Default", "logbucket", OPS.Filter()),
        OPS.Sink("eu-audit-archive", "gcs",
                 OPS.Filter(log_name_contains="cloudaudit.googleapis.com")),
        OPS.Sink("pager", "pubsub", OPS.Filter(min_severity="ERROR")),
    ]
    entries = [
        OPS.LogEntry("cloudaudit.googleapis.com/activity", "gce_instance",
                     "NOTICE", 3.0),
        OPS.LogEntry("compute.googleapis.com/app", "gce_instance",
                     "ERROR", 40.0),
        OPS.LogEntry("compute.googleapis.com/app", "gce_instance",
                     "INFO", 260.0),
    ]
    generated = sum(e.gib for e in entries)
    stored = sum(e.gib for e in entries for _ in OPS.route(e, sinks))
    print(f"  {'log entry':<38} goes to")
    print("  " + "-" * 72)
    for e in entries:
        dests = OPS.route(e, sinks)
        label = f"{e.log_name.split('/')[-1]} / {e.severity} / {e.gib:.0f} GiB"
        print(f"  {label:<38} {', '.join(dests)}")
    print(f"\n  generated {generated:.0f} GiB, stored {stored:.0f} GiB "
          f"-> {stored / generated:.1f}x")

    default_gib = sum(e.gib for e in entries
                      if sinks[1].accepts(e))
    billable = max(0.0, default_gib - OPS.LOG_FREE_GIB)
    print(f"  _Default ingests {default_gib:.0f} GiB; "
          f"{billable:.0f} billable -> "
          f"${billable * OPS.LOG_INGEST_PER_GIB:.2f}/month")

    import random
    series, incident = OPS.build_series(random.Random(11), 360)
    chosen = None
    for dur in (1, 2, 3, 5, 10, 15, 25):
        fires = OPS.evaluate_alert(series, 80.0, dur)
        caught = [f for f in fires if incident[0] <= f[0] <= incident[1]]
        if len(fires) == 1 and caught:
            chosen = (dur, caught[0][0] - incident[0])
            break
    if chosen:
        budget = 0.001 * 30 * 24 * 60
        print(f"\n  alerting: threshold 80%, duration {chosen[0]} min -> one alert,")
        print(f"  {chosen[1]} minutes to detect. Against a 99.9% target "
              f"({budget:.1f} min/month)")
        print(f"  that is {chosen[1] / budget * 100:.0f}% of the monthly error budget "
              f"spent noticing.")
    scorecard.append(("operations", "RISK",
                      f"log duplication {stored / generated:.1f}x; no exclusion set"))

    # ====================================================== 7. the cost
    rule("7. WHAT IT COSTS   (08_billing_cost)")
    monthly_list = hourly * 730 * sim["peak"]
    uptime = sim["instance_hours"] / sim["fixed_instance_hours"]
    print(f"  The web tier at its peak size is "
          f"${monthly_list:,.2f}/month at list.")
    print(f"  Autoscaling means it is really up {uptime:.0%} of the time.\n")
    print(f"  {'lever':<14} {'$/month':>10}  condition")
    print("  " + "-" * 62)
    levers = {
        "on-demand": monthly_list * uptime,
        "+ SUD": monthly_list * BILL.sud_paid_fraction(uptime),
        "CUD 1yr": monthly_list * (1 - BILL.CUD_1YR),
        "CUD 3yr": monthly_list * (1 - BILL.CUD_3YR),
    }
    conds = {"on-demand": "none", "+ SUD": "automatic",
             "CUD 1yr": f"pay all year; break-even {BILL.solve_breakeven(BILL.CUD_1YR):.0%}",
             "CUD 3yr": f"pay 3 years; break-even {BILL.solve_breakeven(BILL.CUD_3YR):.0%}"}
    for k, v in levers.items():
        print(f"  {k:<14} {v:>10,.2f}  {conds[k]}")
    cheapest = min(levers, key=levers.get)
    be3 = BILL.solve_breakeven(BILL.CUD_3YR)
    print(f"\n  cheapest: {cheapest}")
    print(f"  Uptime {uptime:.0%} is BELOW the 3-year break-even of {be3:.0%}, so a")
    print("  commitment would be paying for capacity the autoscaler")
    print("  deliberately switches off. AUTOSCALING AND COMMITTING PULL IN")
    print("  OPPOSITE DIRECTIONS - commit the BASELINE, autoscale the peak.")

    if cheapest == "+ SUD":
        # Find the window where sustained use is genuinely the best choice.
        lo = hi = None
        for i in range(1, 1000):
            u = i / 1000
            costs = {"on-demand": u,
                     "+ SUD": BILL.sud_paid_fraction(u),
                     "CUD 1yr": 1 - BILL.CUD_1YR,
                     "CUD 3yr": 1 - BILL.CUD_3YR}
            if min(costs, key=costs.get) == "+ SUD":
                lo = u if lo is None else lo
                hi = u
        print(f"\n  AND THIS CORRECTS SOMETHING 08_billing_cost SAID. That part")
        print("  reported sustained use winning ZERO of seven rows, and")
        print("  concluded it 'is not a strategy'. It wins here.")
        print(f"\n  The window where SUD is genuinely cheapest is "
              f"{lo:.0%} to {hi:.0%} uptime:")
        print("  above 25% it beats on-demand, below the 3-year break-even it")
        print("  beats a commitment. The grid in that section sampled 25% and")
        print(f"  50% - the two ENDPOINTS - and stepped straight over the")
        print("  interior.")
        print("\n  A COARSE GRID CAN HIDE A WHOLE REGIME. The arithmetic was")
        print("  right and the sampling was wrong, which is harder to notice")
        print("  than an arithmetic error because every printed row is true.")
    scorecard.append(("cost", "RISK" if uptime < be3 else "OK",
                      f"uptime {uptime:.0%} vs 3yr break-even {be3:.0%}"))

    # ================================================== 8. building it
    rule("8. BUILDING IT REPEATABLY   (09_iac)")
    cfg = {}
    for r in [
        IAC.Resource("google_compute_network.vpc", {"name": "acme-eu"}),
        IAC.Resource("google_compute_subnetwork.web", {
            "name": "web-ew1",
            "network": "${google_compute_network.vpc.id}",
            "region": "europe-west1", "ip_cidr_range": str(plan_rows[0][3])}),
        IAC.Resource("google_compute_instance.web", {
            "name": "web-1", "zone": "europe-west1-b",
            "machine_type": f"n2-standard-{vcpu}",
            "subnetwork": "${google_compute_subnetwork.web.id}",
            "boot_image": "debian-12"}),
        IAC.Resource("google_sql_database_instance.orders", {
            "name": "orders", "region": "europe-west1",
            "database_version": "POSTGRES_15", "tier": "db-custom-2-7680"}),
        IAC.Resource("google_storage_bucket.assets", {
            "name": "acme-eu-assets", "location": "EU",
            "storage_class": best}),
    ]:
        cfg[r.address] = r

    lv = IAC.levels(cfg)
    print(f"  {len(cfg)} resources, {len(lv)} dependency levels, "
          f"widest {max(len(g) for g in lv)}")
    for i, g in enumerate(lv):
        print(f"    level {i}: {', '.join(IAC.short(a) for a in g)}")

    renamed = dict(cfg)
    renamed["google_compute_network.vpc"] = IAC.Resource(
        "google_compute_network.vpc", {"name": "acme-eu-v2"})
    acts = IAC.plan(renamed, dict(cfg), dict(cfg))
    final = IAC.cascade(renamed, acts)
    replaced = sorted(a for a, v in final.items() if v == "REPLACE")
    print(f"\n  Renaming the VPC would REPLACE {len(replaced)} of {len(cfg)}:")
    print(f"    {', '.join(IAC.short(a) for a in replaced)}")
    print("  The database and the bucket survive because they reference")
    print("  nothing. That is visible in `plan`, before anything happens.")
    scorecard.append(("repeatability", "OK",
                      f"{len(cfg)} resources in code; rename blast radius {len(replaced)}"))

    # ===================================================== 9. scorecard
    rule("9. THE SCORECARD")
    print(f"  {'area':<18} {'verdict':<7} detail")
    print("  " + "-" * 72)
    for area, verdict, detail in scorecard:
        print(f"  {area:<18} {verdict:<7} {detail}")
    risks = [s for s in scorecard if s[1] == "RISK"]
    print(f"\n  {len(scorecard) - len(risks)} OK, {len(risks)} RISK.")
    print("\n  THE THREE RISKS ARE ALL THE SAME SHAPE: a default that was")
    print("  never revisited. No min instances on the MIG, no exclusion on")
    print("  _Default, no decision about committing the baseline. None is a")
    print("  mistake exactly - each is a thing nobody chose.")
    print("\n  AND NOTE WHAT IS NOT ON THE LIST. Nothing here is broken by a")
    print("  wrong answer; the environment is correct. Everything that")
    print("  showed up is an unexamined default, which is what real review")
    print("  finds, and it is why the guardrails in section 1 matter more")
    print("  than any single resource in the build.")

    # ==================================================== 10. cheat sheet
    rule("10. THE CHEAT SHEET")
    use_house_style()
    fig = plt.figure(figsize=(16, 9.6))
    gs = fig.add_gridspec(2, 3, hspace=0.42, wspace=0.28)
    fig.suptitle("Associate Cloud Engineer - one page",
                 fontsize=15, fontweight="bold", y=0.975)

    # (a) exam weights
    ax = fig.add_subplot(gs[0, 0])
    doms = ["1. setting up", "2. planning", "3. operating", "4. access"]
    wts = [23, 30, 27, 20]
    where = ["01, 08", "03, 04, 05, 06", "07, 09", "02"]
    bars = ax.barh(doms[::-1], wts[::-1],
                   color=[PALETTE["blue"], PALETTE["green"],
                          PALETTE["orange"], PALETTE["vermillion"]][::-1])
    for b, w, p in zip(bars, wts[::-1], where[::-1]):
        ax.text(w + 0.6, b.get_y() + b.get_height() / 2, p,
                va="center", fontsize=8)
    ax.set_xlim(0, 42)
    ax.set_xlabel("% of the exam")
    ax.set_title("Domains, and which part covers them", loc="left", fontsize=11)

    # (b) the four mechanisms
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")
    ax.set_title("Four rule engines, four behaviours", loc="left", fontsize=11)
    ax.text(0, 1.0, "IAM allow", fontsize=9.5, fontweight="bold", va="top")
    ax.text(0, 0.92, "only ADDS. A weaker binding\nsubtracts nothing. Only a\n"
                     "DENY policy subtracts.", fontsize=8.5, va="top")
    ax.text(0, 0.68, "Firewall rule", fontsize=9.5, fontweight="bold", va="top")
    ax.text(0, 0.60, "FIRST MATCH by priority.\nLower number wins; deny beats\n"
                     "allow at a tie. You can outrank.", fontsize=8.5, va="top")
    ax.text(0, 0.36, "Org Policy", fontsize=9.5, fontweight="bold", va="top")
    ax.text(0, 0.28, "INTERSECTS allowed, UNIONS\ndenied, deny wins. A child can\n"
                     "RESET it - so withhold the role.", fontsize=8.5, va="top")
    ax.text(0, 0.04, "Log sinks", fontsize=9.5, fontweight="bold", va="top")
    ax.text(0, -0.04, "MULTIPLIES. Every matching sink\ngets a copy. No ordering.",
            fontsize=8.5, va="top")

    # (c) storage crossovers
    ax = fig.add_subplot(gs[0, 2])
    names, xovers = [], []
    for cold in ("NEARLINE", "COLDLINE", "ARCHIVE"):
        c, s = STORAGE.CLASSES[cold], STORAGE.CLASSES["STANDARD"]
        gap = (STORAGE.storage_cost(c, 1.0, 365)
               - STORAGE.storage_cost(s, 1.0, 365))
        names.append(cold.title())
        xovers.append(-gap / (c.retrieval_per_gb - s.retrieval_per_gb))
    ax.bar(names, xovers, color=PALETTE["sky"])
    for i, v in enumerate(xovers):
        ax.text(i, v + 0.3, f"{v:.1f}", ha="center", fontsize=9)
    ax.set_ylabel("reads/GB/year to beat Standard")
    ax.set_title("Colder is a bet on not reading", loc="left", fontsize=11)

    # (d) the cost levers for this environment
    ax = fig.add_subplot(gs[1, 0])
    ax.bar(list(levers), list(levers.values()),
           color=[PALETTE["grey"], PALETTE["blue"], PALETTE["orange"],
                  PALETTE["green"]])
    ax.axhline(levers["on-demand"], color=PALETTE["vermillion"], ls=":", lw=1)
    ax.set_ylabel("$/month, this web tier")
    ax.tick_params(axis="x", labelrotation=20, labelsize=8)
    ax.set_title(f"Levers at {uptime:.0%} uptime", loc="left", fontsize=11)

    # (e) numbers to know
    ax = fig.add_subplot(gs[1, 1])
    ax.axis("off")
    ax.set_title("Numbers worth memorising", loc="left", fontsize=11)
    lines = [
        "subnet     4 addresses reserved; /29 minimum",
        "           expand yes, shrink NEVER",
        "firewall   implied: deny ingress, allow egress @65535",
        "           health 35.191/16 + 130.211/22; IAP 35.235.240/20",
        "storage    min duration 30 / 90 / 365 days",
        "           retrieval $0.01 / $0.02 / $0.05 per GB",
        "logging    _Required 400d, free, immutable",
        "           _Default 30d; first 50 GiB/project free",
        "SUD        30% at full month; only 10% at half",
        "CUD        1yr break-even 82.5%; 3yr 50.0%",
        "uptime     99.9% = 43.2 min/month",
        "project    ID immutable; 30-day soft delete",
    ]
    for i, t in enumerate(lines):
        ax.text(0, 1.0 - i * 0.085, t, fontsize=8.2, va="top",
                family="monospace",
                fontweight="bold" if not t.startswith(" ") else "normal")

    # (f) the spine
    ax = fig.add_subplot(gs[1, 2])
    ax.axis("off")
    ax.set_title("The decision spine", loc="left", fontsize=11)
    spine = [
        ("1", "Smallest node that covers what you mean", "hierarchy"),
        ("2", "Predefined role, smallest scope, never basic", "IAM"),
        ("3", "Can it be interrupted? Is it stateless?", "compute"),
        ("4", "How OFTEN will you read it?", "storage"),
        ("5", "Same VPC = private already", "network"),
        ("6", "Duration, not threshold", "alerting"),
        ("7", "Delete > right-size > product > discount", "cost"),
        ("8", "Plan before apply; search for REPLACE", "IaC"),
    ]
    for i, (n, text, tag) in enumerate(spine):
        y = 1.0 - i * 0.125
        ax.text(0, y, n, fontsize=10, fontweight="bold",
                color=PALETTE["vermillion"], va="top")
        ax.text(0.06, y, text, fontsize=8.6, va="top")
        ax.text(0.98, y, tag, fontsize=7.6, va="top", ha="right",
                color=PALETTE["grey"])

    save_figure(fig, OUT / "cheat_sheet.png")
    print(f"  figure -> {OUT / 'cheat_sheet.png'}")
    print("\n  One page. If a row on it is not obvious, the part it came from")
    print("  is the one to re-read.")


if __name__ == "__main__":
    main()
