"""Storage: the class you pick is a bet on how often you will read it.

Storage on Google Cloud is two separate decisions that people run together:
WHAT SHAPE the data is (object, block, file) and, for object storage, HOW
COLD you are willing to make it. The second one is arithmetic, and it is
arithmetic with a cliff in it.

  1. The three shapes: object, block, file
  2. Storage classes - the price list, and the two hidden numbers
  3. The minimum-duration cliff                            [arithmetic]
  4. Where a colder class stops being cheaper              [arithmetic]
  5. A real lifecycle rule engine, over a year             [arithmetic]
  6. Location: region, dual-region, multi-region
  7. The database decision, as a resolver                  [runnable]
  8. Access, protection and the things that are not backups

SECTIONS 3, 4 AND 5 ARE ARITHMETIC and exact given the price model.
SECTION 7 IS A REAL RESOLVER - the rules are the exam content and it
prints which one fired.
SECTIONS 1, 6 AND 8 ARE DOCUMENTED.

PRICES ARE A REPRESENTATIVE MODEL - roughly us-central1 list, not a quote,
and they move. The RATIOS between classes are the durable part, and the
minimum durations and retrieval fees are contractual rather than
promotional, so those are the numbers to carry into the exam.

Run:
    python 05_storage/storage_and_databases.py

Concept reference: ACE domain 2 (~30%) - planning and implementing.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "00_setup"))

import matplotlib.pyplot as plt  # noqa: E402
from plotting import PALETTE, save_figure, use_house_style  # noqa: E402

OUT = Path(__file__).parent / "images"


@dataclass(frozen=True)
class StorageClass:
    name: str
    per_gb_month: float      # at-rest storage
    retrieval_per_gb: float  # charged on every read
    min_days: int            # early deletion is billed to here
    rank: int                # coldest wins when lifecycle rules collide


CLASSES = {
    "STANDARD": StorageClass("STANDARD", 0.0200, 0.000, 0, 0),
    "NEARLINE": StorageClass("NEARLINE", 0.0100, 0.010, 30, 1),
    "COLDLINE": StorageClass("COLDLINE", 0.0040, 0.020, 90, 2),
    "ARCHIVE": StorageClass("ARCHIVE", 0.0012, 0.050, 365, 3),
}
ORDER = ["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"]

# A billing month, so that 365 days costs exactly twelve of them.
DAYS_PER_MONTH = 365 / 12


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def storage_cost(cls: StorageClass, gb: float, days: float) -> float:
    """At-rest cost, with the minimum duration applied."""
    billed = max(days, cls.min_days)
    return gb * cls.per_gb_month * billed / DAYS_PER_MONTH


# ---------------------------------------------------------------------------
# 5. A lifecycle rule engine.
# ---------------------------------------------------------------------------
@dataclass
class LifecycleRule:
    action: str                      # "Delete" or a target class name
    age_days: int
    matches_class: set[str] | None = None

    def applies(self, age: int, cls: str) -> bool:
        if age < self.age_days:
            return False
        if self.matches_class and cls not in self.matches_class:
            return False
        return self.action != cls        # a no-op transition is not a match


def evaluate_lifecycle(rules: list[LifecycleRule], age: int,
                       cls: str) -> str | None:
    """Google's documented tie-break, implemented rather than described.

      1. Every rule whose conditions match is a candidate.
      2. DELETE beats SetStorageClass. Always, regardless of order in the
         JSON - there is no rule ordering in a lifecycle policy.
      3. Among SetStorageClass candidates, the COLDEST target wins.

    Returns the action to take, or None.
    """
    hits = [r for r in rules if r.applies(age, cls)]
    if not hits:
        return None
    if any(r.action == "Delete" for r in hits):
        return "Delete"
    return max((r.action for r in hits), key=lambda a: CLASSES[a].rank)


def reads_on_day(age: int, total_reads: float, tau: float) -> float:
    """Access decays with age. New data is hot; a year-old object rarely is."""
    return (total_reads / tau) * math.exp(-age / tau)


def run_policy(rules: list[LifecycleRule], gb: float, horizon: int,
               total_reads: float, tau: float) -> dict:
    """One object through one lifecycle policy, day by day.

    Tracks the EARLY DELETION CHARGE properly: leaving a class before its
    minimum duration - by deleting OR by transitioning away - still bills
    the remaining days at that class's rate.
    """
    cls = "STANDARD"
    entered = 0
    storage = retrieval = early = 0.0
    alive_days = horizon
    trace = []

    for day in range(horizon):
        c = CLASSES[cls]
        storage += gb * c.per_gb_month / DAYS_PER_MONTH
        r = reads_on_day(day, total_reads, tau)
        retrieval += r * gb * c.retrieval_per_gb
        trace.append(cls)

        action = evaluate_lifecycle(rules, day, cls)
        if action is None:
            continue

        held = day - entered + 1
        if held < c.min_days:                      # left early - pay the rest
            early += gb * c.per_gb_month * (c.min_days - held) / DAYS_PER_MONTH
        if action == "Delete":
            alive_days = day + 1
            break
        cls = action
        entered = day + 1

    return {"storage": storage, "retrieval": retrieval, "early": early,
            "total": storage + retrieval + early, "alive": alive_days,
            "final": cls, "trace": trace}


# ---------------------------------------------------------------------------
# 7. The database decision, as a resolver.
# ---------------------------------------------------------------------------
@dataclass
class Need:
    structured: bool = True
    relational: bool = True
    analytical: bool = False
    global_scale: bool = False       # more write throughput than one machine
    sql_engine: str | None = None    # "mysql" | "postgres" | "sqlserver"
    key_value: bool = False
    huge_throughput: bool = False    # sustained, millions of ops/sec
    mobile_offline: bool = False
    cache: bool = False


def choose_database(n: Need) -> tuple[str, str]:
    """The decision, in the order that actually resolves exam scenarios.

    Order matters: the first question that is TRUE decides. That is why
    "it is relational" is nearly useless on its own - three products are.
    """
    if n.cache:
        return ("Memorystore",
                "in-memory cache - Redis or Memcached, managed")
    if not n.structured:
        return ("Cloud Storage",
                "unstructured objects - files, images, backups, archives")
    if n.analytical:
        return ("BigQuery",
                "analytics over large datasets; serverless, columnar, SQL")
    if n.relational and n.global_scale:
        return ("Spanner",
                "relational AND horizontally scalable AND strongly "
                "consistent - the only product that is all three")
    if n.relational:
        engine = f" ({n.sql_engine})" if n.sql_engine else ""
        return ("Cloud SQL" + engine,
                "managed MySQL / PostgreSQL / SQL Server, regional, "
                "vertical scale. AlloyDB if it is PostgreSQL and needs "
                "far more performance")
    if n.mobile_offline:
        return ("Firestore",
                "document NoSQL with offline sync and realtime listeners - "
                "the mobile and web default")
    if n.key_value and n.huge_throughput:
        return ("Bigtable",
                "wide-column NoSQL, single-digit ms at enormous throughput; "
                "time series, IoT, ad tech. NO SQL and no joins")
    if n.key_value:
        return ("Firestore",
                "document NoSQL - Bigtable is overkill below very high "
                "sustained throughput")
    return ("Cloud Storage", "nothing else fits; it is probably just files")


def main() -> None:
    print("STORAGE - THE CLASS YOU PICK IS A BET ON HOW OFTEN YOU WILL READ IT")

    # --------------------------------------------------------- 1. the shapes
    rule("1. THE THREE SHAPES   [documented]")
    print("""  Before any price question, answer this one - it eliminates most
  of the options for free.

    OBJECT   Cloud Storage. A flat namespace of immutable blobs, reached
             over HTTP. You cannot edit part of an object; you replace
             it. There are no real directories - "folders" in the console
             are a prefix convention.
             For: images, backups, logs, data-lake files, static sites.

    BLOCK    Persistent Disk and Hyperdisk. A raw device attached to ONE
             VM (or read-only to several). The VM formats it. Disk types
             and the local-SSD trap are in 03_compute section 7.
             For: boot disks, databases you run yourself.

    FILE     Filestore. Managed NFS - a real POSIX filesystem that MANY
             machines mount at once, with locking and partial writes.
             For: lift-and-shift apps that expect a shared mount, render
             farms, HPC scratch.

  THE QUESTION THAT DECIDES IT: do several machines need to write to the
  same thing at once, with a filesystem? That is Filestore, and it is
  the only one of the three that does it. Persistent Disk is one writer.
  Cloud Storage has no filesystem at all.

  Cloud Storage FUSE lets you MOUNT a bucket, and it is a trap in a
  question: it looks like a filesystem and does not behave like one -
  no partial writes, no POSIX locking, very different latency.""")

    # --------------------------------------------------- 2. the price list
    rule("2. STORAGE CLASSES - the price list, and the two hidden numbers")
    print("  [representative prices - see the docstring. The MINIMUM DURATION")
    print("   and RETRIEVAL FEE columns are the contractual ones.]\n")
    print(f"  {'class':<10} {'$/GB/month':>11} {'retrieval $/GB':>15} "
          f"{'min duration':>13}  meant for")
    print("  " + "-" * 76)
    meant = {"STANDARD": "hot data, websites, anything being worked on",
             "NEARLINE": "read about once a month - backups",
             "COLDLINE": "read about once a quarter - DR copies",
             "ARCHIVE": "read once a year, if ever - compliance"}
    for name in ORDER:
        c = CLASSES[name]
        print(f"  {c.name:<10} {c.per_gb_month:>11.4f} {c.retrieval_per_gb:>15.3f} "
              f"{c.min_days:>10} days  {meant[name]}")

    cheapest = CLASSES["ARCHIVE"]
    dearest = CLASSES["STANDARD"]
    print(f"\n  At rest, ARCHIVE is "
          f"{dearest.per_gb_month / cheapest.per_gb_month:.1f}x cheaper than STANDARD.")
    print("  That number is the one everybody quotes and it is the least")
    print("  important of the three columns.")
    print("\n  ALL FOUR CLASSES HAVE THE SAME DURABILITY AND THE SAME API.")
    print("  Colder does not mean slower to first byte on Google Cloud -")
    print("  there is no thaw or restore step, unlike some other clouds.")
    print("  What changes is what you are BILLED when you read.")

    # ---------------------------------------------- 3. the minimum duration
    rule("3. THE MINIMUM-DURATION CLIFF   [arithmetic]")
    print("  A 1 GB object that is created, never read, and deleted after N")
    print("  days. Minimum durations applied; nothing else.\n")
    lifetimes = [1, 7, 30, 60, 90, 180, 365]
    print(f"  {'days held':>10}", end="")
    for name in ORDER:
        print(f" {name:>11}", end="")
    print("   cheapest")
    print("  " + "-" * 66)
    cliff = {name: [] for name in ORDER}
    for d in lifetimes:
        costs = {n: storage_cost(CLASSES[n], 1.0, d) for n in ORDER}
        for n in ORDER:
            cliff[n].append(costs[n])
        best = min(costs, key=costs.get)
        print(f"  {d:>10}", end="")
        for n in ORDER:
            print(f" {costs[n]:>11.5f}", end="")
        print(f"   {best}")

    one_day = storage_cost(CLASSES["ARCHIVE"], 1.0, 1)
    one_day_std = storage_cost(CLASSES["STANDARD"], 1.0, 1)
    print(f"\n  A ONE-DAY-OLD OBJECT IN ARCHIVE COSTS "
          f"{one_day / one_day_std:.0f}x WHAT IT COSTS IN")
    print("  STANDARD - because you are billed 365 days of Archive either")
    print("  way. The minimum duration is not a discount condition, it is a")
    print("  COMMITMENT: leaving early, by deleting OR by transitioning to")
    print("  another class, still bills the remaining days.")
    print("\n  Read the 'cheapest' column downward. The colder classes do not")
    print("  win until the object has lived long enough to serve its own")
    print("  minimum, which is exactly what the minimum is for.")

    # -------------------------------------------- 4. the retrieval crossover
    rule("4. WHERE A COLDER CLASS STOPS BEING CHEAPER   [arithmetic]")
    print("  1 GB held for a full year, read R times. Storage + retrieval.\n")
    read_counts = [0, 1, 2, 5, 10, 20, 50, 100]
    print(f"  {'reads/yr':>9}", end="")
    for name in ORDER:
        print(f" {name:>11}", end="")
    print("   cheapest")
    print("  " + "-" * 66)
    curves = {name: [] for name in ORDER}
    winners = {}
    for r in read_counts:
        costs = {}
        for n in ORDER:
            c = CLASSES[n]
            costs[n] = storage_cost(c, 1.0, 365) + r * 1.0 * c.retrieval_per_gb
            curves[n].append(costs[n])
        best = min(costs, key=costs.get)
        winners[r] = best
        print(f"  {r:>9}", end="")
        for n in ORDER:
            print(f" {costs[n]:>11.4f}", end="")
        print(f"   {best}")

    # find each crossover exactly
    print("\n  The exact crossovers, solved rather than tabulated:")
    for cold in ("NEARLINE", "COLDLINE", "ARCHIVE"):
        c, s = CLASSES[cold], CLASSES["STANDARD"]
        gap = storage_cost(c, 1.0, 365) - storage_cost(s, 1.0, 365)
        diff = c.retrieval_per_gb - s.retrieval_per_gb
        breakeven = -gap / diff
        print(f"    {cold:<9} beats STANDARD below "
              f"{breakeven:>5.1f} reads per GB per year")

    print("\n  ARCHIVE IS THE CHEAPEST CLASS AND THE EASIEST TO LOSE MONEY ON.")
    print("  Its at-rest price buys you very little room: a handful of reads")
    print("  a year and you are behind Standard, which has no retrieval fee")
    print("  at all.")
    print("\n  So the class is not a property of the DATA, it is a bet on the")
    print("  ACCESS PATTERN. 'Old' does not mean 'cold' - an audit log nobody")
    print("  touches for three years is Archive; a year-old customer invoice")
    print("  that anyone might pull up is not.")

    # -------------------------------------------------- 5. lifecycle engine
    rule("5. A LIFECYCLE POLICY, RUN FOR A YEAR   [arithmetic]")
    print("  Lifecycle rules are evaluated by Google like this, and the")
    print("  script implements it rather than describing it:")
    print("    1. every rule whose conditions match is a candidate")
    print("    2. DELETE beats SetStorageClass, always - there is NO rule")
    print("       ordering in a lifecycle policy")
    print("    3. among SetStorageClass candidates, the COLDEST target wins\n")

    total_reads, tau, horizon = 20.0, 25.0, 730
    print(f"  MODEL: one 1 GB object, read ~{total_reads:.0f} times in its first year")
    print(f"  with access decaying (half-life about {tau * math.log(2):.0f} days),")
    print(f"  observed for {horizon} days. TWO years, deliberately - a one-year")
    print("  horizon makes 'delete at 365' and 'keep forever' cost the same,")
    print("  which flatters every retention policy ever written.\n")

    policies = {
        "A  all Standard, delete at 365": [
            LifecycleRule("Delete", 365)],
        "B  tiered, never delete": [
            LifecycleRule("NEARLINE", 30, {"STANDARD"}),
            LifecycleRule("COLDLINE", 90, {"NEARLINE"}),
            LifecycleRule("ARCHIVE", 365, {"COLDLINE"})],
        "C  straight to Archive at 7": [
            LifecycleRule("ARCHIVE", 7, {"STANDARD"}),
            LifecycleRule("Delete", 60)],
        "D  tiered, delete at 365": [
            LifecycleRule("NEARLINE", 30, {"STANDARD"}),
            LifecycleRule("COLDLINE", 90, {"NEARLINE"}),
            LifecycleRule("Delete", 365)],
    }
    print(f"  {'policy':<32} {'storage':>9} {'retrieval':>10} "
          f"{'early-del':>10} {'TOTAL':>9}  ends as")
    print("  " + "-" * 84)
    results = {}
    for label, rules in policies.items():
        res = run_policy(rules, 1.0, horizon, total_reads, tau)
        results[label] = res
        ends = "deleted" if res["alive"] < horizon else res["final"]
        print(f"  {label:<32} {res['storage']:>9.4f} {res['retrieval']:>10.4f} "
              f"{res['early']:>10.4f} {res['total']:>9.4f}  {ends}")

    base = results["A  all Standard, delete at 365"]["total"]
    aggressive = results["C  straight to Archive at 7"]
    keep = results["B  tiered, never delete"]
    drop = results["D  tiered, delete at 365"]
    best_label = min(results, key=lambda k: results[k]["total"])
    print(f"\n  CHEAPEST: {best_label}")
    print(f"\n  Policy C moved everything to the cheapest class as fast as")
    print("  possible and deleted it early, which is what 'aggressive cost")
    print(f"  optimisation' usually means. It cost "
          f"{aggressive['total'] / base:.1f}x policy A -")
    print(f"  ${aggressive['retrieval']:.4f} of that in RETRIEVAL and "
          f"${aggressive['early']:.4f} in EARLY")
    print("  DELETION, against a storage line that was genuinely the lowest")
    print("  of the four.")
    print("\n  IT OPTIMISED THE ONE COLUMN IT COULD SEE. Every real bucket")
    print("  bill has three columns, and a lifecycle rule can only ever move")
    print("  data between them.")
    print(f"\n  Now compare B and D, which differ ONLY in whether the object is")
    print(f"  deleted at 365 days: ${keep['total']:.4f} against ${drop['total']:.4f}, a "
          f"{(keep['total'] / drop['total'] - 1) * 100:.0f}% difference for")
    print("  a second year of storage.")
    print(f"\n  DELETION IS WORTH LESS THAN YOU EXPECT ONCE THE DATA IS ALREADY")
    print("  COLD, and that is the honest reading. Archive is cheap enough")
    print("  that the argument for deleting has to be made on risk and")
    print("  obligation - what you are liable for by still holding it - not")
    print("  on this number. The savings all happened earlier, in the first")
    print("  90 days, when the data was still expensive.")
    print("\n  Other conditions a lifecycle rule can use: numNewerVersions,")
    print("  daysSinceNoncurrentTime (the pair that keeps object versioning")
    print("  from growing forever), createdBefore, matchesPrefix/Suffix, and")
    print("  isLive. Rules run asynchronously - roughly daily, NOT the")
    print("  instant a condition becomes true.")

    # ------------------------------------------------------- 6. location
    rule("6. LOCATION   [documented]")
    print("""    REGION        one region - us-central1. Cheapest, lowest
                  latency to compute in that region. A regional
                  outage takes the bucket with it.

    DUAL-REGION   two SPECIFIC regions - nam4, eur4. Data is in both.
                  You choose them, so you know where the data is.

    MULTI-REGION  a large area - US, EU, ASIA. Highest availability,
                  highest price, and you do NOT choose the specific
                  regions inside it.

  THE RULE OF THUMB: put the bucket where the COMPUTE is. A multi-region
  bucket read constantly by VMs in one region buys availability you are
  not using and adds egress you are paying for.

  AND THE ONE-WAY DOOR: LOCATION CANNOT BE CHANGED AFTER THE BUCKET IS
  CREATED. Storage class can be changed freely; location means creating
  a new bucket and copying. Bucket NAMES are also globally unique across
  all of Google Cloud, and a deleted name is not immediately reusable.

  Egress: reads from within the same region are free; crossing a region,
  a continent, or out to the internet is not. "Why is the bill so high"
  is more often egress than storage.""")

    # ----------------------------------------------- 7. database resolver
    rule("7. THE DATABASE DECISION   [runnable resolver]")
    scenarios = [
        ("global inventory, outgrowing one machine",
         Need(global_scale=True)),
        ("existing MySQL app, lift and shift",
         Need(sql_engine="mysql")),
        ("dashboards over 5 years of event data",
         Need(analytical=True)),
        ("IoT telemetry, 200k writes/sec",
         Need(relational=False, key_value=True, huge_throughput=True)),
        ("mobile app, works offline, syncs later",
         Need(relational=False, mobile_offline=True)),
        ("session store in front of a database",
         Need(cache=True)),
        ("scanned PDFs, 40 TB, read rarely",
         Need(structured=False)),
    ]
    print(f"  {'the scenario':<42} {'answer':<18} because")
    print("  " + "-" * 72)
    for text, need in scenarios:
        product, why = choose_database(need)
        short = why.split(" - ")[0].split(";")[0]
        print(f"  {text:<42} {product:<18} {short[:60]}")

    print("""
  THE TWO DISTINCTIONS THE EXAM ACTUALLY TESTS:

    Cloud SQL vs SPANNER.  Both are relational and managed. Cloud SQL
    scales UP (a bigger machine) and is regional. Spanner scales OUT,
    is horizontally scalable AND strongly consistent AND global - and
    is the only product that is all three. The trigger words are
    "global", "unlimited scale", "no downtime for maintenance", and
    "more write throughput than one machine".

    FIRESTORE vs BIGTABLE.  Both are NoSQL and neither speaks SQL.
    Firestore is documents, with offline sync, realtime listeners and
    ACID transactions - the mobile/web default. Bigtable is wide-column
    at enormous sustained throughput with single-digit millisecond
    latency, no joins, and a ROW KEY that decides everything about
    performance. If the question says time series, IoT, ad tech or
    "millions of operations per second", it is Bigtable.

  AlloyDB is PostgreSQL-compatible and sits between Cloud SQL and
  Spanner: far more performance than Cloud SQL, without Spanner's
  horizontal model.

  BigQuery is in this list because scenarios put it there, but it is an
  ANALYTICS warehouse, not a transactional database. "Thousands of small
  writes and point lookups" is the wrong shape for it no matter how much
  SQL is in the question.""")

    # ------------------------------------------------ 8. access, protection
    rule("8. ACCESS, PROTECTION, AND WHAT IS NOT A BACKUP   [documented]")
    print("""    UNIFORM BUCKET-LEVEL ACCESS   IAM only. Turn it ON. It is the
                                  recommended default and it makes
                                  permissions auditable in one place.
    FINE-GRAINED (ACLs)           per-OBJECT legacy ACLs alongside IAM.
                                  Two systems, two places to get it
                                  wrong. Only for per-object cases IAM
                                  genuinely cannot express.

    SIGNED URL      time-limited access to one object for someone with
                    NO Google account. The answer to "let a customer
                    download this without making them a principal".
    SIGNED POLICY DOCUMENT  the same idea for uploads.

    OBJECT VERSIONING   keeps noncurrent versions when you overwrite or
                        delete. Protects against YOUR mistakes. Pair it
                        with a lifecycle rule on numNewerVersions or it
                        grows forever.
    RETENTION POLICY    objects CANNOT be deleted until an age. With a
                        LOCK it cannot be shortened or removed, by
                        anyone, including you. This is the compliance
                        answer - WORM.
    OBJECT HOLD         the same idea for one object, toggled by hand.
    SOFT DELETE         a bucket-level window during which deleted data
                        can be restored.

    ENCRYPTION   at rest, always, by default, Google-managed. The two
                 upgrades: CMEK (your key in Cloud KMS - the usual
                 answer to "we must control the key") and CSEK (you
                 supply the key on every request, Google stores
                 nothing).

  NONE OF THAT IS A BACKUP. Versioning and retention protect against
  overwrite and deletion INSIDE one bucket in one project. They do not
  protect against a deleted project, a compromised account with
  storage.admin, or a lifecycle rule that was wrong for six months.
  A backup is a copy somewhere with a different failure mode and a
  different set of people who can destroy it.""")

    # ---------------------------------------------------------------- figure
    use_house_style()
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.2))

    for name in ORDER:
        ax1.plot(lifetimes, cliff[name], "o-", label=name.title())
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("days held before deletion")
    ax1.set_ylabel("$ per GB")
    ax1.set_title("The minimum-duration cliff", loc="left")
    ax1.legend(fontsize=8)

    for name in ORDER:
        ax2.plot(read_counts, curves[name], "o-", label=name.title())
    ax2.set_xlabel("reads per GB per year")
    ax2.set_ylabel("$ per GB-year")
    ax2.set_title("Colder is a bet on not reading", loc="left")
    ax2.legend(fontsize=8)

    labels = [k.split("  ")[0] for k in policies]
    parts = ["storage", "retrieval", "early"]
    colours = [PALETTE["blue"], PALETTE["orange"], PALETTE["vermillion"]]
    bottom = [0.0] * len(labels)
    for part, colour in zip(parts, colours):
        vals = [results[k][part] for k in policies]
        ax3.bar(labels, vals, bottom=bottom, label=part, color=colour)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax3.set_ylabel("$ per GB over a year")
    ax3.set_title("Three columns, not one", loc="left")
    ax3.legend(fontsize=8)
    save_figure(fig, OUT / "storage_and_databases.png")
    print(f"\n  figure -> {OUT / 'storage_and_databases.png'}")

    rule("THE EXAM ANGLE")
    print("""  the scenario says                          the answer
  ------------------------------------------------------------------------
  "accessed once a month"                    NEARLINE
  "disaster recovery copy, quarterly test"   COLDLINE
  "keep 7 years for compliance, never        ARCHIVE + a LOCKED retention
   read"                                     policy
  "move old data to a cheaper class          a LIFECYCLE rule, not a
   automatically"                            script
  "several VMs need the same filesystem"     FILESTORE
  "let a customer download one file, no      a SIGNED URL
   Google account"
  "objects must not be deletable, even       RETENTION POLICY with a LOCK
   by an admin"
  "we must control the encryption key"       CMEK, with Cloud KMS
  "relational, global, strongly              SPANNER
   consistent"
  "managed MySQL for an existing app"        CLOUD SQL
  "time series at millions of ops/sec"       BIGTABLE
  "mobile app that works offline"            FIRESTORE
  "the bucket is in the wrong region"        create a new one and copy.
                                             Location is immutable""")


if __name__ == "__main__":
    main()
