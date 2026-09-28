"""Infrastructure as code: a plan is a three-way diff, and one rename can
destroy four things.

Domain 3 (~27%) includes deploying and managing infrastructure repeatably.
Two mechanisms inside it are almost universally misunderstood, and both
are implementable here:

  - A PLAN IS NOT A DIFF BETWEEN YOUR CODE AND THE CLOUD. It is a
    THREE-WAY comparison of CONFIG, STATE and REALITY, and the five
    combinations behave differently.
  - SOME ATTRIBUTES CANNOT BE CHANGED IN PLACE. Changing one forces a
    replacement, and replacement CASCADES to everything that references
    it through another force-new attribute.

  1. Why IaC at all, and what idempotent means       [runnable]
  2. The dependency graph, and what can run at once  [runnable]
  3. The plan is a three-way diff                    [runnable]
  4. Replacement cascades                            [runnable]
  5. State: where it lives, and what breaks it
  6. Deployment Manager vs Terraform vs the rest
  7. The exam angle

SECTIONS 1-4 RUN. The planner is a real (small) implementation of the
rules Terraform documents, not a description of them. Sections 5 and 6
are documented.

NOTHING HERE CALLS TERRAFORM OR GOOGLE CLOUD. There is no binary to
install and no credentials to hold. The resource types and their
force-new attributes are modelled on the real provider and labelled
where they are approximate.

Run:
    python 09_iac/iac_and_state.py

Concept reference: ACE domain 3 (~27%) - ensuring successful operation.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"

REF = re.compile(r"\$\{([a-z0-9_]+\.[a-z0-9_]+)\.[a-z0-9_]+\}")

# Which attributes cannot be changed in place. Modelled on the real Google
# provider; close enough to be instructive, not a substitute for reading the
# resource documentation, which is where this is authoritative.
FORCE_NEW: dict[str, set[str]] = {
    "google_compute_network": {"name"},
    "google_compute_subnetwork": {"name", "network", "region"},
    # ip_cidr_range is NOT here: a subnet range can be EXPANDED in place.
    # See 06_networking - expand yes, shrink never.
    "google_compute_instance": {"name", "zone", "subnetwork", "boot_image"},
    # machine_type and tags update in place (a stop/start for machine_type).
    "google_sql_database_instance": {"name", "region", "database_version"},
    # tier updates in place.
    "google_storage_bucket": {"name", "location"},
    # storage_class updates in place - 05_storage section 6 said exactly this.
}


@dataclass(frozen=True)
class Resource:
    address: str                       # "google_compute_instance.web"
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def rtype(self) -> str:
        return self.address.split(".")[0]

    def refs(self) -> set[str]:
        """Dependencies, derived from ${...} references in the attributes -
        which is exactly how Terraform builds its graph. You do not declare
        the edges; they fall out of the values."""
        out = set()
        for v in self.attrs.values():
            out |= set(REF.findall(str(v)))
        return out

    def ref_attr(self, other: str) -> str | None:
        """Which attribute of THIS resource points at `other`."""
        for k, v in self.attrs.items():
            if other in REF.findall(str(v)):
                return k
        return None


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------------------
# 2. The graph.
# ---------------------------------------------------------------------------
def levels(config: dict[str, Resource]) -> list[list[str]]:
    """Topological levels. Everything in one level has no dependency on
    anything else in that level, so it can be created IN PARALLEL - which is
    what terraform's -parallelism flag acts on.

    Raises on a cycle, because a cycle is not a slow plan, it is an
    impossible one.
    """
    remaining = {a: (r.refs() & config.keys()) for a, r in config.items()}
    out: list[list[str]] = []
    done: set[str] = set()
    while remaining:
        ready = sorted(a for a, deps in remaining.items() if deps <= done)
        if not ready:
            # Not every remaining resource is IN the cycle - some are merely
            # downstream of it and can never become ready. A node is in a
            # cycle only if it is REACHABLE FROM ITSELF; "has an unresolved
            # dependency" is a different and much larger set.
            def reaches_self(start: str) -> bool:
                seen, stack = set(), list(remaining[start])
                while stack:
                    n = stack.pop()
                    if n == start:
                        return True
                    if n in seen or n not in remaining:
                        continue
                    seen.add(n)
                    stack.extend(remaining[n])
                return False

            in_cycle = sorted(a for a in remaining if reaches_self(a))
            blocked = sorted(set(remaining) - set(in_cycle))
            msg = f"unorderable - cycle among {[short(a) for a in in_cycle]}"
            if blocked:
                msg += f"; also blocked: {[short(a) for a in blocked]}"
            raise ValueError(msg)
        out.append(ready)
        done |= set(ready)
        for a in ready:
            remaining.pop(a)
    return out


# ---------------------------------------------------------------------------
# 3 + 4. The planner.
# ---------------------------------------------------------------------------
def plan(config: dict[str, Resource],
         state: dict[str, Resource],
         reality: dict[str, Resource]) -> dict[str, tuple[str, str]]:
    """THE THREE-WAY DIFF. Returns address -> (action, why).

    CONFIG   what you wrote
    STATE    what the tool believes it made last time
    REALITY  what is actually there now

    Most people picture config vs reality. The tool cannot do that: it only
    manages what is IN STATE, and it detects drift by REFRESHING state
    against reality first. The five combinations below all behave
    differently, and four of them surprise somebody eventually.
    """
    actions: dict[str, tuple[str, str]] = {}
    for addr in sorted(set(config) | set(state) | set(reality)):
        in_c, in_s, in_r = addr in config, addr in state, addr in reality

        if in_c and not in_s and in_r:
            actions[addr] = ("create (WILL FAIL)",
                             "exists but is not in state - needs IMPORT")
        elif in_c and not in_s:
            actions[addr] = ("create", "in config, never made")
        elif in_c and in_s and not in_r:
            actions[addr] = ("create", "deleted outside the tool - recreate")
        elif not in_c and in_s:
            actions[addr] = ("destroy", "removed from config")
        elif not in_c and not in_s and in_r:
            actions[addr] = ("(ignored)", "not managed by this configuration")
        elif in_c and in_s and in_r:
            want, have = config[addr].attrs, reality[addr].attrs
            changed = {k for k in set(want) | set(have)
                       if want.get(k) != have.get(k)}
            if not changed:
                actions[addr] = ("no change", "")
            else:
                forcing = changed & FORCE_NEW.get(config[addr].rtype, set())
                drifted = {k for k in changed
                           if state[addr].attrs.get(k) != have.get(k)}
                why = ", ".join(sorted(changed))
                if drifted:
                    why += "  [DRIFT - changed outside the tool]"
                actions[addr] = (
                    "REPLACE" if forcing else "update in place", why)
    return actions


def cascade(config: dict[str, Resource],
            actions: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Propagate replacements downstream.

    If A is replaced it gets a new id. Anything referencing A through one of
    ITS OWN force-new attributes therefore has to be replaced too - and so
    on, transitively. This is the mechanism behind every "why is it
    destroying my database" question ever asked.
    """
    replaced = {a for a, (act, _) in actions.items() if act == "REPLACE"}
    out = {a: actions[a][0] for a in actions}
    changed = True
    while changed:
        changed = False
        for addr, res in config.items():
            if addr in replaced:
                continue
            for dep in res.refs() & replaced:
                attr = res.ref_attr(dep)
                if attr and attr in FORCE_NEW.get(res.rtype, set()):
                    replaced.add(addr)
                    out[addr] = "REPLACE"
                    changed = True
                    break
    return out


def build_config() -> dict[str, Resource]:
    r = [
        Resource("google_compute_network.vpc", {"name": "prod-net"}),
        Resource("google_compute_subnetwork.web", {
            "name": "web-uc1",
            "network": "${google_compute_network.vpc.id}",
            "region": "us-central1",
            "ip_cidr_range": "10.0.0.0/23"}),
        Resource("google_compute_instance.app", {
            "name": "app-1",
            "zone": "us-central1-a",
            "machine_type": "n2-standard-4",
            "subnetwork": "${google_compute_subnetwork.web.id}",
            "boot_image": "debian-12"}),
        Resource("google_compute_instance.web", {
            "name": "web-1",
            "zone": "us-central1-a",
            "machine_type": "n2-standard-2",
            "subnetwork": "${google_compute_subnetwork.web.id}",
            "boot_image": "debian-12"}),
        Resource("google_sql_database_instance.db", {
            "name": "orders-db",
            "region": "us-central1",
            "database_version": "POSTGRES_15",
            "tier": "db-custom-2-7680"}),
        Resource("google_storage_bucket.assets", {
            "name": "acme-assets",
            "location": "US",
            "storage_class": "STANDARD"}),
    ]
    return {x.address: x for x in r}


def short(addr: str) -> str:
    t, n = addr.split(".")
    return f"{t.replace('google_', '').replace('compute_', '')}.{n}"


def main() -> None:
    print("INFRASTRUCTURE AS CODE - A PLAN IS A THREE-WAY DIFF")
    config = build_config()

    # ------------------------------------------------------ 1. idempotency
    rule("1. WHY IaC AT ALL, AND WHAT IDEMPOTENT MEANS")
    print("""  The progression, and every step is still in use somewhere:

    CONSOLE     fine to learn with, impossible to review, repeat or
                hand over. Nothing records WHY.
    gcloud      repeatable if you remember the flags. Still imperative:
                you say what to DO, not what should EXIST.
    A SHELL     now it is repeatable and in git - but it is not
      SCRIPT    IDEMPOTENT. Run it twice and it either fails on
                "already exists" or creates a second one.
    IaC         you declare the DESIRED STATE. The tool works out the
                difference and does only that. Running it twice is a
                no-op, and that property is the whole point.\n""")

    empty: dict[str, Resource] = {}
    first = plan(config, empty, empty)
    creates = sum(1 for a, _ in first.values() if a == "create")
    print(f"  apply #1 against an empty project: {creates} to create\n")
    # after applying, state and reality both match config
    state = dict(config)
    reality = dict(config)
    second = plan(config, state, reality)
    nochange = sum(1 for a, _ in second.values() if a == "no change")
    print(f"  apply #2, nothing else changed:    "
          f"{len(second) - nochange} to change, {nochange} unchanged")
    print("\n  THAT IS IDEMPOTENCE, and it is why a plan is safe to run in")
    print("  CI on every commit. A shell script cannot give you that")
    print("  second line without you writing the 'does it already exist'")
    print("  check by hand, for every resource, correctly.")

    # ------------------------------------------------------- 2. the graph
    rule("2. THE DEPENDENCY GRAPH, AND WHAT CAN RUN AT ONCE")
    print("  You never declare the edges. They fall out of the REFERENCES:")
    print("  writing ${google_compute_network.vpc.id} as the subnet's")
    print("  network IS the dependency.\n")
    lv = levels(config)
    for i, group in enumerate(lv):
        print(f"    level {i}  ({len(group)} in parallel)")
        for a in group:
            deps = sorted(config[a].refs() & config.keys())
            dep_s = f"  <- {', '.join(short(d) for d in deps)}" if deps else ""
            print(f"      {short(a)}{dep_s}")

    widest = max(len(g) for g in lv)
    print(f"\n  {len(lv)} levels, widest {widest}. Everything inside one level is")
    print("  independent, so the tool creates them CONCURRENTLY - that is")
    print("  what terraform's -parallelism controls. Destroys run in the")
    print("  REVERSE order, which is why a subnet is never torn out from")
    print("  under a running instance.")
    print("\n  Note the database and the bucket sit at level 0 with the VPC:")
    print("  they reference nothing, so nothing waits for them and they")
    print("  wait for nothing. An unconnected resource is free concurrency.")

    cyc = dict(config)
    cyc["google_compute_network.vpc"] = Resource(
        "google_compute_network.vpc",
        {"name": "${google_compute_instance.app.id}"})
    try:
        levels(cyc)
    except ValueError as e:
        print(f"\n  And a cycle is refused, not worked around:\n    {e}")

    # -------------------------------------------------- 3. three-way diff
    rule("3. THE PLAN IS A THREE-WAY DIFF")
    print("""  CONFIG   what you wrote
  STATE    what the tool believes it made last time
  REALITY  what is actually there now

  Most people picture config vs reality. The tool cannot do that - it
  only manages what is IN STATE, and it finds drift by REFRESHING
  state against reality first. Five combinations, five behaviours:\n""")

    cfg3 = dict(config)
    st3 = dict(config)
    rl3 = dict(config)

    # (a) somebody resized the database in the console
    rl3["google_sql_database_instance.db"] = Resource(
        "google_sql_database_instance.db",
        {**config["google_sql_database_instance.db"].attrs,
         "tier": "db-custom-8-30720"})
    # (b) somebody deleted the bucket by hand
    del rl3["google_storage_bucket.assets"]
    # (c) a resource created by hand that the config also wants
    cfg3["google_compute_instance.jump"] = Resource(
        "google_compute_instance.jump",
        {"name": "jump-1", "zone": "us-central1-a",
         "machine_type": "e2-small",
         "subnetwork": "${google_compute_subnetwork.web.id}",
         "boot_image": "debian-12"})
    rl3["google_compute_instance.jump"] = cfg3["google_compute_instance.jump"]
    # (d) a resource removed from the config but still in state and reality
    del cfg3["google_compute_instance.app"]
    # (e) something in reality nobody manages
    rl3["google_compute_instance.someones_test"] = Resource(
        "google_compute_instance.someones_test", {"name": "test"})

    p3 = plan(cfg3, st3, rl3)
    print(f"  {'resource':<26} {'C':>2} {'S':>2} {'R':>2}  {'action':<20} why")
    print("  " + "-" * 92)
    for addr, (act, why) in p3.items():
        c = "y" if addr in cfg3 else "-"
        s = "y" if addr in st3 else "-"
        r = "y" if addr in rl3 else "-"
        print(f"  {short(addr):<26} {c:>2} {s:>2} {r:>2}  {act:<20} {why}")

    interesting = [a for a, (act, _) in p3.items() if act != "no change"]
    print(f"\n  READ THE {len(interesting)} THAT ARE NOT 'no change':")
    print("\n    DRIFT (db):  somebody resized it in the console. The plan")
    print("    wants to put it BACK. Infrastructure as code does not")
    print("    record your change, it REVERTS it - and it will do so at")
    print("    3am in CI without asking. That is the deal, and it is why")
    print("    a managed resource must not be touched by hand.")
    print("\n    DELETED (bucket):  in config and state, gone from reality.")
    print("    The plan recreates it. Note what does NOT come back: the")
    print("    objects that were in it. IaC restores the RESOURCE, never")
    print("    the data - see 05_storage section 8 on what is not a backup.")
    print("\n    NOT IN STATE (jump):  someone built it by hand and then")
    print("    wrote matching config. The plan says CREATE and the apply")
    print("    FAILS on 'already exists'. The fix is terraform import (or")
    print("    an import block), which adopts the existing resource into")
    print("    state. This is the single most common first-week error.")
    print("\n    REMOVED FROM CONFIG (app):  deleting the block does not")
    print("    orphan it, it DESTROYS it. If you meant to stop managing")
    print("    something, that is `terraform state rm`, not a delete key.")
    print("\n    And someones_test is simply invisible: not in config, not")
    print("    in state. IaC has no opinion about resources it does not")
    print("    manage, which is why 'we use Terraform' is never the same")
    print("    sentence as 'everything is in Terraform'.")

    # ------------------------------------------------- 4. the cascade
    rule("4. REPLACEMENT CASCADES")
    print("  Some attributes cannot be changed in place. The provider marks")
    print("  them ForceNew, and changing one destroys and recreates the")
    print("  resource. Then it propagates.\n")

    scenarios = [
        ("rename the VPC",
         "google_compute_network.vpc", "name", "prod-net-v2"),
        ("move the subnet to another region",
         "google_compute_subnetwork.web", "region", "us-east1"),
        ("grow the subnet range",
         "google_compute_subnetwork.web", "ip_cidr_range", "10.0.0.0/22"),
        ("resize the app instance",
         "google_compute_instance.app", "machine_type", "n2-standard-8"),
        ("change the database version",
         "google_sql_database_instance.db", "database_version",
         "POSTGRES_16"),
        ("change the bucket storage class",
         "google_storage_bucket.assets", "storage_class", "NEARLINE"),
    ]
    print(f"  {'you change':<36} {'replaced':>9} {'updated':>8}  what gets replaced")
    print("  " + "-" * 96)
    blast = {}
    for label, addr, attr, value in scenarios:
        new_cfg = dict(config)
        new_cfg[addr] = Resource(addr, {**config[addr].attrs, attr: value})
        acts = plan(new_cfg, dict(config), dict(config))
        final = cascade(new_cfg, acts)
        rep = sorted(a for a, v in final.items() if v == "REPLACE")
        upd = [a for a, v in final.items() if v == "update in place"]
        blast[label] = len(rep)
        names = ", ".join(short(a) for a in rep) if rep else "-"
        print(f"  {label:<36} {len(rep):>9} {len(upd):>8}  {names}")

    worst = max(blast, key=blast.get)
    print(f"\n  RENAMING THE VPC REPLACES {blast[worst]} RESOURCES. One string, in one")
    print("  line, and the network, the subnet and both instances are")
    print("  destroyed and rebuilt - because the subnet's `network` is")
    print("  force-new and the instances' `subnetwork` is force-new, so the")
    print("  replacement walks straight down the graph from section 2.")
    print("\n  THE DATABASE AND THE BUCKET SURVIVE, and not because they are")
    print("  important - because they reference nothing. Blast radius here")
    print("  is a property of the GRAPH, exactly as it was in")
    print("  01_resource_hierarchy, and it is visible before you apply.")
    print("\n  Contrast the rows that cost nothing: resizing an instance and")
    print("  changing a bucket's storage class are in-place updates, and")
    print("  GROWING THE SUBNET RANGE is too - which is the same asymmetry")
    print("  06_networking measured, expand yes and shrink never, showing")
    print("  up here as ForceNew or not.")
    print("\n  WHICH IS THE WHOLE ARGUMENT FOR `terraform plan`: the plan")
    print("  tells you this BEFORE the apply, in a review, with a diff, and")
    print("  the word to search for in it is REPLACE. `gcloud` and the")
    print("  console will not warn you, because they do not know what else")
    print("  you built.")

    # ------------------------------------------------------- 5. state
    rule("5. STATE: WHERE IT LIVES, AND WHAT BREAKS IT   [documented]")
    print("""  State is the file that maps your config to real resource ids.
  It is not a cache and it is not optional - without it the tool
  cannot tell "create this" from "I already made this".

    WHERE IT GOES    a GCS bucket, versioned, with object versioning
                     on. NEVER in git: it contains resource ids and
                     often SECRETS in plain text, and two people on
                     two laptops will overwrite each other.

    LOCKING          a remote backend takes a lock during apply so two
                     applies cannot run at once. A stale lock after a
                     crashed run is a normal operational event.

    DRIFT            any change made outside the tool. Section 3
                     showed what happens: the plan reverts it. The
                     defence is not vigilance, it is not granting
                     humans write access to what the pipeline owns -
                     02_iam and 01_resource_hierarchy are the actual
                     controls.

    IMPORT           adopts an existing resource into state. The
                     answer to "we built it by hand and now want it in
                     code".

    state rm         stop managing something WITHOUT destroying it.
                     The opposite of deleting the block.

    WORKSPACES /     separate state per environment. The cleaner
    SEPARATE STATE   pattern is a separate state file and a separate
                     PROJECT per environment, so a bad apply in dev
                     cannot reach prod - and project is the blast
                     radius boundary from 01_resource_hierarchy.

    MODULES          reusable groups of resources with inputs and
                     outputs. The unit of "every team gets the same
                     VPC shape".

  IF STATE IS LOST and the resources still exist, the tool will try to
  CREATE ALL OF THEM AGAIN and fail on the ones that already exist.
  Recovery is a restore from the bucket's object versions, which is
  why versioning on the state bucket is not optional.""")

    # ------------------------------------------------------- 6. the tools
    rule("6. DEPLOYMENT MANAGER vs TERRAFORM vs THE REST   [documented]")
    print("""    TERRAFORM              the industry default, multi-cloud, huge
                           provider ecosystem, HCL. If a question
                           names a tool, this is usually it.

    INFRASTRUCTURE         Google's MANAGED Terraform: it runs your
      MANAGER              Terraform for you, keeps state in Google
                           Cloud and integrates with IAM. The current
                           Google-native answer.

    DEPLOYMENT MANAGER     Google's ORIGINAL native IaC - YAML with
                           Jinja or Python templates, Google only.
                           Google has announced its deprecation in
                           favour of Infrastructure Manager; exam
                           blueprints lag announcements, so know what
                           it IS and expect it to appear, but do not
                           start anything new on it. Check the current
                           status rather than trusting this line.

    CONFIG CONNECTOR       manage Google Cloud resources as KUBERNETES
                           objects, reconciled by a controller in your
                           cluster. The answer when the team already
                           lives in kubectl and wants one control
                           plane for apps and infrastructure.

    gcloud / client        imperative. Right for one-off investigation
      libraries            and for things IaC genuinely cannot express.

  THE DISTINCTION THE EXAM USES: "repeatable", "version controlled",
  "review the change before it happens", "identical environments" all
  point at IaC rather than gcloud. "Multi-cloud" or a named tool
  points at Terraform. "Managed, in Google Cloud, with IAM" points at
  Infrastructure Manager. "As Kubernetes resources" is Config
  Connector.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    labs = list(blast)
    vals = [blast[k] for k in labs]
    cols = [PALETTE["vermillion"] if v >= 3 else PALETTE["orange"] if v
            else PALETTE["blue"] for v in vals]
    ax1.barh([l.replace(" the ", "\n") for l in labs][::-1], vals[::-1],
             color=cols[::-1])
    ax1.set_xlabel("resources REPLACED by the change")
    ax1.set_title("One edit, four destroys", loc="left")
    ax1.tick_params(axis="y", labelsize=7)

    counts: dict[str, int] = {}
    for act, _ in p3.values():
        key = act.split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    ax2.bar(range(len(counts)), list(counts.values()),
            color=PALETTE["blue"])
    ax2.set_xticks(range(len(counts)))
    ax2.set_xticklabels(list(counts), rotation=25, ha="right", fontsize=8)
    ax2.set_ylabel("resources")
    ax2.set_title("Five combinations, five actions", loc="left")

    for i, group in enumerate(lv):
        for j, a in enumerate(group):
            y = j - (len(group) - 1) / 2
            ax3.scatter([i], [y], s=420, color=PALETTE["sky"], zorder=3)
            ax3.text(i, y, short(a).split(".")[1], ha="center", va="center",
                     fontsize=7, zorder=4)
            for dep in config[a].refs() & config.keys():
                for pi, pg in enumerate(lv):
                    if dep in pg:
                        py = pg.index(dep) - (len(pg) - 1) / 2
                        ax3.annotate("", xy=(i - 0.08, y),
                                     xytext=(pi + 0.08, py),
                                     arrowprops=dict(arrowstyle="->",
                                                     color=PALETTE["grey"],
                                                     lw=1.2))
    ax3.set_xticks(range(len(lv)))
    ax3.set_xticklabels([f"level {i}" for i in range(len(lv))], fontsize=8)
    ax3.set_yticks([])
    ax3.grid(False)
    ax3.set_title("The graph you never wrote", loc="left")
    save_figure(fig, OUT / "iac_and_state.png")
    print(f"\n  figure -> {OUT / 'iac_and_state.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "identical dev, staging and prod"          IaC, one configuration,
                                             separate state and separate
                                             PROJECTS
  "review infrastructure changes before      terraform plan in a pull
   they happen"                              request
  "multi-cloud" or names Terraform           TERRAFORM
  "managed Terraform inside Google Cloud"    INFRASTRUCTURE MANAGER
  "Google's original YAML/Jinja IaC"         DEPLOYMENT MANAGER (and it
                                             is being retired)
  "manage cloud resources with kubectl"      CONFIG CONNECTOR
  "we built it by hand, now put it in        terraform IMPORT
   code"
  "stop managing this without deleting       terraform STATE RM
   it"
  "where does state go"                      a VERSIONED GCS bucket.
                                             Never git
  "two engineers applied at once"            remote backend LOCKING
  "someone changed it in the console"        the next apply REVERTS it
  "why is it destroying my instance"         a FORCE-NEW attribute
                                             changed, or something it
                                             depends on was replaced""")


if __name__ == "__main__":
    main()
