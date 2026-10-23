"""Creates the SQLite sales database: schema.sql + deterministic sample data."""

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app.core.config import ROOT_DIR, get_settings

SCHEMA_PATH = ROOT_DIR / "data" / "database" / "schema.sql"

PRODUCTS = [
    (1, "Amoxicillin/Clavulanate 625 mg tablets", "antibiotic", 1_450_000, 0),
    (2, "Azithromycin 250 mg capsules", "antibiotic", 980_000, 0),
    (3, "Cefixime 400 mg tablets", "antibiotic", 1_320_000, 0),
    (4, "Paracetamol 500 mg tablets", "analgesic", 210_000, 0),
    (5, "Ibuprofen 400 mg tablets", "analgesic", 340_000, 0),
    (6, "Atorvastatin 20 mg tablets", "cardiovascular", 760_000, 0),
    (7, "Losartan 50 mg tablets", "cardiovascular", 540_000, 0),
    (8, "Metformin 500 mg tablets", "diabetes", 290_000, 0),
    (9, "Insulin glargine 100 U/mL pen", "diabetes", 9_800_000, 1),
    (10, "Influenza vaccine 2026/27", "vaccine", 6_200_000, 1),
    (11, "Hepatitis B vaccine", "vaccine", 4_100_000, 1),
    (12, "Adalimumab 40 mg prefilled syringe", "biologic", 78_000_000, 1),
]

CUSTOMERS = [
    (1, "Narges Pharmacy", "pharmacy", "Tehran", 600_000_000),
    (2, "Azadi Pharmacy", "pharmacy", "Tehran", 450_000_000),
    (3, "Shafa Pharmacy", "pharmacy", "Tehran", 500_000_000),
    (4, "Bahar Pharmacy", "pharmacy", "Isfahan", 400_000_000),
    (5, "Sepid Pharmacy", "pharmacy", "Shiraz", 400_000_000),
    (6, "Danesh Pharmacy", "pharmacy", "Mashhad", 350_000_000),
    (7, "Roshan Pharmacy", "pharmacy", "Tabriz", 350_000_000),
    (8, "Alborz General Hospital", "hospital", "Tehran", 8_000_000_000),
    (9, "Zagros Hospital", "hospital", "Shiraz", 5_000_000_000),
    (10, "Sahand Hospital", "hospital", "Tabriz", 4_000_000_000),
    (11, "Toos Hospital", "hospital", "Mashhad", 4_500_000_000),
    (12, "Pardis Clinic", "clinic", "Tehran", 1_200_000_000),
    (13, "Naghsh Clinic", "clinic", "Isfahan", 800_000_000),
    (14, "Arg Clinic", "clinic", "Shiraz", 700_000_000),
    (15, "Mehrgan Clinic", "clinic", "Mashhad", 700_000_000),
]

FIRST_DAY, LAST_DAY = date(2026, 1, 1), date(2026, 9, 30)
ORDERS_PER_CUSTOMER = {"pharmacy": (14, 22), "clinic": (10, 16), "hospital": (22, 30)}
PACKS_PER_LINE = {"pharmacy": (5, 40), "clinic": (5, 30), "hospital": (20, 120)}
HOSPITAL_DISCOUNT = 0.05


def generate_rows(seed: int = 2026) -> tuple[list[tuple], list[tuple]]:
    """Return (orders, order_items) rows, ordered by date and numbered from 1001."""
    rng = random.Random(seed)
    day_count = (LAST_DAY - FIRST_DAY).days + 1
    drafts = []

    for customer_id, _, customer_type, _, _ in CUSTOMERS:
        for _ in range(rng.randint(*ORDERS_PER_CUSTOMER[customer_type])):
            order_date = FIRST_DAY + timedelta(days=rng.randrange(day_count))
            status = rng.choices(["delivered", "returned", "cancelled"], weights=[90, 6, 4])[0]

            if status == "delivered":
                age_days = (LAST_DAY - order_date).days
                unpaid_probability = 0.6 if age_days < 60 else 0.05
                payment_status = "unpaid" if rng.random() < unpaid_probability else "paid"
            else:
                payment_status = "not_applicable"

            # Biologics are hospital-only medicines.
            eligible = [p for p in PRODUCTS if p[2] != "biologic" or customer_type == "hospital"]
            lines = []
            for product_id, _, category, list_price, cold_chain in rng.sample(eligible, k=rng.randint(1, 4)):
                low, high = PACKS_PER_LINE[customer_type]
                if category == "biologic":
                    low, high = 1, 6
                elif cold_chain:
                    high = max(low, high // 4)
                discount = HOSPITAL_DISCOUNT if customer_type == "hospital" else 0.0
                lines.append((product_id, rng.randint(low, high), round(list_price * (1 - discount))))

            drafts.append((order_date, customer_id, status, payment_status, lines))

    drafts.sort(key=lambda d: (d[0], d[1]))
    orders, items = [], []
    for order_id, (order_date, customer_id, status, payment_status, lines) in enumerate(drafts, start=1001):
        orders.append((order_id, customer_id, order_date.isoformat(), status, payment_status))
        for product_id, quantity, unit_price in lines:
            items.append((len(items) + 1, order_id, product_id, quantity, unit_price))
    return orders, items


def build_database(path: Path, force: bool = False) -> bool:
    """Create the database at `path`."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    orders, items = generate_rows()
    with sqlite3.connect(tmp_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", PRODUCTS)
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", CUSTOMERS)
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)
    conn.close()
    tmp_path.replace(path)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create the sample SQLite database.")
    parser.add_argument("--force", action="store_true", help="overwrite an existing database")
    target = get_settings().database_path
    created = build_database(target, force=parser.parse_args().force)
    print(("created " if created else "already exists (use --force): ") + str(target))
