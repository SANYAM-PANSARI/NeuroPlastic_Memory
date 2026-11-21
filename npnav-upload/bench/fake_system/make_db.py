"""Create data/orders.db with a few orders."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    (ROOT / "data").mkdir(exist_ok=True)
    db = ROOT / "data" / "orders.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount_cents INTEGER)")
    con.executemany("INSERT INTO orders VALUES (?, ?)", [(1, 1999), (2, 4500), (3, 120)])
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
