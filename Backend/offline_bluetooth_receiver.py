import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime

import bluetooth


DB_PATH = os.path.join(os.path.dirname(__file__), "offline_queue.db")
SERVICE_NAME = "CollegeWalletOfflineClassic"
SERVICE_UUID = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
RFCOMM_CHANNEL = 4
RECEIVER_VERSION = "HELLO_FIX_V2"
MERCHANT_USERNAME = os.environ.get("RECEIVER_MERCHANT_USERNAME", "").strip()


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sqlite_add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = [row[1] for row in cur.fetchall()]
    if column_name not in cols:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
    cur.close()


def maybe_log_offline_event(event_type, outcome="INFO", merchant_username=None, sender_username=None, amount=None, client_tx_id=None, details=None):
    try:
        if "log_offline_event" in globals():
            log_offline_event(
                event_type=event_type,
                outcome=outcome,
                merchant_username=merchant_username,
                sender_username=sender_username,
                amount=amount,
                client_tx_id=client_tx_id,
                details=details
            )
    except Exception as e:
        print("WARN maybe_log_offline_event failed:", repr(e))


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
        status TEXT NOT NULL DEFAULT 'PENDING',
        last_error TEXT,
        created_at TEXT NOT NULL
    )
    """)
    cur.close()

    sqlite_add_column_if_missing(conn, "offline_payments", "offline_token_id", "TEXT")
    sqlite_add_column_if_missing(conn, "offline_payments", "offline_token_nonce", "TEXT")
    sqlite_add_column_if_missing(conn, "offline_payments", "offline_token_expires_at", "TEXT")
    sqlite_add_column_if_missing(conn, "offline_payments", "offline_token_signature", "TEXT")

    conn.commit()
    conn.close()
    print(f"SQLite queue ready: {DB_PATH}")


def log_offline_event(
    event_type,
    outcome="INFO",
    merchant_username=None,
    sender_username=None,
    amount=None,
    client_tx_id=None,
    details=None
):
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    conn = None
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO offline_audit_events
            (event_type, outcome, merchant_username, sender_username, amount, client_tx_id, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_type,
            outcome,
            merchant_username,
            sender_username,
            amount,
            client_tx_id,
            json.dumps(details or {}, ensure_ascii=False),
            created_at
        ))
        conn.commit()
    except Exception as e:
        print("WARN log_offline_event failed:", repr(e))
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def add_payment(
    merchant_username,
    sender_username,
    amount,
    note=None,
    client_tx_id=None,
    offline_token_id=None,
    offline_token_nonce=None,
    offline_token_expires_at=None,
    offline_token_signature=None
):
    if not client_tx_id:
        raise ValueError("client_tx_id is required")

    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO offline_payments
        (client_tx_id, merchant_username, sender_username, amount, note, status, created_at,
         offline_token_id, offline_token_nonce, offline_token_expires_at, offline_token_signature)
        VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
    """, (
        client_tx_id,
        merchant_username,
        sender_username,
        float(amount),
        note,
        created_at,
        offline_token_id,
        offline_token_nonce,
        offline_token_expires_at,
        offline_token_signature
    ))
    conn.commit()
    conn.close()

    maybe_log_offline_event(
        event_type="offline_payment_queued",
        outcome="SUCCESS",
        merchant_username=merchant_username,
        sender_username=sender_username,
        amount=float(amount),
        client_tx_id=client_tx_id,
        details={"offline_token_id": offline_token_id}
    )

    print(f"Queued offline payment: {client_tx_id}")


def get_rfcomm_proto():
    try:
        return bluetooth.Protocols.RFCOMM
    except Exception:
        return bluetooth.RFCOMM


def get_candidate_bind_addresses():
    addrs = []
    try:
        addrs = bluetooth.read_local_bdaddr()
        print("Local Bluetooth addresses reported by stack:", addrs)
    except Exception as e:
        print("read_local_bdaddr() failed:", repr(e))

    candidates = []

    if addrs:
        candidates.extend(addrs)

    candidates.append("")

    seen = set()
    ordered = []
    for a in candidates:
        if a not in seen:
            seen.add(a)
            ordered.append(a)

    return ordered


def bind_and_listen():
    rfcomm_proto = get_rfcomm_proto()
    last_error = None

    for bind_addr in get_candidate_bind_addresses():
        server_sock = None
        try:
            print(f"Trying bind address: {repr(bind_addr)}")
            server_sock = bluetooth.BluetoothSocket(rfcomm_proto)
            server_sock.bind((bind_addr, RFCOMM_CHANNEL))
            server_sock.listen(1)

            port = server_sock.getsockname()[1]
            print(f"Bind/listen success on address={repr(bind_addr)} port={port}")
            return server_sock, bind_addr, port
        except Exception as e:
            last_error = e
            print(f"Bind/listen failed on address={repr(bind_addr)} -> {repr(e)}")
            traceback.print_exc()
            try:
                if server_sock:
                    server_sock.close()
            except Exception:
                pass

    raise RuntimeError(f"Could not bind RFCOMM server socket. Last error: {last_error}")


def send_json(sock, payload):
    sock.send(json.dumps(payload).encode("utf-8"))


def handle_hello(sock):
    log_offline_event(
        event_type="offline_hello_received",
        outcome="SUCCESS",
        merchant_username=MERCHANT_USERNAME,
        details={"message": "hello received"}
    )

    response = {
        "ok": True,
        "type": "hello_ack",
        "service_name": SERVICE_NAME,
        "service_uuid": SERVICE_UUID,
        "merchant_username": MERCHANT_USERNAME,
        "message": "Merchant receiver is active"
    }
    send_json(sock, response)

    log_offline_event(
        event_type="offline_hello_ack_sent",
        outcome="SUCCESS",
        merchant_username=MERCHANT_USERNAME,
        details={"service_name": SERVICE_NAME, "service_uuid": SERVICE_UUID}
    )

    print("Sent hello_ack with merchant:", MERCHANT_USERNAME)


def handle_pay(sock, payload):
    merchant_username = str(payload.get("merchant_username", "")).strip()
    sender_username = str(payload.get("sender_username", "")).strip()
    amount = payload.get("amount")
    note = payload.get("note")
    client_tx_id = str(payload.get("client_tx_id", "")).strip()

    offline_token_id = str(payload.get("offline_token_id", "")).strip()
    offline_token_nonce = str(payload.get("offline_token_nonce", "")).strip()
    offline_token_expires_at = str(payload.get("offline_token_expires_at", "")).strip()
    offline_token_signature = str(payload.get("offline_token_signature", "")).strip()

    if not merchant_username:
        raise ValueError("merchant_username is missing")
    if not sender_username:
        raise ValueError("sender_username is missing")
    if amount is None:
        raise ValueError("amount is missing")
    if not client_tx_id:
        raise ValueError("client_tx_id is missing")

    amount = float(amount)
    if amount <= 0:
        raise ValueError("amount must be > 0")

    add_payment(
        merchant_username=merchant_username,
        sender_username=sender_username,
        amount=amount,
        note=note,
        client_tx_id=client_tx_id,
        offline_token_id=offline_token_id or None,
        offline_token_nonce=offline_token_nonce or None,
        offline_token_expires_at=offline_token_expires_at or None,
        offline_token_signature=offline_token_signature or None,
    )

    response = {
        "ok": True,
        "type": "pay_ack",
        "message": "Payment queued",
        "client_tx_id": client_tx_id
    }
    send_json(sock, response)

    maybe_log_offline_event(
        event_type="offline_pay_ack_sent",
        outcome="SUCCESS",
        merchant_username=merchant_username,
        sender_username=sender_username,
        amount=float(amount),
        client_tx_id=client_tx_id,
        details={"offline_token_id": offline_token_id or None}
    )

    print("Sent pay_ack")


def handle_client(sock):
    sock.settimeout(5.0)

    data = b""

    while True:
        try:
            chunk = sock.recv(4096)
        except TimeoutError:
            break
        except OSError:
            break

        if not chunk:
            break

        data += chunk

        try:
            raw_text = data.decode("utf-8").strip()
            json.loads(raw_text)
            break
        except json.JSONDecodeError:
            continue

    if not data:
        send_json(sock, {"ok": False, "message": "Empty payload"})
        print("Received empty payload")
        return

    raw_text = data.decode("utf-8").strip()
    print("Received raw payload:", raw_text)

    payload = json.loads(raw_text)
    msg_type = str(payload.get("type", "")).strip().lower()

    if msg_type == "hello":
        handle_hello(sock)
        return

    if msg_type == "pay":
        handle_pay(sock, payload)
        return

    raise ValueError("Unsupported payload type")


def main():
    init_db()

    log_offline_event(
        event_type="receiver_starting",
        outcome="INFO",
        merchant_username=MERCHANT_USERNAME,
        details={"receiver_version": RECEIVER_VERSION}
    )

    server_sock = None
    client_sock = None

    try:
        print("Starting Bluetooth Classic receiver...")
        print("Receiver version:", RECEIVER_VERSION)
        print("Python version:", sys.version)
        print("bluetooth module:", getattr(bluetooth, "__file__", "<unknown>"))
        print("Merchant username from env:", MERCHANT_USERNAME)
        print("IMPORTANT: advertise_service() is intentionally NOT used in this version.")

        server_sock, bind_addr, port = bind_and_listen()

        print()
        print("===== RECEIVER STATUS =====")
        print(f"Bind address used : {repr(bind_addr)}")
        print(f"RFCOMM port/channel: {port} (expected {RFCOMM_CHANNEL})")
        print(f"Service name      : {SERVICE_NAME}")
        print(f"Service UUID      : {SERVICE_UUID}")
        print(f"Merchant username : {MERCHANT_USERNAME}")
        print("Mode              : NO SDP ADVERTISEMENT")
        print("===========================")

        log_offline_event(
            event_type="receiver_ready",
            outcome="SUCCESS",
            merchant_username=MERCHANT_USERNAME,
            details={
                "bind_addr": bind_addr,
                "port": port,
                "service_name": SERVICE_NAME,
                "service_uuid": SERVICE_UUID
            }
        )

        print("Waiting for student connection...")

        while True:
            client_sock, client_info = server_sock.accept()
            print(f"Accepted connection from: {client_info}")

            try:
                handle_client(client_sock)

            except sqlite3.IntegrityError:
                try:
                    send_json(client_sock, {"ok": False, "message": "Duplicate client_tx_id"})
                except Exception:
                    pass

                log_offline_event(
                    event_type="offline_payment_duplicate",
                    outcome="FAILED",
                    merchant_username=MERCHANT_USERNAME,
                    details={"message": "Duplicate client_tx_id"}
                )

                print("Duplicate client_tx_id")

            except Exception as e:
                try:
                    send_json(client_sock, {"ok": False, "message": str(e)})
                except Exception:
                    pass

                log_offline_event(
                    event_type="offline_client_error",
                    outcome="FAILED",
                    merchant_username=MERCHANT_USERNAME,
                    details={"message": str(e)}
                )

                print("Error while handling client:", e)
                traceback.print_exc()

            finally:
                try:
                    client_sock.close()
                except Exception:
                    pass
                client_sock = None
                print("Waiting for next student connection...")

    except KeyboardInterrupt:
        log_offline_event(
            event_type="receiver_stopped",
            outcome="INFO",
            merchant_username=MERCHANT_USERNAME,
            details={"message": "Receiver stopped by user"}
        )
        print("\nReceiver stopped by user.")

    except Exception as e:
        log_offline_event(
            event_type="receiver_crashed",
            outcome="FAILED",
            merchant_username=MERCHANT_USERNAME,
            details={"message": str(e)}
        )
        print("Receiver crashed:", e)
        traceback.print_exc()
        sys.exit(1)

    finally:
        try:
            if client_sock:
                client_sock.close()
        except Exception:
            pass

        try:
            if server_sock:
                server_sock.close()
        except Exception:
            pass

        log_offline_event(
            event_type="receiver_shutdown",
            outcome="INFO",
            merchant_username=MERCHANT_USERNAME,
            details={"message": "Bluetooth Classic receiver shut down"}
        )

        print("Bluetooth Classic receiver shut down.")


if __name__ == "__main__":
    main()