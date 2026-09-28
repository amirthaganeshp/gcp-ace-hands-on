# IAM — inheritance, and why you cannot take it back

> **ACE domain 4 (~20%)** — configuring access and security
> **Runtime:** ~2 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 02_iam/iam_hierarchy.py
```

---

## The idea

Most of this domain reduces to one rule that surprises people:

> **IAM policies inherit downward and they are ADDITIVE.**

Grant someone a role at the organization and **you cannot revoke it at a project**. There is no
"deny" inside an allow policy — only more allows.

The script implements the resolution rules and then demonstrates that, rather than asserting it.

## 1. Resolving effective permissions

Alice has `roles/viewer` at the **organization** and `bigquery.dataViewer` + `bigquery.jobUser` at
the **prod** project:

| scope | effective permissions |
|---|---|
| `dev-sandbox` | 12 |
| `prod-analytics` | **13** |

The one extra is `bigquery.create`.

> **`dataViewer` contributed nothing** — org-level `viewer` already granted `bigquery.get/list`.
> Only `jobUser` added anything. Overlapping grants are normal, which is why **counting roles tells
> you nothing about access**; you have to resolve the union.

*(That pair is the canonical BigQuery least-privilege combination: `dataViewer` lets you read the
data, `jobUser` lets you run a query at all. Grant only the first and the user can see nothing,
because they cannot start a job.)*

## 2. The demonstration — trying to take access away

Bob has `roles/editor` at the **organization** → **30 permissions** on prod.

The prod team wants him read-only on *their* project, so they bind `roles/viewer` at the project:

| | |
|---|---|
| before | **30** permissions |
| after | **30** permissions |
| change | **+0** |
| can Bob still delete compute instances? | **True** |

**Binding a weaker role does not weaken anything.** Allow policies only ever add. The project team
cannot revoke what the organization granted — they must ask whoever owns that level.

> **This is the most commonly missed rule in the domain**, and it is the reason "just add a Viewer
> binding at the project" is wrong in every scenario that phrases it that way.

## 3. IAM Deny — the one thing that *can* override an allow

A deny policy at prod blocking `compute.delete` and `storage.delete`:

| | |
|---|---|
| before deny | 30 |
| **after deny** | **28** |
| can Bob delete compute? | **False** |

**Deny is evaluated after allow and wins.** It is the only way to subtract, it is a *separate
policy type* rather than a binding, and note it left his other editor permissions intact.

## 4. Blast radius — basic vs predefined vs custom

> ⚠️ **Representative permission model, not Google's real lists.** `roles/editor` alone carries
> thousands. Real figures need `gcloud auth login` then `gcloud iam roles describe`. **The
> resolution rules above are exact; these counts are illustrative.**

| role | permissions | services |
|---|---|---|
| `roles/owner` | 36 | **6** |
| `roles/editor` | 30 | **6** |
| `roles/viewer` | 12 | **6** |
| `roles/storage.admin` | 6 | 1 |
| `roles/bigquery.dataViewer` | 2 | 1 |
| `custom/binaryDeployer` | 2 | 2 |

**Basic roles span every service.** That is why *"grant Editor and move on"* is the wrong answer to
every least-privilege question — it is not slightly too much, it is **every service in the
project**.

## 5. Service accounts and impersonation

If Carol can **impersonate** a service account (`roles/iam.serviceAccountTokenCreator`), she has
*its* permissions, not hers.

> **Impersonation is a privilege path.** Auditing *"who can delete objects"* means auditing who can
> impersonate something that can — not just who holds the role directly.

It is also the right answer to **"how do we avoid service account keys"**: attach the account, or
impersonate it. A downloaded key never expires, cannot be rotated by the platform, and ends up in
a git repository.

## 6. Conditions

A binding can carry a condition that must hold for the grant to apply:

```
request.time < timestamp("2026-12-31T00:00:00Z")      time-bound access
resource.name.startsWith("projects/_/buckets/tmp")    one bucket only
resource.type == "storage.googleapis.com/Object"      one resource type
```

Use them for temporary elevation instead of granting a role and trusting someone to remember to
remove it.

## The exam angle

| the scenario says | the answer |
|---|---|
| "revoke access granted at the folder" | **you cannot, at the project** — change it where it was granted, or use an IAM **Deny** policy |
| "grant least privilege" | a **predefined** role at the **smallest scope**. Never a basic role |
| "temporary access for an audit" | a binding with a **condition** |
| "avoid service account keys" | **attach** the SA, or **impersonate** it |
| "who can actually delete this bucket" | direct holders **plus** anyone who can impersonate one |
| "different teams, same project" | bind at the **resource**, not the project |

## Things to try

- Add a binding at the `folder` level and re-resolve. Folder grants reach both projects — which is
  exactly how access spreads faster than anyone intended.
- Deny a permission at the **organization** and check it still applies at a project. Deny inherits
  downward too.
