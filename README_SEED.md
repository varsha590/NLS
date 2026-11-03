# Seeding Guide: Library DB (`library_db`)

This guide explains how to use `seed_library.py` to inspect the PostgreSQL `library_db` database, create the `book_purchases` table, seed realistic data across all tables, and verify referential integrity and sanity queries.

---

## 1. Prerequisites & Dependencies

Activate your virtual environment and install the required packages:

```bash
source .venv/bin/activate
pip install psycopg2-binary faker python-dotenv
```

---

## 2. Database Connection Configuration

`seed_library.py` looks for database connection parameters in two ways:

1. **Explicit Environment Variables**:
   ```bash
   export DB_HOST=localhost
   export DB_PORT=5432
   export DB_NAME=library_db
   export DB_USER=library_db
   export DB_PASSWORD=library_db
   ```

2. **`.env` File Fallback**:
   If the individual variables are not set, it reads `DATABASE_URL` from `.env` in the current working directory:
   ```env
   DATABASE_URL=postgresql://library_db:library_db@localhost:5432/library_db
   ```
   *(SQLAlchemy dialect prefixes like `postgresql+psycopg://` are automatically detected and parsed).*

---

## 3. Schema & `book_purchases` Table

`seed_library.py` operates on the following 12 tables:
- **Core / Parent Tables**: `categories`, `branches`, `publishers`, `authors`, `members`
- **Dependent / Child Tables**: `staff`, `books`, `book_authors`, `book_copies`, `loans`, `fines`
- **Purchases Table**: `book_purchases`

### `book_purchases` DDL
```sql
CREATE TABLE IF NOT EXISTS book_purchases (
    purchase_id    SERIAL PRIMARY KEY,
    member_id      INTEGER       NOT NULL REFERENCES members(member_id),
    book_id        INTEGER       NOT NULL REFERENCES books(book_id),
    branch_id      INTEGER       NOT NULL REFERENCES branches(branch_id),
    purchase_date  DATE          NOT NULL,
    quantity       INTEGER       NOT NULL CHECK (quantity BETWEEN 1 AND 5),
    unit_price     NUMERIC(8,2)  NOT NULL CHECK (unit_price > 0),
    total_amount   NUMERIC(10,2) NOT NULL CHECK (total_amount = quantity * unit_price),
    payment_status VARCHAR(20)   NOT NULL DEFAULT 'paid'
        CHECK (payment_status IN ('paid', 'pending', 'refunded'))
);

CREATE INDEX IF NOT EXISTS idx_bp_member   ON book_purchases(member_id);
CREATE INDEX IF NOT EXISTS idx_bp_book     ON book_purchases(book_id);
CREATE INDEX IF NOT EXISTS idx_bp_branch   ON book_purchases(branch_id);
CREATE INDEX IF NOT EXISTS idx_bp_pdate    ON book_purchases(purchase_date);
```

---

## 4. How to Run

### Safe Execution (Default: skips populated tables)
```bash
python seed_library.py
```
- If tables are empty, it creates `book_purchases` and seeds all tables.
- If tables already have data, it skips existing tables to preserve your data.
- If run in an interactive terminal when tables already have data, it prompts you before truncating.

### Truncate & Reseed (Clean Slate)
To reset all tables and generate a fresh, reproducible dataset with fixed seed (`SEED = 42`):
```bash
python seed_library.py --truncate
```
*(Use `-y` or `--yes` to skip any prompts).*

---

## 5. Seed Volumes & Realism Rules

| Table | Target Count | Realism Rules |
| :--- | :--- | :--- |
| `categories` | 31 | Curated genre variety (Fiction, History, Sci-Fi, etc.) |
| `branches` | 6 | Standard city library branches with addresses and phones |
| `publishers` | 30 | Major Indian and international publishers |
| `authors` | 30 | Renowned author names (mix of Indian and international) |
| `members` | 45 | Realistic names, emails, phones, join dates from 2020-2024 |
| `staff` | 30+ | Branch managers + librarian/support staff mapped to branches |
| `books` | 45 | Real book titles, ISBNs, publication years, category/publisher FKs |
| `book_authors` | 70 | 1-2 authors per book; every author has >= 1 book |
| `book_copies` | ~100 | 1-4 copies per book with conditions (`Available`, `Checked Out`, etc.) |
| `loans` | 80 | Issue dates, due dates (issue + 14d), return dates, non-overlapping active loans |
| `fines` | 30+ | Generated strictly for overdue loans and late returns (`₹5.00/day`) |
| `book_purchases` | 80 | Valid purchase dates >= member join date, quantities 1-5, exact total amount check |

---

## 6. Verification Queries

Upon completion, `seed_library.py` automatically runs:
1. **Row Count Check**: Confirms all tables meet the expected row targets.
2. **Foreign Key Integrity**: Confirms 0 orphan records across all FK relationships.
3. **Five Sanity Queries**:
   - Top 5 members by total purchase amount
   - Books purchased per category
   - Authors with the most books purchased
   - Overdue loans with their unpaid fines
   - Total purchases per branch per month (last 6 months)
