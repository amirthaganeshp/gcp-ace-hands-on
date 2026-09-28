# Kubernetes — against a real cluster

> **ACE domain 2 (~30%)** — planning and implementing a cloud solution
> **Runtime:** ~2 min (plus ~40 s the first time, creating the cluster)
> **Needs:** a **container runtime** — the only part of this repository that does

```bash
python 04_kubernetes/kubernetes_live.py
```

**This is the only part that is not a model.** GKE is *managed Kubernetes* and Kubernetes is open
source, so the thing the exam asks about actually runs here — in containers, via `kind`. Everything
below was measured against a live API server.

No container runtime? See [`setup/README.md`](setup/README.md) — there's an install script.

---

## 1. What a cluster actually is

```
node                     role           version    runtime                status
ace-lab-control-plane    control-plane  v1.37.0    containerd://2.3.4     Ready
ace-lab-worker           worker         v1.37.0    containerd://2.3.4     Ready
ace-lab-worker2          worker         v1.37.0    containerd://2.3.4     Ready
```

Those nodes are **containers on your machine**:

```
ace-lab-control-plane      kindest/node:v1.37.0     Up 12 seconds
ace-lab-worker2            kindest/node:v1.37.0     Up 15 seconds
ace-lab-worker             kindest/node:v1.37.0     Up 15 seconds
```

And the control plane is **12 pods in `kube-system`** — `etcd`, `kube-apiserver`, `kube-scheduler`,
`kube-controller-manager`, plus CoreDNS, kindnet and kube-proxy on every node.

> **On GKE you cannot see any of them.** Google runs the control plane, and `kubectl get pods -n
> kube-system` shows you the add-ons and nothing else. **The whole managed-service trade, visible in
> one command.**

## 2. The reconciliation loop, timed

```
Deployment 'web'  ->  ReplicaSet 'web-569c78b54'  ->  4 Pods
```

**Three objects, not one.** You manage the Deployment; it manages a ReplicaSet; the ReplicaSet
manages Pods. Every rolling update is one ReplicaSet growing while another shrinks.

Delete a pod by hand:

```
Deleting a pod by hand: web-569c78b54-d24lp
back to 4/4 Ready in 8.6s
the replacement is a DIFFERENT pod: web-569c78b54-srbqn
```

**Nothing told it to do that.** The ReplicaSet controller compares desired (4) against observed (3)
and acts. That loop *is* Kubernetes — and it's why deleting a pod to "restart the app" doesn't do
what people think: you get a **new** pod, new name, new IP, none of the old one's local state.

## 3. Scheduling: requests decide placement

```
Where the 4 replicas landed:
  ace-lab-worker             2
  ace-lab-worker2            2
```

**No control-plane node in that list** — it carries a **taint**, and ordinary pods don't tolerate
it. *Taints repel; tolerations permit; node selectors and affinity attract.*

Now a pod requesting more CPU than any node has:

```
phase   Pending
reason  Unschedulable
message 0/3 nodes are available: 1 node(s) had untolerated taint(s),
        2 Insufficient cpu.
```

**It is Pending and it will stay Pending forever.** Nothing is broken, nothing retries into success.

> **Requests are for scheduling. Limits are for runtime.** Requests reserve room and decide
> placement. Limits cap a running container — over the CPU limit it's **throttled**, over the memory
> limit it's **OOM-killed**. A pod with no requests schedules anywhere and is first to be evicted
> under pressure, which is why *"it works in dev"* so often means *"nothing in dev has requests"*.

## 4. Services — and the one that never gets an address

```
name             type           cluster-ip       external       ports
web-clusterip    ClusterIP      10.96.186.122    <pending>      80
web-nodeport     NodePort       10.96.137.80     <pending>      32199
web-lb           LoadBalancer   10.96.128.72     <pending>      30185
```

`web-clusterip` has **4 endpoints — one per Ready pod**. A Service is a stable name and IP in front
of a moving set of pods, and the **readiness probe decides who's in that set**.

Watched over 30 seconds, because *pending* and *pending forever* look identical in one snapshot:

```
t+   1s   external-ip <pending>
t+   8s   external-ip <pending>
t+  16s   external-ip <pending>
t+  23s   external-ip <pending>
```

> **`type: LoadBalancer` will be pending forever here**, and that is not a `kind` limitation to
> apologise for — it's the clearest demonstration in this repo of what a managed service *does*.
>
> That field asks the **cloud controller manager** to go and provision a real load balancer. On GKE
> that component exists and you get a Google Cloud load balancer with a real external IP. Here there
> is no cloud to ask.
>
> **The same YAML. Different outcome, because of who runs the control plane.**

## 5. A rolling update, sampled throughout

```
strategy: RollingUpdate  maxUnavailable=25%  maxSurge=25%   replicas: 4

rollout finished in 10.7s over 10 samples
lowest AVAILABLE seen   3 of 4
highest TOTAL pods seen 5 (surge)
```

**Exactly what 25% of 4 predicts**: never fewer than 3 serving, never more than 5 alive.
maxUnavailable guarantees the floor; maxSurge pays for it with temporary extra pods — which is why a
rolling update **needs headroom**, and why it stalls on a cluster with none.

**The readiness probe paces it.** Each new pod takes 5 s to report Ready, and the Deployment won't
retire an old pod until a new one has. Without a readiness probe Kubernetes assumes a *started*
container is a *working* one, retires the old replicas immediately, and you get a rollout that
reports success while sending traffic to pods that aren't serving yet.

*(This rollout changed an environment variable, not the image, so no pull time is in that number.)*

## 6. Config and secrets

```
stored in etcd   Y29ycmVjdC1ob3JzZS1iYXR0ZXJ5
base64 -d        correct-horse-battery
```

> **A Secret is base64, not encryption.** Anyone who can `get secrets` in the namespace can read it,
> and so can anyone who can read etcd.

What actually protects it: **RBAC** so few principals can get secrets at all; **encryption at rest**
configured on the cluster (on GKE, application-layer secrets encryption with **Cloud KMS**); or
keeping the secret **out of the cluster entirely** — Secret Manager, reached with **Workload
Identity**, so no credential is stored in Kubernetes at all.

## 7. GKE: what Google operates 📝

| | |
|---|---|
| **Standard** | you choose and pay for **nodes**. You size node pools, upgrade them, own the idle capacity |
| **Autopilot** | you pay for what your **pods request**. Google runs the nodes and applies hardened defaults — no privileged pods, no host-access DaemonSets, no SSH to a node |

The exam's default is **Autopilot** unless the scenario needs node-level control. And note that
**requests become the bill** on Autopilot, which makes §3 financial as well as operational.

| | |
|---|---|
| **Node pools** | groups of identical nodes on Standard. Spot node pools + tolerations is the standard cheap-batch pattern — see [`03_compute`](../03_compute/README.md) |
| **HPA / VPA / Cluster Autoscaler** | more **pods** on a metric / **bigger** pods by adjusting requests / more **nodes** when pods won't fit. Three different things |
| **Regional vs zonal** | regional replicates the control plane across zones. Same distinction as a regional MIG |
| **Workload Identity** | bind a Kubernetes SA to an IAM SA. **No downloaded key** — [`02_iam`](../02_iam/README.md)'s argument, in the cluster |
| **Private cluster** | nodes have no external IPs; Cloud NAT out, Private Google Access to Google APIs — [`06_networking` §6](../06_networking/README.md) applied |

## The exam angle

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

## Running this from Windows — two traps worth the detour

The repo's Python runs on Windows; `kubectl`, `kind` and `docker` live in WSL.
[`toolchain.py`](toolchain.py) bridges that, and both of these cost real debugging time.

**`wsl --` hands the command line to a shell. `wsl --exec` does not.** Passing a clean argv list is
*not* enough:

```
docker ps --format {{.Names}}|{{.Image}}
-> /bin/bash: line 1: {{.Image}}: command not found
```

bash saw the pipe. One flag is the difference between a wrapper that is safe and one that merely
looks safe.

**WSL shuts the distro down when it has no processes left — and takes the cluster with it.** A plain
`time.sleep(25)` between two commands was enough to lose it mid-run. Every individual command works;
the script fails anyway, at whichever step happened to follow a pause. `toolchain.held_open()` pins
one `sleep` process open for the duration.

That second one also explains an error you may hit by hand: a cluster whose **workers came back and
whose control plane did not**, reporting `Forbidden` and then `connection refused` — neither of
which says what is wrong. The script now detects stopped containers and starts them:

```
cluster 'ace-lab' already exists - reusing it
1 of its containers are stopped - starting them: ace-lab-control-plane
```

## Things to try

- Delete a **node** container: `docker stop ace-lab-worker`. Watch pods reschedule onto the
  survivor, then `docker start` it and watch nothing move back. **Kubernetes does not rebalance**,
  which surprises people.
- Add `limits: {cpu: 50m}` to the deployment and hammer a pod. It is throttled, not killed. Change
  it to a memory limit and exceed *that* — the container is **OOM-killed and restarted**. Two
  limits, two completely different failure modes.
- Scale to 20 replicas. With `cpu: 50m` requested each, watch where the scheduler runs out, and
  compare that to §3's `Pending`.

## What is not demonstrated here

Not run, and not claimed: anything GKE-specific — Autopilot, node pools, Workload Identity, private
clusters, the cluster autoscaler, Ingress/Gateway, or a real cloud load balancer. §7 is documented
for exactly that reason. `kind` gives you real Kubernetes; it does not give you Google's half of the
arrangement, and §4 is where that becomes visible rather than theoretical.

**The cluster is left running.** To remove it:

```bash
kind delete cluster --name ace-lab
```
