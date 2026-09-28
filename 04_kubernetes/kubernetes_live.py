"""Kubernetes, against a REAL cluster running on this machine.

This is the only part of the repository that is not a model. GKE is
*managed Kubernetes* and Kubernetes is open source, so the thing the exam
asks about actually runs here - in containers, via kind. Everything below
is measured against a live API server.

  1. What a cluster actually is
  2. The reconciliation loop, timed
  3. Scheduling: requests decide placement
  4. Services - and the one that never gets an address
  5. A rolling update, sampled throughout
  6. Config and secrets
  7. GKE: what Google operates, and what you still do   [documented]

NEEDS A CONTAINER RUNTIME. Everything else in this repository needs only
`pip install -r requirements.txt`. See 04_kubernetes/setup/README.md.

RUNTIME ~3-5 minutes, most of it creating the cluster the first time.
The cluster is LEFT RUNNING at the end; the last line says how to remove
it.

Run:
    python 04_kubernetes/kubernetes_live.py

Concept reference: ACE domain 2 (~30%) - planning and implementing.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402
from toolchain import Toolchain, ToolchainError  # noqa: E402

OUT = HERE / "images"
CLUSTER = "ace-lab"
NS = "ace-lab"
IMAGE = "nginx:1.27-alpine"
REPLICAS = 4
# A readiness delay, so a rollout is long enough to MEASURE. Without it the
# whole thing finished in 1.6s over 2 samples, which is too coarse to
# support any claim about the minimum available. It is also realistic:
# almost nothing is ready the instant its process starts.
READY_DELAY = 5

DEPLOYMENT_YAML = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: {REPLICAS}
  selector:
    matchLabels: {{app: web}}
  template:
    metadata:
      labels: {{app: web}}
    spec:
      containers:
        - name: nginx
          image: {IMAGE}
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: 50m
              memory: 32Mi
            limits:
              memory: 128Mi
          readinessProbe:
            httpGet: {{path: /, port: 80}}
            initialDelaySeconds: {READY_DELAY}
            periodSeconds: 2
"""


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def k(tc: Toolchain, *args: str, **kw):
    return tc.run("kubectl", "-n", NS, *args, **kw)


def kjson(tc: Toolchain, *args: str, **kw) -> dict:
    return json.loads(k(tc, *args, "-o", "json", **kw).stdout)


def pod_states(tc: Toolchain, selector: str) -> dict[str, str]:
    data = kjson(tc, "get", "pods", "-l", selector)
    return {i["metadata"]["name"]: i["status"].get("phase", "?")
            for i in data.get("items", [])}


def running_count(tc: Toolchain, selector: str) -> int:
    data = kjson(tc, "get", "pods", "-l", selector)
    n = 0
    for item in data.get("items", []):
        conds = {c["type"]: c["status"]
                 for c in item["status"].get("conditions", [])}
        if item["status"].get("phase") == "Running" and conds.get("Ready") == "True":
            n += 1
    return n


def ensure_cluster(tc: Toolchain) -> bool:
    existing = tc.out("kind", "get", "clusters", check=False).split()
    if CLUSTER in existing:
        print(f"  cluster '{CLUSTER}' already exists - reusing it")
        # EXISTING IS NOT RUNNING. A kind cluster is containers, and when the
        # host stops them - on Windows, WSL shuts the distro down once it has
        # no processes left - they stay stopped. Docker restarts some on
        # daemon start and not others, so a cluster can come back with its
        # workers up and its CONTROL PLANE down. Then kubectl reports
        # "Forbidden" and then "connection refused", and neither says what is
        # wrong. Check, and start what is not running.
        stopped = [ln.split("@@")[0] for ln in tc.out(
            "docker", "ps", "-a", "--filter", f"name={CLUSTER}",
            "--format", "{{.Names}}@@{{.State}}", check=False).splitlines()
            if ln and not ln.endswith("@@running")]
        if stopped:
            print(f"  {len(stopped)} of its containers are stopped - starting "
                  f"them: {', '.join(stopped)}")
            for name in stopped:
                tc.run("docker", "start", name, check=False, timeout=120)
        return False
    cfg = tc.path_for(HERE / "kind-cluster.yaml")
    print(f"  creating cluster '{CLUSTER}' (first time pulls a ~1.3 GB node")
    print("  image; after that it is cached and this takes under a minute)")
    t0 = time.time()
    tc.run("kind", "create", "cluster", "--config", cfg, timeout=900)
    print(f"  created in {time.time() - t0:.0f}s")
    return True


def wait_api(tc: Toolchain, timeout: int = 180) -> float:
    """WSL shuts the distro down when idle, which stops the cluster's
    containers. Docker restarts them, but the API server needs a moment -
    and during that moment kubectl returns 'Forbidden' and then 'connection
    refused', neither of which means what it looks like. So: wait, always.
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if tc.kubectl_ok("get", "--raw", "/readyz", timeout=30):
            return time.time() - t0
        time.sleep(3)
    raise ToolchainError("the API server did not become ready")


def main() -> None:
    print("KUBERNETES - AGAINST A REAL CLUSTER")
    try:
        tc = Toolchain.discover()
    except ToolchainError as exc:
        print(f"\n  CANNOT RUN: {exc}\n")
        raise SystemExit(1)
    print(f"  toolchain: {tc.describe()}")
    with tc.held_open():
        if tc.distro:
            print(f"  holding {tc.distro} open for the duration "
                  f"(see toolchain.held_open)")
        run_all(tc)


def run_all(tc: Toolchain) -> None:
    ensure_cluster(tc)
    tc.run("kubectl", "config", "use-context", f"kind-{CLUSTER}")
    waited = wait_api(tc)
    print(f"  API server ready (waited {waited:.0f}s)")
    # The API answering is NOT the cluster being usable. Workers report
    # NotReady until the CNI is up on them, and a first run reached section 1
    # while two of three nodes were still False. Wait for the thing you
    # actually need, not the first thing that responds.
    t0 = time.time()
    tc.run("kubectl", "wait", "--for=condition=Ready", "node", "--all",
           "--timeout=300s", timeout=330)
    print(f"  all nodes Ready (waited a further {time.time() - t0:.0f}s)")
    tc.run("kubectl", "create", "namespace", NS, check=False)
    tc.run("kubectl", "-n", NS, "delete", "all", "--all", "--wait=false",
           check=False)

    # ============================================= 1. what a cluster is
    rule("1. WHAT A CLUSTER ACTUALLY IS")
    nodes = kjson(tc, "get", "nodes")["items"]
    print(f"  {'node':<24} {'role':<14} {'version':<10} {'runtime':<22} status")
    print("  " + "-" * 82)
    for n in nodes:
        name = n["metadata"]["name"]
        labels = n["metadata"].get("labels", {})
        role = "control-plane" if "node-role.kubernetes.io/control-plane" \
            in labels else "worker"
        info = n["status"]["nodeInfo"]
        ready = next((c["status"] for c in n["status"]["conditions"]
                      if c["type"] == "Ready"), "?")
        print(f"  {name:<24} {role:<14} {info['kubeletVersion']:<10} "
              f"{info['containerRuntimeVersion']:<22} "
              f"{'Ready' if ready == 'True' else ready}")

    print("\n  And now the part that is easy to forget - those nodes are")
    print("  CONTAINERS on this machine:\n")
    ps = tc.out("docker", "ps", "--filter", f"name={CLUSTER}",
                "--format", "{{.Names}}|{{.Image}}|{{.Status}}")
    for line in ps.splitlines():
        name, image, status = line.split("|")
        print(f"    {name:<26} {image:<24} {status}")

    sys_pods = kjson(tc, "get", "pods", "-n", "kube-system")["items"]
    names = sorted(p["metadata"]["name"] for p in sys_pods)
    print(f"\n  The control plane itself runs as {len(names)} pods in kube-system:")
    for n in names:
        print(f"    {n}")
    print("\n  etcd, the API server, the scheduler and the controller manager")
    print("  are all just pods. ON GKE YOU CANNOT SEE ANY OF THEM - Google")
    print("  runs the control plane, and `kubectl get pods -n kube-system`")
    print("  shows you the add-ons and nothing else. That is the whole")
    print("  managed-service trade, visible in one command.")

    # ============================================ 2. reconciliation loop
    rule("2. THE RECONCILIATION LOOP, TIMED")
    print(f"  A Deployment of {REPLICAS} x {IMAGE}, with explicit resource")
    print(f"  REQUESTS and a readiness probe that takes {READY_DELAY}s to pass.\n")
    k(tc, "apply", "-f", "-", stdin=DEPLOYMENT_YAML)
    k(tc, "rollout", "status", "deployment/web", "--timeout=300s", timeout=330)

    owners = kjson(tc, "get", "pods", "-l", "app=web")["items"][0]
    rs = owners["metadata"]["ownerReferences"][0]["name"]
    print(f"  Deployment 'web'  ->  ReplicaSet '{rs}'  ->  {REPLICAS} Pods")
    print("\n  THREE OBJECTS, NOT ONE. You manage the Deployment; it manages a")
    print("  ReplicaSet; the ReplicaSet manages Pods. Every rolling update")
    print("  below is one ReplicaSet growing while another shrinks.\n")

    # Snapshot BEFORE the delete. Capturing it afterwards is too late - the
    # ReplicaSet can create the replacement in well under a second, so the
    # "new" pod is already in the set and nothing looks new.
    before = set(pod_states(tc, "app=web"))
    victim = sorted(before)[0]
    print(f"  Deleting a pod by hand: {victim}")
    t0 = time.time()
    k(tc, "delete", "pod", victim, "--wait=false")
    trace: list[tuple[float, int]] = []
    replacement = None
    while time.time() - t0 < 120:
        states = pod_states(tc, "app=web")
        ready = running_count(tc, "app=web")
        trace.append((time.time() - t0, ready))
        fresh = set(states) - before
        if fresh:
            replacement = sorted(fresh)[0]
        if victim not in states and ready == REPLICAS:
            break
        time.sleep(1)
    recovered = time.time() - t0

    print(f"\n  back to {REPLICAS}/{REPLICAS} Ready in {recovered:.1f}s")
    if replacement:
        print(f"  the replacement is a DIFFERENT pod: {replacement}")
    print("\n  NOTHING TOLD IT TO DO THAT. The ReplicaSet controller compares")
    print("  desired (4) against observed (3) and acts. That loop is what")
    print("  Kubernetes IS - and it is why deleting a pod to 'restart the")
    print("  app' does not do what people think: you get a NEW pod, with a")
    print("  new name, a new IP, and none of the old one's local state.")

    # =================================================== 3. scheduling
    rule("3. SCHEDULING: REQUESTS DECIDE PLACEMENT")
    placement: dict[str, int] = {}
    for p in kjson(tc, "get", "pods", "-l", "app=web")["items"]:
        node = p["spec"].get("nodeName", "?")
        placement[node] = placement.get(node, 0) + 1
    print(f"  Where the {REPLICAS} replicas landed:")
    for node, n in sorted(placement.items()):
        print(f"    {node:<26} {n}")
    print("\n  No control-plane node in that list: it carries a TAINT, and")
    print("  ordinary pods do not tolerate it. Taints repel; tolerations")
    print("  permit; node selectors and affinity attract.\n")

    cap = nodes[0]["status"]["allocatable"]
    print(f"  One node's allocatable capacity: cpu={cap['cpu']}, "
          f"memory={cap['memory']}")
    print("\n  Now a pod that asks for more CPU than any node has:\n")
    manifest = """apiVersion: v1
kind: Pod
metadata:
  name: too-big
  labels: {app: too-big}
spec:
  containers:
    - name: c
      image: %s
      resources:
        requests:
          cpu: "64"
""" % IMAGE
    k(tc, "apply", "-f", "-", stdin=manifest)
    time.sleep(6)
    pod = kjson(tc, "get", "pod", "too-big")
    phase = pod["status"].get("phase")
    cond = next((c for c in pod["status"].get("conditions", [])
                 if c["type"] == "PodScheduled"), {})
    print(f"    phase   {phase}")
    print(f"    reason  {cond.get('reason', '-')}")
    print(f"    message {cond.get('message', '-')[:120]}")
    print(f"\n  IT IS {phase}, AND IT WILL STAY {phase} FOREVER. Nothing is")
    print("  broken, nothing retries into success - the scheduler simply")
    print("  cannot find a node that satisfies the request.")
    print("\n  REQUESTS ARE FOR SCHEDULING. LIMITS ARE FOR RUNTIME.")
    print("  Requests reserve room and decide placement. Limits cap what a")
    print("  running container may use - over the CPU limit it is throttled,")
    print("  over the memory limit it is OOM-killed. A pod with no requests")
    print("  schedules anywhere and is the first thing evicted under")
    print("  pressure, which is why 'it works in dev' so often means")
    print("  'nothing in dev has requests'.")
    k(tc, "delete", "pod", "too-big", "--wait=false", check=False)

    # ===================================================== 4. services
    rule("4. SERVICES - AND THE ONE THAT NEVER GETS AN ADDRESS")
    for name, stype in (("web-clusterip", "ClusterIP"),
                        ("web-nodeport", "NodePort"),
                        ("web-lb", "LoadBalancer")):
        k(tc, "expose", "deployment", "web", "--port=80",
          f"--name={name}", f"--type={stype}", check=False)
    print("  Created one Service of each type. Watching the LoadBalancer for")
    print("  30 seconds, because 'pending' and 'pending forever' look the")
    print("  same in a single snapshot:\n")
    t0 = time.time()
    while time.time() - t0 < 30:
        s = kjson(tc, "get", "service", "web-lb")
        ing = s.get("status", {}).get("loadBalancer", {}).get("ingress")
        print(f"    t+{time.time() - t0:4.0f}s   external-ip "
              f"{ing[0] if ing else '<pending>'}")
        if ing:
            break
        time.sleep(7)
    print()
    svcs = kjson(tc, "get", "services")["items"]
    print(f"  {'name':<16} {'type':<14} {'cluster-ip':<16} {'external':<14} ports")
    print("  " + "-" * 74)
    lb_pending = False
    for s in sorted(svcs, key=lambda x: x["metadata"]["name"]):
        meta, spec, status = s["metadata"], s["spec"], s.get("status", {})
        ing = status.get("loadBalancer", {}).get("ingress")
        ext = ing[0].get("ip", ing[0].get("hostname", "?")) if ing else "<pending>"
        if spec["type"] == "LoadBalancer" and not ing:
            lb_pending = True
        ports = ",".join(str(p.get("nodePort") or p["port"])
                         for p in spec.get("ports", []))
        print(f"  {meta['name']:<16} {spec['type']:<14} "
              f"{spec.get('clusterIP', '-'):<16} {ext:<14} {ports}")

    eps = kjson(tc, "get", "endpoints", "web-clusterip")
    n_eps = sum(len(s.get("addresses", []))
                for s in eps.get("subsets", []))
    print(f"\n  web-clusterip has {n_eps} endpoints - one per READY pod. A")
    print("  Service is a stable name and IP in front of a moving set of")
    print("  pods; the readiness probe decides who is in that set.")

    if lb_pending:
        print("\n  AND web-lb IS STILL <pending>. IT WILL BE PENDING FOREVER.")
        print("\n  That is not a bug and not a kind limitation to apologise")
        print("  for - it is the single clearest demonstration of what a")
        print("  managed service does. `type: LoadBalancer` asks the CLOUD")
        print("  CONTROLLER MANAGER to go and provision a real load balancer.")
        print("  On GKE that component exists, and you get a Google Cloud")
        print("  load balancer with a real external IP. Here there is no")
        print("  cloud to ask.")
        print("\n  THE SAME YAML. Different outcome, because of who is")
        print("  running the control plane. That is the entire managed-vs-")
        print("  self-hosted question in one field.")

    # ================================================ 5. rolling update
    rule("5. A ROLLING UPDATE, SAMPLED THROUGHOUT")
    probe = time.time()
    kjson(tc, "get", "deployment", "web")
    rtt = time.time() - probe
    print(f"  Sampling the Deployment while it rolls. One round trip to the")
    print(f"  API through this toolchain takes ~{rtt:.2f}s, so that is the")
    print("  resolution here - the minimum below is a SAMPLED minimum, not a")
    print("  proven one. Stated because it matters.\n")

    strat = kjson(tc, "get", "deployment", "web")["spec"]["strategy"]
    ru = strat.get("rollingUpdate", {})
    print(f"  strategy: {strat['type']}  maxUnavailable="
          f"{ru.get('maxUnavailable')}  maxSurge={ru.get('maxSurge')}")
    print(f"  replicas: {REPLICAS}\n")

    k(tc, "set", "env", "deployment/web", f"ROLLOUT={int(time.time())}")
    samples: list[tuple[float, int, int]] = []
    t0 = time.time()
    while time.time() - t0 < 180:
        d = kjson(tc, "get", "deployment", "web")["status"]
        avail = d.get("availableReplicas", 0) or 0
        total = d.get("replicas", 0) or 0
        samples.append((time.time() - t0, avail, total))
        if (d.get("updatedReplicas") == REPLICAS
                and avail == REPLICAS and total == REPLICAS):
            break
        time.sleep(0.4)
    took = time.time() - t0

    min_avail = min(a for _, a, _ in samples)
    max_total = max(t for _, _, t in samples)
    print(f"  rollout finished in {took:.1f}s over {len(samples)} samples")
    print(f"  lowest AVAILABLE seen   {min_avail} of {REPLICAS}")
    print(f"  highest TOTAL pods seen {max_total} (surge)")
    print(f"\n  SERVICE WAS NEVER FULLY DOWN: at the worst sampled moment")
    print(f"  {min_avail} of {REPLICAS} replicas were still serving. maxUnavailable")
    print("  guarantees the floor; maxSurge pays for it with temporary extra")
    print("  pods - which is why a rolling update needs headroom, and why it")
    print("  stalls on a cluster with none.")
    print(f"\n  AND THE READINESS PROBE IS WHAT PACES IT. Each new pod takes")
    print(f"  {READY_DELAY}s to report Ready, and the Deployment will not retire an old")
    print("  pod until a new one has. Without a readiness probe Kubernetes")
    print("  assumes a started container is a working one, retires the old")
    print("  replicas immediately, and you get a rollout that reports success")
    print("  while sending traffic to pods that are not serving yet.")
    print("\n  This rollout changed an ENVIRONMENT VARIABLE, not the image, so")
    print("  no pull time is in that number. A real image change adds")
    print("  however long the pull takes, on every node.")
    print("\n  `kubectl rollout undo deployment/web` goes back: the previous")
    print("  ReplicaSet still exists at 0 replicas, and undo scales it up")
    print("  again. That is why the old ReplicaSets are worth leaving alone.")

    # ============================================= 6. config and secrets
    rule("6. CONFIG AND SECRETS")
    k(tc, "create", "configmap", "app-config",
      "--from-literal=LOG_LEVEL=info", check=False)
    k(tc, "create", "secret", "generic", "db-creds",
      "--from-literal=password=correct-horse-battery", check=False)
    secret = kjson(tc, "get", "secret", "db-creds")
    stored = secret["data"]["password"]
    decoded = base64.b64decode(stored).decode()
    print(f"  stored in etcd   {stored}")
    print(f"  base64 -d        {decoded}")
    print("\n  A SECRET IS BASE64, NOT ENCRYPTION. Base64 is an encoding -")
    print("  anyone who can `get secrets` in this namespace can read that")
    print("  value, and so can anyone who can read etcd.")
    print("\n  What actually protects it:")
    print("    - RBAC, so few principals can get secrets at all")
    print("    - encryption at rest, configured on the cluster (on GKE,")
    print("      application-layer secrets encryption with Cloud KMS)")
    print("    - keeping the secret OUT of the cluster entirely: Secret")
    print("      Manager, reached with WORKLOAD IDENTITY, so no credential")
    print("      is stored in Kubernetes at all")
    print("\n  A ConfigMap is the same object without even the pretence.")
    print("  Neither belongs in git; both belong in whatever you use to")
    print("  hold secrets properly.")

    # ================================================= 7. GKE specifics
    rule("7. GKE: WHAT GOOGLE OPERATES   [documented]")
    print("""  Everything above is Kubernetes. This is the part that is GKE,
  and it is where the exam questions live.

    AUTOPILOT vs STANDARD
      STANDARD   you choose and pay for NODES. You size node pools,
                 you upgrade them, you own the capacity that is idle.
      AUTOPILOT  you pay for what your PODS REQUEST. Google runs the
                 nodes, applies hardened defaults and will not let you
                 do certain things (no privileged pods, no DaemonSets
                 that need host access, no SSH to a node).
      The exam's default answer is AUTOPILOT unless the scenario needs
      node-level control - a DaemonSet with host access, a specific
      machine type, a GPU you pick, or an operator that needs it.
      NOTE THAT REQUESTS BECOME THE BILL on Autopilot, which makes
      section 3's point financial as well as operational.

    NODE POOLS      groups of identical nodes in a Standard cluster.
                    Different machine types, Spot nodes, GPU nodes, and
                    taints per pool. Spot node pools plus tolerations is
                    the standard cheap-batch pattern - see 03_compute.

    AUTOSCALING     three different things, and they get confused:
      HPA           more PODS, on a metric. The usual one.
      VPA           bigger pods - adjusts requests.
      CLUSTER       more NODES, when pods will not fit. Only meaningful
        AUTOSCALER  on Standard; Autopilot does it implicitly.

    REGIONAL vs ZONAL   a REGIONAL cluster replicates the control plane
                    across zones and spreads nodes. Zonal is cheaper and
                    a zone outage takes the cluster. Same distinction as
                    a regional MIG in 03_compute.

    WORKLOAD IDENTITY   the right way for a pod to authenticate to
                    Google Cloud: bind a Kubernetes service account to
                    an IAM service account. NO DOWNLOADED KEY - the
                    same argument 02_iam makes, in the cluster.

    PRIVATE CLUSTER nodes have no external IPs. They reach the internet
                    through Cloud NAT and Google APIs through Private
                    Google Access - 06_networking section 6, applied.

    GKE also gives you: the Gateway/Ingress controller wiring
    `type: LoadBalancer` to a real Google Cloud load balancer, Artifact
    Registry for images, Binary Authorization, and automatic upgrades on
    a release channel.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    ax1.step([t for t, _ in trace], [c for _, c in trace], where="post",
             color=PALETTE["blue"], lw=2)
    ax1.axhline(REPLICAS, color=PALETTE["grey"], ls=":", lw=1)
    ax1.set_xlabel("seconds after deleting one pod")
    ax1.set_ylabel("Ready pods")
    ax1.set_ylim(0, REPLICAS + 0.6)
    ax1.set_title(f"Self-healed in {recovered:.0f}s", loc="left")

    ax2.step([s[0] for s in samples], [s[2] for s in samples], where="post",
             color=PALETTE["orange"], lw=1.6, label="total (surge)")
    ax2.step([s[0] for s in samples], [s[1] for s in samples], where="post",
             color=PALETTE["blue"], lw=2, label="available")
    ax2.axhline(REPLICAS, color=PALETTE["grey"], ls=":", lw=1)
    ax2.set_xlabel("seconds into the rolling update")
    ax2.set_ylabel("pods")
    ax2.set_title(f"Never below {min_avail}/{REPLICAS}", loc="left")
    ax2.legend(fontsize=8)

    ax3.axis("off")
    ax3.set_title("The same YAML, two outcomes", loc="left")
    ax3.text(0, 0.92, "type: LoadBalancer", fontsize=11, family="monospace",
             fontweight="bold", va="top")
    ax3.text(0, 0.74, "here (kind)", fontsize=10, fontweight="bold", va="top",
             color=PALETTE["vermillion"])
    ax3.text(0, 0.66, "EXTERNAL-IP  <pending>\nforever - there is no cloud\n"
                      "controller manager to ask",
             fontsize=9, va="top", family="monospace")
    ax3.text(0, 0.40, "on GKE", fontsize=10, fontweight="bold", va="top",
             color=PALETTE["green"])
    ax3.text(0, 0.32, "EXTERNAL-IP  34.x.x.x\na real Google Cloud load\n"
                      "balancer, provisioned for you",
             fontsize=9, va="top", family="monospace")
    ax3.text(0, 0.06, "That field is the managed-service\ntrade, in one line.",
             fontsize=9.5, va="top", style="italic")

    save_figure(fig, OUT / "kubernetes_live.png")
    print(f"\n  figure -> {OUT / 'kubernetes_live.png'}")

    # ---------------------------------------------------------------- tidy
    k(tc, "delete", "all", "--all", "--wait=false", check=False)
    k(tc, "delete", "configmap", "app-config", "--wait=false", check=False)
    k(tc, "delete", "secret", "db-creds", "--wait=false", check=False)

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "we do not want to manage nodes"           GKE AUTOPILOT
  "we need a DaemonSet with host access"     GKE STANDARD
  "a pod must call a Google Cloud API"       WORKLOAD IDENTITY. Never a
                                             downloaded key
  "expose this to the internet"              a SERVICE of type
                                             LoadBalancer, or an
                                             Ingress/Gateway
  "expose it only inside the cluster"        ClusterIP - the default
  "survive a zone failure"                   a REGIONAL cluster
  "the pod is Pending and nothing happens"   no node satisfies its
                                             REQUESTS
  "the container keeps restarting"           LIVENESS probe failing, or
                                             an OOM kill at its LIMIT
  "traffic goes to a pod that is not ready"  the READINESS probe is
                                             missing
  "roll back the bad release"                kubectl rollout undo
  "cheap batch on GKE"                       a SPOT node pool plus
                                             tolerations
  "nodes must have no public IPs"            a PRIVATE cluster + Cloud
                                             NAT""")

    print(f"\n  The cluster is still running. To remove it:")
    print(f"      kind delete cluster --name {CLUSTER}")
    if tc.distro:
        print(f"  (from inside WSL, or:  wsl -d {tc.distro} -- bash -lc "
              f"\"kind delete cluster --name {CLUSTER}\")")


if __name__ == "__main__":
    main()
