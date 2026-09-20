import os
import sqlite3
import uuid
import requests
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "offline_queue.db")


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS offline_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_tx_id TEXT UNIQUE NOT NULL,
        merchant_username TEXT NOT NULL,
        sender_username TEXT NOT NULL,
        amount REAL NOT NULL,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING',     -- PENDING / SYNCED / FAILED
        last_error TEXT,
        created_at TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()
    print("✅ SQLite offline queue ready:", DB_PATH)


def add_payment(merchant_username, sender_username, amount, note=None, client_tx_id=None):
    init_db()
    if client_tx_id is None:
        client_tx_id = str(uuid.uuid4())

    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO offline_payments (client_tx_id, merchant_username, sender_username, amount, note, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
    """, (client_tx_id, merchant_username, sender_username, float(amount), note, created_at))
    conn.commit()
    conn.close()
    print("✅ Added offline payment:", client_tx_id)
    return client_tx_id


def list_pending(merchant_username):
    init_db()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT client_tx_id, sender_username, amount, note, created_at
        FROM offline_payments
        WHERE merchant_username=? AND status='PENDING'
        ORDER BY id ASC
    """, (merchant_username,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sync_pending(base_url, merchant_username):
    init_db()

    pending = list_pending(merchant_username)
    if not pending:
        print("✅ No pending offline payments to sync.")
        return []

    payload = {
        "merchant_username": merchant_username,
        "payments": [
            {
                "client_tx_id": p["client_tx_id"],
                "sender_username": p["sender_username"],
                "amount": p["amount"],
                "note": p["note"]
            }
            for p in pending
        ]
    }

    url = base_url.rstrip("/") + "/offline/sync"
    print("➡️ Syncing to:", url)

    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()

    results = data.get("results", [])

    # Update local statuses
    conn = db_conn()
    cur = conn.cursor()

    for res in results:
        txid = res.get("client_tx_id")
        st = res.get("status")
        msg = res.get("message")

        if st in ("SUCCESS", "DUPLICATE"):
            cur.execute("""
                UPDATE offline_payments
                SET status='SYNCED', last_error=NULL
                WHERE client_tx_id=?
            """, (txid,))
        else:
            cur.execute("""
                UPDATE offline_payments
                SET status='FAILED', last_error=?
                WHERE client_tx_id=?
            """, (msg or "FAILED", txid))

    conn.commit()
    conn.close()

    print("✅ Sync done. Results:", results)
    return results


if __name__ == "__main__":
    # Example usage (manual testing)
    # 1) python offline_queue.py
    # Then edit values below:
    BASE_URL = "http://192.168.101.13:5000"   # change to your laptop IP
    MERCHANT = "Canteen"

    init_db()
    # add_payment(MERCHANT, "Ayudh", 5, "offline test")  # uncomment to add a test pending item
    sync_pending(BASE_URL, MERCHANT)