# Networking — address arithmetic you cannot undo, and rules that are not routes

> **ACE domain 2 (~30%)** — planning and implementing a cloud solution
> **Runtime:** ~3 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 06_networking/vpc_and_firewall.py
```

Networking splits cleanly into a part that is **real arithmetic** — which runs here, on Python's
`ipaddress` module and a firewall evaluator implementing Google's documented rules — and a part
that **is** Google's infrastructure, which is documented and labelled.

---

## 1. A VPC is global. A subnet is regional.

This is the single biggest structural difference from AWS, where a VPC is regional.

- Instances in **different regions on the same VPC** reach each other by **internal IP** — no
  peering, no VPN, no gateway.
- A subnet lives in one region but spans **every zone** in it. There is no per-zone subnet, so a
  zonal outage costs you instances, not addresses.
- **Routes and firewall rules are global objects** on the VPC. One rule can apply to instances on
  three continents.
- **Auto mode** creates a subnet in every region from `10.128.0.0/9`. Use **custom mode** for
  anything real — you can convert auto → custom, but **never custom → auto**.

## 2. The four addresses Google takes from every subnet

Network address, default gateway, second-to-last (reserved), broadcast.

| prefix | addresses | usable | lost |
|---|---|---|---|
| `/29` | 8 | **4** | **50.0%** |
| `/28` | 16 | 12 | 25.0% |
| `/27` | 32 | 28 | 12.5% |
| `/26` | 64 | 60 | 6.2% |
| `/25` | 128 | 124 | 3.1% |
| `/24` | 256 | 252 | 1.6% |
| `/22` | 1024 | 1020 | 0.4% |
| `/20` | 4096 | 4092 | 0.1% |

A **`/29` is the smallest subnet GCP allows** and hands you 4 usable addresses — half the range is
overhead. It stops mattering above about `/24`, which is why *"a `/24` per tier"* is the sane
default rather than a tight fit.

## 3. Packing an address space, and why the tight plan is the wrong one

The script sizes each subnet to demand, rounds up to a power of two, and allocates from
`10.0.0.0/16` — including the **alignment rule**, that a subnet must start on its own boundary:

```
subnet       region             want cidr              usable  spare
web-uc1      us-central1         500 10.0.0.0/23          508      8
app-uc1      us-central1         100 10.0.2.0/25          124     24
data-uc1     us-central1          25 10.0.2.128/27         28      3
web-ew1      europe-west1         50 10.0.2.192/26         60     10
batch-ase1   asia-southeast1      10 10.0.3.0/28           12      2

requested 685 hosts; allocated 752 addresses (1.10x)
```

**This is the smallest possible plan and it is the wrong one.** Read it in address order and
`europe-west1` is sitting at `10.0.2.192/26`, **wedged between two `us-central1` subnets**:

| region | subnets | summarised as |
|---|---|---|
| asia-southeast1 | 1 | 1 CIDR |
| europe-west1 | 1 | 1 CIDR |
| **us-central1** | 3 | **3 CIDRs** — any single CIDR also swallows **2 foreign subnets** |

The alternative — one aligned `/20` per region, gaps left on purpose:

| region | block | addresses | in use | headroom |
|---|---|---|---|---|
| asia-southeast1 | `10.0.0.0/20` | 4096 | 16 | 4080 |
| europe-west1 | `10.0.16.0/20` | 4096 | 64 | 4032 |
| us-central1 | `10.0.32.0/20` | 4096 | 672 | 3424 |

```
dense plan      752 addresses, 5 CIDR(s) to describe it
blocked plan  12288 addresses, 3 CIDR(s) - one per region
cost of blocking: 11536 addresses, 18% of the /16
still free afterwards: 53248
```

> **The trade is not about addresses.** Private address space is free. What a blocked plan buys is
> **one route, firewall range or VPN advertisement per region** instead of one per subnet; **room
> to expand each subnet in place** — the only resize direction that exists; and a sentence you can
> say out loud: *"`10.0.16.0/20` is europe-west1."*

**The rule that costs people a rebuild:** you can **expand** a subnet's primary range later, you can
**never shrink it**, and you can never expand into something already allocated. Leave the gaps. The
addresses are free; the migration is not.

GKE then needs **two secondary ranges** on top — pods and services — and the pod range is the one
that is always too small. A `/21` primary with a `/17` pod range is not unusual.

## 4. The peering trap — overlap is permanent

| network to join | CIDR | overlaps | can peer? |
|---|---|---|---|
| acquired-co VPC | `10.0.0.0/16` | True | **NO** |
| partner VPC | `10.1.0.0/16` | False | yes |
| on-prem via VPN | `192.168.0.0/16` | False | yes |
| lab VPC | `10.0.128.0/17` | **True** | **NO** |

**VPC peering refuses overlapping ranges.** There is no NAT in the peering path and no renumbering
on the fly — one side has to be rebuilt. That is why `10.0.0.0/16` for everything is a decision you
regret during an acquisition.

Note the lab VPC: a `/17` sitting **inside** our `/16` still overlaps. **Containment is overlap.**

Peering is also **non-transitive**: A–B and B–C does not give you A–C.

## 5. Firewall rules — why your allow did nothing

Rules, plus the two **implied** rules every VPC has at 65535 (*deny all ingress, allow all egress*,
neither deletable):

```
  800  allow INGRESS allow-health-checks      ports=80
  900  deny  INGRESS sec-deny-public-ingress  ports=all
 1000  allow INGRESS allow-http-https         ports=80,443
 1000  allow INGRESS allow-iap-ssh            ports=22
```

| traffic | without the deny | with the deny at 900 |
|---|---|---|
| browser → :443 | allow *(allow-http-https)* | **deny** |
| Google health checker → :80 | allow | **allow** *(priority 800 outranks it)* |
| IAP tunnel → :22 | allow | **deny** |
| scanner → :3389 | deny *(implied-deny-ingress)* | deny |
| VM calling an API → :443 | allow *(implied-allow-**egress**)* | allow |

**Lower number wins**, evaluation stops at the first match, and at the **same** number **deny beats
allow**. Adding another allow at 1000, or 5000, or 65534, changes nothing — evaluation never
reaches it.

### 5b. Where the firewall is *not* IAM

Re-declare the same IAP rule at **priority 100** instead of 1000, everything else unchanged:

| traffic | verdict | matched |
|---|---|---|
| browser → :443 | deny | sec-deny-public-ingress |
| IAP tunnel → :22 | **allow** | **allow-iap-ssh** |

In [`02_iam`](../02_iam/README.md), binding a weaker role could not take anything away and there was
no number to change — the only subtraction in that system is a **Deny policy**. Here **priority is
an explicit lever**: a rule you write can outrank a deny someone else wrote, in either direction, at
any time.

> **Which is the security lesson.** A blanket deny at 900 is **not a guardrail** — anyone with
> `compute.securityAdmin` writes 100 and walks past it. Real guardrails are **Org Policy** and **IAM
> Deny**, which live *above* the project.

## 6. Getting out, and getting in 📝

**A firewall rule is not a route.** Allowing egress does not give an instance a path; it only
declines to stop one. An instance with no external IP has no path to the internet no matter what
you allow.

| | |
|---|---|
| **Cloud NAT** | outbound only, no external IPs on the VMs. Regional, managed, needs a **Cloud Router**. **Cannot** do inbound — there is no port forwarding |
| **Private Google Access** | a **subnet** setting. Instances with no external IP reach Google APIs over internal paths. **Free** — and the right answer when the only destination is Google |
| **Private Service Connect / VPC Service Controls** | a private endpoint inside your VPC; a perimeter data cannot leave |
| **External IP** | **ephemeral by default** — it changes on stop/start. Reserve a **static** one for anything DNS points at |
| **Cloud DNS** | managed zones; a **private** zone resolves only inside the VPCs you authorise |

## 7. The load balancer matrix 📝

| what you are told | what to choose |
|---|---|
| HTTP(S), worldwide users, one anycast IP | **global external Application LB** |
| URL-based routing, Cloud CDN, Cloud Armor, SSL offload | same — all layer-7 features |
| TCP/UDP, must preserve client IP, any port | **external passthrough Network LB** (L4) |
| TLS that is not HTTP, needs offload | **proxy Network LB** |
| only inside the VPC, layer 7 | **internal Application LB** |
| only inside the VPC, layer 4 | **internal passthrough Network LB** |

Two facts decide most questions:

- Only the **global** Application LB gives one **anycast IP worldwide** plus layer-7 routing. Cloud
  CDN, Cloud Armor or path-based routing in the scenario ⇒ this one.
- **Passthrough** means the packet arrives with the **original client IP** and nothing is
  terminated. "Must see the client IP" or a non-HTTP protocol ⇒ **not** a proxy LB.

Autoscaling belongs to the **managed instance group behind** the LB, not the LB.

## 8. Connecting networks 📝

| | |
|---|---|
| **VPC peering** | two VPCs, private, no charge for the link, **non-transitive**, ranges must not overlap. Each side administers its own network |
| **Shared VPC** | one **host** project owns the network; **service** projects attach. *Peering joins networks; Shared VPC joins **projects** to one network* |
| **Cloud VPN** | IPsec over the public internet. **HA VPN** gives an SLA and two interfaces. Quick, cheap, bandwidth limited per tunnel |
| **Cloud Interconnect** | **Dedicated** (physical link into a Google facility) or **Partner** (via a provider). The answer to consistent high bandwidth, low latency, or *"not over the public internet"* |

Choosing: internet is fine → **VPN**. Not fine, or tens of gigabits → **Interconnect**. Both ends
are yours in GCP → **peering** or **Shared VPC**.

## The exam angle

| the scenario says | the answer |
|---|---|
| "instances in two regions must talk privately" | **same VPC, internal IPs.** Nothing else needed |
| "private VMs need OS patches from the internet" | **Cloud NAT** (+ Cloud Router) |
| "private VMs only need Google APIs" | **Private Google Access** on the subnet — *not* NAT |
| "I added an allow rule and it is still blocked" | a **lower-numbered deny** is winning. Change *that* rule |
| "stop anyone opening 0.0.0.0/0" | **Org Policy** — a firewall deny can be outranked |
| "central network team, one project per team" | **Shared VPC** |
| "merge two networks, both on 10.0.0.0/16" | **you cannot peer them.** One must be renumbered |
| "global HTTP(S), one IP, a WAF" | global external **Application LB** + **Cloud Armor** |
| "must see the real client IP" | **passthrough** Network LB |
| "the subnet is full" | **expand** the primary range. You cannot shrink it back |

## Things to try

- Change a subnet's demand in `demand` so it crosses a power of two — 500 → 509 hosts — and watch
  the prefix jump a whole size. This is why capacity plans get rounded generously.
- Set `BLOCK = 22` instead of `20` and re-read the headroom column. How much expansion room is
  "enough" is the actual decision; the script only shows you the number.
- Add a firewall rule at priority `0` and confirm nothing can outrank it. Then ask who in your
  organisation is allowed to write one.

## What is not demonstrated here

Not simulated, and not claimed: real packet forwarding, routes and route priority, Cloud Router and
BGP, Cloud Armor policies, CDN cache behaviour, MTU, or the performance of any load balancer. The
CIDR arithmetic and the firewall evaluation order are exact; everything under §6–§8 is documented
because there is no honest local proxy for Google's network.
