# The resource hierarchy — where a setting attaches decides who it reaches

> **ACE domain 1 (~23%)** — setting up a cloud solution environment
> **Runtime:** ~2 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 01_resource_hierarchy/hierarchy_and_policy.py
```

Nearly all of domain 1 is one idea: **everything attaches somewhere in a tree**, and where you
attach it decides both its reach and *who can change it*.

**§3 is a real evaluator** implementing Google's documented inheritance and merge rules; **§5 is
arithmetic**. §1, §2, §6 and §7 are documented 📝, with §1's blast-radius counts computed from the
tree.

This part closes two threads left open elsewhere: [`02_iam`](../02_iam/README.md) showed allow
policies only ever **add**, and [`06_networking`](../06_networking/README.md) showed a firewall deny
is **not** a guardrail because priority can outrank it. §4 shows what an actual guardrail is made
of.

---

## 1. The hierarchy, and blast radius

```
organization  acme.com
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
```

**Folders exist to be a policy boundary, not to be tidy.** A folder grouping projects nobody ever
applies a shared policy to is decoration. Folders nest up to 10 deep; projects cannot contain
projects.

| attach an IAM binding or Org Policy at | reaches |
|---|---|
| organization `acme.com` | **7 projects** |
| folder `product` | 4 |
| folder `product-eu` | 2 |
| folder `core-infra` | 2 |
| project `shop-eu-prod` | 1 |

The organization node is not "the top of the tidy tree", it is **a switch with 7 projects behind
it**. Everything in this domain inherits downward, so the only real question is ever: **the smallest
node that covers what I mean.**

There is exactly one thing above the organization: nothing. You cannot attach a policy higher —
which is why the org node is the only place a guardrail can be truly unavoidable.

## 2. Projects — three identifiers, and which one is forever 📝

| | |
|---|---|
| **Project ID** | **globally unique across all of Google Cloud**, chosen by you, and **immutable**. What almost every CLI call takes. A deleted ID is not reusable |
| **Project name** | a display label. Not unique, changeable |
| **Project number** | generated, numeric, immutable. Appears in service account emails |

The trap is the ID: *"rename the project"* is only ever the **name**, and if the **ID** is wrong the
answer is a new project plus a migration.

**The project is the unit of nearly everything** — billing attaches per project, **quotas are per
project** (§5 — which is why *"just use more projects"* is a legitimate architecture, not a hack),
IAM policies and enabled APIs live in one, and deleting a project deletes everything in it.

**Deletion is a 30-day soft delete** — the project goes to a pending state and can be restored. A
**lien** blocks deletion entirely until removed: that is the answer to *"stop anyone deleting the
production project"*.

**Moving a project between folders** is allowed and re-resolves every inherited policy immediately.
A useful tool and a very good way to surprise yourself.

## 3. Organization Policy — a real evaluator

**Org Policy is not IAM.** IAM says *who* may act. Org Policy says *what configurations may exist*,
no matter who is asking. **An owner of the project cannot create a resource an Org Policy forbids.**

| constraint kind | resolution |
|---|---|
| **Boolean** | enforced or not. The **closest** policy in the chain wins — no merge |
| **List** | allowed/denied values with `inheritFromParent`. Merging **intersects** allowed and **unions** denied, and **deny always wins** |

```
constraints/gcp.resourceLocations
  organization  allow [us-central1, us-east1, europe-west1, europe-west4]
  product-eu    deny  [us-central1, us-east1]
  product-us    deny  [europe-west1, europe-west4]
```

| project | us-central1 | us-east1 | europe-west1 | europe-west4 | asia-east1 |
|---|---|---|---|---|---|
| `net-hub` | yes | yes | yes | yes | **NO** |
| `shop-eu-prod` | NO | NO | yes | yes | **NO** |
| `shop-us-prod` | yes | yes | NO | NO | **NO** |
| `sandbox-alice` | yes | yes | yes | yes | **NO** |

**`asia-east1` is refused everywhere and no node mentions it.** An allow list is a **whitelist** —
anything not on it is denied. That is the behaviour people forget when they add one region and
wonder why a different team's deployment broke.

Note the two folders: each denies what the other needs, from a single org-level allow list. **Data
residency in two lines, enforced on everyone.**

## 4. Org Policy vs IAM — only one of them is a guardrail

```
constraints/compute.vmExternalIpAccess
  organization  allow []      (no VM may have an external IP)

can shop-us-dev give a VM an external IP?   False
```

The dev team needs one bastion. They set a policy **at their own project** with
`inheritFromParent = false`:

| | |
|---|---|
| can the **bastion** now have an external IP? | **True** |
| can any **other** VM in that project? | False |
| did it affect the sibling prod project? | False |
| effective policy now sourced from | `shop-us-dev` (**RESET** — inheritFromParent=false) |

**The org-level policy was overridden at the project.** That is *by design* —
`inheritFromParent=false` is the documented escape hatch, and without it every exception would have
to be granted at the organization, where it would apply to everybody.

> **So what makes it a guardrail? Not the mechanism.** It is the IAM permission to use it:
> `orgpolicy.policies.create`, carried by `roles/orgpolicy.policyAdmin`. Grant that at the
> organization **only**, and a project team cannot do what the block above just did — they have to
> ask.

### The three mechanisms, side by side

| | |
|---|---|
| **IAM allow** | purely additive. A weaker binding lower down subtracts nothing — [`02_iam`](../02_iam/README.md) |
| **Firewall rule** | priority. A rule you write can outrank someone else's deny — [`06_networking`](../06_networking/README.md) |
| **Org Policy** | restricts what may **exist**, regardless of IAM. Can be overridden at a child — so the guardrail is really the IAM permission that lets you |

> **A guardrail is not a mechanism, it is a mechanism plus control of who can change it.** The only
> two that hold against a determined project owner are an **Org Policy** and an **IAM Deny policy**,
> both attached *above* them, with the admin role withheld.

A boolean constraint, for contrast:

```
iam.disableServiceAccountKeyCreation
  shop-eu-prod     enforced=True   set at acme.com
  sandbox-alice    enforced=False  set at sandbox-alice
```

Closest wins — no merge, no intersection. This constraint is the platform-level answer to `02_iam`'s
*"avoid downloading service account keys"*: **not a policy document asking people not to, but the
API refusing.**

## 5. Quotas — which one actually stops your deployment

> ⚠️ Representative defaults for a new project with billing on. Real limits vary by project age,
> spend history and region.

**The plan:** 8 × `n2-standard-8` in `us-central1`, 200 GB boot disk each, 8 with an external IP.

| quota | scope | need | limit | headroom | |
|---|---|---|---|---|---|
| CPUS (per region) | regional | 64 | 72 | 8 | |
| **N2_CPUS (per region)** | regional | 64 | 48 | **−16** | **BLOCKS** |
| CPUS_ALL_REGIONS | global | 64 | 96 | 32 | |
| IN_USE_ADDRESSES (per region) | regional | 8 | 8 | 0 | exactly at the limit, which is allowed |
| DISKS_TOTAL_GB (per region) | regional | 1600 | 4096 | 2496 | |
| INSTANCES (per region) | regional | 8 | 100 | 92 | |

Taking each quota alone, the largest fleet of this shape it permits:

| quota | largest fleet it alone allows |
|---|---|
| **N2_CPUS (per region)** | **6** ← the binding one |
| CPUS (per region) | 9 |
| CPUS_ALL_REGIONS | 12 |
| DISKS_TOTAL_GB (per region) | 20 |
| INSTANCES (per region) | 100 |
| IN_USE_ADDRESSES (per region) | no limit at this shape |

**The plan asked for 8. The largest that fits is 6.** And note which quota stops it: not the
instance count — the number the plan was *written* in — and not the general CPU quota either, but
the **per-machine-family** one, which most people don't know exists until it fires.

> **One deployment consumes several quotas at once, and the one that stops you is rarely the one you
> were thinking about.** Switching family would move the ceiling without changing a single thing
> about the workload — worth knowing before you file a request that takes two days.

**Two kinds of quota, and the exam distinguishes them:**

| | |
|---|---|
| **Rate** quotas | requests per minute/day. They **reset**. A 429 here means slow down and retry |
| **Allocation** quotas | things you **hold** — vCPUs, IPs, disks. They do **not** reset. Release the resource or request an increase |

Quotas are **per project** and mostly **per region**. Three consequences:

- *"We hit a quota"* → **more projects is a valid answer**, and often the intended one
- a second region does **not** consume the first region's regional quota, but **does** consume
  `CPUS_ALL_REGIONS`
- a quota increase is a **request, not a setting**. It takes time, so it belongs in the plan, not in
  the incident

**Quotas are not limits.** Some caps are architectural and cannot be raised at any price.

## 6. Billing structure 📝

**A billing account is not in the project tree.** It is a separate resource projects are *linked*
to — which is why billing admins and project admins are usually different people.

- one project links to exactly **one** billing account; one billing account pays for **many**
  projects
- a project with no billing account **cannot use most services**. *"It worked yesterday"* +
  *"everything is failing"* + *"nothing changed"* is very often a closed billing account
- moving a project between billing accounts needs permission on **both** sides

| role | what it is for |
|---|---|
| `roles/billing.admin` | manage the billing account |
| **`roles/billing.user`** | **link projects to it** — the one that lets someone create a project that actually works |
| `roles/billing.viewer` | see the spend |
| `roles/billing.creator` | create new billing accounts |

**Billing export to BigQuery** is the answer to nearly every *"analyse our spend"* question. The
console reports are fixed; the export is the data. **Turn it on before you need it — it is not
retroactive.** Budgets and discount programmes are in `08_billing_cost`.

## 7. Labels vs tags vs network tags 📝

Three different things with confusingly similar names. The exam uses the confusion deliberately.

| | |
|---|---|
| **Labels** | key-value pairs for **organising and billing**. They flow into the billing export, so *"how much does team X spend"* is a label question. **No access-control meaning at all.** Not inherited |
| **Tags** (Resource Manager) | key-value pairs that **are inherited** down the hierarchy and **can be referenced in IAM conditions and Org Policy conditions**. This is the one with teeth |
| **Network tags** | plain strings on a VM, used **only** as firewall and route targets. No hierarchy, no IAM, no billing — the ones in [`06_networking` §5](../06_networking/README.md) |

> Cost attribution ⇒ **labels**. Applying policy conditionally ⇒ **tags**. A firewall rule ⇒
> **network tags**.

## The exam angle

| the scenario says | the answer |
|---|---|
| "apply this to every project, including future ones" | **Organization Policy** at the org node |
| "data must stay in the EU" | `gcp.resourceLocations`, at the folder that owns it |
| "no VM may have a public IP" | `compute.vmExternalIpAccess` |
| "nobody may download service account keys" | `iam.disableServiceAccountKeyCreation` — a boolean |
| "an owner should not be able to turn this off" | **withhold `roles/orgpolicy.policyAdmin`** below the org |
| "stop anyone deleting this project" | a **lien** |
| "rename the project" | the **name** only. The ID is immutable |
| "we hit a CPU quota" | request an increase, or use another **region** or **project** |
| "how much did team X spend" | **labels** + billing export to BigQuery |
| "apply policy to everything tagged prod" | **tags**, not labels |
| "let this person set up projects that can actually bill" | `roles/billing.user` |
| "everything broke and nothing changed" | check the **billing link** |

## Things to try

Both of these are checked, with the results:

```
baseline          shop-eu-prod  ['europe-west1', 'europe-west4']
org denies ew4    shop-eu-prod  ['europe-west1']
eu resets         shop-eu-prod  ['europe-west1', 'europe-west4', 'asia-east1']
```

- Add `denied={"europe-west4"}` at the **organization** and re-resolve. The EU projects lose a
  region their own folder never mentioned — **deny inherits, and there is no "allow it back"
  below**.
- Set `inherit_from_parent=False` on `product-eu`'s policy. `asia-east1` — refused everywhere in
  §3 — **becomes allowed**, because a reset discards the parent's *allow list* along with
  everything else, leaving only the folder's deny-list. That is the subtle half of the escape
  hatch: overriding to add one exception silently removes every restriction you were relying on.
- Change `vcpu_each` to 4 in §5 and re-read both quota tables. The binding quota changes, and so
  does the answer to "what should we ask support for".

## What is not demonstrated here

Not simulated, and not claimed: real project creation, real Org Policy enforcement (the evaluator
implements the documented resolution rules, it does not call the API), real quota values, custom
constraints, Org Policy **dry-run** mode, or Policy Intelligence / Policy Simulator. The resolution
rules in §3 and the arithmetic in §5 are exact given their inputs.
