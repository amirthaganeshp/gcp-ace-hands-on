# Service names — what things are called now

Google renames services, and exam material, blog posts and your own notes will disagree about what
something is called. **The old name is usually the one you learned it by**, so this table is
old → new.

> ⚠️ Naming and deprecation status move. Treat the "status" column as a pointer to check, not as a
> fact with a date on it.

---

## Renamed

| you may know it as | it is now | note |
|---|---|---|
| **Stackdriver** | **Google Cloud Operations suite** | Stackdriver Logging → **Cloud Logging**, Monitoring → **Cloud Monitoring**, Trace/Debugger/Profiler kept their names |
| **Cloud Functions** | **Cloud Run functions** | folded into Cloud Run. The *concept* is unchanged; questions may use either name |
| **Container Registry** (`gcr.io`) | **Artifact Registry** | Artifact Registry handles more than containers (Maven, npm, apt) and is the current answer |
| **Cloud Dataflow / Dataproc / Datalab** etc. | **Dataflow, Dataproc, …** | the "Cloud" prefix was dropped from many product names |
| **Cloud Deployment Manager** | → **Infrastructure Manager** | not a rename so much as a replacement — see below |
| **Anthos** | **GKE Enterprise** | the multi-cluster / hybrid platform |
| **Preemptible VMs** | **Spot VMs** | *not* the same thing — see the distinction below |
| **Cloud Memorystore** | **Memorystore** | |
| **Cloud AutoML / AI Platform** | **Vertex AI** | mostly outside ACE scope; relevant if you also sit PMLE |
| **Cloud Identity-Aware Proxy** | **IAP** | unchanged, but usually written as the acronym |
| **Cloud Armor** | **Cloud Armor** | unchanged; pairs with the global Application LB |
| **HTTP(S) Load Balancer** | **global external Application Load Balancer** | the whole LB family was renamed — see below |

## The load balancer renaming

This one catches people out because **every** name changed, not just one.

| old name | current name |
|---|---|
| HTTP(S) Load Balancing | **(global/regional) external Application Load Balancer** |
| Internal HTTP(S) Load Balancing | **internal Application Load Balancer** |
| TCP/SSL Proxy Load Balancing | **(global/regional) external proxy Network Load Balancer** |
| Network Load Balancing | **external passthrough Network Load Balancer** |
| Internal TCP/UDP Load Balancing | **internal passthrough Network Load Balancer** |

**The words that carry the meaning are `Application` vs `Network` (layer 7 vs 4), `proxy` vs
`passthrough` (terminated vs original client IP), and `external` vs `internal`.** Parse a new name
by those three axes and the old name falls out. See
[`06_networking` §7](../06_networking/README.md).

## Being retired or replaced

| | |
|---|---|
| **Deployment Manager** | Google has announced its deprecation in favour of **Infrastructure Manager** (managed Terraform). Exam blueprints lag announcements — know what it *is*, expect it in questions, start nothing new on it |
| **Cloud IoT Core** | retired. If it appears, the answer involves Pub/Sub and partners instead |
| **Cloud Debugger** | retired from the Operations suite; Trace and Profiler remain |
| **`gsutil`** | being folded into **`gcloud storage`**, which is also faster. Both work today; `gcloud storage` is the current answer |
| **`gcloud beta`/`alpha` commands** | commands graduate out of these groups. A command that "doesn't exist" may have moved to GA, or the reverse |

## Pairs that sound like renames and are not

These are **different products**, and the exam uses the similarity.

| | |
|---|---|
| **Preemptible VM** vs **Spot VM** | Spot is the newer model. **Preemptible VMs are always stopped within 24 hours; Spot VMs have no such limit.** Otherwise similar |
| **Labels** vs **Tags** vs **network tags** | three things. Labels = billing/organisation. Tags (Resource Manager) = inherited, usable in IAM and Org Policy conditions. Network tags = firewall targets only. → [`01_resource_hierarchy` §7](../01_resource_hierarchy/README.md) |
| **Commitment** vs **Reservation** | a commitment is **billing**; a reservation is **capacity**. → [`08_billing_cost` §3](../08_billing_cost/README.md) |
| **Cloud NAT** vs **Private Google Access** | NAT reaches the internet; PGA reaches Google APIs only, and is free. → [`06_networking` §6](../06_networking/README.md) |
| **Firestore** vs **Datastore** | Firestore is the current product; Datastore mode exists for legacy compatibility |
| **Cloud Run** vs **Cloud Run functions** | the same platform; functions is the source-deployed, single-function form |
| **Sole-tenant** vs **Confidential VM** | tenancy vs memory encryption. Different axes entirely. → [`03_compute` §8](../03_compute/README.md) |
| **Cloud Interconnect** vs **Cloud VPN** | dedicated/partner physical link vs IPsec over the public internet |
| **`gcloud auth login`** vs **`gcloud auth application-default login`** | two credential stores. → [`00_setup`](../00_setup/README.md) |
| **Instance template** vs **machine image** vs **custom image** | a template describes how to make instances; a machine image captures a whole existing instance; a custom image is a boot disk to launch from |
| **Cloud Build** vs **Cloud Deploy** | Build produces the artifact **once** (CI); Deploy promotes that **same** artifact through environments with approval gates (CD). → [`09_iac` §6b](../09_iac/README.md) |
| **Container Registry** vs **Artifact Registry** | see *Renamed* above — Artifact Registry is the current one, and it also holds Maven/npm/apt, not only containers |
| **App Engine versions/traffic-split** vs **Cloud Run revisions/traffic** | the same idea, two products. App Engine is where the exam introduced it and still favours testing it there. → [`03_compute` §1b](../03_compute/README.md) |

## Things whose *name* is the answer

Worth memorising as strings, because a question will name them and nothing else will fit:

```
constraints/gcp.resourceLocations
constraints/compute.vmExternalIpAccess
constraints/iam.disableServiceAccountKeyCreation
constraints/compute.requireOsLogin
constraints/sql.restrictPublicIp

roles/orgpolicy.policyAdmin          the one to withhold below the org
roles/iam.serviceAccountTokenCreator impersonation
roles/billing.user                   link projects to a billing account
roles/iam.securityReviewer           read IAM policies without changing them

_Required    400 days, free, cannot be modified or disabled
_Default     30 days, chargeable, can be excluded from and re-retained

35.191.0.0/16 + 130.211.0.0/22   Google health checkers
35.235.240.0/20                  IAP TCP forwarding
```
