# Storage — the class you pick is a bet on how often you will read it

> **ACE domain 2 (~30%)** — planning and implementing a cloud solution
> **Runtime:** ~3 s on a laptop CPU · **Needs:** nothing — no project, no credentials

```bash
python 05_storage/storage_and_databases.py
```

Storage is two decisions people run together: **what shape** the data is (object, block, file),
and — for object storage — **how cold** you are willing to make it. The second is arithmetic, and
it has a cliff in it.

**§3, §4 and §5 are arithmetic**, exact given the price model. **§7 is a real resolver** that prints
which rule fired. **§1, §6 and §8 are documented** 📝.

> ⚠️ **Prices are a representative model.** The **minimum durations** and **retrieval fees** are
> contractual rather than promotional, so those are the numbers to carry into the exam. The at-rest
> dollars move.

---

## 1. The three shapes 📝

| | |
|---|---|
| **Object** — Cloud Storage | a flat namespace of immutable blobs over HTTP. You cannot edit part of an object, you replace it. **There are no real directories** — "folders" in the console are a prefix convention |
| **Block** — Persistent Disk, Hyperdisk | a raw device attached to **one** VM. Disk types and the local-SSD trap live in [`03_compute` §7](../03_compute/README.md) |
| **File** — Filestore | managed **NFS** — a real POSIX filesystem **many** machines mount at once, with locking and partial writes |

**The question that decides it:** do several machines need to write to the same thing at once, with
a filesystem? That is **Filestore**, and it is the only one of the three that does it.

Cloud Storage **FUSE** lets you *mount* a bucket, and it is a trap in a question: it looks like a
filesystem and does not behave like one — no partial writes, no POSIX locking, very different
latency.

## 2. The price list, and the two hidden numbers

| class | $/GB/month | retrieval $/GB | min duration | meant for |
|---|---|---|---|---|
| **Standard** | 0.0200 | **0.000** | **0 days** | hot data, websites, anything being worked on |
| **Nearline** | 0.0100 | 0.010 | 30 days | read about once a month — backups |
| **Coldline** | 0.0040 | 0.020 | 90 days | read about once a quarter — DR copies |
| **Archive** | 0.0012 | **0.050** | **365 days** | read once a year, if ever — compliance |

At rest, Archive is **16.7× cheaper** than Standard. *That number is the one everybody quotes and
it is the least important of the three columns.*

**All four classes have the same durability and the same API.** Colder does not mean slower to
first byte on Google Cloud — there is no thaw or restore step, unlike some other clouds. What
changes is what you are **billed** when you read.

## 3. The minimum-duration cliff

A 1 GB object, created, never read, deleted after N days:

| days held | Standard | Nearline | Coldline | Archive | cheapest |
|---|---|---|---|---|---|
| 1 | **0.00066** | 0.00986 | 0.01184 | 0.01440 | Standard |
| 7 | **0.00460** | 0.00986 | 0.01184 | 0.01440 | Standard |
| 30 | 0.01973 | **0.00986** | 0.01184 | 0.01440 | Nearline |
| 60 | 0.03945 | 0.01973 | **0.01184** | 0.01440 | Coldline |
| 90 | 0.05918 | 0.02959 | **0.01184** | 0.01440 | Coldline |
| 180 | 0.11836 | 0.05918 | 0.02367 | **0.01440** | Archive |
| 365 | 0.24000 | 0.12000 | 0.04800 | **0.01440** | Archive |

> **A one-day-old object in Archive costs 22× what it costs in Standard** — because you are billed
> 365 days of Archive either way.

The minimum duration is **not a discount condition, it is a commitment**: leaving early — by
deleting **or by transitioning to another class** — still bills the remaining days. Read the
*cheapest* column downward: colder classes do not win until the object has lived long enough to
serve its own minimum, which is exactly what the minimum is for.

## 4. Where a colder class stops being cheaper

1 GB held for a year, read R times:

| reads/yr | Standard | Nearline | Coldline | Archive | cheapest |
|---|---|---|---|---|---|
| 0 | 0.2400 | 0.1200 | 0.0480 | **0.0144** | Archive |
| 1 | 0.2400 | 0.1300 | 0.0680 | **0.0644** | Archive |
| 2 | 0.2400 | 0.1400 | **0.0880** | 0.1144 | Coldline |
| 5 | 0.2400 | 0.1700 | **0.1480** | 0.2644 | Coldline |
| 10 | 0.2400 | **0.2200** | 0.2480 | 0.5144 | Nearline |
| 20 | **0.2400** | 0.3200 | 0.4480 | 1.0144 | Standard |
| 100 | **0.2400** | 1.1200 | 2.0480 | 5.0144 | Standard |

Solved exactly rather than tabulated:

```
NEARLINE  beats STANDARD below  12.0 reads per GB per year
COLDLINE  beats STANDARD below   9.6 reads per GB per year
ARCHIVE   beats STANDARD below   4.5 reads per GB per year
```

> **Archive is the cheapest class and the easiest to lose money on.** Its at-rest price buys very
> little room: about **four and a half reads a year** and you are behind Standard, which has no
> retrieval fee at all.

So the class is not a property of the **data**, it is a bet on the **access pattern**. *"Old" does
not mean "cold"* — an audit log nobody touches for three years is Archive; a year-old customer
invoice anyone might pull up is not.

## 5. A lifecycle policy, run for two years

Google evaluates lifecycle rules like this, and the script **implements** it:

1. every rule whose conditions match is a candidate
2. **Delete beats SetStorageClass**, always — *there is no rule ordering in a lifecycle policy*
3. among SetStorageClass candidates, the **coldest target wins**

**The model:** one 1 GB object, ~20 reads in its first year with access decaying (half-life ~17
days), observed for **730 days**. Two years deliberately — a one-year horizon makes *"delete at
365"* and *"keep forever"* cost exactly the same, which flatters every retention policy ever
written.

| policy | storage | retrieval | early-del | **TOTAL** | ends as |
|---|---|---|---|---|---|
| **A** all Standard, delete at 365 | 0.2407 | 0.0000 | 0.0000 | 0.2407 | deleted |
| **B** tiered, never delete | 0.0906 | 0.0644 | 0.0000 | 0.1550 | ARCHIVE |
| **C** straight to Archive at 7 | **0.0074** | **0.6519** | 0.0123 | **0.6715** | deleted |
| **D** tiered, delete at 365 | 0.0763 | 0.0644 | 0.0000 | **0.1407** | deleted |

**Policy C is what "aggressive cost optimisation" usually means** — cheapest class as fast as
possible, delete early. It had **genuinely the lowest storage line of the four** and cost **2.8×
policy A**, because $0.6519 went to retrieval and $0.0123 to early deletion.

> **It optimised the one column it could see.** Every real bucket bill has three columns, and a
> lifecycle rule can only ever move data between them.

**B vs D differ only in whether the object is deleted at 365 days:** $0.1550 against $0.1407 — a
**10% difference** for a whole extra year of storage.

> **Deletion is worth less than you expect once the data is already cold.** Archive is cheap enough
> that the case for deleting has to be made on **risk and obligation** — what you are liable for by
> still holding it — not on this number. The savings all happened earlier, in the first 90 days,
> while the data was still expensive.

Other lifecycle conditions: `numNewerVersions`, `daysSinceNoncurrentTime` (the pair that keeps
object versioning from growing forever), `createdBefore`, `matchesPrefix`/`Suffix`, `isLive`. Rules
run **asynchronously — roughly daily**, not the instant a condition becomes true.

## 6. Location 📝

| | |
|---|---|
| **Region** | one region. Cheapest, lowest latency to compute there. A regional outage takes the bucket with it |
| **Dual-region** | two **specific** regions (`nam4`, `eur4`). You choose them, so you know where the data is |
| **Multi-region** | a large area (`US`, `EU`, `ASIA`). Highest availability, highest price, and you do **not** choose the regions inside it |

**Rule of thumb: put the bucket where the compute is.** A multi-region bucket read constantly by VMs
in one region buys availability you are not using and adds egress you are paying for.

> **The one-way door: location cannot be changed after the bucket is created.** Storage class can be
> changed freely; location means creating a new bucket and copying. Bucket **names are globally
> unique** across all of Google Cloud, and a deleted name is not immediately reusable.

Reads from within the same region are free; crossing a region, a continent, or out to the internet
is not. *"Why is the bill so high"* is more often **egress** than storage.

## 7. The database decision — a runnable resolver

```
the scenario                               answer             because
------------------------------------------------------------------------
global inventory, outgrowing one machine   Spanner            relational AND horizontally scalable AND strongly consistent
existing MySQL app, lift and shift         Cloud SQL (mysql)  managed MySQL / PostgreSQL / SQL Server, regional, vertical
dashboards over 5 years of event data      BigQuery           analytics over large datasets
IoT telemetry, 200k writes/sec             Bigtable           wide-column NoSQL, single-digit ms at enormous throughput
mobile app, works offline, syncs later     Firestore          document NoSQL with offline sync and realtime listeners
session store in front of a database       Memorystore        in-memory cache
scanned PDFs, 40 TB, read rarely           Cloud Storage      unstructured objects
```

**Order matters** — the first question that is true decides. Which is why *"it's relational"* is
nearly useless on its own: three products are.

### The two distinctions the exam actually tests

**Cloud SQL vs Spanner.** Both relational, both managed. Cloud SQL scales **up** (a bigger machine)
and is regional. Spanner scales **out**, and is horizontally scalable **and** strongly consistent
**and** global — the only product that is all three. Trigger words: *global*, *unlimited scale*, *no
downtime for maintenance*, *more write throughput than one machine*.

**Firestore vs Bigtable.** Both NoSQL, neither speaks SQL. **Firestore** is documents, with offline
sync, realtime listeners and ACID transactions — the mobile/web default. **Bigtable** is wide-column
at enormous sustained throughput, single-digit ms, **no joins**, and a **row key that decides
everything** about performance. *Time series, IoT, ad tech, "millions of operations per second"* ⇒
Bigtable.

**AlloyDB** is PostgreSQL-compatible and sits between the two: far more performance than Cloud SQL,
without Spanner's horizontal model.

**BigQuery** is in the list because scenarios put it there, but it is an **analytics warehouse**, not
a transactional database — *"thousands of small writes and point lookups"* is the wrong shape for it
no matter how much SQL is in the question.

## 8. Access, protection, and what is not a backup 📝

| | |
|---|---|
| **Uniform bucket-level access** | IAM only. **Turn it on** — the recommended default, and it makes permissions auditable in one place |
| **Fine-grained (ACLs)** | per-object legacy ACLs *alongside* IAM. Two systems, two places to get it wrong |
| **Signed URL** | time-limited access to one object for someone with **no Google account**. The answer to *"let a customer download this without making them a principal"* |
| **Object versioning** | keeps noncurrent versions on overwrite/delete. Protects against **your** mistakes. Pair with a `numNewerVersions` lifecycle rule or it grows forever |
| **Retention policy** | objects **cannot** be deleted until an age. **Locked**, it cannot be shortened or removed by anyone, including you. This is the compliance answer — WORM |
| **Object hold** | the same idea for one object, toggled by hand |
| **Soft delete** | a bucket-level window during which deleted data can be restored |
| **Encryption** | at rest, always, by default. Upgrades: **CMEK** (your key in Cloud KMS — the usual answer to *"we must control the key"*) and **CSEK** (you supply it per request; Google stores nothing) |

> **None of that is a backup.** Versioning and retention protect against overwrite and deletion
> *inside one bucket in one project*. They do not protect against a deleted project, a compromised
> account with `storage.admin`, or a lifecycle rule that was wrong for six months. A backup is a
> copy somewhere with a **different failure mode** and a **different set of people who can destroy
> it**.

## The exam angle

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
| "the bucket is in the wrong region" | **create a new one and copy** — location is immutable |

## Things to try

- Sweep `total_reads` in §5 and watch the ranking move (verified):

  | reads/yr | A | B | C | D | cheapest |
  |---|---|---|---|---|---|
  | 1 | 0.2407 | 0.0939 | **0.0523** | 0.0795 | **C** |
  | 2 | 0.2407 | 0.0971 | 0.0848 | **0.0827** | D |
  | 5 | 0.2407 | 0.1067 | 0.1826 | **0.0924** | D |
  | 20 | 0.2407 | 0.1550 | 0.6715 | **0.1407** | D |

  **The "aggressive" policy C wins at exactly one read a year and loses at two.** It was never
  wrong in itself — it was wrong for that access pattern, which is the whole argument of the
  section. A policy tuned this finely is one behaviour change away from being the most expensive
  option you have.
- Add a fifth policy that transitions to Archive at day 30 *and* deletes at day 45. Watch the
  early-deletion column carry almost the entire cost.
- Change `horizon` back to 365 and confirm that B and D become identical. That is the measurement
  artefact the section was rebuilt to avoid.

## What is not demonstrated here

Not simulated, and not claimed: real object upload or download, actual latency of any class, Class A
and Class B **operation charges** (which are also higher on the colder classes), egress pricing,
replication behaviour, or any real database. §3–§5 are exact given the price model; §7 is a
decision procedure, not a benchmark.
