# CLI reference

ACE is the most command-line-heavy of the three Google Cloud certifications, so this is a **primary
deliverable of this repository**, not an appendix.

> ⚠️ **Nothing here is executed by this repository.** These are documented commands, checked against
> the SDK's own help where possible. Flags move between releases — `gcloud <group> <verb> --help` is
> authoritative, always.

---

## The shape of every gcloud command

```
gcloud  <group> <subgroup...>  <VERB>  [NAME]  --flags
        └─ compute networks    subnets create   web-uc1  --network=prod-net
```

**Learn the verbs, not the commands.** They are near-universal:

| verb | |
|---|---|
| `create` / `delete` | make and unmake |
| `list` | many, filterable |
| `describe` | one, in full |
| `update` / `patch` | change in place |
| `add-*` / `remove-*` | `add-iam-policy-binding`, `add-tags` |
| `get-*` / `set-*` | `get-iam-policy`, `set-machine-type` |

**And learn the zonal/regional/global split**, because it decides which flag is mandatory:

| scope | needs | examples |
|---|---|---|
| **zonal** | `--zone` | instances, zonal disks, zonal MIGs |
| **regional** | `--region` | subnets, addresses, regional MIGs, Cloud SQL |
| **global** | neither | **networks**, firewall rules, routes, images, snapshots |

A VPC is global and a subnet is regional — see [`06_networking`](../06_networking/README.md) §1. If
a command rejects `--region`, the resource is probably global.

## Global flags — the ones worth memorising

| flag | |
|---|---|
| `--project=ID` | override the active configuration for **one** command |
| `--format=...` | see [Format and filter](#format-and-filter) below |
| `--filter=...` | server- or client-side filtering |
| `--quiet` / `-q` | assume yes. **Required in scripts**, dangerous everywhere else |
| `--impersonate-service-account=SA` | act as a service account **without a key** |
| `--log-http` | print the REST calls being made. The best learning tool in the SDK |
| `--help` | on any group or verb |
| `--verbosity=debug` | when `--log-http` is too much |

---

## 1. Setup, configuration and auth → [`00_setup`](../00_setup/README.md)

```bash
gcloud init                                   # interactive: login + project + region
gcloud info                                   # paths, active config, active account
gcloud version
gcloud components list
gcloud components install kubectl beta
gcloud components update
```

**Configurations** — a named bundle of account + project + region + zone:

```bash
gcloud config configurations create dev
gcloud config configurations list             # the ACTIVE one is marked
gcloud config configurations activate dev
gcloud config set project my-project-id
gcloud config set compute/region us-central1
gcloud config set compute/zone us-central1-a
gcloud config list
gcloud config get-value project
gcloud config unset compute/zone
```

**Auth — three different things:**

```bash
gcloud auth login                             # YOU, for gcloud commands
gcloud auth application-default login         # ADC, for CLIENT LIBRARIES and Terraform
gcloud auth list                              # which accounts, which is active
gcloud auth revoke user@example.com
gcloud auth print-access-token                # a token, for curl against the REST API
gcloud auth activate-service-account --key-file=key.json
```

> **`gcloud auth login` and `gcloud auth application-default login` are separate credential
> stores.** Doing one does not do the other. This is the most common *"but I am logged in"*
> confusion in the whole SDK.

**Project precedence, highest first:** `--project` flag → `CLOUDSDK_CORE_PROJECT` env var → active
configuration.

---

## 2. Resource hierarchy → [`01_resource_hierarchy`](../01_resource_hierarchy/README.md)

```bash
gcloud organizations list
gcloud organizations describe ORG_ID

gcloud resource-manager folders create --display-name="product" --organization=ORG_ID
gcloud resource-manager folders list --organization=ORG_ID
gcloud resource-manager folders list --folder=PARENT_FOLDER_ID

gcloud projects create my-project-id --name="My Project" --folder=FOLDER_ID
gcloud projects list
gcloud projects list --filter="parent.id=FOLDER_ID"
gcloud projects describe my-project-id
gcloud projects delete my-project-id          # 30-day soft delete
gcloud projects undelete my-project-id
gcloud projects move my-project-id --folder=OTHER_FOLDER_ID
```

**Liens** — stop anyone deleting a project:

```bash
gcloud resource-manager liens create \
  --restrictions=resourcemanager.projects.delete \
  --reason="production" --project=my-project-id
gcloud resource-manager liens list --project=my-project-id
```

**Services (APIs)** — most things fail until the API is enabled:

```bash
gcloud services list --enabled
gcloud services list --available
gcloud services enable compute.googleapis.com
gcloud services disable compute.googleapis.com
```

**Organization Policy:**

```bash
gcloud org-policies list --organization=ORG_ID
gcloud org-policies list --project=my-project-id --show-unset
gcloud org-policies describe constraints/compute.vmExternalIpAccess --organization=ORG_ID
gcloud org-policies set-policy policy.yaml
gcloud org-policies delete constraints/... --project=my-project-id
```

*(Older SDKs use `gcloud resource-manager org-policies ...` — same idea, different group.)*

**Quotas:**

```bash
gcloud compute project-info describe --project=my-project-id   # regional quotas
gcloud compute regions describe us-central1                    # quotas for one region
```

---

## 3. IAM → [`02_iam`](../02_iam/README.md)

```bash
gcloud projects get-iam-policy my-project-id --format=json
gcloud projects add-iam-policy-binding my-project-id \
  --member="user:alice@example.com" --role="roles/viewer"
gcloud projects remove-iam-policy-binding my-project-id \
  --member="user:alice@example.com" --role="roles/viewer"
```

**`--member` prefixes matter and are examinable:**

```
user:alice@example.com
group:team@example.com
serviceAccount:sa@project.iam.gserviceaccount.com
domain:example.com
allUsers                 # public - the internet
allAuthenticatedUsers    # anyone with a Google account, not just your org
```

The same `add-iam-policy-binding` verb exists at every level — that is inheritance in the CLI:

```bash
gcloud organizations add-iam-policy-binding ORG_ID --member=... --role=...
gcloud resource-manager folders add-iam-policy-binding FOLDER_ID --member=... --role=...
gcloud storage buckets add-iam-policy-binding gs://bucket --member=... --role=...
```

**Roles:**

```bash
gcloud iam roles list                                  # predefined
gcloud iam roles list --project=my-project-id          # custom
gcloud iam roles describe roles/storage.objectViewer   # its permission list
gcloud iam roles create myRole --project=my-project-id \
  --title="My Role" --permissions=storage.objects.get,storage.objects.list
```

**Service accounts:**

```bash
gcloud iam service-accounts create pipeline-sa --display-name="Pipeline"
gcloud iam service-accounts list
gcloud iam service-accounts describe pipeline-sa@PROJECT.iam.gserviceaccount.com

# Let alice IMPERSONATE it - the right answer, no key involved
gcloud iam service-accounts add-iam-policy-binding \
  pipeline-sa@PROJECT.iam.gserviceaccount.com \
  --member="user:alice@example.com" \
  --role="roles/iam.serviceAccountTokenCreator"

gcloud compute instances list --impersonate-service-account=pipeline-sa@PROJECT.iam.gserviceaccount.com
```

```bash
gcloud iam service-accounts keys create key.json --iam-account=SA_EMAIL
```

> ⚠️ **That last one is the command to avoid.** A downloaded key never expires, cannot be rotated by
> the platform, and ends up in a git repository. Attach the service account or impersonate it. The
> org policy `constraints/iam.disableServiceAccountKeyCreation` makes the API refuse.

**Conditions** — time-bound or resource-bound access:

```bash
gcloud projects add-iam-policy-binding my-project-id \
  --member="user:auditor@example.com" --role="roles/viewer" \
  --condition='expression=request.time < timestamp("2026-12-31T00:00:00Z"),title=temp-audit'
```

---

## 4. Compute → [`03_compute`](../03_compute/README.md)

### Compute Engine

```bash
gcloud compute instances create web-1 \
  --zone=us-central1-a --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud \
  --subnet=web-uc1 --tags=web,http-server \
  --metadata-from-file=startup-script=startup.sh \
  --service-account=SA_EMAIL --scopes=cloud-platform \
  --no-address                                   # no external IP

gcloud compute instances list
gcloud compute instances describe web-1 --zone=us-central1-a
gcloud compute instances stop  web-1 --zone=us-central1-a
gcloud compute instances start web-1 --zone=us-central1-a
gcloud compute instances delete web-1 --zone=us-central1-a --keep-disks=boot
gcloud compute instances set-machine-type web-1 --zone=us-central1-a \
  --machine-type=e2-standard-4                   # instance must be STOPPED
gcloud compute instances add-tags web-1 --zone=us-central1-a --tags=https-server
```

**Connecting:**

```bash
gcloud compute ssh web-1 --zone=us-central1-a
gcloud compute ssh web-1 --zone=us-central1-a --tunnel-through-iap   # no external IP
gcloud compute scp local.txt web-1:~/ --zone=us-central1-a
```

**Disks, snapshots, images:**

```bash
gcloud compute disks create data-1 --zone=us-central1-a --size=200GB --type=pd-balanced
gcloud compute disks resize data-1 --zone=us-central1-a --size=500GB   # grow only
gcloud compute disks snapshot data-1 --zone=us-central1-a --snapshot-names=data-1-snap
gcloud compute snapshots list
gcloud compute images create web-golden --source-disk=web-1 --source-disk-zone=us-central1-a
gcloud compute images list --filter="family=debian-12"
```

**Instance templates and managed instance groups:**

```bash
gcloud compute instance-templates create web-tpl \
  --machine-type=e2-medium --image-family=debian-12 --image-project=debian-cloud \
  --tags=web

gcloud compute instance-groups managed create web-mig \
  --template=web-tpl --size=3 --region=us-central1     # REGIONAL = multi-zone

gcloud compute instance-groups managed set-autoscaling web-mig --region=us-central1 \
  --min-num-replicas=2 --max-num-replicas=10 \
  --target-cpu-utilization=0.6 --cool-down-period=90

gcloud compute instance-groups managed list-instances web-mig --region=us-central1
gcloud compute instance-groups managed resize web-mig --region=us-central1 --size=5
gcloud compute instance-groups managed rolling-action start-update web-mig \
  --region=us-central1 --version=template=web-tpl-v2
gcloud compute instance-groups managed rolling-action restart web-mig --region=us-central1
```

**Spot:**

```bash
gcloud compute instances create batch-1 --zone=us-central1-a \
  --provisioning-model=SPOT --instance-termination-action=DELETE
```

### Cloud Run

```bash
gcloud run deploy web --source=. --region=us-central1 \
  --allow-unauthenticated --concurrency=80 --min-instances=0 --max-instances=20 \
  --set-env-vars=LOG_LEVEL=info --memory=512Mi --cpu=1

gcloud run services list --region=us-central1
gcloud run services describe web --region=us-central1
gcloud run revisions list --service=web --region=us-central1
```

**Traffic between revisions** — the same versions-and-splits idea as App Engine:

```bash
gcloud run services update-traffic web --region=us-central1 \
  --to-revisions=web-00042-abc=10,web-00041-xyz=90       # canary
gcloud run services update-traffic web --region=us-central1 --to-latest   # promote
```

```bash
gcloud run deploy web --region=us-central1 --no-allow-unauthenticated   # private
gcloud run services add-iam-policy-binding web --region=us-central1 \
  --member="user:alice@example.com" --role="roles/run.invoker"
```

### Cloud Run functions

```bash
gcloud run deploy hello-fn --source=. --function=handler \
  --trigger-http --region=us-central1 --allow-unauthenticated

gcloud run deploy on-upload --source=. --function=process \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized,bucket=acme-uploads" \
  --region=us-central1
```

### App Engine

```bash
gcloud app deploy app.yaml --version=v2         # a NEW version; the old one keeps serving
gcloud app deploy app.yaml --version=v2 --no-promote   # deployed, but 0% of traffic

gcloud app services set-traffic default --splits=v2=0.1,v1=0.9   # canary
gcloud app services set-traffic default --splits=v2=1            # promote

gcloud app versions list
gcloud app versions describe v1 --service=default
gcloud app versions delete v1 --service=default   # only after nothing points at it

gcloud app browse                                 # opens the live URL
gcloud app logs tail -s default
```

### Artifact Registry

The image store behind Cloud Run, GKE and Cloud Build. Container Registry (`gcr.io`) is its
predecessor — see [`SERVICE_NAMES.md`](SERVICE_NAMES.md).

```bash
gcloud artifacts repositories create web-images --repository-format=docker \
  --location=us-central1

gcloud auth configure-docker us-central1-docker.pkg.dev   # once, per machine

docker push us-central1-docker.pkg.dev/PROJECT/web-images/web:v2
gcloud artifacts docker images list us-central1-docker.pkg.dev/PROJECT/web-images
gcloud artifacts repositories add-iam-policy-binding web-images \
  --location=us-central1 --member="serviceAccount:SA_EMAIL" \
  --role="roles/artifactregistry.reader"
```

---

## 5. GKE → `04_kubernetes`

```bash
gcloud container clusters create-auto prod --region=us-central1      # Autopilot
gcloud container clusters create prod --zone=us-central1-a \
  --num-nodes=3 --machine-type=e2-standard-4 --enable-autoscaling \
  --min-nodes=1 --max-nodes=10

gcloud container clusters list
gcloud container clusters get-credentials prod --region=us-central1  # writes kubeconfig
gcloud container clusters resize prod --num-nodes=5 --region=us-central1
gcloud container node-pools create batch-pool --cluster=prod --region=us-central1 \
  --machine-type=n2-standard-8 --num-nodes=2
gcloud container node-pools list --cluster=prod --region=us-central1
```

> **`get-credentials` is the bridge**: it writes the cluster into your kubeconfig so `kubectl` works.
> *"kubectl can't reach the cluster"* is almost always this step missing.

```bash
kubectl get nodes
kubectl get pods -A
kubectl apply -f deployment.yaml
kubectl create deployment web --image=nginx
kubectl expose deployment web --type=LoadBalancer --port=80
kubectl scale deployment web --replicas=5
kubectl autoscale deployment web --min=2 --max=10 --cpu-percent=60
kubectl rollout status deployment/web
kubectl rollout undo deployment/web
kubectl logs POD_NAME
kubectl exec -it POD_NAME -- /bin/sh
kubectl describe pod POD_NAME
kubectl config get-contexts
kubectl config use-context CONTEXT
```

---

## 6. Storage and databases → [`05_storage`](../05_storage/README.md)

**`gcloud storage` is the current command** — faster than `gsutil`, which is being folded into it.

```bash
gcloud storage buckets create gs://acme-assets \
  --location=us-central1 --default-storage-class=STANDARD \
  --uniform-bucket-level-access

gcloud storage buckets list
gcloud storage buckets describe gs://acme-assets
gcloud storage buckets update gs://acme-assets --lifecycle-file=lifecycle.json
gcloud storage buckets update gs://acme-assets --versioning
gcloud storage buckets update gs://acme-assets --retention-period=7d

gcloud storage cp local.txt gs://acme-assets/
gcloud storage cp -r gs://acme-assets/data ./data
gcloud storage rsync -r ./site gs://acme-assets/site
gcloud storage ls gs://acme-assets/**
gcloud storage rm gs://acme-assets/old.txt
gcloud storage objects update gs://acme-assets/f.txt --storage-class=NEARLINE
```

| `gsutil` | `gcloud storage` |
|---|---|
| `gsutil mb` | `gcloud storage buckets create` |
| `gsutil ls` | `gcloud storage ls` |
| `gsutil cp` | `gcloud storage cp` |
| `gsutil rsync` | `gcloud storage rsync` |
| `gsutil lifecycle set` | `gcloud storage buckets update --lifecycle-file=` |
| `gsutil iam ch` | `gcloud storage buckets add-iam-policy-binding` |
| `gsutil signurl` | `gcloud storage sign-url` |

**Cloud SQL:**

```bash
gcloud sql instances create orders-db --database-version=POSTGRES_15 \
  --tier=db-custom-2-7680 --region=us-central1
gcloud sql instances list
gcloud sql instances patch orders-db --tier=db-custom-4-15360
gcloud sql databases create orders --instance=orders-db
gcloud sql users create app --instance=orders-db --password=...
gcloud sql backups create --instance=orders-db
gcloud sql backups list --instance=orders-db
gcloud sql connect orders-db --user=postgres
```

**BigQuery** uses its own CLI:

```bash
bq ls
bq mk --dataset my_dataset
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `p.d.t`'
bq load --source_format=CSV my_dataset.my_table gs://bucket/data.csv
bq show my_dataset.my_table
```

---

## 7. Networking → [`06_networking`](../06_networking/README.md)

```bash
gcloud compute networks create prod-net --subnet-mode=custom
gcloud compute networks list
gcloud compute networks subnets create web-uc1 \
  --network=prod-net --region=us-central1 --range=10.0.0.0/23
gcloud compute networks subnets expand-ip-range web-uc1 \
  --region=us-central1 --prefix-length=22        # GROW only, never shrink
gcloud compute networks subnets update web-uc1 --region=us-central1 \
  --enable-private-ip-google-access
gcloud compute networks subnets list --filter="region:us-central1"
```

**Firewall rules** — note `--priority`, the lever from `06_networking` §5:

```bash
gcloud compute firewall-rules create allow-http \
  --network=prod-net --direction=INGRESS --action=ALLOW \
  --rules=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 \
  --target-tags=web --priority=1000

gcloud compute firewall-rules create allow-iap-ssh \
  --network=prod-net --allow=tcp:22 --source-ranges=35.235.240.0/20

gcloud compute firewall-rules list \
  --format="table(name,network,direction,priority,allowed[].map().firewall_rule().list())" \
  --sort-by=priority
gcloud compute firewall-rules update allow-http --priority=500
```

**Cloud NAT** — outbound for instances with no external IP:

```bash
gcloud compute routers create nat-router --network=prod-net --region=us-central1
gcloud compute routers nats create prod-nat --router=nat-router --region=us-central1 \
  --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges
```

**Peering, Shared VPC, addresses:**

```bash
gcloud compute networks peerings create to-partner \
  --network=prod-net --peer-project=partner-project --peer-network=partner-net

gcloud compute shared-vpc enable HOST_PROJECT_ID
gcloud compute shared-vpc associated-projects add SERVICE_PROJECT_ID --host-project=HOST_PROJECT_ID

gcloud compute addresses create web-ip --region=us-central1      # static, regional
gcloud compute addresses create lb-ip --global                   # for a global LB
gcloud compute addresses list
```

**Load balancing** (global external Application LB, in order):

```bash
gcloud compute health-checks create http web-hc --port=80
gcloud compute backend-services create web-be --global \
  --protocol=HTTP --health-checks=web-hc
gcloud compute backend-services add-backend web-be --global \
  --instance-group=web-mig --instance-group-region=us-central1
gcloud compute url-maps create web-map --default-service=web-be
gcloud compute target-http-proxies create web-proxy --url-map=web-map
gcloud compute forwarding-rules create web-fr --global \
  --target-http-proxy=web-proxy --ports=80 --address=lb-ip
```

**Cloud DNS:**

```bash
gcloud dns managed-zones create prod-zone --dns-name=example.com. --description="prod"
gcloud dns record-sets create www.example.com. --zone=prod-zone --type=A --ttl=300 --rrdatas=1.2.3.4
```

---

## 8. Operations → [`07_operations`](../07_operations/README.md)

```bash
gcloud logging logs list
gcloud logging read 'resource.type="gce_instance" AND severity>=ERROR' \
  --limit=20 --freshness=1d
gcloud logging read 'protoPayload.methodName="v1.compute.instances.delete"' --limit=10
```

**Sinks** — remember every matching sink receives a copy:

```bash
gcloud logging sinks create security-archive \
  storage.googleapis.com/projects/P/buckets/audit-archive \
  --log-filter='logName:"cloudaudit.googleapis.com"'

gcloud logging sinks create org-sink \
  bigquery.googleapis.com/projects/P/datasets/logs \
  --organization=ORG_ID --include-children        # AGGREGATED sink

gcloud logging sinks list
gcloud logging sinks describe security-archive
gcloud logging sinks update security-archive --log-filter='...'
```

> After creating a sink, **grant its writer identity permission on the destination** — the
> `writerIdentity` in `describe` output. A sink that routes nothing is usually this.

**Buckets, exclusions and metrics:**

```bash
gcloud logging buckets list --location=global
gcloud logging buckets update _Default --location=global --retention-days=90
gcloud logging sinks update _Default --exclusion=name=noisy,filter='resource.type="gce_instance"'
gcloud logging metrics create error_count --description="errors" --log-filter='severity>=ERROR'
```

*(`_Required` cannot be modified, excluded from or disabled.)*

---

## 9. Billing → [`08_billing_cost`](../08_billing_cost/README.md)

```bash
gcloud billing accounts list
gcloud billing accounts describe BILLING_ACCOUNT_ID
gcloud billing projects link my-project-id --billing-account=0X0X0X-0X0X0X-0X0X0X
gcloud billing projects describe my-project-id
gcloud billing projects unlink my-project-id
gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID
```

> **A budget is a notification, not a cap.** To actually stop spend you wire the budget to Pub/Sub
> and a function that unlinks billing — see `08_billing_cost` §5.

---

## 10. Deployment → [`09_iac`](../09_iac/README.md)

```bash
gcloud deployment-manager deployments create my-dep --config=config.yaml
gcloud deployment-manager deployments update my-dep --config=config.yaml
gcloud deployment-manager deployments list
gcloud deployment-manager deployments delete my-dep
```

*(Deployment Manager is being retired in favour of **Infrastructure Manager**, which runs Terraform
for you — check its current command group rather than trusting a line in this file.)*

### Cloud Build — where CI/CD sits, not a fourth IaC tool

Cloud Build **runs** things; it does not decide what your infrastructure should look like. It is
the CI runner that `terraform apply`, a container build, or a deploy step happens *inside* —
[`09_iac` §6b](../09_iac/README.md#6b-where-cloud-build-fits) has the full distinction.

```bash
# cloudbuild.yaml drives this - steps are just containers run in sequence
gcloud builds submit --config=cloudbuild.yaml .
gcloud builds submit --tag=us-central1-docker.pkg.dev/PROJECT/web-images/web:v2 .   # no yaml at all

gcloud builds list --limit=5
gcloud builds describe BUILD_ID
gcloud builds log BUILD_ID

gcloud builds triggers create github \
  --repo-name=web --repo-owner=acme --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
gcloud builds triggers list
gcloud builds triggers run TRIGGER_ID --branch=main
```

A minimal `cloudbuild.yaml` that builds an image, pushes it, then applies Terraform:

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args: [build, -t, us-central1-docker.pkg.dev/$PROJECT_ID/web-images/web:$SHORT_SHA, .]
  - name: gcr.io/cloud-builders/docker
    args: [push, us-central1-docker.pkg.dev/$PROJECT_ID/web-images/web:$SHORT_SHA]
  - name: hashicorp/terraform
    args: [apply, -auto-approve]
```

**Cloud Deploy** is the layer above this, for progressive delivery **after** an image exists —
promote the same artifact through dev → staging → prod, with approval gates:

```bash
gcloud deploy apply --file=clouddeploy.yaml --region=us-central1
gcloud deploy releases create web-v2 --delivery-pipeline=web-pipeline \
  --region=us-central1 --image=web=us-central1-docker.pkg.dev/PROJECT/web-images/web:v2
gcloud deploy rollouts list --release=web-v2 --delivery-pipeline=web-pipeline --region=us-central1
gcloud deploy rollouts approve ROLLOUT_ID --release=web-v2 \
  --delivery-pipeline=web-pipeline --region=us-central1
```

> **Cloud Build builds the artifact once. Cloud Deploy moves that same artifact through
> environments.** A scenario that says *"build on every push"* wants Build; one that says
> *"promote the same image from staging to production with an approval step"* wants Deploy.

---

## Format and filter

The most useful two flags in the SDK, and the most skipped.

```bash
gcloud compute instances list --format=json
gcloud compute instances list --format=yaml
gcloud compute instances list --format="value(name)"
gcloud compute instances list --format="table(name, zone.basename(), status, machineType.basename())"
gcloud compute instances list --format="csv(name,status)"
gcloud projects list --format="value(projectId)" --sort-by=projectId --limit=10
```

```bash
gcloud compute instances list --filter="status=RUNNING"
gcloud compute instances list --filter="name~^web"                 # regex
gcloud compute instances list --filter="zone:us-central1-a"        # substring
gcloud compute instances list --filter="labels.env=prod AND status=RUNNING"
gcloud compute instances list --filter="NOT status=TERMINATED"
gcloud compute disks list --filter="-users:*"                      # UNATTACHED disks
```

**The combination is where the value is** — this is how you fix a whole fleet:

```bash
gcloud compute instances list --filter="status=TERMINATED" --format="value(name,zone)" \
  | while read -r name zone; do gcloud compute instances delete "$name" --zone="$zone" -q; done
```

And the one that answers *"what is quietly costing money"* from
[`08_billing_cost` §7](../08_billing_cost/README.md):

```bash
gcloud compute disks list --filter="-users:*" --format="table(name,zone.basename(),sizeGb)"
gcloud compute addresses list --filter="status=RESERVED" --format="table(name,region,address)"
```

---

## Commands that are one-way

| | |
|---|---|
| `gcloud projects delete` | 30-day recovery, then permanent |
| `gcloud compute instances delete` | the boot disk goes too unless `--keep-disks=boot` |
| `gcloud compute networks subnets expand-ip-range` | **grow only** — there is no shrink |
| `gcloud sql instances delete` | gone, with its backups |
| `gcloud storage rm -r` | no undo without object versioning |
| bucket **location** | immutable. New bucket and copy |
| project **ID** | immutable. New project and migrate |

**`--quiet` suppresses every confirmation for all of the above.** It belongs in scripts you have
read twice.
