"""
seed_library.py — Seed the library_db PostgreSQL database with realistic dummy data.

Reads connection details from environment variables:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

Falls back to parsing DATABASE_URL from .env if those vars are not set.

Usage:
    pip install psycopg2-binary faker python-dotenv
    export DB_HOST=localhost DB_PORT=5432 DB_NAME=library_db \
           DB_USER=library_db DB_PASSWORD=library_db
    python seed_library.py
"""

from __future__ import annotations

import argparse
import os
import sys
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Faker setup
# ---------------------------------------------------------------------------

try:
    from faker import Faker
except ImportError:
    sys.exit("Install faker first:  pip install faker")

SEED = 42
random.seed(SEED)
fake = Faker(["en_IN", "en_US", "en_GB"])
fake.seed_instance(SEED)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_dsn() -> dict:
    """Build psycopg2 connect-kwargs from env vars or fall back to DATABASE_URL."""
    if os.environ.get("DB_HOST"):
        return dict(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from dotenv import dotenv_values
            url = dotenv_values(".env").get("DATABASE_URL", "")
        except ImportError:
            pass
    if not url:
        sys.exit(
            "Set DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD "
            "or DATABASE_URL in environment / .env"
        )
    # Strip SQLAlchemy dialect prefix
    for prefix in (
        "postgresql+psycopg://", "postgresql+psycopg2://",
        "postgresql://", "postgres://",
    ):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return {"dsn": url}


def connect() -> psycopg2.extensions.connection:
    kwargs = _get_dsn()
    try:
        conn = psycopg2.connect(**kwargs)
        conn.autocommit = False
        return conn
    except psycopg2.Error as exc:
        sys.exit(f"Cannot connect to database: {exc}")


# ---------------------------------------------------------------------------
# Schema inspection
# ---------------------------------------------------------------------------

def inspect_schema(cur) -> dict[str, list[dict]]:
    cur.execute("""
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)
    schema: dict[str, list[dict]] = defaultdict(list)
    for table, col, dtype, nullable, default in cur.fetchall():
        schema[table].append(
            dict(name=col, type=dtype, nullable=(nullable == "YES"), default=default)
        )
    return dict(schema)


def print_schema_summary(schema: dict[str, list[dict]]) -> None:
    print("\n" + "=" * 60)
    print("SCHEMA SUMMARY")
    print("=" * 60)
    for table, cols in sorted(schema.items()):
        print(f"\n  TABLE: {table}")
        for c in cols:
            nn = "" if c["nullable"] else " NOT NULL"
            df = f"  default={c['default']}" if c["default"] else ""
            print(f"    {c['name']}: {c['type']}{nn}{df}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Re-run safety and reset
# ---------------------------------------------------------------------------

ALL_TABLES = [
    "book_purchases", "fines", "loans", "book_copies", "book_authors",
    "books", "staff", "members", "authors", "publishers", "branches", "categories",
]


def table_row_count(cur, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def should_seed(cur, table: str) -> bool:
    n = table_row_count(cur, table)
    if n > 0:
        print(f"  [SKIP] {table} already has {n} rows — leaving untouched.")
        return False
    return True


def truncate_tables(cur) -> None:
    """Truncate all library tables in cascade order and restart identity sequences."""
    print("  [TRUNCATE] Truncating all library tables and restarting IDs …")
    cur.execute(f"TRUNCATE TABLE {', '.join(ALL_TABLES)} RESTART IDENTITY CASCADE;")
    print("  [OK] All tables truncated successfully.")


# ---------------------------------------------------------------------------
# CREATE book_purchases (uses existing PK/FK naming conventions)
# ---------------------------------------------------------------------------

_CREATE_BOOK_PURCHASES = """
CREATE TABLE IF NOT EXISTS book_purchases (
    purchase_id    SERIAL PRIMARY KEY,
    member_id      INTEGER       NOT NULL REFERENCES members(member_id),
    book_id        INTEGER       NOT NULL REFERENCES books(book_id),
    branch_id      INTEGER       NOT NULL REFERENCES branches(branch_id),
    purchase_date  DATE          NOT NULL,
    quantity       INTEGER       NOT NULL CHECK (quantity BETWEEN 1 AND 5),
    unit_price     NUMERIC(8,2)  NOT NULL CHECK (unit_price > 0),
    total_amount   NUMERIC(10,2) NOT NULL
        CHECK (total_amount = quantity * unit_price),
    payment_status VARCHAR(20)   NOT NULL DEFAULT 'paid'
        CHECK (payment_status IN ('paid', 'pending', 'refunded'))
);
"""


def create_book_purchases_table(cur) -> None:
    cur.execute(_CREATE_BOOK_PURCHASES)
    print("  [OK] book_purchases table created (or already existed).")


# ---------------------------------------------------------------------------
# Static reference data (mirrors real-world variety for group-by queries)
# ---------------------------------------------------------------------------

CATEGORIES = [
    "Fiction", "Non-Fiction", "Science & Technology", "History",
    "Biography", "Children", "Mystery & Thriller", "Self-Help",
    "Philosophy", "Psychology", "Poetry", "Romance",
    "Science Fiction", "Fantasy", "Graphic Novels", "True Crime",
    "Business & Economics", "Health & Wellness", "Travel", "Art & Photography",
    "Cookbooks & Culinary", "Classics", "Horror", "Drama & Theatre",
    "Politics & Society", "Religion & Spirituality", "Education", "Law & Criminology",
    "Music & Performing Arts", "Sports & Fitness", "Environmental Studies",
]

BRANCH_DATA = [
    ("Central Library",    "12 MG Road, Mumbai",         "022-41234567"),
    ("Andheri Branch",     "45 Versova Lane, Andheri",   "022-41234568"),
    ("Pune City Branch",   "7 FC Road, Pune",             "020-41234569"),
    ("Delhi North Branch", "33 Rohini Sector 8, Delhi",   "011-41234570"),
    ("Bangalore Tech Hub", "88 Koramangala 4th Block",    "080-41234571"),
    ("Chennai Central",    "5 Anna Salai, Chennai",       "044-41234572"),
]

PUBLISHER_NAMES = [
    "Penguin Random House", "HarperCollins India", "Rupa Publications",
    "Westland Books", "Pan Macmillan", "Oxford University Press",
    "Bloomsbury Publishing", "Hachette India", "Simon & Schuster",
    "Aleph Book Company", "Juggernaut Books", "Scholastic India",
    "Jaico Publishing", "Fingerprint! Publishing", "Notion Press",
    "Macmillan Publishers", "Sage Publications", "Tata McGraw-Hill",
    "Wiley India", "Elsevier", "Cambridge University Press",
    "Harper Perennial", "Vintage Books", "Picador", "Anchor Books",
    "Farrar Straus Giroux", "Knopf", "Little Brown", "Torchlight",
    "Speaking Tiger",
]

AUTHOR_PAIRS = [
    ("Arundhati", "Roy"),      ("Vikram", "Seth"),
    ("Amitav", "Ghosh"),       ("Chetan", "Bhagat"),
    ("R.K.", "Narayan"),       ("Jhumpa", "Lahiri"),
    ("Ruskin", "Bond"),        ("Anita", "Desai"),
    ("Kiran", "Desai"),        ("Rohinton", "Mistry"),
    ("Salman", "Rushdie"),     ("Shashi", "Tharoor"),
    ("Devdutt", "Pattanaik"),  ("Sudha", "Murty"),
    ("Preeti", "Shenoy"),      ("Ravinder", "Singh"),
    ("Durjoy", "Datta"),       ("Amish", "Tripathi"),
    ("Stephen", "King"),       ("J.K.", "Rowling"),
    ("George", "Orwell"),      ("Gabriel", "Garcia Marquez"),
    ("Haruki", "Murakami"),    ("Kazuo", "Ishiguro"),
    ("Chimamanda", "Adichie"), ("Colm", "Toibin"),
    ("Ian", "McEwan"),         ("Zadie", "Smith"),
    ("Aravind", "Adiga"),      ("Pankaj", "Mishra"),
]

STAFF_ROLES = [
    "Branch Manager", "Senior Librarian", "Librarian",
    "Assistant Librarian", "Cataloguer", "Reference Specialist",
    "Circulation Desk Staff", "IT Support",
]

BOOK_TITLES = [
    "The God of Small Things", "A Suitable Boy", "The Shadow Lines",
    "2 States", "Malgudi Days", "The Namesake", "The Room on the Roof",
    "Clear Light of Day", "The Inheritance of Loss", "A Fine Balance",
    "Midnight's Children", "The Great Indian Novel", "Jaya",
    "How I Taught My Grandmother to Read", "The Story of My Assassins",
    "The Immortals of Meluha", "It", "Harry Potter and the Sorcerers Stone",
    "Nineteen Eighty-Four", "One Hundred Years of Solitude",
    "Norwegian Wood", "The Remains of the Day", "Purple Hibiscus",
    "The Master", "Atonement", "White Teeth", "The White Tiger",
    "The Reluctant Fundamentalist", "Train to Pakistan", "The Argumentative Indian",
    "Shantaram", "The Palace of Illusions", "The Alchemist", "Siddhartha",
    "Life of Pi", "Interpreter of Maladies", "An Equal Music",
    "The Space Between Us", "Slumdog Millionaire", "Delhi A Novel",
    "The Hungry Tide", "Ramayana Retold", "The Mahabharata Secret",
    "Scion of Ikshvaku", "I Too Had a Love Story",
]

LOAN_PERIOD_DAYS = 14
DAILY_FINE = Decimal("5.00")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _random_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

def seed_categories(cur) -> None:
    if not should_seed(cur, "categories"):
        return
    rows = [{"name": c} for c in CATEGORIES]
    psycopg2.extras.execute_batch(
        cur, "INSERT INTO categories (name) VALUES (%(name)s)", rows
    )
    print(f"  [OK] categories — {len(rows)} rows inserted.")


def seed_branches(cur) -> None:
    if not should_seed(cur, "branches"):
        return
    rows = [{"name": n, "address": a, "phone": p} for n, a, p in BRANCH_DATA]
    psycopg2.extras.execute_batch(
        cur,
        "INSERT INTO branches (name, address, phone) VALUES (%(name)s, %(address)s, %(phone)s)",
        rows,
    )
    print(f"  [OK] branches — {len(rows)} rows inserted.")


def seed_publishers(cur) -> None:
    if not should_seed(cur, "publishers"):
        return
    rows = [{"name": n, "email": fake.company_email()} for n in PUBLISHER_NAMES]
    psycopg2.extras.execute_batch(
        cur,
        "INSERT INTO publishers (name, email) VALUES (%(name)s, %(email)s)",
        rows,
    )
    print(f"  [OK] publishers — {len(rows)} rows inserted.")


def seed_authors(cur) -> None:
    if not should_seed(cur, "authors"):
        return
    rows = [
        {
            "author_name": f"{first} {last}",
            "last_name": last,
            "bio": fake.paragraph(nb_sentences=2),
        }
        for first, last in AUTHOR_PAIRS
    ]
    psycopg2.extras.execute_batch(
        cur,
        "INSERT INTO authors (author_name, last_name, bio) VALUES (%(author_name)s, %(last_name)s, %(bio)s)",
        rows,
    )
    print(f"  [OK] authors — {len(rows)} rows inserted.")


def seed_members(cur) -> None:
    if not should_seed(cur, "members"):
        return
    emails_used: set[str] = set()
    rows = []
    for _ in range(45):
        first = fake.first_name()
        last  = fake.last_name()
        for _ in range(20):
            email = (
                f"{first.lower().replace(' ', '')}"
                f".{last.lower().replace(' ', '')}"
                f"{random.randint(1, 9999)}@{fake.free_email_domain()}"
            )
            if email not in emails_used:
                emails_used.add(email)
                break
        joined = _random_date(date(2020, 1, 1), date(2024, 6, 30))
        status = random.choices(
            ["Active", "Suspended", "Expired"], weights=[80, 10, 10]
        )[0]
        rows.append(dict(
            first_name=first, last_name=last,
            email=email,
            phone=fake.phone_number()[:28],
            joined_date=joined,
            status=status,
        ))
    psycopg2.extras.execute_batch(
        cur,
        """INSERT INTO members (first_name, last_name, email, phone, joined_date, status)
           VALUES (%(first_name)s, %(last_name)s, %(email)s, %(phone)s, %(joined_date)s, %(status)s)""",
        rows,
    )
    print(f"  [OK] members — {len(rows)} rows inserted.")


def seed_staff(cur, branch_ids: list[int]) -> None:
    if not should_seed(cur, "staff"):
        return
    rows = []
    for branch_id in branch_ids:
        rows.append(dict(
            first_name=fake.first_name(), last_name=fake.last_name(),
            role="Branch Manager", branch_id=branch_id,
        ))
        for _ in range(random.randint(2, 4)):
            rows.append(dict(
                first_name=fake.first_name(), last_name=fake.last_name(),
                role=random.choice(STAFF_ROLES[2:]),
                branch_id=branch_id,
            ))
    while len(rows) < 30:
        rows.append(dict(
            first_name=fake.first_name(), last_name=fake.last_name(),
            role=random.choice(STAFF_ROLES),
            branch_id=random.choice(branch_ids),
        ))
    psycopg2.extras.execute_batch(
        cur,
        "INSERT INTO staff (first_name, last_name, role, branch_id) VALUES (%(first_name)s, %(last_name)s, %(role)s, %(branch_id)s)",
        rows,
    )
    print(f"  [OK] staff — {len(rows)} rows inserted.")


def seed_books(cur, publisher_ids: list[int], category_ids: list[int]) -> None:
    if not should_seed(cur, "books"):
        return
    isbns_used: set[str] = set()
    titles_used: list[str] = list(BOOK_TITLES)
    random.shuffle(titles_used)
    rows = []
    for i in range(45):
        title = titles_used[i] if i < len(titles_used) else fake.sentence(nb_words=4).rstrip(".")
        for _ in range(30):
            isbn = fake.isbn13(separator="")[:20]
            if isbn not in isbns_used:
                isbns_used.add(isbn)
                break
        rows.append(dict(
            isbn=isbn,
            title=title,
            publication_year=random.randint(1990, 2024),
            publisher_id=random.choice(publisher_ids),
            category_id=random.choice(category_ids),
        ))
    psycopg2.extras.execute_batch(
        cur,
        """INSERT INTO books (isbn, title, publication_year, publisher_id, category_id)
           VALUES (%(isbn)s, %(title)s, %(publication_year)s, %(publisher_id)s, %(category_id)s)""",
        rows,
    )
    print(f"  [OK] books — {len(rows)} rows inserted.")


def seed_book_authors(cur, book_ids: list[int], author_ids: list[int]) -> None:
    if not should_seed(cur, "book_authors"):
        return
    pairs: set[tuple[int, int]] = set()
    for book_id in book_ids:
        n = random.randint(1, 2)
        for author_id in random.sample(author_ids, min(n, len(author_ids))):
            pairs.add((book_id, author_id))
    # Ensure every author has at least one book
    for author_id in author_ids:
        if not any(a == author_id for _, a in pairs):
            pairs.add((random.choice(book_ids), author_id))
    # Pad toward 70 rows
    all_combos = [(b, a) for b in book_ids for a in author_ids]
    random.shuffle(all_combos)
    for combo in all_combos:
        if len(pairs) >= 70:
            break
        pairs.add(combo)
    rows = [{"book_id": b, "author_id": a} for b, a in pairs]
    psycopg2.extras.execute_batch(
        cur,
        "INSERT INTO book_authors (book_id, author_id) VALUES (%(book_id)s, %(author_id)s)",
        rows,
    )
    print(f"  [OK] book_authors — {len(rows)} rows inserted.")


def seed_book_copies(cur, book_ids: list[int], branch_ids: list[int]) -> None:
    if not should_seed(cur, "book_copies"):
        return
    rows = []
    for book_id in book_ids:
        for _ in range(random.randint(1, 4)):
            rows.append(dict(
                book_id=book_id,
                branch_id=random.choice(branch_ids),
                status=random.choices(
                    ["Available", "Checked Out", "Lost", "Maintenance"],
                    weights=[65, 20, 5, 10],
                )[0],
            ))
    while len(rows) < 30:
        rows.append(dict(
            book_id=random.choice(book_ids),
            branch_id=random.choice(branch_ids),
            status="Available",
        ))
    psycopg2.extras.execute_batch(
        cur,
        "INSERT INTO book_copies (book_id, branch_id, status) VALUES (%(book_id)s, %(branch_id)s, %(status)s)",
        rows,
    )
    print(f"  [OK] book_copies — {len(rows)} rows inserted.")


def seed_loans(
    cur,
    copy_ids: list[int],
    member_ids: list[int],
    staff_ids: list[int],
) -> list[tuple]:
    if not should_seed(cur, "loans"):
        return []
    today = date.today()
    rows: list[dict] = []
    outcomes: list[str] = []
    active_copies: set[int] = set()
    attempts = 0
    while len(rows) < 80 and attempts < 600:
        attempts += 1
        copy_id   = random.choice(copy_ids)
        member_id = random.choice(member_ids)
        staff_id  = random.choice(staff_ids)
        issue = _random_date(date(2023, 1, 1), today - timedelta(days=1))
        due   = issue + timedelta(days=LOAN_PERIOD_DAYS)
        outcome = random.choices(
            ["returned_on_time", "returned_late", "still_out", "overdue"],
            weights=[45, 20, 20, 15],
        )[0]
        if outcome in ("still_out", "overdue"):
            if copy_id in active_copies:
                continue
            active_copies.add(copy_id)
            return_date = None
        elif outcome == "returned_on_time":
            return_date = _random_date(issue + timedelta(days=1), due)
        else:
            return_date = _random_date(due + timedelta(days=1), due + timedelta(days=30))
        rows.append(dict(
            copy_id=copy_id,
            member_id=member_id,
            staff_id=staff_id,
            issue_date=issue,
            due_date=due,
            return_date=return_date,
        ))
        outcomes.append(outcome)
    psycopg2.extras.execute_batch(
        cur,
        """INSERT INTO loans (copy_id, member_id, staff_id, issue_date, due_date, return_date)
           VALUES (%(copy_id)s, %(member_id)s, %(staff_id)s, %(issue_date)s, %(due_date)s, %(return_date)s)""",
        rows,
    )
    print(f"  [OK] loans — {len(rows)} rows inserted.")
    cur.execute("SELECT loan_id, due_date, return_date FROM loans ORDER BY loan_id")
    loan_rows = cur.fetchall()
    return list(zip(
        [r[0] for r in loan_rows],
        outcomes,
        [r[1] for r in loan_rows],
        [r[2] for r in loan_rows],
    ))


def seed_fines(cur, loan_info: list[tuple]) -> None:
    if not should_seed(cur, "fines"):
        return
    today = date.today()
    seen_loans: set[int] = set()
    rows = []
    for loan_id, outcome, due_date, return_date in loan_info:
        if loan_id in seen_loans:
            continue
        if outcome == "returned_late" and return_date:
            days_late = (return_date - due_date).days
            if days_late <= 0:
                continue
            amount = DAILY_FINE * days_late
            status = random.choice(["Paid", "Unpaid"])
        elif outcome == "overdue":
            days_late = (today - due_date).days
            if days_late <= 0:
                continue
            amount = DAILY_FINE * days_late
            status = "Unpaid"
        else:
            continue
        seen_loans.add(loan_id)
        rows.append(dict(loan_id=loan_id, amount=str(amount), status=status))
    if rows:
        psycopg2.extras.execute_batch(
            cur,
            "INSERT INTO fines (loan_id, amount, status) VALUES (%(loan_id)s, %(amount)s, %(status)s)",
            rows,
        )
    print(f"  [OK] fines — {len(rows)} rows inserted.")


def seed_book_purchases(
    cur,
    member_ids: list[int],
    book_ids: list[int],
    branch_ids: list[int],
    member_joined: dict[int, date],
) -> None:
    if not should_seed(cur, "book_purchases"):
        return
    today = date.today()
    rows = []
    attempts = 0
    while len(rows) < 80 and attempts < 600:
        attempts += 1
        member_id = random.choice(member_ids)
        book_id   = random.choice(book_ids)
        branch_id = random.choice(branch_ids)
        earliest  = member_joined.get(member_id, date(2022, 1, 1))
        purchase_date = _random_date(max(earliest, date(2022, 11, 1)), today)
        quantity      = random.randint(1, 5)
        unit_price    = Decimal(str(round(random.uniform(150.0, 1500.0), 2)))
        total_amount  = (unit_price * quantity).quantize(Decimal("0.01"))
        payment_status = random.choices(
            ["paid", "pending", "refunded"], weights=[75, 15, 10]
        )[0]
        rows.append(dict(
            member_id=member_id,
            book_id=book_id,
            branch_id=branch_id,
            purchase_date=purchase_date,
            quantity=quantity,
            unit_price=str(unit_price),
            total_amount=str(total_amount),
            payment_status=payment_status,
        ))
    psycopg2.extras.execute_batch(
        cur,
        """INSERT INTO book_purchases
               (member_id, book_id, branch_id, purchase_date,
                quantity, unit_price, total_amount, payment_status)
           VALUES
               (%(member_id)s, %(book_id)s, %(branch_id)s, %(purchase_date)s,
                %(quantity)s, %(unit_price)s, %(total_amount)s, %(payment_status)s)""",
        rows,
    )
    print(f"  [OK] book_purchases — {len(rows)} rows inserted.")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _run_query(cur, label: str, sql: str) -> None:
    print(f"\n--- {label} ---")
    cur.execute(sql)
    if cur.description is None:
        print("  (no result set)")
        return
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        print("  (no rows)")
        return
    widths = [
        max(len(str(c)), max((len(str(r[i])) for r in rows), default=0))
        for i, c in enumerate(cols)
    ]
    header = "  " + "  |  ".join(str(c).ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        print("  " + "  |  ".join(str(v).ljust(w) for v, w in zip(row, widths)))


def verify(cur) -> None:
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # Row counts
    print("\n--- Row counts (minimum 30 expected) ---")
    tables = [
        "authors", "book_authors", "book_copies", "book_purchases",
        "books", "branches", "categories", "fines", "loans",
        "members", "publishers", "staff",
    ]
    for tbl in tables:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        n = cur.fetchone()[0]
        min_expected = 6 if tbl == "branches" else 30
        flag = "OK " if n >= min_expected else "LOW"
        print(f"  [{flag}] {tbl}: {n} rows")

    # FK violations
    print("\n--- Foreign key violations (should all be 0) ---")
    fk_checks = [
        ("book_authors.book_id",     "SELECT COUNT(*) FROM book_authors ba LEFT JOIN books b ON ba.book_id=b.book_id WHERE b.book_id IS NULL"),
        ("book_authors.author_id",   "SELECT COUNT(*) FROM book_authors ba LEFT JOIN authors a ON ba.author_id=a.author_id WHERE a.author_id IS NULL"),
        ("book_copies.book_id",      "SELECT COUNT(*) FROM book_copies bc LEFT JOIN books b ON bc.book_id=b.book_id WHERE b.book_id IS NULL"),
        ("book_copies.branch_id",    "SELECT COUNT(*) FROM book_copies bc LEFT JOIN branches br ON bc.branch_id=br.branch_id WHERE br.branch_id IS NULL"),
        ("books.publisher_id",       "SELECT COUNT(*) FROM books b LEFT JOIN publishers p ON b.publisher_id=p.publisher_id WHERE p.publisher_id IS NULL"),
        ("books.category_id",        "SELECT COUNT(*) FROM books b LEFT JOIN categories c ON b.category_id=c.category_id WHERE c.category_id IS NULL"),
        ("fines.loan_id",            "SELECT COUNT(*) FROM fines f LEFT JOIN loans l ON f.loan_id=l.loan_id WHERE l.loan_id IS NULL"),
        ("loans.copy_id",            "SELECT COUNT(*) FROM loans l LEFT JOIN book_copies bc ON l.copy_id=bc.copy_id WHERE bc.copy_id IS NULL"),
        ("loans.member_id",          "SELECT COUNT(*) FROM loans l LEFT JOIN members m ON l.member_id=m.member_id WHERE m.member_id IS NULL"),
        ("loans.staff_id",           "SELECT COUNT(*) FROM loans l LEFT JOIN staff s ON l.staff_id=s.staff_id WHERE s.staff_id IS NULL"),
        ("staff.branch_id",          "SELECT COUNT(*) FROM staff s LEFT JOIN branches b ON s.branch_id=b.branch_id WHERE b.branch_id IS NULL"),
        ("purchases.member_id",      "SELECT COUNT(*) FROM book_purchases bp LEFT JOIN members m ON bp.member_id=m.member_id WHERE m.member_id IS NULL"),
        ("purchases.book_id",        "SELECT COUNT(*) FROM book_purchases bp LEFT JOIN books b ON bp.book_id=b.book_id WHERE b.book_id IS NULL"),
        ("purchases.branch_id",      "SELECT COUNT(*) FROM book_purchases bp LEFT JOIN branches br ON bp.branch_id=br.branch_id WHERE br.branch_id IS NULL"),
    ]
    all_clean = True
    for label, sql in fk_checks:
        cur.execute(sql)
        n = cur.fetchone()[0]
        status = "OK  " if n == 0 else "FAIL"
        print(f"  [{status}] {label}: {n} orphan rows")
        if n:
            all_clean = False
    if all_clean:
        print("  All FK references are valid.")

    # Sanity queries
    _run_query(cur, "Top 5 members by total purchase amount",
        """SELECT m.first_name || ' ' || m.last_name AS member,
                  SUM(bp.total_amount) AS total_spent
           FROM book_purchases bp
           JOIN members m ON bp.member_id = m.member_id
           GROUP BY m.member_id, m.first_name, m.last_name
           ORDER BY total_spent DESC
           LIMIT 5""")

    _run_query(cur, "Books purchased per category",
        """SELECT c.name AS category, COUNT(bp.purchase_id) AS purchases
           FROM book_purchases bp
           JOIN books b ON bp.book_id = b.book_id
           JOIN categories c ON b.category_id = c.category_id
           GROUP BY c.name
           ORDER BY purchases DESC""")

    _run_query(cur, "Authors with the most books purchased",
        """SELECT a.author_name, COUNT(bp.purchase_id) AS purchases
           FROM book_purchases bp
           JOIN books b       ON bp.book_id   = b.book_id
           JOIN book_authors ba ON b.book_id  = ba.book_id
           JOIN authors a      ON ba.author_id = a.author_id
           GROUP BY a.author_id, a.author_name
           ORDER BY purchases DESC
           LIMIT 10""")

    _run_query(cur, "Overdue loans with unpaid fines",
        """SELECT l.loan_id,
                  m.first_name || ' ' || m.last_name AS member,
                  l.due_date,
                  COALESCE(f.amount::text, 'no fine') AS fine_amount,
                  COALESCE(f.status, 'n/a')           AS fine_status
           FROM loans l
           JOIN members m ON l.member_id = m.member_id
           LEFT JOIN fines f ON l.loan_id = f.loan_id
           WHERE l.return_date IS NULL
             AND l.due_date < CURRENT_DATE
           ORDER BY l.due_date
           LIMIT 15""")

    _run_query(cur, "Total purchases per branch per month (last 6 months)",
        """SELECT br.name AS branch,
                  TO_CHAR(DATE_TRUNC('month', bp.purchase_date), 'YYYY-MM') AS month,
                  COUNT(*)              AS purchases,
                  SUM(bp.total_amount)  AS revenue
           FROM book_purchases bp
           JOIN branches br ON bp.branch_id = br.branch_id
           WHERE bp.purchase_date >= CURRENT_DATE - INTERVAL '6 months'
           GROUP BY br.name, DATE_TRUNC('month', bp.purchase_date)
           ORDER BY branch, month""")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the library_db PostgreSQL database.")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate all tables and re-seed from scratch (never deletes data silently).",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip interactive confirmation when truncating.",
    )
    args = parser.parse_args()

    print("Connecting to database …")
    conn = connect()
    cur  = conn.cursor()

    print("\nStep 1 — Inspecting schema …")
    schema = inspect_schema(cur)
    print_schema_summary(schema)

    print("Step 2 — Creating book_purchases table …")
    create_book_purchases_table(cur)

    # Check for truncate or existing rows
    has_existing = any(table_row_count(cur, t) > 0 for t in ALL_TABLES)
    if args.truncate:
        truncate_tables(cur)
    elif has_existing and sys.stdin.isatty() and not args.yes:
        try:
            answer = input("\nExisting data detected. Would you like to truncate and re-seed from scratch? [y/N]: ").strip().lower()
            if answer in ("y", "yes"):
                truncate_tables(cur)
        except EOFError:
            pass

    print("\nStep 3 — Seeding tables …")
    try:
        # Parents first (no FK dependencies)
        seed_categories(cur)
        seed_branches(cur)
        seed_publishers(cur)
        seed_authors(cur)
        seed_members(cur)

        # Fetch generated IDs
        cur.execute("SELECT category_id  FROM categories  ORDER BY category_id")
        category_ids = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT branch_id    FROM branches    ORDER BY branch_id")
        branch_ids = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT publisher_id FROM publishers  ORDER BY publisher_id")
        publisher_ids = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT author_id    FROM authors     ORDER BY author_id")
        author_ids = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT member_id, joined_date FROM members ORDER BY member_id")
        member_rows = cur.fetchall()
        member_ids  = [r[0] for r in member_rows]
        member_joined: dict[int, date] = {r[0]: r[1] for r in member_rows}

        # FK children of the above
        seed_staff(cur, branch_ids)
        cur.execute("SELECT staff_id FROM staff ORDER BY staff_id")
        staff_ids = [r[0] for r in cur.fetchall()]

        seed_books(cur, publisher_ids, category_ids)
        cur.execute("SELECT book_id FROM books ORDER BY book_id")
        book_ids = [r[0] for r in cur.fetchall()]

        seed_book_authors(cur, book_ids, author_ids)

        seed_book_copies(cur, book_ids, branch_ids)
        cur.execute("SELECT copy_id FROM book_copies ORDER BY copy_id")
        copy_ids = [r[0] for r in cur.fetchall()]

        # Loans & fines
        loan_info = seed_loans(cur, copy_ids, member_ids, staff_ids)
        if loan_info:
            seed_fines(cur, loan_info)
        else:
            print("  [SKIP] fines — loans table was already populated, skipping.")

        # Purchases
        seed_book_purchases(cur, member_ids, book_ids, branch_ids, member_joined)

        conn.commit()
        print("\nAll data committed successfully.")

    except Exception as exc:
        conn.rollback()
        print(f"\n[ERROR] Transaction rolled back: {exc}")
        raise

    print("\nStep 5 — Verifying …")
    verify(cur)

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()

