# Decisions — every "the scenario says → the answer" in one place

Collected from the nine built parts. Each section links back to where it is demonstrated, because a
table like this is only useful once you have seen *why*.

---

## Setting up → [`00_setup`](../00_setup/README.md)

| the scenario says | the answer |
|---|---|
| "switch between two projects constantly" | `gcloud config configurations` |
| "my script can't authenticate but gcloud works" | `gcloud auth application-default login` — a **different** credential store |
| "run one command against a different project" | the `--project` flag |
| "no local install, already authenticated" | **Cloud Shell** |
| "act as a service account without a key" | `--impersonate-service-account` |
| "the command doesn't exist" | `gcloud beta` / `alpha`, or `gcloud components install` |
| "files installed in Cloud Shell vanished" | only **`$HOME`** persists |

## Hierarchy, org policy, quotas → [`01_resource_hierarchy`](../01_resource_hierarchy/README.md)

| the scenario says | the answer |
|---|---|
| "apply this to every project, including future ones" | **Organization Policy** at the org node |
| "data must stay in the EU" | `gcp.resourceLocations` at the folder that owns it |
| "no VM may have a public IP" | `compute.vmExternalIpAccess` |
| "nobody may download service account keys" | `iam.disableServiceAccountKeyCreation` |
| "an owner should not be able to turn this off" | withhold `roles/orgpolicy.policyAdmin` below the org |
| "stop anyone deleting this project" | a **lien** |
| "rename the project" | the **name** only — the ID is immutable |
| "we hit a CPU quota" | request an increase, or use another **region** or **project** |
| "how much did team X spend" | **labels** + billing export to BigQuery |
| "apply policy to everything tagged prod" | **tags**, not labels |
| "let this person set up projects that can bill" | `roles/billing.user` |
| "everything broke and nothing changed" | check the **billing link** |

## Access and security → [`02_iam`](../02_iam/README.md)

| the scenario says | the answer |
|---|---|
| "revoke access granted at the folder" | **you cannot, at the project.** Change it where granted, or use an IAM **Deny** policy |
| "grant least privilege" | a **predefined** role at the **smallest scope**. Never a basic role |
| "temporary access for an audit" | a binding with a **condition** |
| "avoid service account keys" | **attach** the SA, or **impersonate** it |
| "who can actually delete this bucket" | direct holders **plus** anyone who can impersonate one |
| "different teams, same project" | bind at the **resource**, not the project |

## Compute → [`03_compute`](../03_compute/README.md)

| the scenario says | the answer |
|---|---|
| "lift and shift", "cannot be rewritten", "needs a specific OS" | **Compute Engine** |
| "containers, and the team wants Kubernetes" | **GKE** (Autopilot unless they ask to manage nodes) |
| "stateless container, HTTP, spiky traffic" | **Cloud Run** |
| "run code when a file lands in a bucket" | **Cloud Run functions** |
| "fault-tolerant batch, cost is the priority" | **Spot VMs**, with checkpointing |
| "must run for exactly 24 hours" | **not preemptible** — those stop within 24 h |
| "survive a zone failure" | **regional** managed instance group |
| "licence counted per physical core" | **sole-tenant nodes** |
| "memory must be encrypted in use" | **Confidential VM** |
| "fastest possible scratch disk" | **Local SSD** — and accept that it is ephemeral |
| "the instance is gone but we need the data" | only if **keep boot disk** was set |
| "scaling is too slow" | a **baked image** and **min instances**, not a faster autoscaler |
| "legacy app, no containers, gradual traffic shift to a new version" | **App Engine** — `versions` + `services set-traffic` |
| "one command from source to a running URL" | `gcloud run deploy --source=.` — builds via Cloud Build, pushes to Artifact Registry, deploys |
| "no infrastructure at all, just deploy my code" | **App Engine standard**, or **Cloud Run** if it is a container |

## Kubernetes and GKE → [`04_kubernetes`](../04_kubernetes/README.md)

| the scenario says | the answer |
|---|---|
| "we do not want to manage nodes" | **GKE Autopilot** |
| "we need a DaemonSet with host access" | **GKE Standard** |
| "a pod must call a Google Cloud API" | **Workload Identity**. Never a downloaded key |
| "expose this to the internet" | a Service of type **LoadBalancer**, or Ingress/Gateway |
| "expose it only inside the cluster" | **ClusterIP** — the default |
| "survive a zone failure" | a **regional** cluster |
| "the pod is Pending and nothing happens" | no node satisfies its **requests** |
| "the container keeps restarting" | **liveness** probe failing, or an OOM kill at its **limit** |
| "traffic goes to a pod that is not ready" | the **readiness** probe is missing |
| "roll back the bad release" | `kubectl rollout undo` |
| "cheap batch on GKE" | a **Spot node pool** plus tolerations |
| "nodes must have no public IPs" | a **private cluster** + Cloud NAT |

## Storage and databases → [`05_storage`](../05_storage/README.md)

| the scenario says | the answer |
|---|---|
| "accessed once a month" | **Nearline** |
| "DR copy, tested quarterly" | **Coldline** |
| "keep 7 years for compliance, never read" | **Archive** + a **locked retention policy** |
| "move old data to a cheaper class automatically" | a **lifecycle rule**, not a script |
| "several VMs need the same filesystem" | **Filestore** |
| "let a customer download one file, no Google account" | a **signed URL** |
| "objects must not be deletable, even by an admin" | **retention policy with a lock** |
| "we must control the encryption key" | **CMEK** with Cloud KMS |
| "relational, global, strongly consistent" | **Spanner** |
| "managed MySQL for an existing app" | **Cloud SQL** |
| "time series at millions of ops/sec" | **Bigtable** |
| "mobile app that works offline" | **Firestore** |
| "the bucket is in the wrong region" | create a new one and copy — location is immutable |

## Networking → [`06_networking`](../06_networking/README.md)

| the scenario says | the answer |
|---|---|
| "instances in two regions must talk privately" | **same VPC, internal IPs.** Nothing else needed |
| "private VMs need OS patches from the internet" | **Cloud NAT** (+ Cloud Router) |
| "private VMs only need Google APIs" | **Private Google Access** — *not* NAT |
| "I added an allow rule and it is still blocked" | a **lower-numbered deny** is winning |
| "stop anyone opening 0.0.0.0/0" | **Org Policy** — a firewall deny can be outranked |
| "central network team, one project per team" | **Shared VPC** |
| "merge two networks, both on 10.0.0.0/16" | **you cannot peer them.** One must be renumbered |
| "global HTTP(S), one IP, a WAF" | global external **Application LB** + **Cloud Armor** |
| "must see the real client IP" | **passthrough** Network LB |
| "the subnet is full" | **expand** the primary range. You cannot shrink it back |

## Operations → [`07_operations`](../07_operations/README.md)

| the scenario says | the answer |
|---|---|
| "who deleted the instance" | **Admin Activity** audit log — already on, cannot be off |
| "who **read** the customer table" | **Data Access** audit log — must be **enabled** first |
| "keep audit logs 7 years" | a **sink** to Cloud Storage. `_Required` is 400 days and fixed |
| "centralise logs from every project" | an **aggregated sink** with `includeChildren` |
| "our logging bill is too high" | **exclude at ingestion.** Routing elsewhere adds a copy |
| "alert when a VM runs out of memory" | install the **Ops Agent** first |
| "alert on queue depth" | a **custom** or **log-based** metric |
| "we get paged constantly" | raise the **duration**, not the threshold |
| "is the site up for users in Asia" | an **uptime check** |
| "which microservice is slow" | **Cloud Trace** |
| "which function is burning CPU" | **Cloud Profiler** |
| "one dashboard across our projects" | a **metrics scope** |

## Billing and cost → [`08_billing_cost`](../08_billing_cost/README.md)

| the scenario says | the answer |
|---|---|
| "stop spending when we hit the budget" | **you cannot with a budget alone.** Budget → Pub/Sub → function that disables billing |
| "warn us before we overspend" | a **forecasted-spend** alert |
| "steady workload running 24/7" | **committed use discount** |
| "we already run it all month — what do we apply for" | **nothing.** Sustained use is automatic |
| "fault-tolerant batch, cheapest" | **Spot VMs** |
| "guarantee we can get the capacity" | a **reservation**. A commitment is billing, not capacity |
| "find waste for us" | **Recommender** |
| "estimate before we build" | the **pricing calculator** |
| "bill is high and compute looks normal" | **egress**, idle static IPs, unattached disks, log ingestion |
| "cancel our 3-year commitment" | **you cannot** |

## Infrastructure as code → [`09_iac`](../09_iac/README.md)

| the scenario says | the answer |
|---|---|
| "identical dev, staging and prod" | IaC, one configuration, separate state and separate **projects** |
| "review infrastructure changes before they happen" | `terraform plan` in a pull request |
| "multi-cloud", or names Terraform | **Terraform** |
| "managed Terraform inside Google Cloud" | **Infrastructure Manager** |
| "Google's original YAML/Jinja IaC" | **Deployment Manager** (being retired) |
| "manage cloud resources with kubectl" | **Config Connector** |
| "we built it by hand, now put it in code" | `terraform import` |
| "stop managing this without deleting it" | `terraform state rm` |
| "where does state go" | a **versioned GCS bucket**. Never git |
| "two engineers applied at once" | remote backend **locking** |
| "someone changed it in the console" | the next apply **reverts** it |
| "why is it destroying my instance" | a **force-new** attribute changed, or something upstream was replaced |
| "build and deploy automatically on every push" | a **Cloud Build trigger** |
| "promote the same image through dev, staging, prod with approval" | **Cloud Deploy** |
| "run terraform apply from CI, not a laptop" | **Cloud Build**, calling Terraform as a step |

---

## The five rules that decide more questions than anything else

1. **IAM allow policies only ever add.** A weaker binding lower down subtracts nothing; only an IAM
   **Deny** policy subtracts. → `02_iam`
2. **Where you attach a policy decides its blast radius, and the answer is always the smallest node
   that covers what you mean.** → `01_resource_hierarchy`
3. **A guardrail is a mechanism *plus* control of who can change it.** A firewall deny can be
   outranked by priority; an Org Policy can be reset at a child — unless the admin role is withheld
   above them. → `01_resource_hierarchy` §4, `06_networking` §5b
4. **Some things are immutable: project ID, bucket location, subnet shrink, a commitment.** If the
   scenario asks to change one, the answer is "create a new one and migrate". → everywhere
5. **Cost is decided before the discount.** Not running it, then right-sizing, then the right
   product — *then* a discount programme. → `08_billing_cost` §1

## And one rule these tables cannot give you

→ [`10_capstone_summary`](../10_capstone_summary/README.md) builds one environment end to end by
importing the engines from all nine parts, then scores it: **5 OK, 3 RISK — and all three risks are
defaults nobody revisited**, not wrong answers.

It also **overturned a conclusion from `08_billing_cost`**. That part reported sustained use winning
zero of seven rows; the capstone's autoscaled tier lands at 42% uptime, where SUD *is* cheapest. The
grid had sampled the two endpoints of the window and stepped over its interior.

> **A table of right answers will not tell you which question you are in.** That is what the
> capstone is for, and it is why it imports the real engines rather than restating their results.
