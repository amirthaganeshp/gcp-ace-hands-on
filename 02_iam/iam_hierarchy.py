"""IAM: who can do what, and why you cannot take it back lower down.

Access and security is ~20% of the ACE exam, and most of it reduces to one
rule that surprises people:

    IAM POLICIES INHERIT DOWNWARD AND THEY ARE ADDITIVE.

Grant someone a role at the organization and you cannot revoke it at a
project. There is no "deny" in an allow policy - only more allows. This
file implements the resolution rules and then demonstrates that.

  1. The hierarchy, and what a policy attaches to
  2. Resolving effective permissions - the union of everything above
  3. The demonstration: trying to take access away at a lower level
  4. IAM DENY policies - the one thing that CAN override an allow
  5. Blast radius: basic vs predefined vs custom roles
  6. Service accounts, and impersonation as a privilege path
  7. Conditions - time-bound and resource-bound access

EXECUTED IN FULL. The resolver is real logic; every result below is
computed by it, not asserted.

NOTE ON THE PERMISSION DATA: the permissions attached to each role here
are a REPRESENTATIVE MODEL, not Google's real lists - roles/editor alone
carries thousands. Fetching the real ones needs `gcloud auth login`
first, then `gcloud iam roles describe`. The RESOLUTION RULES are exact;
the permission counts are illustrative and labelled wherever they appear.

Run:
    python 02_iam/iam_hierarchy.py

Concept reference: ACE domain 4 (~20%) - configuring access and security.
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
# A representative permission model. NOT Google's real lists - see the note
# in the docstring. Chosen so the SHAPE is right: basic roles span every
# service, predefined roles span one, custom roles span exactly what you list.
# ---------------------------------------------------------------------------
SERVICES = ["compute", "storage", "bigquery", "iam", "billing", "logging"]
VERBS = ["get", "list", "create", "update", "delete", "setIamPolicy"]

ROLES: dict[str, set[str]] = {
    # Basic roles: every service, and that is the whole problem with them.
    "roles/viewer": {f"{s}.{v}" for s in SERVICES for v in ("get", "list")},
    "roles/editor": {f"{s}.{v}" for s in SERVICES
                     for v in ("get", "list", "create", "update", "delete")},
    "roles/owner": {f"{s}.{v}" for s in SERVICES for v in VERBS},

    # Predefined roles: one service, a sensible slice of it.
    "roles/storage.objectViewer": {"storage.get", "storage.list"},
    "roles/storage.admin": {f"storage.{v}" for v in VERBS},
    "roles/bigquery.dataViewer": {"bigquery.get", "bigquery.list"},
    "roles/bigquery.jobUser": {"bigquery.create"},
    "roles/compute.instanceAdmin": {f"compute.{v}" for v in
                                    ("get", "list", "create", "update", "delete")},
    "roles/logging.viewer": {"logging.get", "logging.list"},

    # A custom role: exactly what you asked for, nothing else.
    "custom/binaryDeployer": {"storage.get", "compute.update"},
}


@dataclass
class Node:
    """A node in the resource hierarchy."""
    name: str
    kind: str                                    # organization | folder | project
    parent: "Node | None" = None
    # principal -> set of roles bound AT THIS NODE
    bindings: dict[str, set[str]] = field(default_factory=dict)
    # principal -> set of permissions DENIED at this node (IAM Deny policy)
    denies: dict[str, set[str]] = field(default_factory=dict)

    def bind(self, principal: str, role: str) -> "Node":
        self.bindings.setdefault(principal, set()).add(role)
        return self

    def deny(self, principal: str, permissions: set[str]) -> "Node":
        self.denies.setdefault(principal, set()).update(permissions)
        return self

    def chain(self) -> list["Node"]:
        """This node and every ancestor, root first."""
        out, n = [], self
        while n:
            out.append(n)
            n = n.parent
        return list(reversed(out))


def effective_permissions(node: Node, principal: str) -> set[str]:
    """Resolve what a principal can actually do at a node.

    THE RULES, and they are the exam content:
      1. Collect every role bound to the principal at this node AND at every
         ancestor. Inheritance is downward.
      2. UNION their permissions. Allow policies are purely additive - there
         is no subtraction anywhere in this step.
      3. THEN subtract anything an IAM DENY policy blocks, at this node or
         any ancestor. Deny is evaluated after allow and wins.
    """
    allowed: set[str] = set()
    denied: set[str] = set()
    for anc in node.chain():
        for role in anc.bindings.get(principal, set()):
            allowed |= ROLES.get(role, set())
        denied |= anc.denies.get(principal, set())
    return allowed - denied


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def build() -> dict[str, Node]:
    org = Node("acme.com", "organization")
    data = Node("data-platform", "folder", parent=org)
    prod = Node("prod-analytics", "project", parent=data)
    dev = Node("dev-sandbox", "project", parent=data)
    return {"org": org, "folder": data, "prod": prod, "dev": dev}


def main() -> None:
    print("IAM - INHERITANCE, AND WHY YOU CANNOT TAKE IT BACK")
    nodes = build()
    org, folder, prod, dev = nodes["org"], nodes["folder"], nodes["prod"], nodes["dev"]

    # ------------------------------------------------------------ 1. shape
    rule("1. THE HIERARCHY")
    print("""  organization  acme.com
    folder        data-platform
      project       prod-analytics
      project       dev-sandbox

  A policy can attach at ANY of these, and also at some individual
  resources (a bucket, a BigQuery dataset). Whatever you attach it to,
  it applies there AND to everything beneath.""")

    # ------------------------------------------ 2. resolving, additively
    rule("2. RESOLVING EFFECTIVE PERMISSIONS")

    org.bind("alice@acme.com", "roles/viewer")
    # dataViewer + jobUser is the canonical BigQuery least-privilege pair:
    # dataViewer lets you READ the data, jobUser lets you RUN a query at all.
    prod.bind("alice@acme.com", "roles/bigquery.dataViewer")
    prod.bind("alice@acme.com", "roles/bigquery.jobUser")

    print("  Bindings for alice@acme.com:")
    print("    organization  roles/viewer")
    print("    prod project  roles/bigquery.dataViewer + roles/bigquery.jobUser\n")
    counts = {}
    for label, node in (("dev-sandbox", dev), ("prod-analytics", prod)):
        perms = effective_permissions(node, "alice@acme.com")
        counts[label] = perms
        print(f"  effective on {label:<16} {len(perms):>2} permissions")

    extra = counts["prod-analytics"] - counts["dev-sandbox"]
    print(f"\n  prod has {len(extra)} permission(s) dev does not: {sorted(extra)}")
    print("  The project binding ADDS to the organization one. Nothing was")
    print("  replaced.")
    print("\n  Note dataViewer contributed NOTHING here - org-level viewer already")
    print("  granted bigquery.get/list. Only jobUser added anything. Overlapping")
    print("  grants are normal, and it is why counting roles tells you nothing")
    print("  about access; you have to resolve the union.")

    # ------------------------------------------- 3. the thing people expect
    rule("3. TRYING TO TAKE ACCESS AWAY LOWER DOWN")

    org.bind("bob@acme.com", "roles/editor")
    before = effective_permissions(prod, "bob@acme.com")
    print(f"  bob has roles/editor at the ORGANIZATION -> "
          f"{len(before)} permissions on prod-analytics\n")
    print("  Now the prod team wants bob to be read-only on their project.")
    print("  They bind roles/viewer to bob AT THE PROJECT:\n")
    prod.bind("bob@acme.com", "roles/viewer")
    after = effective_permissions(prod, "bob@acme.com")

    print(f"    before  {len(before)} permissions")
    print(f"    after   {len(after)} permissions")
    print(f"    change  {len(after) - len(before):+d}\n")
    can_delete = "compute.delete" in after
    print(f"    can bob still delete compute instances?  {can_delete}")
    print("\n  Binding a WEAKER role does not weaken anything. Allow policies")
    print("  only ever add. The project team cannot revoke what the")
    print("  organization granted - they have to ask whoever owns that level.")
    print("\n  THIS IS THE MOST COMMONLY MISSED RULE IN THE DOMAIN.")

    # ----------------------------------------------------- 4. IAM Deny
    rule("4. IAM DENY - the one thing that CAN override an allow")

    prod.deny("bob@acme.com", {"compute.delete", "storage.delete"})
    after_deny = effective_permissions(prod, "bob@acme.com")
    print("  A DENY policy at prod-analytics blocking compute.delete and")
    print("  storage.delete:\n")
    print(f"    permissions before deny  {len(after)}")
    print(f"    permissions after deny   {len(after_deny)}")
    print(f"    can bob delete compute?  {'compute.delete' in after_deny}")
    print("\n  Deny is evaluated AFTER allow and wins. It is the only way to")
    print("  subtract, and it is a separate policy type - not a binding.")
    print("  Note it did not touch his other editor permissions.")

    # --------------------------------------------- 5. blast radius
    rule("5. BLAST RADIUS - basic vs predefined vs custom")
    print("  [representative permission model - see the note in the docstring]\n")
    print(f"  {'role':<34} {'perms':>6} {'services':>9}")
    print("  " + "-" * 52)
    radius = []
    for role in ("roles/owner", "roles/editor", "roles/viewer",
                 "roles/storage.admin", "roles/bigquery.dataViewer",
                 "custom/binaryDeployer"):
        perms = ROLES[role]
        svcs = {p.split(".")[0] for p in perms}
        radius.append((role, len(perms), len(svcs)))
        print(f"  {role:<34} {len(perms):>6} {len(svcs):>9}")

    print("\n  Basic roles span EVERY service. That is why 'grant Editor and move")
    print("  on' is the wrong answer to every least-privilege question: it is")
    print("  not slightly too much, it is every service in the project.")

    # ------------------------------------------------ 6. service accounts
    rule("6. SERVICE ACCOUNTS AND IMPERSONATION")

    sa = "pipeline-sa@prod-analytics.iam.gserviceaccount.com"
    prod.bind(sa, "roles/storage.admin")
    prod.bind("carol@acme.com", "roles/logging.viewer")

    carol_direct = effective_permissions(prod, "carol@acme.com")
    sa_perms = effective_permissions(prod, sa)
    print(f"  carol directly         {len(carol_direct)} permissions")
    print(f"  the service account    {len(sa_perms)} permissions\n")
    print("  If carol is granted roles/iam.serviceAccountTokenCreator on that")
    print("  service account, she can IMPERSONATE it - and then she has its")
    print(f"  {len(sa_perms)} permissions, not her {len(carol_direct)}.")
    print("\n  IMPERSONATION IS A PRIVILEGE PATH. Auditing 'who can delete")
    print("  objects' means auditing who can impersonate something that can,")
    print("  not just who holds the role directly.")
    print("\n  And it is the right answer to 'how do we avoid service account")
    print("  KEYS' - attach the account, or impersonate it. A downloaded key")
    print("  never expires, cannot be rotated by the platform, and ends up in")
    print("  a git repository.")

    # ------------------------------------------------------ 7. conditions
    rule("7. IAM CONDITIONS")
    print("""  A binding can carry a CONDITION - an expression that must hold for
  the grant to apply:

    request.time < timestamp("2026-12-31T00:00:00Z")   time-bound access
    resource.name.startsWith("projects/_/buckets/tmp") one bucket only
    resource.type == "storage.googleapis.com/Object"   one resource type

  Use them for temporary elevation instead of granting a role and
  trusting someone to remember to remove it. Conditions are evaluated
  as part of the allow, so a false condition simply means the binding
  does not apply.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4))

    labels = [r.replace("roles/", "").replace("custom/", "custom: ")
              for r, _, _ in radius]
    counts = [c for _, c, _ in radius]
    cols = [PALETTE["vermillion"] if "/" not in r or r.startswith("roles/owner")
            or r in ("roles/editor", "roles/viewer") else PALETTE["blue"]
            for r, _, _ in radius]
    ax1.barh(labels[::-1], counts[::-1], color=cols[::-1])
    ax1.set_xlabel("permissions (representative model)")
    ax1.set_title("Blast radius by role type", loc="left")

    stages = ["org\nviewer", "+ project\nbinding", "+ weaker\nrole", "+ DENY"]
    vals = [len(effective_permissions(dev, "bob@acme.com")), len(before),
            len(after), len(after_deny)]
    ax2.plot(stages, vals, "o-", color=PALETTE["blue"], lw=2)
    ax2.set_ylabel("effective permissions")
    ax2.set_title("Only DENY ever subtracts", loc="left")
    save_figure(fig, OUT / "iam_hierarchy.png")
    print(f"\n  figure -> {OUT / 'iam_hierarchy.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "revoke access granted at the folder"      you cannot, at the project.
                                             Change it where it was granted,
                                             or use an IAM DENY policy
  "grant least privilege"                    PREDEFINED role at the smallest
                                             scope. Never a basic role
  "temporary access for an audit"            a binding with a CONDITION
  "avoid service account keys"                attach the SA, or impersonate
  "who can actually delete this bucket"      direct holders PLUS anyone who
                                             can impersonate a holder
  "different teams, same project"            separate resources and bind at
                                             the resource, not the project""")


if __name__ == "__main__":
    main()
