"""Generate a SYNTHETIC OCDS fixture shaped like the Kenya PPIP feed (ocds-5whusi).

Every buyer, supplier and person here is fictional ("Mfano", "Kielelezo" and "Sampuli" are
Swahili for "example", "model" and "sample"). The fixture deliberately reproduces the data
problems the OCP Data Registry documents for the real feed, so the agent is built to cope:

* extreme value outliers (one award at KES 99 trillion)
* supplier identifier schemes that break the org-id pattern, malformed KRA PINs
* buyer names missing from `parties` (only in `buyer.name`), and a few missing altogether
* releases with empty `awards`
* a supplier winning most of one buyer's awards for one item, under four name spellings
* four same-supplier awards just under a quotation threshold within 45 days (possible splitting)
* contact points carrying personal e-mails (ingest must drop them)
* sole-proprietor suppliers trading under a person's name (must be pseudonymised)

    python -m zabuni.data.synth data/sample_ocds.jsonl.gz
"""
from __future__ import annotations

import gzip
import json
import math
import random
import sys
from pathlib import Path

SEED = 20261012
PREFIX = "ocds-synth0"

BUYERS = [
    ("KE-SYN-001", "County Government of Mfano"),
    ("KE-SYN-002", "County Government of Kielelezo"),
    ("KE-SYN-003", "County Government of Sampuli"),
    ("KE-SYN-004", "Mfano Water and Sanitation Company"),
    ("KE-SYN-005", "Kielelezo Level 5 Hospital"),
    ("KE-SYN-006", "State Department for Mfano Services"),
    ("KE-SYN-007", "County Government of Jaribio"),
    ("KE-SYN-008", "County Government of Kifani"),
    ("KE-SYN-009", "Sampuli Technical Training Institute"),
    ("KE-SYN-010", "Jaribio Agricultural Development Authority"),
    ("KE-SYN-011", "Kifani County Referral Hospital"),
    ("KE-SYN-012", "Mfano Rural Roads Board"),
]

SCALE = 6  # awards per item = n x SCALE (MRI stays rare on purpose)

# item key -> (title, category, base KES, log-sd, n awards before SCALE)
ITEMS = {
    "maize_seed": ("Supply and delivery of certified maize seed", "goods", 4_200_000, 0.30, 34),
    "fertiliser": ("Supply and delivery of DAP planting fertiliser", "goods", 6_500_000, 0.30, 30),
    "computers": ("Supply and delivery of desktop computers and laptops", "goods", 3_800_000, 0.35, 28),
    "pharma": ("Supply of pharmaceuticals and non-pharmaceuticals", "goods", 12_000_000, 0.40, 30),
    "stationery": ("Supply of office stationery and consumables", "goods", 900_000, 0.35, 26),
    "gravelling": ("Gravelling and murraming of rural access roads", "works", 18_000_000, 0.40, 30),
    "borehole": ("Drilling and equipping of community borehole", "works", 7_500_000, 0.30, 26),
    "cleaning": ("Provision of office cleaning services", "services", 2_400_000, 0.30, 22),
    "fuel": ("Supply and delivery of fuel and lubricants", "goods", 5_000_000, 0.30, 24),
    "medical": ("Supply of medical and surgical consumables", "goods", 1_300_000, 0.30, 22),
    "desks": ("Supply and delivery of school desks and lockers", "goods", 2_800_000, 0.30, 20),
    "solar": ("Installation of solar-powered street lights", "works", 9_000_000, 0.35, 18),
    "ambulance": ("Supply of fully equipped type B ambulance", "goods", 14_000_000, 0.15, 12),
    "irrigation": ("Construction of small-holder irrigation scheme", "works", 22_000_000, 0.45, 16),
    "feasibility": ("Consultancy for feasibility study and detailed design", "services", 6_000_000, 0.40, 14),
    "mri": ("Supply, installation and commissioning of MRI machine", "goods", 180_000_000, 0.20, 2),
}

COMPANIES = [
    "Jabali Supplies Ltd", "Mto Agrovet Limited", "Nyota General Contractors Ltd", "Pwani Pharmaceuticals Ltd",
    "Savanna Technologies Limited", "Upeo Builders & Engineering Ltd", "Bonde Fuel Distributors Ltd",
    "Safi Cleaning Services Ltd", "Kisima Drilling Company Limited", "Tausi Stationers Ltd",
    "Mvua Agro Inputs Ltd", "Imara Construction Ltd", "Afya Medical Supplies Ltd", "Kompyuta Systems Ltd",
    "Ziwa Logistics Ltd", "Shamba Seeds Ltd", "Barabara Works Ltd", "Maji Engineering Ltd",
    "Radiant Imaging Solutions Ltd", "Mwanga Energy Ltd", "Dawa Bora Pharmaceuticals Ltd",
    "Elimu Furniture Works Ltd", "Jua Solar Solutions Ltd", "Huduma Ambulance Services Ltd",
    "Mfereji Irrigation Engineering Ltd", "Ramani Consultants Ltd", "Tiba Surgical Supplies Ltd",
    "Mbegu Bora Seeds Ltd", "Mbolea Agro Distributors Ltd", "Kalamu Office Supplies Ltd",
    "Nuru Electricals Ltd", "Chemchemi Drilling Ltd", "Barabara Kuu Contractors Ltd", "Petro Mafuta Ltd",
    "Usafi Hygiene Services Ltd", "Teknolojia Hub Ltd", "Pamoja Construction Co. Ltd", "Kesho Ventures Ltd",
    "Shujaa General Supplies Ltd", "Mlima Holdings Ltd",
]
PERSONS = ["Achieng Otieno", "Mwangi Kariuki"]  # fictional sole proprietors
KILELE_VARIANTS = ["Kilele Traders Ltd", "KILELE TRADERS LIMITED", "Kilele Traders Ltd.", "Kilele Traders"]


def _pin(rng: random.Random) -> str:
    return f"P{rng.randint(0, 999_999_999):09d}{chr(rng.randint(65, 90))}"


def _supplier(rng: random.Random, name: str, *, bad: bool = False) -> dict:
    if bad:  # breaks its own scheme, like the real feed
        return {"id": f"KRA-{rng.randint(1000, 9999)}", "name": name,
                "identifier": {"scheme": "KRA", "id": f"P0{rng.randint(1_000_000, 9_999_999)}"}}
    pin = _pin(rng)
    return {"id": f"KE-KRA-{pin}", "name": name, "identifier": {"scheme": "KE-KRA", "id": pin}}


def generate(n_empty: int = 240) -> list[dict]:
    rng = random.Random(SEED)
    releases: list[dict] = []
    seq = 0

    def make(item: str, buyer: tuple[str, str], supplier: dict, amount: float, year: int, **kw) -> dict:
        nonlocal seq
        seq += 1
        title, cat, *_ = ITEMS[item]
        ocid = f"{PREFIX}-{seq:05d}"
        date = f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T10:00:00Z"
        buyer_party = {"id": buyer[0], "name": buyer[1], "roles": ["buyer"],
                       "contactPoint": {"name": "Procurement Officer (fictional)",
                                        "email": f"officer{seq}@example.go.ke", "telephone": "0712345678"}}
        sup_party = {"id": supplier["id"], "name": supplier["name"], "roles": ["supplier"],
                     "contactPoint": {"name": "Director (fictional)", "email": f"director{seq}@example.co.ke"}}
        parties = [buyer_party, sup_party]
        buyer_ref = {"id": buyer[0], "name": buyer[1]}
        if kw.get("buyer_not_in_parties"):
            parties = [sup_party]
        if kw.get("buyer_missing"):
            parties, buyer_ref = [sup_party], {"id": buyer[0]}
        if kw.get("supplier_not_in_parties"):
            parties = [p for p in parties if p is not sup_party]
        award = {"id": f"{ocid}-AWD-1", "date": date, "status": kw.get("status", "active"),
                 "value": {"amount": round(amount, 2), "currency": kw.get("currency", "KES")},
                 "suppliers": [{"id": supplier["id"], "name": supplier["name"]}]}
        if "identifier" in supplier:
            award["suppliers"][0]["identifier"] = supplier["identifier"]
        return {
            "ocid": ocid, "id": f"{ocid}-{year}0101", "date": date, "tag": ["compiled"],
            "initiationType": "tender", "buyer": buyer_ref, "parties": parties,
            "tender": {"id": f"T-{seq:05d}", "title": f"{title} ({buyer[1].split()[-1]} {year})",
                       "mainProcurementCategory": cat, "procurementMethod": "open", "status": "complete",
                       "value": {"amount": round(amount * rng.uniform(0.95, 1.15), -3), "currency": "KES"}},
            "awards": [award],
            "contracts": [{"id": f"{ocid}-CON-1", "awardID": award["id"], "status": "active",
                           "value": award["value"]}],
        }

    company_suppliers = {c: _supplier(rng, c, bad=rng.random() < 0.15) for c in COMPANIES}
    for item, (_t, _c, base, sd, n) in ITEMS.items():
        for _ in range(n if item == "mri" else n * SCALE):
            buyer = rng.choice(BUYERS)
            sup = company_suppliers[rng.choice(COMPANIES)]
            amount = math.exp(math.log(base) + rng.gauss(0, sd))
            kw = {}
            r = rng.random()
            if r < 0.10:
                kw["buyer_not_in_parties"] = True
            elif r < 0.13:
                kw["buyer_missing"] = True
            if rng.random() < 0.05:
                kw["status"] = "cancelled"
            releases.append(make(item, buyer, sup, amount, rng.randint(2019, 2025), **kw))

    # Planted: one supplier, under four name spellings and a broken identifier scheme,
    # wins most borehole awards at County Government of Mfano.
    mfano = BUYERS[0]
    for i in range(20):
        sup = _supplier(rng, KILELE_VARIANTS[i % 4], bad=True)
        amount = math.exp(math.log(7_500_000) + rng.gauss(0.15, 0.25))
        releases.append(make("borehole", mfano, sup, amount, 2022 + i % 4))
    for _ in range(3):
        releases.append(make("borehole", mfano, company_suppliers["Kisima Drilling Company Limited"],
                             math.exp(math.log(7_500_000) + rng.gauss(0, 0.3)), rng.randint(2022, 2025)))

    # Planted: possible contract splitting. Four awards for the same item, same buyer, same
    # supplier, each just under a KES 2m quotation threshold, inside 45 days (sum about KES 7.4m).
    hosp = BUYERS[4]
    afya = company_suppliers["Afya Medical Supplies Ltd"]
    for day, amt in [(3, 1_890_000), (17, 1_940_000), (29, 1_760_000), (44, 1_830_000)]:
        r = make("medical", hosp, afya, amt, 2024)
        d = f"2024-03-{day:02d}T10:00:00Z" if day <= 31 else f"2024-04-{day - 31:02d}T10:00:00Z"
        r["date"] = r["awards"][0]["date"] = d
        r["tender"]["procurementMethod"] = "limited"
        releases.append(r)

    # Planted: an extreme value that is almost certainly a data-entry error.
    releases.append(make("gravelling", BUYERS[2], company_suppliers["Barabara Works Ltd"],
                         99_000_000_000_000, 2024))
    # Planted: sole proprietors (must be pseudonymised, never named).
    for p in PERSONS:
        for _ in range(3):
            releases.append(make(rng.choice(["stationery", "cleaning"]), rng.choice(BUYERS),
                                 {"id": f"IND-{rng.randint(100, 999)}", "name": p},
                                 math.exp(math.log(900_000) + rng.gauss(0, 0.3)), rng.randint(2022, 2025)))
    # Planted: one of the two MRI awards is in USD, leaving too few KES comparables.
    releases[[i for i, r in enumerate(releases) if "MRI" in r["tender"]["title"]][0]]["awards"][0]["value"]["currency"] = "USD"

    # Tenders that never reached award (empty awards array, as in the real feed).
    for _ in range(n_empty):
        r = make(rng.choice(list(ITEMS)), rng.choice(BUYERS), company_suppliers[rng.choice(COMPANIES)],
                 1_000_000, rng.randint(2021, 2025))
        r["awards"], r["contracts"] = [], []
        r["tender"]["status"] = "active" if rng.random() < 0.5 else "cancelled"
        releases.append(r)

    rng.shuffle(releases)
    return releases


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    out = Path(argv[0] if argv else "data/sample_ocds.jsonl.gz")
    out.parent.mkdir(parents=True, exist_ok=True)
    rel = generate()
    payload = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rel).encode()
    with open(out, "wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as fh:
        fh.write(payload)  # mtime=0 keeps the file byte-identical across runs
    print(f"Wrote {len(rel)} SYNTHETIC releases to {out}")


if __name__ == "__main__":
    main()
