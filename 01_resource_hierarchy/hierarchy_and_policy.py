"""The resource hierarchy: where a setting attaches decides who it reaches.

Domain 1 of the ACE exam (~23%) is "setting up a cloud solution environment",
and nearly all of it is one idea: EVERYTHING ATTACHES SOMEWHERE IN A TREE,
and where you attach it decides both its reach and who can change it.

  1. The hierarchy, and the blast radius of attaching at each level
  2. Projects: three identifiers, and which one is forever
  3. Organization Policy - a real evaluator                   [runnable]
  4. Org Policy vs IAM, and why only one of them is a guardrail
  5. Quotas: which one actually stops your deployment        [arithmetic]
  6. Billing structure
  7. Labels vs tags vs network tags - three things, similar names

SECTION 3 IS A REAL EVALUATOR implementing Google's documented inheritance
and merge rules; section 5 is arithmetic. Sections 1, 2, 6 and 7 are
documented, with the blast-radius counts in 1 computed from the tree.

This part completes two threads left open elsewhere in the repository:
02_iam showed that allow policies only ever ADD, and 06_networking showed
that a firewall deny is not a guardrail because priority can outrank it.
Section 4 here shows what an actual guardrail is made of.

Run:
    python 01_resource_hierarchy/hierarchy_and_policy.py

Concept reference: ACE domain 1 (~23%) - setting up the environment.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"


# ---------------------------------------------------------------------------
# The tree.
# ---------------------------------------------------------------------------
@dataclass
class Node:
    name: str
    kind: str                                    # organization | folder | project
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)
    # constraint name -> policy set AT THIS NODE
    list_policies: dict[str, "ListPolicy"] = field(default_factory=dict)
    bool_policies: dict[str, bool] = field(default_factory=dict)

    def add(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    def chain(self) -> list["Node"]:
        """Root first, this node last."""
        out, n = [], self
        while n:
            out.append(n)
            n = n.parent
        return list(reversed(out))

    def projects(self) -> list["Node"]:
        """Every project at or below this node - the blast radius."""
        if self.kind == "project":
            return [self]
        return [p for c in self.children for p in c.projects()]


@dataclass
class ListPolicy:
    """A list constraint, as the API actually models it."""
    allowed: set[str] | None = None       # None = "no allow list at this node"
    denied: set[str] = field(default_factory=set)
    inherit_from_parent: bool = True


def effective_list_policy(node: Node, constraint: str) -> tuple[set[str] | None,
                                                                set[str], str]:
    """Resolve a list constraint down the chain. THE RULES:

      1. Walk from the ROOT down to the node.
      2. inheritFromParent = FALSE is a RESET. Everything above is discarded
         and this node's policy stands alone. This is the override mechanism,
         and it is the whole of section 4.
      3. inheritFromParent = TRUE merges: allowed values INTERSECT, denied
         values UNION.
      4. DENY WINS. A value denied anywhere in the surviving chain is denied,
         even if a node below explicitly allows it.

    Returns (allowed, denied, where_it_was_last_reset).
    """
    allowed: set[str] | None = None
    denied: set[str] = set()
    source = "(default - unrestricted)"

    for anc in node.chain():
        pol = anc.list_policies.get(constraint)
        if pol is None:
            continue
        if not pol.inherit_from_parent:
            allowed = set(pol.allowed) if pol.allowed is not None else None
            denied = set(pol.denied)
            source = f"{anc.name} (RESET - inheritFromParent=false)"
            continue
        if pol.allowed is not None:
            allowed = set(pol.allowed) if allowed is None else allowed & pol.allowed
        denied |= pol.denied
        source = anc.name if source.startswith("(default") else source
    return allowed, denied, source


def value_permitted(node: Node, constraint: str, value: str) -> bool:
    allowed, denied, _ = effective_list_policy(node, constraint)
    if value in denied:
        return False
    return allowed is None or value in allowed


def effective_bool_policy(node: Node, constraint: str) -> tuple[bool, str]:
    """Boolean constraints: the CLOSEST policy in the chain wins.

    A policy set on a node overrides its parent for that node and everything
    below it. There is no merge and no intersection - it is simply the
    nearest setting. Unset anywhere in the chain means not enforced.
    """
    for anc in reversed(node.chain()):
        if constraint in anc.bool_policies:
            return anc.bool_policies[constraint], anc.name
    return False, "(unset - not enforced)"


# ---------------------------------------------------------------------------
# 5. Quotas.
# ---------------------------------------------------------------------------
@dataclass
class Quota:
    name: str
    scope: str            # "regional" or "global"
    limit: int
    unit: str


# Representative defaults for a NEW project with billing enabled. Real limits
# vary by project age, spend history and region - check the console. The
# SHAPE is what matters: several quotas apply to one deployment at once.
QUOTAS = [
    Quota("CPUS (per region)", "regional", 72, "vCPU"),
    Quota("N2_CPUS (per region)", "regional", 48, "vCPU"),
    Quota("CPUS_ALL_REGIONS", "global", 96, "vCPU"),
    Quota("IN_USE_ADDRESSES (per region)", "regional", 8, "external IP"),
    Quota("DISKS_TOTAL_GB (per region)", "regional", 4096, "GB"),
    Quota("INSTANCES (per region)", "regional", 100, "instances"),
]


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def build_tree() -> tuple[Node, dict[str, Node]]:
    org = Node("acme.com", "organization")
    core = org.add(Node("core-infra", "folder"))
    core.add(Node("net-hub", "project"))
    core.add(Node("logging", "project"))
    product = org.add(Node("product", "folder"))
    eu = product.add(Node("product-eu", "folder"))
    eu.add(Node("shop-eu-prod", "project"))
    eu.add(Node("shop-eu-dev", "project"))
    us = product.add(Node("product-us", "folder"))
    us.add(Node("shop-us-prod", "project"))
    us.add(Node("shop-us-dev", "project"))
    org.add(Node("sandbox-alice", "project"))

    index = {}

    def walk(n: Node) -> None:
        index[n.name] = n
        for c in n.children:
            walk(c)
    walk(org)
    return org, index


def main() -> None:
    print("THE RESOURCE HIERARCHY - WHERE A SETTING ATTACHES DECIDES ITS REACH")
    org, idx = build_tree()

    # ------------------------------------------------------ 1. the tree
    rule("1. THE HIERARCHY, AND BLAST RADIUS")
    print("""  organization  acme.com
    folder        core-infra
      project       net-hub
      project       logging
    folder        product
      folder        product-eu
        project       shop-eu-prod
        project       shop-eu-dev
      folder        product-us
        project       shop-us-prod
        project       shop-us-dev
    project       sandbox-alice

  FOLDERS EXIST TO BE A POLICY BOUNDARY, not to be tidy. A folder that
  groups projects nobody ever applies a shared policy to is decoration.
  Folders can nest (up to 10 deep); projects cannot contain projects.

  What an IAM binding or an Org Policy at each node reaches:\n""")
    radius = []
    for name in ("acme.com", "product", "product-eu", "core-infra",
                 "shop-eu-prod"):
        n = idx[name]
        hits = n.projects()
        radius.append((name, len(hits)))
        print(f"  {n.kind:<13} {name:<15} -> {len(hits)} project(s): "
              f"{', '.join(p.name for p in hits)}")

    print("\n  The organization node is not 'the top of the tidy tree', it is")
    print(f"  A SWITCH WITH {radius[0][1]} PROJECTS BEHIND IT. Everything in domain 1 -")
    print("  IAM, Org Policy, billing, logging sinks - inherits downward, so")
    print("  the only real question is ever: THE SMALLEST NODE THAT COVERS")
    print("  WHAT I MEAN.")
    print("\n  There is exactly one thing above the organization: nothing.")
    print("  You cannot attach a policy higher, which is why the org node is")
    print("  the only place a guardrail can be truly unavoidable.")

    # --------------------------------------------------------- 2. projects
    rule("2. PROJECTS - three identifiers, and which one is forever")
    print("""    PROJECT ID      globally unique across ALL of Google Cloud,
                    chosen by you, and IMMUTABLE. This is what almost
                    every CLI command and API call takes. You cannot
                    rename it, ever. A deleted ID is not reusable.
    PROJECT NAME    a display label. Not unique, and you can change it.
    PROJECT NUMBER  generated, numeric, immutable. Turns up in service
                    account emails and some API paths.

  The one that appears in an exam question as a trap is the ID: "rename
  the project" is only ever the NAME, and if the ID is wrong the answer
  is a new project plus a migration.

  THE PROJECT IS THE UNIT OF nearly everything:
    - billing attaches per project
    - QUOTAS are per project (section 5 - this is why "just use more
      projects" is a legitimate architecture, not a hack)
    - IAM policies, APIs enabled, and resources all live in one
    - deleting a project deletes everything in it

  DELETION is a 30-DAY soft delete: the project goes to a pending state
  and can be restored. A LIEN blocks deletion entirely until removed -
  that is the answer to "stop anyone deleting the production project".

  MOVING a project between folders is allowed and re-resolves every
  inherited policy immediately. That is a useful tool and a very good
  way to surprise yourself.""")

    # ------------------------------------------------- 3. the org policy
    rule("3. ORGANIZATION POLICY - a real evaluator")
    print("""  Org Policy is NOT IAM. IAM says WHO may act. Org Policy says WHAT
  configurations are permitted to exist, no matter who is asking. An
  owner of the project cannot create a resource an Org Policy forbids.

  Two kinds of constraint:
    BOOLEAN  enforced or not. The CLOSEST policy in the chain wins.
    LIST     allowed / denied values, with inheritFromParent. Merging
             INTERSECTS allowed values and UNIONS denied ones, and
             DENY ALWAYS WINS.\n""")

    LOC = "constraints/gcp.resourceLocations"
    org.list_policies[LOC] = ListPolicy(
        allowed={"us-central1", "us-east1", "europe-west1", "europe-west4"})
    idx["product-eu"].list_policies[LOC] = ListPolicy(
        denied={"us-central1", "us-east1"})
    idx["product-us"].list_policies[LOC] = ListPolicy(
        denied={"europe-west1", "europe-west4"})

    regions = ["us-central1", "us-east1", "europe-west1", "europe-west4",
               "asia-east1"]
    print(f"  {LOC}")
    print("    organization  allow [us-central1, us-east1, europe-west1, europe-west4]")
    print("    product-eu    deny  [us-central1, us-east1]")
    print("    product-us    deny  [europe-west1, europe-west4]\n")
    print(f"  {'project':<16}", end="")
    for r in regions:
        print(f" {r:>14}", end="")
    print()
    print("  " + "-" * 88)
    allowed_counts = {}
    for pname in ("net-hub", "shop-eu-prod", "shop-us-prod", "sandbox-alice"):
        n = idx[pname]
        print(f"  {pname:<16}", end="")
        ok = 0
        for r in regions:
            p = value_permitted(n, LOC, r)
            ok += p
            print(f" {'yes' if p else 'NO':>14}", end="")
        allowed_counts[pname] = ok
        print()

    print("\n  asia-east1 is refused EVERYWHERE, and no node mentions it. An")
    print("  allow list is a WHITELIST: anything not on it is denied, which")
    print("  is the behaviour people forget when they add one region and")
    print("  wonder why a different team's deployment broke.")
    print("\n  And note the EU and US folders: each denies what the other")
    print("  needs, from a single org-level allow list. That is data")
    print("  residency expressed in two lines, enforced on everyone.")

    # ------------------------------------------------ 4. the guardrail
    rule("4. ORG POLICY vs IAM - only one of them is a guardrail")

    EXTIP = "constraints/compute.vmExternalIpAccess"
    org.list_policies[EXTIP] = ListPolicy(allowed=set())      # allow nothing
    print(f"  {EXTIP}")
    print("    organization  allow []      (no VM may have an external IP)\n")
    before = value_permitted(idx["shop-us-dev"], EXTIP,
                             "projects/shop-us-dev/zones/us-central1-a/instances/bastion")
    print(f"  can shop-us-dev give a VM an external IP?   {before}")

    print("\n  Now the dev team needs one bastion host. They set a policy AT")
    print("  THEIR PROJECT with inheritFromParent = FALSE:\n")
    bastion = "projects/shop-us-dev/zones/us-central1-a/instances/bastion"
    idx["shop-us-dev"].list_policies[EXTIP] = ListPolicy(
        allowed={bastion}, inherit_from_parent=False)
    after = value_permitted(idx["shop-us-dev"], EXTIP, bastion)
    other = value_permitted(idx["shop-us-dev"], EXTIP,
                            "projects/shop-us-dev/zones/us-central1-a/instances/web")
    sibling = value_permitted(idx["shop-us-prod"], EXTIP, bastion)
    _, _, src = effective_list_policy(idx["shop-us-dev"], EXTIP)
    print(f"  can the BASTION now have an external IP?     {after}")
    print(f"  can any OTHER VM in that project?            {other}")
    print(f"  did it affect the sibling prod project?      {sibling}")
    print(f"  effective policy now sourced from            {src}")

    print("\n  THE ORG-LEVEL POLICY WAS OVERRIDDEN AT THE PROJECT. That is by")
    print("  design - inheritFromParent=false is the documented escape hatch,")
    print("  and without it every exception would have to be granted at the")
    print("  organization, where it would apply to everybody.")
    print("\n  SO WHAT MAKES IT A GUARDRAIL? Not the mechanism. The IAM")
    print("  permission to use it: orgpolicy.policies.create, carried by")
    print("  roles/orgpolicy.policyAdmin. Grant that at the organization")
    print("  only, and a project team CANNOT do what the block above just")
    print("  did - they have to ask.")
    print("\n  THE THREE MECHANISMS, SIDE BY SIDE:")
    print("""
    IAM ALLOW        purely additive. A weaker binding lower down
                     subtracts nothing.                      [02_iam]
    FIREWALL RULE    priority. A rule you write can outrank someone
                     else's deny, so a deny is not a guardrail.
                                                       [06_networking]
    ORG POLICY       restricts what may EXIST, regardless of IAM. It
                     can be overridden at a child - so the guardrail
                     is really the IAM permission that lets you.

  Which is the actual lesson: A GUARDRAIL IS NOT A MECHANISM, IT IS A
  MECHANISM PLUS CONTROL OF WHO CAN CHANGE IT. The only two that hold
  against a determined project owner are an Org Policy and an IAM DENY
  policy, both attached ABOVE them, with the admin role withheld.""")

    SAKEY = "constraints/iam.disableServiceAccountKeyCreation"
    org.bool_policies[SAKEY] = True
    idx["sandbox-alice"].bool_policies[SAKEY] = False
    print(f"\n  A BOOLEAN constraint, for contrast: {SAKEY.split('/')[1]}")
    for pname in ("shop-eu-prod", "sandbox-alice"):
        enforced, where = effective_bool_policy(idx[pname], SAKEY)
        print(f"    {pname:<16} enforced={str(enforced):<6} set at {where}")
    print("\n  Closest wins - no merge, no intersection. This particular")
    print("  constraint is the platform-level answer to 02_iam's 'avoid")
    print("  downloading service account keys': not a policy document asking")
    print("  people not to, but the API refusing.")

    # ------------------------------------------------------- 5. quotas
    rule("5. QUOTAS - which one actually stops your deployment   [arithmetic]")
    print("  [representative defaults for a new project with billing on -")
    print("   real limits vary by project age, spend history and region]\n")
    fleet_n = 8
    vcpu_each = 8
    disk_each = 200
    ext_ips = 8
    print(f"  THE PLAN: {fleet_n} x n2-standard-{vcpu_each} in us-central1, "
          f"{disk_each} GB boot disk")
    print(f"  each, {ext_ips} of them with an external IP.\n")
    usage = {
        "CPUS (per region)": fleet_n * vcpu_each,
        "N2_CPUS (per region)": fleet_n * vcpu_each,
        "CPUS_ALL_REGIONS": fleet_n * vcpu_each,
        "IN_USE_ADDRESSES (per region)": ext_ips,
        "DISKS_TOTAL_GB (per region)": fleet_n * disk_each,
        "INSTANCES (per region)": fleet_n,
    }
    print(f"  {'quota':<32} {'scope':<9} {'need':>7} {'limit':>7} "
          f"{'headroom':>9}  ")
    print("  " + "-" * 72)
    binding = []
    for q in QUOTAS:
        used = usage[q.name]
        head = q.limit - used
        flag = ("  <-- BLOCKS" if head < 0
                else "  <-- exactly at the limit, which is allowed" if head == 0
                else "")
        if head < 0:
            binding.append(q.name)
        print(f"  {q.name:<32} {q.scope:<9} {used:>7} {q.limit:>7} "
              f"{head:>9}{flag}")

    print(f"\n  {len(binding)} quota(s) block this deployment: "
          f"{', '.join(binding) if binding else 'none'}")
    print("  (headroom 0 is fine - a quota is a ceiling you may sit on, not")
    print("   one you must stay under)")

    # For each quota independently: the largest fleet of this shape it allows.
    def need_at(name: str, n: int) -> int:
        return {"CPUS (per region)": n * vcpu_each,
                "N2_CPUS (per region)": n * vcpu_each,
                "CPUS_ALL_REGIONS": n * vcpu_each,
                "IN_USE_ADDRESSES (per region)": min(ext_ips, n),
                "DISKS_TOTAL_GB (per region)": n * disk_each,
                "INSTANCES (per region)": n}[name]

    ceilings = []
    for q in QUOTAS:
        n = 0
        while n < 10_000 and need_at(q.name, n + 1) <= q.limit:
            n += 1
        ceilings.append((q.name, n))
    max_fleet, binding_quota = min((n, name) for name, n in ceilings)

    print(f"\n  {'quota':<32} largest fleet it alone allows")
    print("  " + "-" * 62)
    for name, n in sorted(ceilings, key=lambda t: t[1]):
        mark = "  <-- the binding one" if name == binding_quota else ""
        shown = "no limit at this shape" if n >= 10_000 else f"{n}"
        print(f"  {name:<32} {shown:>8}{mark}")

    print(f"\n  THE PLAN ASKED FOR {fleet_n}. THE LARGEST THAT FITS IS "
          f"{max_fleet}, and the quota")
    print(f"  that stops it is {binding_quota}.")
    print("\n  NOTE WHICH ONE IT IS. Not the instance count - the number the")
    print("  plan was written in - and not the general CPU quota either, but")
    print("  the PER-MACHINE-FAMILY one, which most people do not know")
    print("  exists until it fires. ONE DEPLOYMENT CONSUMES SEVERAL QUOTAS")
    print("  AT ONCE, and the one that stops you is rarely the one you were")
    print("  thinking about.")
    print("\n  Switching family would move the ceiling without changing a")
    print("  single thing about the workload, which is worth knowing before")
    print("  you file a quota request that takes two days.")
    print("\n  TWO KINDS OF QUOTA, and the exam distinguishes them:")
    print("    RATE quotas       requests per minute / per day. They RESET.")
    print("                      A 429 here means slow down and retry.")
    print("    ALLOCATION quotas things you HOLD - vCPUs, IP addresses,")
    print("                      disks. They do not reset. You release the")
    print("                      resource or you request an increase.")
    print("\n  Quotas are PER PROJECT and mostly PER REGION. Three")
    print("  consequences that answer real questions:")
    print("    - 'we hit a quota' -> more projects is a valid answer, and")
    print("      often the intended one")
    print("    - deploying to a second region does NOT use the first")
    print("      region's regional quota, but DOES use CPUS_ALL_REGIONS")
    print("    - a quota increase is a REQUEST, not a setting. It takes")
    print("      time, so it belongs in the plan, not in the incident")
    print("\n  Quotas are not LIMITS. Some caps are architectural and cannot")
    print("  be raised at any price.")

    # ------------------------------------------------------ 6. billing
    rule("6. BILLING STRUCTURE   [documented]")
    print("""  A BILLING ACCOUNT IS NOT IN THE PROJECT TREE. It is a separate
  resource that projects are LINKED to, which is why billing admins
  and project admins are usually different people.

    - one project links to exactly ONE billing account
    - one billing account can pay for MANY projects
    - a project with no billing account linked cannot use most
      services. "It worked yesterday" plus "everything is failing"
      plus "nothing changed" is very often a closed billing account
    - moving a project between billing accounts needs permission on
      BOTH: billing.resourceAssociations.create on the target and
      the project, and billing.resourceAssociations.delete on the
      source

  ROLES worth knowing by name, because the exam names them:
    roles/billing.admin          manage the billing account
    roles/billing.user           LINK projects to it - this is the one
                                 that lets someone create a project
                                 that actually works
    roles/billing.viewer         see the spend
    roles/billing.creator        create new billing accounts

  BILLING EXPORT TO BIGQUERY is the answer to nearly every "analyse
  our spend" question. The console reports are fixed; the export is
  the data. Turn it on before you need it - it is NOT retroactive.

  Budgets, alerts, and the discount programmes are in 08_billing_cost.""")

    # -------------------------------------------------------- 7. labels
    rule("7. LABELS vs TAGS vs NETWORK TAGS   [documented]")
    print("""  Three different things with confusingly similar names. The exam
  uses the confusion deliberately.

    LABELS          key-value pairs on a resource, for ORGANISING and
                    especially for BILLING. They flow into the billing
                    export, so "how much does team X spend" is a label
                    question. They carry NO access-control meaning
                    whatsoever. Not inherited.

    TAGS            (Resource Manager tags) key-value pairs that ARE
                    INHERITED down the hierarchy and CAN be referenced
                    in IAM conditions and Org Policy conditions. This
                    is the one with teeth - "apply this policy to
                    everything tagged env=prod, wherever it lives".

    NETWORK TAGS    plain strings on a VM, used ONLY as firewall rule
                    targets and route targets. No hierarchy, no IAM,
                    no billing. These are the ones in 06_networking
                    section 5.

  IF THE QUESTION IS ABOUT COST ATTRIBUTION, IT IS LABELS.
  IF IT IS ABOUT APPLYING POLICY CONDITIONALLY, IT IS TAGS.
  IF IT IS ABOUT A FIREWALL RULE, IT IS NETWORK TAGS.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    names = [n for n, _ in radius]
    counts = [c for _, c in radius]
    ax1.barh(names[::-1], counts[::-1], color=PALETTE["blue"])
    ax1.set_xlabel("projects reached")
    ax1.set_title("Blast radius by attach point", loc="left")

    ax2.bar(range(len(allowed_counts)), list(allowed_counts.values()),
            color=PALETTE["green"])
    ax2.axhline(len(regions), color=PALETTE["grey"], ls=":", lw=1)
    ax2.set_ylabel(f"regions permitted (of {len(regions)})")
    ax2.set_xticks(range(len(allowed_counts)))
    ax2.set_xticklabels(list(allowed_counts), rotation=25, ha="right", fontsize=8)
    ax2.set_title("resourceLocations, resolved", loc="left")

    qn = [q.name.split(" (")[0] for q in QUOTAS]
    frac = [usage[q.name] / q.limit * 100 for q in QUOTAS]
    cols = [PALETTE["vermillion"] if f >= 100 else PALETTE["orange"]
            if f >= 75 else PALETTE["blue"] for f in frac]
    ax3.barh(qn[::-1], frac[::-1], color=cols[::-1])
    ax3.axvline(100, color=PALETTE["black"], lw=1)
    ax3.set_xlabel("% of quota consumed by one deployment")
    ax3.set_title("Several quotas, one plan", loc="left")
    save_figure(fig, OUT / "hierarchy_and_policy.png")
    print(f"\n  figure -> {OUT / 'hierarchy_and_policy.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "apply this to every project, including     ORGANIZATION POLICY at the
   future ones"                               organization node
  "data must stay in the EU"                  gcp.resourceLocations, at
                                              the folder that owns it
  "no VM may have a public IP"                compute.vmExternalIpAccess
  "nobody may download service account        iam.disableServiceAccount
   keys"                                      KeyCreation - a boolean
  "an owner should not be able to turn        withhold roles/orgpolicy.
   this off"                                  policyAdmin below the org
  "stop anyone deleting this project"         a LIEN
  "rename the project"                        the NAME only. The ID is
                                              immutable
  "we hit a CPU quota"                        request an increase, or use
                                              another region or project
  "how much did team X spend"                 LABELS + billing export to
                                              BigQuery
  "apply policy to everything tagged prod"    TAGS, not labels
  "let this person set up projects that       roles/billing.user
   can actually bill"
  "everything broke and nothing changed"      check the BILLING LINK""")


if __name__ == "__main__":
    main()
