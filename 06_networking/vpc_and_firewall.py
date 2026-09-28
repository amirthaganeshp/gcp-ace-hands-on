"""Networking: address arithmetic you cannot undo, and rules that are not routes.

Networking is the densest part of ACE domain 2 (~30%), and it splits cleanly
into a part that is REAL ARITHMETIC - which runs here - and a part that is
Google's infrastructure, which is documented and labelled as such.

  1. The shape: a VPC is GLOBAL, a subnet is REGIONAL
  2. Sizing a subnet - the four addresses Google takes from every one
  3. Planning an address space that will not collide later
  4. The peering trap: overlapping ranges can never be joined
  5. Firewall rules - a real priority evaluator, and why your allow did nothing
  6. Getting out, and getting in: Cloud NAT and Private Google Access
  7. The load balancer matrix
  8. Connecting networks: peering vs Shared VPC vs VPN vs Interconnect

EXECUTED IN FULL for sections 2-5: the CIDR maths uses Python's ipaddress
module and the firewall evaluator implements Google's documented rules
(lowest priority number wins; deny beats allow at the same number; two
implied rules sit at 65535). Sections 6-8 are DOCUMENTED - there is no
honest local proxy for a Google load balancer.

Run:
    python 06_networking/vpc_and_firewall.py

Concept reference: ACE domain 2 (~30%) - planning and implementing.
"""

from __future__ import annotations

import ipaddress
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"

# Google reserves FOUR addresses in every subnet primary range:
#   .0      network address
#   .1      default gateway
#   last-1  second-to-last, reserved by Google for future use
#   last    broadcast
RESERVED_PER_SUBNET = 4

# A subnet primary IPv4 range cannot be smaller than /29 (8 addresses,
# 4 usable). That floor is the reason tiny subnets are a bad habit.
MIN_PREFIX = 29


def usable(net: ipaddress.IPv4Network) -> int:
    """Addresses you can actually assign to instances."""
    return net.num_addresses - RESERVED_PER_SUBNET


def prefix_for(hosts: int) -> int:
    """Smallest subnet that fits `hosts` instances, reserved addresses included."""
    needed = hosts + RESERVED_PER_SUBNET
    prefix = 32 - math.ceil(math.log2(needed))
    return min(prefix, MIN_PREFIX)


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------------------
# Firewall: Google's evaluation rules, implemented rather than described.
# ---------------------------------------------------------------------------
@dataclass
class FirewallRule:
    name: str
    priority: int                       # 0..65535, LOWER number = higher priority
    direction: str                      # INGRESS | EGRESS
    action: str                         # allow | deny
    ranges: list[str]                   # source (ingress) or destination (egress)
    ports: set[int] | None = None       # None = every port
    targets: set[str] = field(default_factory=set)   # target tags; empty = all VMs

    def matches(self, conn: "Connection") -> bool:
        if self.direction != conn.direction:
            return False
        if self.targets and not (self.targets & conn.target_tags):
            return False
        if self.ports is not None and conn.port not in self.ports:
            return False
        addr = ipaddress.ip_address(conn.peer_ip)
        return any(addr in ipaddress.ip_network(r) for r in self.ranges)


@dataclass
class Connection:
    peer_ip: str
    port: int
    direction: str
    target_tags: set[str] = field(default_factory=set)


# The two IMPLIED rules. Every VPC has them, they cannot be deleted, and they
# sit at the lowest possible priority so anything you write outranks them.
IMPLIED = [
    FirewallRule("implied-deny-ingress", 65535, "INGRESS", "deny", ["0.0.0.0/0"]),
    FirewallRule("implied-allow-egress", 65535, "EGRESS", "allow", ["0.0.0.0/0"]),
]


def evaluate(rules: list[FirewallRule], conn: Connection) -> tuple[str, str]:
    """First match wins, and the order is the exam content.

    Rules are sorted by priority NUMBER ascending - 0 is the strongest, 65535
    the weakest. At equal priority, DENY is evaluated before ALLOW. Evaluation
    stops at the first rule that matches; nothing below it is consulted.
    """
    ordered = sorted(rules + IMPLIED,
                     key=lambda r: (r.priority, 0 if r.action == "deny" else 1))
    for r in ordered:
        if r.matches(conn):
            return r.action, r.name
    return "deny", "(no rule matched)"


def main() -> None:
    print("NETWORKING - ADDRESS ARITHMETIC, AND RULES THAT ARE NOT ROUTES")

    # --------------------------------------------------------------- 1. shape
    rule("1. A VPC IS GLOBAL. A SUBNET IS REGIONAL.")
    print("""  vpc  prod-net                                      GLOBAL
    subnet  web-uc1      10.0.0.0/22     us-central1     regional
    subnet  web-ew1      10.0.8.0/22     europe-west1    regional
    subnet  batch-ase1   10.0.16.0/24    asia-southeast1 regional

  This is the single biggest structural difference from AWS, where a VPC
  is regional. Consequences that turn up in exam scenarios:

    - Instances in DIFFERENT REGIONS on the same VPC reach each other by
      INTERNAL IP, with no peering, no VPN, no gateway.
    - A subnet lives in exactly one region but spans every ZONE in it.
      There is no per-zone subnet, so a zonal outage costs you instances,
      not addresses.
    - Routes and firewall rules are GLOBAL objects on the VPC. One rule
      can apply to instances on three continents.
    - Auto mode creates a subnet in every region for you from the
      10.128.0.0/9 block. Use CUSTOM mode for anything real - and note
      you can convert auto to custom, but never custom back to auto.""")

    # ------------------------------------------------------- 2. the four IPs
    rule("2. SIZING A SUBNET - the four addresses Google takes")
    print(f"  Every subnet loses {RESERVED_PER_SUBNET} addresses: network, gateway,")
    print("  second-to-last (reserved), broadcast.\n")
    print(f"  {'prefix':<8} {'addresses':>10} {'usable':>8} {'lost':>8}")
    print("  " + "-" * 38)
    overhead = []
    for p in range(29, 19, -1):
        net = ipaddress.ip_network(f"10.0.0.0/{p}")
        u = usable(net)
        pct = RESERVED_PER_SUBNET / net.num_addresses * 100
        overhead.append((p, pct))
        print(f"  /{p:<7} {net.num_addresses:>10} {u:>8} {pct:>7.1f}%")

    tiny = usable(ipaddress.ip_network("10.0.0.0/29"))
    print(f"\n  A /29 is the SMALLEST subnet GCP allows, and it gives you {tiny}")
    print("  usable addresses - half the range is overhead. The overhead")
    print("  becomes irrelevant above about /24, which is why 'a /24 per tier'")
    print("  is the sane default rather than a tight fit.")

    # ------------------------------------------------- 3. planning the space
    rule("3. PLANNING AN ADDRESS SPACE THAT WILL NOT COLLIDE")
    demand = [
        ("web-uc1",    "us-central1",     500),
        ("app-uc1",    "us-central1",     100),
        ("data-uc1",   "us-central1",      25),
        ("web-ew1",    "europe-west1",     50),
        ("batch-ase1", "asia-southeast1",  10),
    ]
    supernet = ipaddress.ip_network("10.0.0.0/16")
    print(f"  Allocating from {supernet} ({supernet.num_addresses} addresses).\n")
    print(f"  {'subnet':<12} {'region':<17} {'want':>5} {'cidr':<16} "
          f"{'usable':>7} {'spare':>6}")
    print("  " + "-" * 70)

    cursor = int(supernet.network_address)
    plan: list[tuple[str, int, int, ipaddress.IPv4Network]] = []
    for name, region, hosts in demand:
        p = prefix_for(hosts)
        size = 2 ** (32 - p)
        # a subnet must start on its own boundary - this is the alignment rule
        cursor = (cursor + size - 1) // size * size
        net = ipaddress.ip_network((cursor, p))
        cursor += size
        plan.append((name, hosts, usable(net), net))
        print(f"  {name:<12} {region:<17} {hosts:>5} {str(net):<16} "
              f"{usable(net):>7} {usable(net) - hosts:>6}")

    wanted = sum(h for _, h, _, _ in plan)
    got = sum(n.num_addresses for _, _, _, n in plan)
    print(f"\n  requested {wanted} hosts; allocated {got} addresses "
          f"({got / wanted:.2f}x)")
    print(f"  {supernet.num_addresses - got} addresses of the /16 still free.\n")
    print("  THE RULE THAT COSTS PEOPLE A REBUILD: you can EXPAND a subnet's")
    print("  primary range later, but you can never SHRINK it and you can")
    print("  never expand it into something already allocated. Leave gaps on")
    print("  purpose. The addresses are free; the migration is not.")
    print("\n  GKE needs two SECONDARY ranges on top of this - one for pods,")
    print("  one for services - and the pod range is the one that is always")
    print("  too small. A /21 primary with a /17 pod range is not unusual.")

    # --------------------------------------- 3b. what dense packing costs
    rule("3b. DENSE PACKING vs PER-REGION BLOCKS")
    regions = sorted({r for _, r, _ in demand})

    # Read the interleaving out of the plan rather than asserting it.
    ordered_plan = sorted(zip((r for _, r, _ in demand), plan),
                          key=lambda t: int(t[1][3].network_address))
    interleaved = [
        (ordered_plan[i][1][0], ordered_plan[i][1][3], ordered_plan[i][0])
        for i in range(1, len(ordered_plan) - 1)
        if ordered_plan[i][0] != ordered_plan[i - 1][0]
        and ordered_plan[i][0] != ordered_plan[i + 1][0]
    ]
    print("  Look at what the packer above actually produced, in address order:\n")
    for region, (name, _, _, net) in ordered_plan:
        print(f"    {str(net):<16} {name:<12} {region}")
    if interleaved:
        for name, net, region in interleaved:
            print(f"\n  {region} landed at {net}, wedged BETWEEN subnets of")
            print("  another region.")
        print("  It is the smallest possible plan and it is the wrong one.\n")
    else:
        print("\n  (nothing interleaved this time - but nothing prevented it)\n")
    by_region: dict[str, list[ipaddress.IPv4Network]] = {r: [] for r in regions}
    for (name, region, _), (_, _, _, net) in zip(demand, plan):
        by_region[region].append(net)

    print(f"  {'region':<17} {'subnets':>7}  summarised as")
    print("  " + "-" * 60)
    dense_summary = 0
    for region, nets in by_region.items():
        merged = list(ipaddress.collapse_addresses(nets))
        # can one CIDR cover this region without swallowing another region's?
        span = ipaddress.ip_network(
            (min(int(n.network_address) for n in nets),
             32 - math.ceil(math.log2(
                 max(int(n.broadcast_address) for n in nets)
                 - min(int(n.network_address) for n in nets) + 1))),
            strict=False)
        foreign = [n for r2, ns in by_region.items() if r2 != region
                   for n in ns if span.overlaps(n)]
        dense_summary += len(merged)
        verdict = (f"{len(merged)} CIDR(s)" if not foreign
                   else f"{len(merged)} CIDR(s) - any single CIDR also "
                        f"swallows {len(foreign)} foreign subnet(s)")
        print(f"  {region:<17} {len(nets):>7}  {verdict}")

    # The alternative: a /20 per region, blocked and aligned, gaps on purpose.
    BLOCK = 20
    print(f"\n  The alternative - one aligned /{BLOCK} per region, gaps on purpose:\n")
    print(f"  {'region':<17} {'block':<16} {'addresses':>10} {'in use':>7} {'headroom':>9}")
    print("  " + "-" * 64)
    cursor2 = int(supernet.network_address)
    block_total = 0
    blocks: dict[str, ipaddress.IPv4Network] = {}
    for region in regions:
        block = ipaddress.ip_network((cursor2, BLOCK))
        blocks[region] = block
        cursor2 += block.num_addresses
        used = sum(n.num_addresses for n in by_region[region])
        block_total += block.num_addresses
        print(f"  {region:<17} {str(block):<16} {block.num_addresses:>10} "
              f"{used:>7} {block.num_addresses - used:>9}")

    print(f"\n  dense plan   {got:>6} addresses, {dense_summary} CIDR(s) to describe it")
    print(f"  blocked plan {block_total:>6} addresses, {len(regions)} CIDR(s) - one per region")
    print(f"  cost of blocking: {block_total - got} addresses, "
          f"{(block_total - got) / supernet.num_addresses * 100:.0f}% of the /16")
    print(f"  still free afterwards: {supernet.num_addresses - block_total}\n")
    print("  THE TRADE IS NOT ABOUT ADDRESSES. Private address space is free;")
    print("  what you are really buying with a blocked plan is:")
    print("    - ONE route, firewall range or VPN advertisement per region")
    print("      instead of one per subnet")
    print("    - room to EXPAND each subnet in place, which is the only")
    print("      resize direction that exists")
    eu = next((r for r in regions if r.startswith("europe")), regions[0])
    print(f"    - a sentence you can say out loud: '{blocks[eu]} is {eu}'")
    print("\n  Pack densely only when the /16 is genuinely scarce - which, on")
    print("  RFC 1918 space, it almost never is.")

    # --------------------------------------------------- 4. the peering trap
    rule("4. THE PEERING TRAP - overlap is permanent")
    ours = ipaddress.ip_network("10.0.0.0/16")
    candidates = [
        ("acquired-co VPC", ipaddress.ip_network("10.0.0.0/16")),
        ("partner VPC",     ipaddress.ip_network("10.1.0.0/16")),
        ("on-prem via VPN", ipaddress.ip_network("192.168.0.0/16")),
        ("lab VPC",         ipaddress.ip_network("10.0.128.0/17")),
    ]
    print(f"  Our network: {ours}\n")
    print(f"  {'network to join':<20} {'cidr':<18} {'overlaps':>9}  can peer?")
    print("  " + "-" * 62)
    for label, net in candidates:
        clash = ours.overlaps(net)
        print(f"  {label:<20} {str(net):<18} {str(clash):>9}  "
              f"{'NO' if clash else 'yes'}")
    print("\n  VPC PEERING REFUSES OVERLAPPING RANGES. There is no NAT in the")
    print("  peering path and no way to renumber on the fly - one side has to")
    print("  be rebuilt on a different range. That is why 10.0.0.0/16 for")
    print("  everything is a decision you regret during an acquisition.")
    print("\n  Note the lab VPC: a /17 sitting INSIDE our /16 still overlaps.")
    print("  Containment is overlap.")
    print("\n  Peering is also NON-TRANSITIVE. A-B and B-C does not give you")
    print("  A-C; you need A-C explicitly, and then all three must be")
    print("  mutually non-overlapping.")

    # ------------------------------------------------------- 5. the firewall
    rule("5. FIREWALL RULES - why your allow did nothing")

    security_lockdown = FirewallRule(
        "sec-deny-public-ingress", 900, "INGRESS", "deny", ["0.0.0.0/0"])
    allow_web = FirewallRule(
        "allow-http-https", 1000, "INGRESS", "allow", ["0.0.0.0/0"],
        ports={80, 443}, targets={"web"})
    allow_health = FirewallRule(
        "allow-health-checks", 800, "INGRESS", "allow",
        ["35.191.0.0/16", "130.211.0.0/22"], ports={80}, targets={"web"})
    allow_iap = FirewallRule(
        "allow-iap-ssh", 1000, "INGRESS", "allow", ["35.235.240.0/20"],
        ports={22}, targets={"web"})

    web = {"web"}
    traffic = [
        ("browser on the internet -> :443",
         Connection("203.0.113.9", 443, "INGRESS", web)),
        ("Google health checker  -> :80",
         Connection("35.191.2.7", 80, "INGRESS", web)),
        ("IAP tunnel for SSH     -> :22",
         Connection("35.235.240.5", 22, "INGRESS", web)),
        ("someone scanning       -> :3389",
         Connection("198.51.100.4", 3389, "INGRESS", web)),
        ("the VM calling an API  -> :443",
         Connection("142.250.1.1", 443, "EGRESS", web)),
    ]

    staged = [allow_health, security_lockdown, allow_web, allow_iap]
    print("  Rules in the VPC (plus the two implied rules at 65535):\n")
    for r in sorted(staged, key=lambda r: r.priority):
        ports = "all" if r.ports is None else ",".join(str(p) for p in sorted(r.ports))
        print(f"    {r.priority:>5}  {r.action:<5} {r.direction:<7} "
              f"{r.name:<24} ports={ports}")

    print("\n  FIRST, WITHOUT the security team's rule:")
    print(f"  {'traffic':<34} {'verdict':<7} matched")
    print("  " + "-" * 72)
    without = [allow_health, allow_web, allow_iap]
    before_verdicts = {}
    for label, conn in traffic:
        verdict, why = evaluate(without, conn)
        before_verdicts[label] = verdict
        print(f"  {label:<34} {verdict:<7} {why}")

    print("\n  NOW the security team adds a blanket deny at priority 900:")
    print(f"  {'traffic':<34} {'verdict':<7} matched")
    print("  " + "-" * 72)
    after_verdicts = {}
    for label, conn in traffic:
        verdict, why = evaluate(staged, conn)
        after_verdicts[label] = verdict
        print(f"  {label:<34} {verdict:<7} {why}")

    broken = [k for k in before_verdicts if before_verdicts[k] != after_verdicts[k]]
    print(f"\n  {len(broken)} of {len(traffic)} flows changed verdict:")
    for k in broken:
        print(f"    {k:<34} {before_verdicts[k]} -> {after_verdicts[k]}")
    print("\n  The health check at priority 800 SURVIVED - it outranks the deny.")
    print("\n  LOWER NUMBER WINS. Adding another allow at 1000, or at 5000, or")
    print("  at 65534, changes nothing at all - evaluation never reaches it.")
    print("\n  At the SAME priority number, DENY beats ALLOW.")

    # -------------------------------- 5b. where the firewall differs from IAM
    print("\n  But now the contrast that matters. Re-add the IAP rule at")
    print("  priority 100 instead of 1000 and re-run the same traffic:\n")
    outranking = [allow_health, security_lockdown, allow_web,
                  FirewallRule("allow-iap-ssh", 100, "INGRESS", "allow",
                               ["35.235.240.0/20"], ports={22}, targets={"web"})]
    print(f"  {'traffic':<34} {'verdict':<7} matched")
    print("  " + "-" * 72)
    for label, conn in traffic:
        verdict, why = evaluate(outranking, conn)
        print(f"  {label:<34} {verdict:<7} {why}")

    print("\n  THE FIREWALL IS NOT IAM. In 02_iam, binding a weaker role could")
    print("  not take anything away, and there was no number to change - the")
    print("  only subtraction in the whole system is a DENY POLICY.")
    print("  Here, PRIORITY is an explicit lever: a rule you write can outrank")
    print("  a deny someone else wrote, in either direction, at any time.")
    print("\n  Which is the security lesson too. A blanket deny at 900 is NOT a")
    print("  guardrail - anyone with compute.securityAdmin can write 100 and")
    print("  walk straight past it. Real guardrails are ORG POLICY and IAM")
    print("  DENY, which live above the project. See 01_resource_hierarchy.")
    print("\n  Note the egress result: it was allowed by the IMPLIED rule, with")
    print("  no rule written. Egress is open by default; ingress is closed by")
    print("  default. Half of 'it cannot reach the internet' tickets are")
    print("  actually a missing route or NAT, not a firewall rule - see 6.")

    # ------------------------------------------------------ 6. out, and in
    rule("6. GETTING OUT, AND GETTING IN   [documented]")
    print("""  A FIREWALL RULE IS NOT A ROUTE. Allowing egress does not give an
  instance a path; it only declines to stop one. An instance with no
  external IP has no path to the internet no matter what you allow.

    Cloud NAT               outbound only, no external IPs on the VMs.
                            Regional, managed, needs a Cloud Router. This
                            is the answer to "private VMs need to reach
                            the internet for patches".
                            It CANNOT be used for inbound - there is no
                            port forwarding.

    Private Google Access   a SUBNET setting. Lets instances with no
                            external IP reach Google APIs and services
                            over internal paths. Free, and the right
                            answer when the only destination is Google -
                            you do not need NAT for that.

    Private Service Connect / VPC Service Controls go further: reach a
    service by a private endpoint inside your VPC, and draw a perimeter
    that data cannot leave.

    External IP             ephemeral by default; it changes on stop/start.
                            Reserve a STATIC one for anything DNS points at.

    Cloud DNS               managed zones; a PRIVATE zone resolves only
                            inside the VPCs you authorise.""")

    # ------------------------------------------- 7. load balancer selection
    rule("7. THE LOAD BALANCER MATRIX   [documented]")
    print("""  Pick on three questions: external or internal, what protocol,
  and does it need to be global.

    what you are told                           what to choose
    ---------------------------------------------------------------------
    HTTP(S), worldwide users, one anycast IP    GLOBAL EXTERNAL
                                                APPLICATION LB
    HTTP(S), URL-based routing, Cloud CDN,      same - these are all
    Cloud Armor, SSL offload                    layer-7 features
    TCP/UDP, must preserve client IP,           EXTERNAL PASSTHROUGH
    extreme throughput, any port                NETWORK LB (layer 4)
    TLS that is not HTTP, needs offload         PROXY NETWORK LB
    only inside the VPC, layer 7                INTERNAL APPLICATION LB
    only inside the VPC, layer 4                INTERNAL PASSTHROUGH
                                                NETWORK LB
    one region, no need for global anycast      any REGIONAL variant

  Two facts that decide most questions:
    - Only the GLOBAL application LB gives you ONE anycast IP worldwide
      and layer-7 routing. If the scenario mentions Cloud CDN, Cloud
      Armor, or path-based routing, it is this one.
    - PASSTHROUGH means the packet arrives with the ORIGINAL client IP
      and nothing is terminated. If the scenario insists on seeing the
      client IP or on a non-HTTP protocol, it is not a proxy LB.

  Autoscaling belongs to the managed instance group behind the LB, not
  to the LB itself - see 03_compute.""")

    # --------------------------------------------- 8. connecting networks
    rule("8. CONNECTING NETWORKS   [documented]")
    print("""    VPC PEERING        two VPCs, private, no charge for the link
                       itself, NON-TRANSITIVE, ranges must not overlap.
                       Each side administers its own network.

    SHARED VPC         one HOST project owns the network; SERVICE
                       projects attach and run instances in it. This is
                       the answer to "central network team, separate
                       project per team, one address space".
                       Peering joins NETWORKS; Shared VPC joins PROJECTS
                       to one network. Do not confuse them.

    CLOUD VPN          IPsec over the public internet. HA VPN gives an
                       SLA and two interfaces. Quick, cheap, bandwidth
                       limited per tunnel.

    CLOUD INTERCONNECT Dedicated (a physical link into a Google facility)
                       or Partner (through a service provider). The
                       answer when the scenario says consistent high
                       bandwidth, low latency, or "not over the public
                       internet".

    Choosing: internet is fine -> VPN. Not fine, or you need tens of
    gigabits -> Interconnect. Both ends are yours in GCP -> peering or
    Shared VPC.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4))

    prefixes = [p for p, _ in overhead]
    pcts = [pc for _, pc in overhead]
    ax1.plot([f"/{p}" for p in prefixes], pcts, "o-", color=PALETTE["vermillion"])
    ax1.set_ylabel("addresses lost to reservation (%)")
    ax1.set_xlabel("subnet prefix")
    ax1.set_title("The 4-address tax, by subnet size", loc="left")

    names = [n for n, _, _, _ in plan]
    want = [h for _, h, _, _ in plan]
    alloc = [n.num_addresses for _, _, _, n in plan]
    x = range(len(names))
    ax2.bar([i - 0.2 for i in x], want, width=0.4,
            label="hosts requested", color=PALETTE["blue"])
    ax2.bar([i + 0.2 for i in x], alloc, width=0.4,
            label="addresses allocated", color=PALETTE["orange"])
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(names, rotation=30, ha="right")
    ax2.set_yscale("log")
    ax2.legend()
    ax2.set_title("Rounding up to a power of two", loc="left")
    save_figure(fig, OUT / "vpc_and_firewall.png")
    print(f"\n  figure -> {OUT / 'vpc_and_firewall.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "instances in two regions must talk         same VPC, internal IPs.
   privately"                                 Nothing else needed
  "private VMs need OS patches from the       CLOUD NAT (+ Cloud Router)
   internet"
  "private VMs only need Google APIs"         PRIVATE GOOGLE ACCESS on
                                              the subnet - not NAT
  "I added an allow rule and it is still      a lower-NUMBERED deny is
   blocked"                                   winning. Change THAT rule
  "stop anyone opening 0.0.0.0/0 to the       ORG POLICY, not a firewall
   internet"                                  deny - priority can be
                                              outranked
  "central network team, one project per      SHARED VPC
   team"
  "merge two networks, both on 10.0.0.0/16"   you cannot peer them.
                                              One must be renumbered
  "global HTTP(S) with one IP and a WAF"      global external APPLICATION
                                              LB + Cloud Armor
  "must see the real client IP"               PASSTHROUGH network LB
  "the subnet is full"                        EXPAND the primary range.
                                              You cannot shrink it back""")


if __name__ == "__main__":
    main()
