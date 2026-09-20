from flask import Flask, request, jsonify, render_template_string, session, redirect
from functools import wraps
import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool
import os
import sqlite3
from flask import send_from_directory
import os
import json
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash


from offline_receiver_control import start_receiver, stop_receiver, get_receiver_status

print("app.py started")

app = Flask(__name__)
app.secret_key = "change_this_to_any_random_string_123"

# -------------------- DB POOL CONFIG --------------------
db_pool = MySQLConnectionPool(
    pool_name="wallet_pool",
    pool_size=10,
    host="127.0.0.1",
    user="root",
    password="ayudh",
    database="college_digital_wallet",
    port=3306,
    auth_plugin="mysql_native_password",
)

print("Database pool created successfully")


def get_conn():
    return db_pool.get_connection()


def ip_to_network_id(ip: str) -> str:
    if not ip or "." not in ip:
        return "unknown"
    parts = ip.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else ip





def merchant_login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if session.get("merchant_username") is None:
            return redirect("/merchant/merchantlogin")
        return view_func(*args, **kwargs)
    return wrapper


def ensure_audit_table():
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            event_type VARCHAR(100) NOT NULL,
            outcome VARCHAR(30) NOT NULL DEFAULT 'INFO',
            actor_username VARCHAR(50) NULL,
            merchant_username VARCHAR(50) NULL,
            sender_username VARCHAR(50) NULL,
            receiver_username VARCHAR(50) NULL,
            amount DECIMAL(10,2) NULL,
            client_tx_id VARCHAR(64) NULL,
            details_json TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_audit_created_at (created_at),
            INDEX idx_audit_event_type (event_type),
            INDEX idx_audit_client_tx_id (client_tx_id),
            INDEX idx_audit_merchant_username (merchant_username)
        ) ENGINE=InnoDB
        """)
        conn.commit()
    except Exception as e:
        print("WARN ensure_audit_table failed:", repr(e))
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def log_audit_event(
    event_type,
    outcome="INFO",
    actor_username=None,
    merchant_username=None,
    sender_username=None,
    receiver_username=None,
    amount=None,
    client_tx_id=None,
    details=None
):
    conn = None
    cur = None
    try:
        ensure_audit_table()
        details_json = json.dumps(details or {}, ensure_ascii=False)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_events
            (event_type, outcome, actor_username, merchant_username, sender_username, receiver_username, amount, client_tx_id, details_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_type,
                outcome,
                actor_username,
                merchant_username,
                sender_username,
                receiver_username,
                amount,
                client_tx_id,
                details_json
            )
        )
        conn.commit()
    except Exception as e:
        print("WARN log_audit_event failed:", repr(e))
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        

ONLINE_TOKEN_TTL_SECONDS = 90
ONLINE_TOKEN_SECRET = os.environ.get(
    "ONLINE_TOKEN_SECRET",
    "collegewallet_online_token_secret_v1_change_me"
)


def ensure_online_token_table():
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS online_payment_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            token_id VARCHAR(64) NOT NULL UNIQUE,
            sender_username VARCHAR(50) NOT NULL,
            merchant_username VARCHAR(50) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            note VARCHAR(255) NULL,
            nonce VARCHAR(64) NOT NULL,
            expires_at DATETIME NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ISSUED',
            signature VARCHAR(64) NOT NULL,
            transaction_id INT NULL,
            reject_reason VARCHAR(255) NULL,
            used_at DATETIME NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_opt_token_id (token_id),
            INDEX idx_opt_status (status),
            INDEX idx_opt_sender (sender_username),
            INDEX idx_opt_merchant (merchant_username),
            INDEX idx_opt_expires_at (expires_at)
        ) ENGINE=InnoDB
        """)
        conn.commit()
    except Exception as e:
        print("WARN ensure_online_token_table failed:", repr(e))
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def token_amount_str(amount) -> str:
    return f"{float(amount):.2f}"


def token_dt_to_str(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if value is None:
        return ""
    raw = str(value).strip()
    if raw.endswith("Z"):
        return raw
    if "T" in raw:
        return raw + "Z" if not raw.endswith("Z") else raw
    if " " in raw:
        return raw.replace(" ", "T") + "Z"
    return raw



OFFLINE_TOKEN_TTL_HOURS = 72
OFFLINE_TOKEN_SECRET = os.environ.get(
    "OFFLINE_TOKEN_SECRET",
    "collegewallet_offline_token_secret_v1_change_me"
)


def sqlite_add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = [row[1] for row in cur.fetchall()]
    if column_name not in cols:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
    cur.close()


def offline_token_amount_str(amount) -> str:
    return f"{float(amount):.2f}"


def offline_token_dt_to_str(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if value is None:
        return ""
    raw = str(value).strip()
    if raw.endswith("Z"):
        return raw
    if "T" in raw:
        return raw if raw.endswith("Z") else raw + "Z"
    if " " in raw:
        return raw.replace(" ", "T") + "Z"
    return raw


def build_offline_token_signature(
    sender_username: str,
    token_id: str,
    nonce: str,
    expires_at_str: str,
    max_amount
) -> str:
    raw = "|".join([
        (sender_username or "").strip(),
        (token_id or "").strip(),
        (nonce or "").strip(),
        (expires_at_str or "").strip(),
        offline_token_amount_str(max_amount),
    ])
    return hmac.new(
        OFFLINE_TOKEN_SECRET.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def ensure_offline_token_table():
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS offline_payment_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            token_id VARCHAR(64) NOT NULL UNIQUE,
            sender_username VARCHAR(50) NOT NULL,
            nonce VARCHAR(64) NOT NULL,
            max_amount DECIMAL(10,2) NOT NULL,
            expires_at DATETIME NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ISSUED',
            signature VARCHAR(64) NOT NULL,
            used_merchant_username VARCHAR(50) NULL,
            used_amount DECIMAL(10,2) NULL,
            client_tx_id VARCHAR(64) NULL,
            reject_reason VARCHAR(255) NULL,
            used_at DATETIME NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_offline_token_sender (sender_username),
            INDEX idx_offline_token_status (status),
            INDEX idx_offline_token_expires_at (expires_at)
        ) ENGINE=InnoDB
        """)
        conn.commit()
    except Exception as e:
        print("WARN ensure_offline_token_table failed:", repr(e))
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def build_online_token_signature(
    sender_username: str,
    merchant_username: str,
    amount,
    token_id: str,
    nonce: str,
    expires_at_str: str
) -> str:
    raw = "|".join([
        (sender_username or "").strip(),
        (merchant_username or "").strip(),
        token_amount_str(amount),
        (token_id or "").strip(),
        (nonce or "").strip(),
        (expires_at_str or "").strip(),
    ])
    return hmac.new(
        ONLINE_TOKEN_SECRET.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def ensure_password_hash_column():
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM users LIKE 'password_hash'")
        row = cur.fetchone()
        if not row:
            cur.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL")
            conn.commit()
    except Exception as e:
        print("WARN ensure_password_hash_column failed:", repr(e))
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def backfill_password_hashes():
    conn = None
    cur = None
    try:
        ensure_password_hash_column()

        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT id, username, password, password_hash
            FROM users
            WHERE password IS NOT NULL
              AND password <> ''
              AND (password_hash IS NULL OR password_hash = '')
        """)
        rows = cur.fetchall() or []

        if not rows:
            return

        update_cur = conn.cursor()
        updated_count = 0

        for row in rows:
            plain_password = row.get("password")
            if not plain_password:
                continue

            hashed = generate_password_hash(plain_password)
            update_cur.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (hashed, row["id"])
            )
            updated_count += 1

        conn.commit()
        update_cur.close()

        print(f"Password hash backfill complete. Updated: {updated_count}")

    except Exception as e:
        print("WARN backfill_password_hashes failed:", repr(e))
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def verify_password_and_upgrade(user_row, plain_password: str) -> bool:
    stored_hash = (user_row.get("password_hash") or "").strip()
    stored_plain = user_row.get("password") or ""

    # Preferred: hash check
    if stored_hash:
        try:
            return check_password_hash(stored_hash, plain_password)
        except Exception as e:
            print("WARN check_password_hash failed:", repr(e))
            return False

    # Temporary fallback: plain-text check, then auto-upgrade hash
    if stored_plain and stored_plain == plain_password:
        conn = None
        cur = None
        try:
            conn = get_conn()
            cur = conn.cursor()
            new_hash = generate_password_hash(plain_password)
            cur.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (new_hash, user_row["id"])
            )
            conn.commit()
            print(f"Auto-upgraded password hash for user: {user_row.get('username')}")
        except Exception as e:
            print("WARN auto-upgrade password hash failed:", repr(e))
        finally:
            try:
                if cur:
                    cur.close()
            except Exception:
                pass
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        return True

    return False



# -------------------- HEALTH CHECK --------------------
@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "db": row["ok"]}), 200
    except Exception as e:
        print("ERROR in /health:", repr(e))
        return jsonify({"status": "failure", "message": str(e)}), 500


# -------------------- STUDENT LOGIN API --------------------
@app.route("/login", methods=["POST"])
def login():
    ensure_password_hash_column()
    backfill_password_hashes()

    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        log_audit_event(
            event_type="student_login",
            outcome="FAILED",
            actor_username=username,
            details={"reason": "username and password required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "username and password required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()

        if not user:
            log_audit_event(
                event_type="student_login",
                outcome="FAILED",
                actor_username=username,
                details={"reason": "Invalid username or password", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Invalid username or password"}), 401

        if not verify_password_and_upgrade(user, password):
            log_audit_event(
                event_type="student_login",
                outcome="FAILED",
                actor_username=username,
                details={"reason": "Invalid username or password", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Invalid username or password"}), 401

        log_audit_event(
            event_type="student_login",
            outcome="SUCCESS",
            actor_username=username,
            details={"ip": request.remote_addr}
        )

        return jsonify({
            "status": "success",
            "message": "Login successful",
            "username": user.get("username"),
            "full_name": user.get("full_name"),
            "studentId": user.get("student_id"),
            "program": user.get("program"),
            "balance": float(user.get("balance") or 0.0),
        }), 200

    except Exception as e:
        print("ERROR in /login:", repr(e))
        log_audit_event(
            event_type="student_login",
            outcome="FAILED",
            actor_username=username,
            details={"reason": f"Server error: {str(e)}", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


# -------------------- ONLINE PAYMENT --------------------
@app.route("/pay/online", methods=["POST"])
def pay_online():
    data = request.json or {}

    sender_username = data.get("sender_username")
    receiver_username = data.get("receiver_username")
    amount = data.get("amount")
    note = data.get("note")

    if not sender_username or not receiver_username:
        log_audit_event(
            event_type="online_payment",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=receiver_username,
            details={"reason": "sender_username and receiver_username required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "sender_username and receiver_username required"}), 400

    if sender_username == receiver_username:
        log_audit_event(
            event_type="online_payment",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=receiver_username,
            details={"reason": "sender and receiver cannot be the same", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "sender and receiver cannot be the same"}), 400

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        log_audit_event(
            event_type="online_payment",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=receiver_username,
            details={"reason": "amount must be a number", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "amount must be a number"}), 400

    if amount <= 0:
        log_audit_event(
            event_type="online_payment",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=receiver_username,
            amount=amount,
            details={"reason": "amount must be > 0", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "amount must be > 0"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        log_audit_event(
            event_type="online_payment",
            outcome="REQUESTED",
            sender_username=sender_username,
            receiver_username=receiver_username,
            amount=amount,
            details={"note": note, "ip": request.remote_addr}
        )

        conn.start_transaction()

        cur.execute(
            "SELECT id, username, role, balance FROM users WHERE username=%s FOR UPDATE",
            (sender_username,)
        )
        sender = cur.fetchone()

        cur.execute(
            "SELECT id, username, role, balance FROM users WHERE username=%s FOR UPDATE",
            (receiver_username,)
        )
        receiver = cur.fetchone()

        if not sender:
            conn.rollback()
            log_audit_event(
                event_type="online_payment",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=receiver_username,
                amount=amount,
                details={"reason": "Sender not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender not found"}), 404

        if not receiver:
            conn.rollback()
            log_audit_event(
                event_type="online_payment",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=receiver_username,
                amount=amount,
                details={"reason": "Receiver not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Receiver not found"}), 404

        if receiver.get("role") != "merchant":
            conn.rollback()
            log_audit_event(
                event_type="online_payment",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=receiver_username,
                amount=amount,
                details={"reason": "Receiver must be a merchant", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Receiver must be a merchant"}), 400

        sender_balance = float(sender.get("balance") or 0)
        receiver_balance = float(receiver.get("balance") or 0)

        if sender_balance < amount:
            conn.rollback()
            log_audit_event(
                event_type="online_payment",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=receiver_username,
                amount=amount,
                details={"reason": "Insufficient balance", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Insufficient balance"}), 400

        new_sender_balance = sender_balance - amount
        new_receiver_balance = receiver_balance + amount

        cur.execute("UPDATE users SET balance=%s WHERE id=%s", (new_sender_balance, sender["id"]))
        cur.execute("UPDATE users SET balance=%s WHERE id=%s", (new_receiver_balance, receiver["id"]))

        cur.execute(
            """
            INSERT INTO transactions (sender_user_id, receiver_user_id, amount, method, status, note)
            VALUES (%s, %s, %s, 'ONLINE', 'SUCCESS', %s)
            """,
            (sender["id"], receiver["id"], amount, note)
        )
        tx_id = cur.lastrowid

        conn.commit()

        log_audit_event(
            event_type="online_payment",
            outcome="SUCCESS",
            sender_username=sender_username,
            receiver_username=receiver_username,
            amount=amount,
            details={"transaction_id": tx_id, "note": note, "ip": request.remote_addr}
        )

        return jsonify({
            "status": "success",
            "message": "Payment successful",
            "transaction_id": tx_id,
            "sender": sender_username,
            "receiver": receiver_username,
            "amount": amount,
            "sender_new_balance": round(new_sender_balance, 2),
            "receiver_new_balance": round(new_receiver_balance, 2),
        }), 200

    except Exception as e:
        print("ERROR in /pay/online:", repr(e))
        conn.rollback()
        log_audit_event(
            event_type="online_payment",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=receiver_username,
            amount=amount if isinstance(amount, (int, float)) else None,
            details={"reason": f"Server error: {str(e)}", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


@app.route("/token/issue/online", methods=["POST"])
def issue_online_token():
    ensure_online_token_table()

    data = request.json or {}
    sender_username = (data.get("sender_username") or "").strip()
    merchant_username = (data.get("merchant_username") or data.get("receiver_username") or "").strip()
    amount = data.get("amount")
    note = data.get("note")

    if not sender_username or not merchant_username:
        log_audit_event(
            event_type="online_token_issue",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=merchant_username,
            details={"reason": "sender_username and merchant_username required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "sender_username and merchant_username required"}), 400

    if sender_username == merchant_username:
        log_audit_event(
            event_type="online_token_issue",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=merchant_username,
            details={"reason": "sender and merchant cannot be the same", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "sender and merchant cannot be the same"}), 400

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        log_audit_event(
            event_type="online_token_issue",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=merchant_username,
            details={"reason": "amount must be a number", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "amount must be a number"}), 400

    if amount <= 0:
        log_audit_event(
            event_type="online_token_issue",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=merchant_username,
            amount=amount,
            details={"reason": "amount must be > 0", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "amount must be > 0"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            "SELECT id, username, role, balance FROM users WHERE username=%s",
            (sender_username,)
        )
        sender = cur.fetchone()

        cur.execute(
            "SELECT id, username, role, balance FROM users WHERE username=%s",
            (merchant_username,)
        )
        merchant = cur.fetchone()

        if not sender:
            log_audit_event(
                event_type="online_token_issue",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                amount=amount,
                details={"reason": "Sender not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender not found"}), 404

        if sender.get("role") != "student":
            log_audit_event(
                event_type="online_token_issue",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                amount=amount,
                details={"reason": "Sender must be a student", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender must be a student"}), 400

        if not merchant:
            log_audit_event(
                event_type="online_token_issue",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                amount=amount,
                details={"reason": "Merchant not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Merchant not found"}), 404

        if merchant.get("role") != "merchant":
            log_audit_event(
                event_type="online_token_issue",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                amount=amount,
                details={"reason": "Receiver must be a merchant", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Receiver must be a merchant"}), 400

        sender_balance = float(sender.get("balance") or 0.0)
        if sender_balance < amount:
            log_audit_event(
                event_type="online_token_issue",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                amount=amount,
                details={"reason": "Insufficient balance", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Insufficient balance"}), 400

        token_id = uuid.uuid4().hex
        nonce = uuid.uuid4().hex
        expires_at_dt = datetime.utcnow() + timedelta(seconds=ONLINE_TOKEN_TTL_SECONDS)
        expires_at_str = token_dt_to_str(expires_at_dt)
        signature = build_online_token_signature(
            sender_username=sender_username,
            merchant_username=merchant_username,
            amount=amount,
            token_id=token_id,
            nonce=nonce,
            expires_at_str=expires_at_str
        )

        cur.execute(
            """
            INSERT INTO online_payment_tokens
            (token_id, sender_username, merchant_username, amount, note, nonce, expires_at, status, signature)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ISSUED', %s)
            """,
            (
                token_id,
                sender_username,
                merchant_username,
                amount,
                note,
                nonce,
                expires_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                signature
            )
        )
        conn.commit()

        log_audit_event(
            event_type="online_token_issue",
            outcome="SUCCESS",
            sender_username=sender_username,
            receiver_username=merchant_username,
            merchant_username=merchant_username,
            amount=amount,
            client_tx_id=token_id,
            details={
                "expires_at": expires_at_str,
                "ttl_seconds": ONLINE_TOKEN_TTL_SECONDS,
                "ip": request.remote_addr
            }
        )

        return jsonify({
            "status": "success",
            "message": "Online payment token issued",
            "token_id": token_id,
            "nonce": nonce,
            "expires_at": expires_at_str,
            "signature": signature
        }), 200

    except Exception as e:
        print("ERROR in /token/issue/online:", repr(e))
        try:
            conn.rollback()
        except Exception:
            pass

        log_audit_event(
            event_type="online_token_issue",
            outcome="FAILED",
            sender_username=sender_username,
            receiver_username=merchant_username,
            amount=amount if isinstance(amount, (int, float)) else None,
            details={"reason": f"Server error: {str(e)}", "ip": request.remote_addr}
        )

        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


@app.route("/pay/online/tokenized", methods=["POST"])
def pay_online_tokenized():
    ensure_online_token_table()

    data = request.json or {}
    token_id = (data.get("token_id") or "").strip()
    nonce = (data.get("nonce") or "").strip()
    expires_at = (data.get("expires_at") or "").strip()
    signature = (data.get("signature") or "").strip()

    if not token_id or not nonce or not expires_at or not signature:
        log_audit_event(
            event_type="online_token_consume",
            outcome="FAILED",
            client_tx_id=token_id or None,
            details={"reason": "token_id, nonce, expires_at, signature required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "token_id, nonce, expires_at, signature required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        cur.execute(
            """
            SELECT token_id, sender_username, merchant_username, amount, note, nonce, expires_at,
                   status, signature, transaction_id
            FROM online_payment_tokens
            WHERE token_id=%s
            FOR UPDATE
            """,
            (token_id,)
        )
        token = cur.fetchone()

        if not token:
            conn.rollback()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                client_tx_id=token_id,
                details={"reason": "Token not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Token not found"}), 404

        sender_username = token["sender_username"]
        merchant_username = token["merchant_username"]
        amount = float(token["amount"] or 0.0)
        note = token.get("note")
        db_nonce = token.get("nonce") or ""
        db_signature = token.get("signature") or ""
        db_expires_at_str = token_dt_to_str(token.get("expires_at"))
        status = (token.get("status") or "").upper()

        if status == "USED":
            conn.rollback()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Token already used", "transaction_id": token.get("transaction_id"), "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Token already used"}), 409

        if status == "EXPIRED":
            conn.rollback()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Token already expired", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Token expired"}), 400

        if status == "REJECTED":
            conn.rollback()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Token already rejected", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Token rejected"}), 400

        token_expires_dt = token.get("expires_at")
        if token_expires_dt and token_expires_dt <= datetime.utcnow():
            cur.execute(
                """
                UPDATE online_payment_tokens
                SET status='EXPIRED', reject_reason='Token expired'
                WHERE token_id=%s
                """,
                (token_id,)
            )
            conn.commit()

            log_audit_event(
                event_type="online_token_expired",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Token expired during consume", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Token expired"}), 400

        expected_signature = build_online_token_signature(
            sender_username=sender_username,
            merchant_username=merchant_username,
            amount=amount,
            token_id=token_id,
            nonce=db_nonce,
            expires_at_str=db_expires_at_str
        )

        if nonce != db_nonce or expires_at != db_expires_at_str or signature != db_signature or signature != expected_signature:
            cur.execute(
                """
                UPDATE online_payment_tokens
                SET status='REJECTED', reject_reason='Token signature mismatch'
                WHERE token_id=%s
                """,
                (token_id,)
            )
            conn.commit()

            log_audit_event(
                event_type="online_token_signature_failed",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Token signature mismatch", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Invalid token"}), 400

        cur.execute(
            "SELECT id, username, role, balance FROM users WHERE username=%s FOR UPDATE",
            (sender_username,)
        )
        sender = cur.fetchone()

        cur.execute(
            "SELECT id, username, role, balance FROM users WHERE username=%s FOR UPDATE",
            (merchant_username,)
        )
        receiver = cur.fetchone()

        if not sender:
            cur.execute(
                "UPDATE online_payment_tokens SET status='REJECTED', reject_reason='Sender not found' WHERE token_id=%s",
                (token_id,)
            )
            conn.commit()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Sender not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender not found"}), 404

        if not receiver:
            cur.execute(
                "UPDATE online_payment_tokens SET status='REJECTED', reject_reason='Merchant not found' WHERE token_id=%s",
                (token_id,)
            )
            conn.commit()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Merchant not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Merchant not found"}), 404

        if receiver.get("role") != "merchant":
            cur.execute(
                "UPDATE online_payment_tokens SET status='REJECTED', reject_reason='Receiver must be merchant' WHERE token_id=%s",
                (token_id,)
            )
            conn.commit()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Receiver must be a merchant", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Receiver must be a merchant"}), 400

        sender_balance = float(sender.get("balance") or 0.0)
        receiver_balance = float(receiver.get("balance") or 0.0)

        if sender_balance < amount:
            cur.execute(
                "UPDATE online_payment_tokens SET status='REJECTED', reject_reason='Insufficient balance' WHERE token_id=%s",
                (token_id,)
            )
            conn.commit()
            log_audit_event(
                event_type="online_token_consume",
                outcome="FAILED",
                sender_username=sender_username,
                receiver_username=merchant_username,
                merchant_username=merchant_username,
                amount=amount,
                client_tx_id=token_id,
                details={"reason": "Insufficient balance", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Insufficient balance"}), 400

        new_sender_balance = sender_balance - amount
        new_receiver_balance = receiver_balance + amount

        cur.execute("UPDATE users SET balance=%s WHERE id=%s", (new_sender_balance, sender["id"]))
        cur.execute("UPDATE users SET balance=%s WHERE id=%s", (new_receiver_balance, receiver["id"]))

        cur.execute(
            """
            INSERT INTO transactions (sender_user_id, receiver_user_id, amount, method, status, note)
            VALUES (%s, %s, %s, 'ONLINE', 'SUCCESS', %s)
            """,
            (sender["id"], receiver["id"], amount, note)
        )
        tx_id = cur.lastrowid

        cur.execute(
            """
            UPDATE online_payment_tokens
            SET status='USED', used_at=UTC_TIMESTAMP(), transaction_id=%s, reject_reason=NULL
            WHERE token_id=%s
            """,
            (tx_id, token_id)
        )

        conn.commit()

        log_audit_event(
            event_type="online_token_used",
            outcome="SUCCESS",
            sender_username=sender_username,
            receiver_username=merchant_username,
            merchant_username=merchant_username,
            amount=amount,
            client_tx_id=token_id,
            details={"transaction_id": tx_id, "note": note, "ip": request.remote_addr}
        )

        return jsonify({
            "status": "success",
            "message": "Payment successful",
            "transaction_id": tx_id,
            "sender": sender_username,
            "receiver": merchant_username,
            "amount": amount,
            "sender_new_balance": round(new_sender_balance, 2),
            "receiver_new_balance": round(new_receiver_balance, 2),
        }), 200

    except Exception as e:
        print("ERROR in /pay/online/tokenized:", repr(e))
        try:
            conn.rollback()
        except Exception:
            pass

        log_audit_event(
            event_type="online_token_consume",
            outcome="FAILED",
            client_tx_id=token_id or None,
            details={"reason": f"Server error: {str(e)}", "ip": request.remote_addr}
        )

        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


@app.route("/token/issue/offline-pack", methods=["POST"])
def issue_offline_token_pack():
    ensure_offline_token_table()

    data = request.json or {}
    sender_username = (data.get("sender_username") or "").strip()

    try:
        pack_size = int(data.get("pack_size") or 5)
    except (TypeError, ValueError):
        pack_size = 5

    pack_size = max(1, min(pack_size, 20))

    if not sender_username:
        log_audit_event(
            event_type="offline_token_pack_issue",
            outcome="FAILED",
            actor_username=sender_username,
            sender_username=sender_username,
            details={"reason": "sender_username required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "sender_username required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            "SELECT username, role, balance FROM users WHERE username=%s",
            (sender_username,)
        )
        sender = cur.fetchone()

        if not sender:
            log_audit_event(
                event_type="offline_token_pack_issue",
                outcome="FAILED",
                actor_username=sender_username,
                sender_username=sender_username,
                details={"reason": "Sender not found", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender not found"}), 404

        if sender.get("role") != "student":
            log_audit_event(
                event_type="offline_token_pack_issue",
                outcome="FAILED",
                actor_username=sender_username,
                sender_username=sender_username,
                details={"reason": "Sender must be a student", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender must be a student"}), 400

        sender_balance = float(sender.get("balance") or 0.0)
        if sender_balance <= 0:
            log_audit_event(
                event_type="offline_token_pack_issue",
                outcome="FAILED",
                actor_username=sender_username,
                sender_username=sender_username,
                details={"reason": "Sender balance must be > 0", "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Sender balance must be > 0"}), 400

        expires_at_dt = datetime.utcnow() + timedelta(hours=OFFLINE_TOKEN_TTL_HOURS)
        expires_at_str = offline_token_dt_to_str(expires_at_dt)

        tokens = []

        for _ in range(pack_size):
            token_id = uuid.uuid4().hex
            nonce = uuid.uuid4().hex
            max_amount = sender_balance
            signature = build_offline_token_signature(
                sender_username=sender_username,
                token_id=token_id,
                nonce=nonce,
                expires_at_str=expires_at_str,
                max_amount=max_amount
            )

            cur.execute(
                """
                INSERT INTO offline_payment_tokens
                (token_id, sender_username, nonce, max_amount, expires_at, status, signature)
                VALUES (%s, %s, %s, %s, %s, 'ISSUED', %s)
                """,
                (
                    token_id,
                    sender_username,
                    nonce,
                    max_amount,
                    expires_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    signature
                )
            )

            tokens.append({
                "token_id": token_id,
                "nonce": nonce,
                "expires_at": expires_at_str,
                "signature": signature,
                "max_amount": round(float(max_amount), 2)
            })

        conn.commit()

        log_audit_event(
            event_type="offline_token_pack_issue",
            outcome="SUCCESS",
            actor_username=sender_username,
            sender_username=sender_username,
            details={
                "pack_size": pack_size,
                "ttl_hours": OFFLINE_TOKEN_TTL_HOURS,
                "max_amount_per_token": round(sender_balance, 2),
                "ip": request.remote_addr
            }
        )

        return jsonify({
            "status": "success",
            "message": "Offline token pack issued",
            "sender_username": sender_username,
            "pack_size": pack_size,
            "ttl_hours": OFFLINE_TOKEN_TTL_HOURS,
            "tokens": tokens
        }), 200

    except Exception as e:
        print("ERROR in /token/issue/offline-pack:", repr(e))
        try:
            conn.rollback()
        except Exception:
            pass

        log_audit_event(
            event_type="offline_token_pack_issue",
            outcome="FAILED",
            actor_username=sender_username,
            sender_username=sender_username,
            details={"reason": f"Server error: {str(e)}", "ip": request.remote_addr}
        )

        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()

# -------------------- TRANSACTIONS LIST API --------------------
@app.route("/transactions/<username>", methods=["GET"])
def transactions(username):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("SELECT id, username FROM users WHERE username=%s", (username,))
        user = cur.fetchone()

        if not user:
            return jsonify({"status": "failure", "message": "User not found"}), 404

        user_id = user["id"]

        cur.execute(
            """
            SELECT
                t.id,
                t.amount,
                t.method,
                t.status,
                t.note,
                t.created_at,
                u1.username AS sender_username,
                u2.username AS receiver_username
            FROM transactions t
            JOIN users u1 ON u1.id = t.sender_user_id
            JOIN users u2 ON u2.id = t.receiver_user_id
            WHERE t.sender_user_id=%s OR t.receiver_user_id=%s
            ORDER BY t.created_at DESC
            LIMIT 30
            """,
            (user_id, user_id)
        )
        rows = cur.fetchall() or []
        for r in rows:
            r["amount"] = float(r["amount"])

        return jsonify({"status": "success", "username": username, "transactions": rows}), 200

    except Exception as e:
        print("ERROR in /transactions:", repr(e))
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


# -------------------- MERCHANT DISCOVERY (API used by phone) --------------------
MERCHANT_TTL_SECONDS = 60
OFFLINE_ACCEPTING_STATE = {}


@app.route("/merchant/checkin", methods=["POST"])
def merchant_checkin():
    data = request.json or {}
    merchant_username = data.get("merchant_username")
    network_id = data.get("networkId")

    if not merchant_username or not network_id:
        log_audit_event(
            event_type="merchant_checkin",
            outcome="FAILED",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"reason": "merchant_username and networkId required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "merchant_username and networkId required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("SELECT username, role FROM users WHERE username=%s", (merchant_username,))
        u = cur.fetchone()
        if not u:
            log_audit_event(
                event_type="merchant_checkin",
                outcome="FAILED",
                actor_username=merchant_username,
                merchant_username=merchant_username,
                details={"reason": "Merchant user not found", "network_id": network_id, "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "Merchant user not found"}), 404
        if u.get("role") != "merchant":
            log_audit_event(
                event_type="merchant_checkin",
                outcome="FAILED",
                actor_username=merchant_username,
                merchant_username=merchant_username,
                details={"reason": "User is not a merchant", "network_id": network_id, "ip": request.remote_addr}
            )
            return jsonify({"status": "failure", "message": "User is not a merchant"}), 403

        cur.execute(
            """
            INSERT INTO merchant_presence (merchant_username, network_id, last_seen)
            VALUES (%s, %s, NOW())
            ON DUPLICATE KEY UPDATE network_id=VALUES(network_id), last_seen=NOW()
            """,
            (merchant_username, network_id)
        )
        conn.commit()

        log_audit_event(
            event_type="merchant_checkin",
            outcome="SUCCESS",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"network_id": network_id, "ip": request.remote_addr}
        )

        return jsonify({
            "status": "success",
            "message": "Merchant checked in",
            "merchant_username": merchant_username,
            "networkId": network_id,
            "ttlSeconds": MERCHANT_TTL_SECONDS
        }), 200

    except Exception as e:
        print("ERROR in /merchant/checkin:", repr(e))
        conn.rollback()
        log_audit_event(
            event_type="merchant_checkin",
            outcome="FAILED",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"reason": f"Server error: {str(e)}", "network_id": network_id, "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


@app.route("/merchant/checkout", methods=["POST"])
def merchant_checkout():
    data = request.json or {}
    merchant_username = data.get("merchant_username")

    if not merchant_username:
        log_audit_event(
            event_type="merchant_checkout",
            outcome="FAILED",
            details={"reason": "merchant_username required", "ip": request.remote_addr}
        )
        return jsonify({"status": "failure", "message": "merchant_username required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("DELETE FROM merchant_presence WHERE merchant_username=%s", (merchant_username,))
        conn.commit()

        log_audit_event(
            event_type="merchant_checkout",
            outcome="SUCCESS",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"ip": request.remote_addr}
        )

        return jsonify({"status": "success", "message": "Merchant checked out"}), 200
    except Exception as e:
        print("ERROR in /merchant/checkout:", repr(e))
        conn.rollback()

        log_audit_event(
            event_type="merchant_checkout",
            outcome="FAILED",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"reason": f"Server error: {str(e)}", "ip": request.remote_addr}
        )

        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/merchants", methods=["GET"])
def get_merchants():
    network_id = request.args.get("networkId")
    if not network_id:
        return jsonify({"status": "failure", "message": "networkId query param required"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            f"""
            SELECT u.username
            FROM users u
            JOIN merchant_presence p ON p.merchant_username = u.username
            WHERE u.role='merchant'
              AND p.network_id=%s
              AND p.last_seen >= (NOW() - INTERVAL {MERCHANT_TTL_SECONDS} SECOND)
            ORDER BY u.username
            """,
            (network_id,)
        )
        rows = cur.fetchall() or []
        merchants = [r["username"] for r in rows]

        return jsonify({
            "status": "success",
            "networkId": network_id,
            "ttlSeconds": MERCHANT_TTL_SECONDS,
            "merchants": merchants
        }), 200

    except Exception as e:
        print("ERROR in /merchants:", repr(e))
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()

        
@app.route("/college-logo")
def college_logo():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "ICK logo.png")


# -------------------- MERCHANT WEB: LOGIN + DASHBOARD --------------------
MERCHANT_LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Merchant Login | College Digital Wallet</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>

  <style>
    :root{
      --bg1:#0B0F2B;
      --bg2:#1A237E;
      --bg3:#283593;
      --card:#0f1a55cc;
      --stroke:#ffffff33;
      --text:#ffffff;
      --muted:#ffffffb3;
      --btn:#4f8dff;
      --btnText:#fff;
    }

    * { box-sizing: border-box; }

    body{
      margin:0;
      min-height:100vh;
      font-family: Arial, sans-serif;
      color:var(--text);
      background:
        radial-gradient(900px 500px at 25% 20%, rgba(255,255,255,0.12), transparent 60%),
        radial-gradient(800px 600px at 75% 60%, rgba(255,255,255,0.10), transparent 60%),
        linear-gradient(180deg, var(--bg1), var(--bg2), var(--bg3));
      display:flex;
      align-items:center;
      justify-content:center;
      padding: 22px;
    }

    .wave {
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.22;
      background:
        radial-gradient(1200px 420px at 15% 85%, rgba(120,170,255,0.55), transparent 70%),
        radial-gradient(1000px 420px at 85% 90%, rgba(80,120,255,0.45), transparent 70%),
        radial-gradient(900px 420px at 50% 95%, rgba(255,255,255,0.18), transparent 70%);
      filter: blur(2px);
    }

    .container{
      width: min(520px, 100%);
    }

    .header{
      text-align:center;
      margin-bottom: 14px;
    }

    .header h1{
      margin:0;
      font-size: 34px;
      font-weight: 800;
      letter-spacing: 0.2px;
    }

    .header p{
      margin:8px 0 0 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.35;
    }

    .card{
      margin-top: 18px;
      background: var(--card);
      border: 1px solid var(--stroke);
      border-radius: 22px;
      box-shadow: 0 18px 40px rgba(0,0,0,0.35);
      padding: 22px;
      backdrop-filter: blur(10px);
    }

    .logo-wrap{
      display:flex;
      justify-content:center;
      margin-bottom: 8px;
    }

    .logo-wrap img{
      width: 150px;
      max-width: 100%;
      height: 100px;
      object-fit: contain;
      display: block;
      filter: drop-shadow(0 8px 16px rgba(0,0,0,0.18));
    }

    .login-title{
      text-align:center;
      font-size: 24px;
      font-weight: 800;
      color: var(--text);
      margin: 6px 0 18px 0;
      letter-spacing: 0.2px;
    }

    label{
      display:block;
      font-weight: 700;
      margin: 12px 0 6px;
      color: var(--text);
      opacity: 0.95;
    }

    input[type="text"], input[type="password"]{
      width:100%;
      border:1px solid rgba(255,255,255,0.18);
      outline:none;
      color: var(--text);
      padding: 14px 14px;
      border-radius: 16px;
      font-size: 16px;
      background: rgba(255,255,255,0.12) !important;
      box-shadow: none !important;
      -webkit-appearance: none;
      appearance: none;
      transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
    }

    input[type="text"]:focus, input[type="password"]:focus{
      background: rgba(255,255,255,0.14) !important;
      border-color: rgba(79,141,255,0.55);
      box-shadow: 0 0 0 5px rgba(79,141,255,0.16) !important;
    }

    input::placeholder{
      color: rgba(255,255,255,0.55);
    }

    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus,
    textarea:-webkit-autofill,
    select:-webkit-autofill{
      -webkit-text-fill-color: var(--text) !important;
      transition: background-color 999999s ease-out 0s;
      -webkit-box-shadow: 0 0 0 1000px rgba(255,255,255,0.12) inset !important;
      box-shadow: 0 0 0 1000px rgba(255,255,255,0.12) inset !important;
      border: 1px solid rgba(255,255,255,0.18) !important;
    }

    input[type="text"]::selection, input[type="password"]::selection{
      background: rgba(79,141,255,0.35);
    }

    .password-wrap{
      position: relative;
    }

    .eye-btn{
      position: absolute;
      right: 10px;
      top: 50%;
      transform: translateY(-50%);
      border: 0;
      background: rgba(255,255,255,0.14);
      color: rgba(255,255,255,0.9);
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: 12px;
      padding: 8px 10px;
      cursor: pointer;
      font-weight: 800;
      line-height: 1;
    }

    .eye-btn:hover{
      background: rgba(255,255,255,0.20);
    }

    .row{
      display:flex;
      align-items:center;
      gap: 10px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }

    .btn{
      width:100%;
      margin-top: 16px;
      padding: 12px 14px;
      border:0;
      border-radius: 14px;
      cursor:pointer;
      background: var(--btn);
      color: var(--btnText);
      font-weight: 800;
      font-size: 15px;
      letter-spacing: 0.4px;
      box-shadow: 0 10px 22px rgba(79,141,255,0.28);
    }

    .error{
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(255,0,0,0.10);
      border: 1px solid rgba(255,0,0,0.25);
      color: #ffd0d0;
      font-weight: 700;
      font-size: 13px;
    }

    .footer{
      text-align:center;
      margin-top: 14px;
      color: rgba(255,255,255,0.75);
      font-size: 12px;
    }

        .toast-wrap{
      position: fixed;
      top: 18px;
      right: 18px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .toast{
      min-width: 260px;
      max-width: 360px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(9,16,52,0.96);
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 40px rgba(0,0,0,0.30);
      color: #fff;
      opacity: 0;
      transform: translateY(-12px);
      transition: opacity 0.22s ease, transform 0.22s ease;
    }

    .toast.show{
      opacity: 1;
      transform: translateY(0);
    }

    .toast.success{
      border-color: rgba(56,189,99,0.45);
    }

    .toast.error{
      border-color: rgba(255,99,132,0.40);
    }

    .toast-title{
      font-size: 14px;
      font-weight: 800;
      margin-bottom: 4px;
    }

    .toast-text{
      font-size: 13px;
      color: rgba(255,255,255,0.82);
      line-height: 1.35;
    }
  </style>
</head>

<body>
  <div class="toast-wrap" id="toastWrap"></div>
  <div class="wave"></div>

  <div class="container">
    <div class="header">
      <h1>Welcome</h1>
      <p>to <b>College Credential Digital Wallet</b></p>
    </div>

    <div class="card">
      <div class="logo-wrap">
        <img src="/college-logo" alt="Islington College Logo" />
      </div>

      <div class="login-title">Merchant Login</div>

      <form method="POST" action="/merchant/merchantlogin">
        <label>Username</label>
        <div class="password-wrap">
          <input name="username" type="text" placeholder="e.g. Canteen" required />
        </div>

        <label>Password</label>
        <div class="password-wrap">
          <input id="passwordInput" name="password" type="password" placeholder="Password" required />
          <button type="button" class="eye-btn" onclick="togglePassword()" aria-label="Toggle password visibility">
            👁
          </button>
        </div>

        <div class="row">
          <label style="display:flex; align-items:center; gap:8px; margin:0; font-weight:600;">
            <input type="checkbox" name="remember" style="width:16px; height:16px; accent-color: var(--btn);" />
            Remember me
          </label>
        </div>

        <button class="btn" type="submit">LOGIN</button>
      </form>

      {% if error %}
        <div class="error">{{ error }}</div>
      {% endif %}

      <div class="footer">
        Only merchant accounts can log in.
      </div>
    </div>
  </div>

    <script>
    function togglePassword(){
      const input = document.getElementById("passwordInput");
      if (!input) return;
      input.type = (input.type === "password") ? "text" : "password";
    }

    function showToast(message, type = "success", title = "Notification") {
      const wrap = document.getElementById("toastWrap");
      if (!wrap || !message) return;

      const toast = document.createElement("div");
      toast.className = "toast " + type;
      toast.innerHTML = `
        <div class="toast-title">${title}</div>
        <div class="toast-text">${message}</div>
      `;

      wrap.appendChild(toast);

      requestAnimationFrame(() => toast.classList.add("show"));

      setTimeout(() => {
        toast.classList.remove("show");
      }, 2600);

      setTimeout(() => {
        toast.remove();
      }, 3000);
    }

    window.addEventListener("load", function () {
      const toastCode = {{ request.args.get('toast', '')|tojson }};
      const toastMap = {
        logout_success: {
          title: "Logout",
          message: "Logged out successfully ✅",
          type: "success"
        }
      };

      const item = toastMap[toastCode];
      if (item) {
        showToast(item.message, item.type, item.title);
      }
    });
  </script>
</body>
</html>
"""


@app.route("/merchant/merchantlogin", methods=["GET", "POST"])
def merchant_login():
    ensure_password_hash_column()
    backfill_password_hashes()

    if request.method == "GET":
        return render_template_string(MERCHANT_LOGIN_HTML, error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username or not password:
        log_audit_event(
            event_type="merchant_login",
            outcome="FAILED",
            actor_username=username,
            merchant_username=username,
            details={"reason": "Username and password required", "ip": request.remote_addr}
        )
        return render_template_string(MERCHANT_LOGIN_HTML, error="Username and password required")

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, username, role, password, password_hash FROM users WHERE username=%s",
            (username,)
        )
        u = cur.fetchone()

        if not u:
            log_audit_event(
                event_type="merchant_login",
                outcome="FAILED",
                actor_username=username,
                merchant_username=username,
                details={"reason": "Invalid credentials", "ip": request.remote_addr}
            )
            return render_template_string(MERCHANT_LOGIN_HTML, error="Invalid credentials")

        if not verify_password_and_upgrade(u, password):
            log_audit_event(
                event_type="merchant_login",
                outcome="FAILED",
                actor_username=username,
                merchant_username=username,
                details={"reason": "Invalid credentials", "ip": request.remote_addr}
            )
            return render_template_string(MERCHANT_LOGIN_HTML, error="Invalid credentials")

        if u.get("role") != "merchant":
            log_audit_event(
                event_type="merchant_login",
                outcome="FAILED",
                actor_username=username,
                merchant_username=username,
                details={"reason": "This account is not a merchant", "ip": request.remote_addr}
            )
            return render_template_string(MERCHANT_LOGIN_HTML, error="This account is not a merchant")

        session["merchant_username"] = u["username"]

        log_audit_event(
            event_type="merchant_login",
            outcome="SUCCESS",
            actor_username=u["username"],
            merchant_username=u["username"],
            details={"ip": request.remote_addr}
        )

        return redirect(f"/merchant/{u['username']}?toast=login_success")

    finally:
        cur.close()
        conn.close()


@app.route("/merchant/logout", methods=["GET"])
def merchant_logout():
    merchant_username = session.get("merchant_username")
    if merchant_username:
        log_audit_event(
            event_type="merchant_logout",
            outcome="SUCCESS",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"ip": request.remote_addr}
        )

    session.pop("merchant_username", None)
    return redirect("/merchant/merchantlogin?toast=logout_success")


MERCHANT_DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Merchant Dashboard | CollegeWallet</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>

  <style>
    :root{
      --bg:#04091d;
      --bg-2:#07112e;
      --bg-3:#0a173d;
      --navy-1:#08122f;
      --navy-2:#0b1a45;
      --navy-3:#10245b;
      --navy-4:#17357d;
      --panel:#0a173e;
      --panel-2:#0d1d4b;
      --panel-3:#11265f;
      --line:rgba(255,255,255,0.08);
      --line-2:rgba(255,255,255,0.12);
      --text:#f5f7ff;
      --text-soft:#c8d2f6;
      --text-muted:#8ea0d4;
      --white-soft:rgba(255,255,255,0.05);

      --green:#49d17d;
      --green-bg:rgba(73,209,125,0.14);

      --red:#ff5f73;
      --red-bg:rgba(255,95,115,0.14);

      --amber:#ffbd59;
      --amber-bg:rgba(255,189,89,0.14);

      --cyan:#69d1ff;
      --cyan-bg:rgba(105,209,255,0.14);

      --shadow:0 18px 40px rgba(0,0,0,0.34);
      --radius-xl:28px;
      --radius-lg:22px;
      --radius-md:18px;
      --radius-sm:14px;
    }

    *{ box-sizing:border-box; }

    html, body{
      margin:0;
      height:100%;
      overflow:hidden;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(700px 400px at 15% 10%, rgba(79,114,255,0.10), transparent 60%),
        radial-gradient(800px 500px at 90% 5%, rgba(65,145,255,0.08), transparent 60%),
        linear-gradient(180deg, #030715 0%, #06102b 35%, #07143a 100%);
      color:var(--text);
    }

    body{
      display:grid;
      grid-template-columns: 276px minmax(0, 1fr);
      height:100vh;
    }

    .sidebar{
      height:100vh;
      position:sticky;
      top:0;
      overflow:hidden;
      padding:12px 12px 12px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02)),
        linear-gradient(180deg, rgba(8,18,47,0.98), rgba(7,16,40,0.98));
      border-right:1px solid rgba(255,255,255,0.08);
      display:flex;
      flex-direction:column;
      gap:10px;
    }

    .brand{
      padding:12px;
      border-radius:22px;
      border:1px solid rgba(255,255,255,0.08);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02)),
        linear-gradient(180deg, rgba(13,29,75,0.98), rgba(9,20,54,0.98));
      box-shadow: var(--shadow);
    }

    .brand-logo-wrap{
      width:100%;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:4px 0 8px;
    }

    .brand-logo{
      width:100%;
      max-width:176px;
      max-height:82px;
      height:auto;
      object-fit:contain;
      display:block;
      filter: drop-shadow(0 8px 18px rgba(0,0,0,0.25));
    }

    .brand-divider{
      height:1px;
      background:linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent);
      margin:2px 0 8px;
    }

    .brand-text{
      display:flex;
      flex-direction:column;
      gap:2px;
      text-align:center;
    }

    .brand-title{
      font-size:22px;
      font-weight:900;
      letter-spacing:-0.3px;
      margin:0;
    }

    .brand-subtitle{
      font-size:12px;
      color:var(--text-muted);
      margin:0;
      font-weight:700;
      letter-spacing:0.4px;
    }

    .nav{
      display:grid;
      gap:8px;
    }

    .nav-link{
      min-height:52px;
      border-radius:18px;
      border:1px solid rgba(255,255,255,0.09);
      background:
        linear-gradient(180deg, rgba(23,53,125,0.22), rgba(11,25,68,0.96));
      color:var(--text);
      display:flex;
      align-items:center;
      justify-content:space-between;
      padding:0 14px;
      font-size:14px;
      font-weight:800;
      letter-spacing:0.1px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
      position:relative;
      overflow:hidden;
      cursor:pointer;
      appearance:none;
      outline:none;
      width:100%;
    }

    .nav-link::before{
      content:"";
      position:absolute;
      left:0;
      top:0;
      bottom:0;
      width:4px;
      background:transparent;
      transition:0.2s ease;
    }

    .nav-link .nav-left{
      display:flex;
      align-items:center;
      gap:11px;
    }

    .nav-link .nav-dot{
      width:9px;
      height:9px;
      border-radius:50%;
      background:rgba(255,255,255,0.30);
    }

    .nav-link .nav-right{
      font-size:11px;
      color:var(--text-muted);
      font-weight:800;
      text-transform:uppercase;
      letter-spacing:0.7px;
    }

    .nav-link.active{
      background:
        linear-gradient(180deg, rgba(78,111,255,0.24), rgba(13,30,78,0.98));
      border-color: rgba(255,255,255,0.14);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.05),
        0 10px 28px rgba(0,0,0,0.26);
    }

    .nav-link.active::before{
      background:var(--cyan);
      box-shadow:0 0 16px rgba(105,209,255,0.45);
    }

    .nav-link.active .nav-dot{
      background:var(--cyan);
      box-shadow:0 0 0 6px rgba(105,209,255,0.10), 0 0 12px rgba(105,209,255,0.36);
    }

    .sidebar-card{
      border-radius:20px;
      padding:13px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02)),
        linear-gradient(180deg, rgba(11,24,63,0.98), rgba(9,20,53,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: var(--shadow);
    }

    .card-label{
      font-size:10px;
      font-weight:900;
      color:var(--text-muted);
      text-transform:uppercase;
      letter-spacing:1.2px;
      margin-bottom:10px;
    }

    .status-list{
      display:grid;
      gap:9px;
    }

    .status-row{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      padding:10px 11px;
      border-radius:15px;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.06);
    }

    .status-left{
      display:flex;
      align-items:center;
      gap:9px;
      min-width:0;
    }

    .signal-dot{
      width:10px;
      height:10px;
      border-radius:50%;
      flex-shrink:0;
    }

    .signal-dot.on{
      background:var(--green);
      box-shadow:0 0 0 6px rgba(73,209,125,0.10), 0 0 12px rgba(73,209,125,0.34);
    }

    .signal-dot.off{
      background:var(--red);
      box-shadow:0 0 0 6px rgba(255,95,115,0.10), 0 0 12px rgba(255,95,115,0.30);
    }

    .status-name{
      font-size:13px;
      font-weight:800;
      color:var(--text-soft);
      line-height:1.25;
    }

    .status-text{
      font-size:11px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:0.8px;
      white-space:nowrap;
    }

    .status-text.live{ color:var(--green); }
    .status-text.dead{ color:var(--red); }

    .merchant-name{
      font-size:17px;
      font-weight:900;
      line-height:1.2;
      margin-bottom:5px;
    }

    .merchant-meta{
      color:var(--text-soft);
      font-size:12px;
      line-height:1.5;
    }

    .logout-link{
      margin-top:auto;
      min-height:44px;
      display:flex;
      align-items:center;
      justify-content:center;
      text-decoration:none;
      color:var(--text);
      font-weight:800;
      letter-spacing:0.2px;
      border-radius:15px;
      border:1px solid rgba(255,255,255,0.10);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04));
    }

    .main{
      height:100vh;
      overflow-y:auto;
      padding:22px;
      scroll-behavior:smooth;
    }

    .main::-webkit-scrollbar{
      width:10px;
    }

    .main::-webkit-scrollbar-track{
      background:rgba(255,255,255,0.03);
      border-radius:20px;
    }

    .main::-webkit-scrollbar-thumb{
      background:rgba(255,255,255,0.12);
      border-radius:20px;
    }

    .page{
      display:none;
      animation: fadeIn 0.18s ease;
    }

    .page.active{
      display:block;
    }

    @keyframes fadeIn{
      from{ opacity:0; transform:translateY(6px); }
      to{ opacity:1; transform:translateY(0); }
    }

    .header{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:20px;
      margin-bottom:18px;
    }

    .header h2{
      margin:0;
      font-size:44px;
      font-weight:900;
      letter-spacing:-0.8px;
      line-height:1;
    }

    .header-sub{
      margin-top:8px;
      color:var(--text-muted);
      font-size:14px;
      font-weight:700;
      line-height:1.55;
    }

    .header-right{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }

    .top-chip{
      min-height:48px;
      display:inline-flex;
      align-items:center;
      padding:0 16px;
      border-radius:16px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.03)),
        linear-gradient(180deg, rgba(11,25,67,0.98), rgba(9,20,54,0.98));
      border:1px solid rgba(255,255,255,0.09);
      color:var(--text-soft);
      font-size:14px;
      font-weight:800;
      box-shadow: var(--shadow);
      gap:8px;
    }

    .top-chip b{
      color:var(--text);
      margin-left:2px;
    }

    .hero-strip{
      display:grid;
      grid-template-columns: 1.35fr 0.8fr 0.9fr;
      gap:14px;
      margin-bottom:18px;
    }

    .hero-card{
      border-radius:22px;
      padding:18px 20px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.03)),
        linear-gradient(180deg, rgba(11,24,66,0.98), rgba(8,18,48,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: var(--shadow);
      min-height:94px;
      display:flex;
      flex-direction:column;
      justify-content:center;
    }

    .hero-label{
      font-size:11px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:1.2px;
      color:var(--text-muted);
      margin-bottom:8px;
    }

    .hero-main{
      font-size:24px;
      font-weight:900;
      letter-spacing:-0.3px;
      line-height:1.2;
    }

    .hero-sub{
      margin-top:4px;
      font-size:13px;
      color:var(--text-soft);
      font-weight:700;
    }

    .stats{
      display:grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap:14px;
      margin-bottom:18px;
    }

    .stat-card{
      min-height:146px;
      border-radius:24px;
      padding:18px;
      position:relative;
      overflow:hidden;
      background:
        radial-gradient(circle at 80% 20%, rgba(255,255,255,0.08), transparent 28%),
        linear-gradient(180deg, rgba(20,40,98,0.96), rgba(10,23,62,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: var(--shadow);
    }

    .stat-label{
      font-size:11px;
      font-weight:900;
      color:var(--text-muted);
      text-transform:uppercase;
      letter-spacing:1.2px;
      margin-bottom:12px;
    }

    .stat-value{
      font-size:28px;
      font-weight:900;
      letter-spacing:-0.4px;
      margin-bottom:12px;
    }

    .stat-foot{
      font-size:13px;
      color:var(--text-soft);
      line-height:1.5;
    }

    .stat-rail{
      margin-top:14px;
      height:7px;
      border-radius:999px;
      background:rgba(255,255,255,0.06);
      overflow:hidden;
    }

    .stat-rail span{
      display:block;
      height:100%;
      border-radius:inherit;
      background:linear-gradient(90deg, rgba(120,154,255,0.9), rgba(76,114,255,0.9));
      box-shadow:0 0 14px rgba(76,114,255,0.28);
    }

    .panel{
      border-radius:26px;
      padding:20px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.03)),
        linear-gradient(180deg, rgba(10,23,62,0.98), rgba(8,18,48,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: var(--shadow);
      margin-bottom:18px;
    }

    .panel-head{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:14px;
      margin-bottom:18px;
    }

    .panel-title{
      margin:0;
      font-size:22px;
      font-weight:900;
      letter-spacing:-0.3px;
    }

    .panel-sub{
      margin:6px 0 0;
      color:var(--text-muted);
      font-size:13px;
      line-height:1.5;
    }

    .head-tag{
      min-height:38px;
      display:inline-flex;
      align-items:center;
      padding:0 14px;
      border-radius:999px;
      background:rgba(255,255,255,0.05);
      border:1px solid rgba(255,255,255,0.08);
      color:var(--text-soft);
      font-size:12px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:0.8px;
      white-space:nowrap;
    }

    .controls-layout{
      display:grid;
      grid-template-columns: 1.45fr 0.8fr;
      gap:16px;
    }

    .controls-left{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:16px;
    }

    .control-card,
    .sync-card{
      min-height:292px;
      border-radius:22px;
      padding:18px;
      background:
        linear-gradient(180deg, rgba(17,38,95,0.96), rgba(12,26,66,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
      display:flex;
      flex-direction:column;
      justify-content:space-between;
    }

    .control-card h4,
    .sync-card h4{
      margin:0 0 14px;
      font-size:18px;
      font-weight:900;
      letter-spacing:-0.2px;
    }

    .control-top{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
      margin-bottom:14px;
    }

    .mode-icon{
      width:58px;
      height:58px;
      border-radius:18px;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:15px;
      font-weight:900;
      letter-spacing:0.8px;
      flex-shrink:0;
      border:1px solid rgba(255,255,255,0.08);
      background:
        radial-gradient(circle at 30% 30%, rgba(255,255,255,0.10), transparent 42%),
        linear-gradient(180deg, rgba(27,54,122,0.96), rgba(13,28,69,0.98));
      color:var(--text);
      box-shadow:0 10px 22px rgba(0,0,0,0.24);
    }

    .mode-icon.sync{
      background:
        radial-gradient(circle at 30% 30%, rgba(255,255,255,0.10), transparent 42%),
        linear-gradient(180deg, rgba(46,57,108,0.96), rgba(17,28,66,0.98));
    }

    .state-pill{
      display:inline-flex;
      align-items:center;
      gap:10px;
      min-height:42px;
      padding:0 14px;
      border-radius:999px;
      font-size:13px;
      font-weight:900;
      letter-spacing:0.4px;
      border:1px solid transparent;
      width:max-content;
      max-width:100%;
    }

    .state-pill .state-dot{
      width:10px;
      height:10px;
      border-radius:50%;
    }

    .state-pill.is-on{
      background:var(--green-bg);
      border-color:rgba(73,209,125,0.22);
      color:#baf6cf;
      box-shadow:0 0 18px rgba(73,209,125,0.08) inset;
    }

    .state-pill.is-on .state-dot{
      background:var(--green);
      box-shadow:0 0 0 5px rgba(73,209,125,0.10), 0 0 12px rgba(73,209,125,0.35);
    }

    .state-pill.is-off{
      background:var(--red-bg);
      border-color:rgba(255,95,115,0.22);
      color:#ffc3cb;
      box-shadow:0 0 18px rgba(255,95,115,0.08) inset;
    }

    .state-pill.is-off .state-dot{
      background:var(--red);
      box-shadow:0 0 0 5px rgba(255,95,115,0.10), 0 0 12px rgba(255,95,115,0.32);
    }

    .control-body{
      display:grid;
      gap:12px;
      margin-bottom:14px;
    }

    .mode-note{
      min-height:60px;
      border-radius:16px;
      padding:14px 15px;
      background:rgba(255,255,255,0.05);
      border:1px solid rgba(255,255,255,0.07);
      color:var(--text-soft);
      font-size:13px;
      line-height:1.55;
      display:flex;
      align-items:center;
    }

    .mode-mini-grid{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:10px;
    }

    .mode-mini{
      border-radius:16px;
      padding:12px 13px;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.06);
    }

    .mode-mini-label{
      font-size:10px;
      color:var(--text-muted);
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:1px;
      margin-bottom:6px;
    }

    .mode-mini-value{
      font-size:14px;
      font-weight:900;
      color:var(--text);
      line-height:1.35;
    }

    .btn-row,
    .sync-actions{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      margin-top:2px;
    }

    .btn{
      min-height:44px;
      padding:0 16px;
      border-radius:14px;
      border:1px solid rgba(255,255,255,0.10);
      cursor:pointer;
      color:var(--text);
      font-size:13px;
      font-weight:900;
      letter-spacing:0.2px;
      transition:transform 0.12s ease, opacity 0.12s ease, box-shadow 0.12s ease;
    }

    .btn:hover{
      transform:translateY(-1px);
      opacity:0.97;
    }

    .btn.start-btn{
      background:
        linear-gradient(180deg, rgba(33,60,135,0.98), rgba(17,35,82,0.98));
      box-shadow:0 10px 24px rgba(7,16,45,0.35), inset 0 1px 0 rgba(255,255,255,0.05);
    }

    .btn.stop-btn{
      background:
        linear-gradient(180deg, rgba(23,35,78,0.98), rgba(13,22,53,0.98));
      box-shadow:0 10px 24px rgba(7,16,45,0.26), inset 0 1px 0 rgba(255,255,255,0.04);
    }

    .btn.sync-btn{
      background:
        linear-gradient(180deg, rgba(30,58,130,0.98), rgba(16,34,83,0.98));
      box-shadow:0 10px 24px rgba(7,16,45,0.30), inset 0 1px 0 rgba(255,255,255,0.05);
    }

    .queue-badge{
      display:inline-flex;
      align-items:center;
      gap:10px;
      min-height:38px;
      padding:0 14px;
      border-radius:999px;
      background:var(--amber-bg);
      border:1px solid rgba(255,189,89,0.22);
      color:#ffdca0;
      font-size:12px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:0.7px;
      width:max-content;
    }

    .queue-badge::before{
      content:"";
      width:9px;
      height:9px;
      border-radius:50%;
      background:var(--amber);
      box-shadow:0 0 0 5px rgba(255,189,89,0.10), 0 0 10px rgba(255,189,89,0.28);
    }
        .logout-link{
      border: 0;
      appearance: none;
      font: inherit;
      cursor: pointer;
    }

    .toast-wrap{
      position: fixed;
      top: 18px;
      right: 18px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .toast{
      min-width: 260px;
      max-width: 360px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(9,16,52,0.96);
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 40px rgba(0,0,0,0.30);
      color: #fff;
      opacity: 0;
      transform: translateY(-12px);
      transition: opacity 0.22s ease, transform 0.22s ease;
    }

    .toast.show{
      opacity: 1;
      transform: translateY(0);
    }

    .toast.success{
      border-color: rgba(56,189,99,0.45);
    }

    .toast.error{
      border-color: rgba(255,99,132,0.40);
    }

    .toast.pending{
      border-color: rgba(255,193,7,0.45);
    }

    .toast-title{
      font-size: 14px;
      font-weight: 800;
      margin-bottom: 4px;
    }

    .toast-text{
      font-size: 13px;
      color: rgba(255,255,255,0.82);
      line-height: 1.35;
    }

    .modal-backdrop{
      position: fixed;
      inset: 0;
      background: rgba(7,12,32,0.55);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 9998;
      padding: 16px;
    }

    .modal-backdrop.show{
      display: flex;
    }

    .confirm-card{
      width: min(420px, 100%);
      background: rgba(15,26,85,0.96);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 22px;
      box-shadow: 0 24px 50px rgba(0,0,0,0.32);
      padding: 22px;
    }

    .confirm-card h3{
      margin: 0 0 10px 0;
      font-size: 22px;
      font-weight: 800;
      color: #fff;
    }

    .confirm-card p{
      margin: 0;
      color: rgba(255,255,255,0.78);
      line-height: 1.55;
      font-size: 14px;
    }

    .confirm-actions{
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 18px;
    }

    .confirm-btn{
      border: 0;
      border-radius: 14px;
      padding: 11px 16px;
      font-weight: 800;
      font-size: 14px;
      cursor: pointer;
    }

    .cancel-btn{
      background: rgba(255,255,255,0.10);
      color: #fff;
    }

    .logout-confirm-btn{
      background: linear-gradient(135deg, #4f8dff, #245dff);
      color: #fff;
    }

    .sync-summary{
      display:grid;
      gap:12px;
      margin:12px 0 14px;
    }

    .sync-mini{
      padding:12px 14px;
      border-radius:16px;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.06);
    }

    .sync-mini-label{
      font-size:11px;
      color:var(--text-muted);
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:1px;
      margin-bottom:6px;
    }

    .sync-mini-value{
      font-size:16px;
      font-weight:900;
      color:var(--text);
      line-height:1.4;
    }

    .transactions-toolbar{
      display:grid;
      grid-template-columns: 1.2fr auto auto;
      gap:12px;
      margin-bottom:14px;
      align-items:center;
    }

    .search-box{
      position:relative;
    }

    .search-box input{
      width:100%;
      height:48px;
      padding:0 16px 0 42px;
      border-radius:16px;
      outline:none;
      border:1px solid rgba(255,255,255,0.08);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02)),
        linear-gradient(180deg, rgba(12,26,67,0.98), rgba(10,22,56,0.98));
      color:var(--text);
      font-size:14px;
      font-weight:700;
    }

    .search-box svg{
      position:absolute;
      left:14px;
      top:50%;
      transform:translateY(-50%);
      opacity:0.7;
      pointer-events:none;
    }

    .chip-group{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      justify-content:flex-end;
    }

    .filter-chip{
      min-height:40px;
      padding:0 14px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,0.08);
      background:rgba(255,255,255,0.05);
      color:var(--text-soft);
      font-size:12px;
      font-weight:900;
      letter-spacing:0.5px;
      text-transform:uppercase;
      cursor:pointer;
    }

    .filter-chip.active{
      background:
        linear-gradient(180deg, rgba(78,111,255,0.26), rgba(14,28,74,0.98));
      color:var(--text);
      border-color:rgba(255,255,255,0.12);
      box-shadow:0 8px 20px rgba(0,0,0,0.20);
    }

    .table-panel{
      border-radius:26px;
      padding:22px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.03)),
        linear-gradient(180deg, rgba(10,23,62,0.98), rgba(8,18,48,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: var(--shadow);
      overflow:hidden;
      margin-bottom:18px;
    }

    .table-head{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:14px;
      margin-bottom:18px;
    }

    .table-head h3{
      margin:0;
      font-size:30px;
      font-weight:900;
      letter-spacing:-0.4px;
    }

    .table-head p{
      margin:6px 0 0;
      color:var(--text-muted);
      font-size:13px;
      line-height:1.5;
    }

    .table-chip{
      min-height:40px;
      display:inline-flex;
      align-items:center;
      padding:0 14px;
      border-radius:999px;
      background:rgba(255,255,255,0.05);
      border:1px solid rgba(255,255,255,0.08);
      color:var(--text-soft);
      font-size:12px;
      font-weight:900;
      letter-spacing:0.7px;
      text-transform:uppercase;
      white-space:nowrap;
    }

    .table-shell{
      border-radius:20px;
      overflow:hidden;
      border:1px solid rgba(255,255,255,0.06);
      background:linear-gradient(180deg, rgba(16,33,80,0.96), rgba(11,23,59,0.98));
    }

    table{
      width:100%;
      border-collapse:collapse;
    }

    thead th{
      text-align:left;
      padding:16px 18px;
      color:var(--text-muted);
      font-size:11px;
      font-weight:900;
      letter-spacing:1px;
      text-transform:uppercase;
      background:rgba(255,255,255,0.04);
    }

    tbody td{
      padding:18px;
      border-top:1px solid rgba(255,255,255,0.06);
      color:var(--text);
      font-size:14px;
      vertical-align:middle;
    }

    tbody tr:hover{
      background:rgba(255,255,255,0.03);
    }

    .cell-strong{
      font-weight:800;
    }

    .amount{
      font-size:16px;
      font-weight:900;
      letter-spacing:-0.2px;
    }

    .method-badge,
    .status-badge,
    .activity-badge{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap:8px;
      min-height:32px;
      padding:0 12px;
      border-radius:999px;
      font-size:11px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:0.6px;
      border:1px solid transparent;
      white-space:nowrap;
    }

    .method-badge::before,
    .status-badge::before,
    .activity-badge::before{
      content:"";
      width:8px;
      height:8px;
      border-radius:50%;
    }

    .method-badge.online{
      color:#bce9ff;
      background:rgba(105,209,255,0.12);
      border-color:rgba(105,209,255,0.18);
    }

    .method-badge.online::before{
      background:var(--cyan);
      box-shadow:0 0 10px rgba(105,209,255,0.35);
    }

    .method-badge.offline{
      color:#d3c7ff;
      background:rgba(151,122,255,0.12);
      border-color:rgba(151,122,255,0.18);
    }

    .method-badge.offline::before{
      background:#977aff;
      box-shadow:0 0 10px rgba(151,122,255,0.30);
    }

    .status-badge.success,
    .activity-badge.success{
      color:#baf6cf;
      background:var(--green-bg);
      border-color:rgba(73,209,125,0.20);
    }

    .status-badge.success::before,
    .activity-badge.success::before{
      background:var(--green);
      box-shadow:0 0 10px rgba(73,209,125,0.36);
    }

    .status-badge.failed,
    .activity-badge.failed{
      color:#ffc3cb;
      background:var(--red-bg);
      border-color:rgba(255,95,115,0.20);
    }

    .status-badge.failed::before,
    .activity-badge.failed::before{
      background:var(--red);
      box-shadow:0 0 10px rgba(255,95,115,0.30);
    }

    .status-badge.pending,
    .activity-badge.pending{
      color:#ffdca0;
      background:var(--amber-bg);
      border-color:rgba(255,189,89,0.20);
    }

    .status-badge.pending::before,
    .activity-badge.pending::before{
      background:var(--amber);
      box-shadow:0 0 10px rgba(255,189,89,0.28);
    }

    .status-badge.default,
    .activity-badge.default{
      color:var(--text-soft);
      background:rgba(255,255,255,0.08);
      border-color:rgba(255,255,255,0.08);
    }

    .status-badge.default::before,
    .activity-badge.default::before{
      background:#cad5ff;
      box-shadow:0 0 10px rgba(202,213,255,0.22);
    }

    .activity-badge.info{
      color:#cdeeff;
      background:rgba(105,209,255,0.12);
      border-color:rgba(105,209,255,0.20);
    }

    .activity-badge.info::before{
      background:var(--cyan);
      box-shadow:0 0 10px rgba(105,209,255,0.30);
    }

    .note-text{
      color:var(--text-soft);
    }

    .empty-state{
      padding:28px 18px;
      text-align:center;
      color:var(--text-muted);
      font-weight:800;
    }

    .analytics-top{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:20px;
      margin-bottom:18px;
    }

    .analytics-chips{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      justify-content:flex-end;
    }

    .status-chip{
      min-height:44px;
      padding:0 14px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,0.08);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.03)),
        linear-gradient(180deg, rgba(11,25,67,0.98), rgba(9,20,54,0.98));
      color:var(--text-soft);
      display:inline-flex;
      align-items:center;
      gap:10px;
      font-size:13px;
      font-weight:900;
      white-space:nowrap;
    }

    .status-chip::before{
      content:"";
      width:9px;
      height:9px;
      border-radius:50%;
      background:var(--red);
      box-shadow:0 0 0 6px rgba(255,95,115,0.10), 0 0 12px rgba(255,95,115,0.30);
    }

    .status-chip.live::before{
      background:var(--green);
      box-shadow:0 0 0 6px rgba(73,209,125,0.10), 0 0 12px rgba(73,209,125,0.34);
    }

    .analytics-grid{
      display:grid;
      grid-template-columns: 1.5fr 1fr;
      gap:16px;
      margin-bottom:18px;
    }

    .analytics-side{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:16px;
    }

    .chart-card{
      border-radius:24px;
      padding:18px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.03)),
        linear-gradient(180deg, rgba(12,26,67,0.98), rgba(9,20,53,0.98));
      border:1px solid rgba(255,255,255,0.08);
      box-shadow: var(--shadow);
      min-height:320px;
    }

    .chart-title{
      font-size:18px;
      font-weight:900;
      margin:0 0 6px;
      letter-spacing:-0.2px;
    }

    .chart-sub{
      color:var(--text-muted);
      font-size:13px;
      line-height:1.5;
      margin-bottom:14px;
      font-weight:700;
    }

    .bars-wrap{
      height:230px;
      border-radius:18px;
      padding:16px 18px 10px;
      border:1px solid rgba(255,255,255,0.06);
      background:rgba(255,255,255,0.03);
      display:flex;
      align-items:flex-end;
      justify-content:space-between;
      gap:14px;
    }

    .bar-col{
      flex:1;
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:flex-end;
      gap:10px;
      height:100%;
    }

    .bar{
      width:100%;
      max-width:42px;
      border-radius:10px 10px 8px 8px;
      background:linear-gradient(180deg, rgba(122,168,255,0.95), rgba(78,124,255,0.95));
      box-shadow:0 10px 22px rgba(78,124,255,0.24);
      min-height:12px;
      transition:height 0.25s ease;
    }

    .bar-label{
      font-size:12px;
      color:var(--text-soft);
      font-weight:800;
      letter-spacing:0.2px;
    }

    .donut-wrap{
      display:flex;
      align-items:center;
      justify-content:center;
      margin:10px 0 18px;
    }

    .donut{
      width:150px;
      height:150px;
      border-radius:50%;
      position:relative;
      display:flex;
      align-items:center;
      justify-content:center;
    }

    .donut::after{
      content:"";
      position:absolute;
      width:98px;
      height:98px;
      border-radius:50%;
      background:linear-gradient(180deg, rgba(10,23,62,0.98), rgba(8,18,48,0.98));
      border:1px solid rgba(255,255,255,0.05);
      box-shadow:inset 0 1px 0 rgba(255,255,255,0.04);
    }

    .donut-center{
      position:relative;
      z-index:1;
      text-align:center;
    }

    .donut-value{
      font-size:20px;
      font-weight:900;
      line-height:1;
      margin-bottom:6px;
    }

    .donut-label{
      font-size:11px;
      font-weight:900;
      color:var(--text-muted);
      letter-spacing:1px;
      text-transform:uppercase;
    }

    .legend{
      display:grid;
      gap:10px;
      margin-top:6px;
    }

    .legend-row{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      padding:10px 12px;
      border-radius:14px;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.06);
      font-size:13px;
      font-weight:800;
      color:var(--text-soft);
    }

    .legend-left{
      display:flex;
      align-items:center;
      gap:10px;
    }

    .legend-dot{
      width:9px;
      height:9px;
      border-radius:50%;
    }

    .activity-list{
      display:grid;
      gap:12px;
    }

    .activity-item{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:14px;
      padding:14px 16px;
      border-radius:18px;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.06);
    }

    .activity-left{
      display:flex;
      align-items:flex-start;
      gap:12px;
      min-width:0;
      flex:1;
    }

    .activity-icon{
      width:42px;
      height:42px;
      border-radius:14px;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:11px;
      font-weight:900;
      letter-spacing:0.8px;
      border:1px solid rgba(255,255,255,0.08);
      background:
        radial-gradient(circle at 30% 30%, rgba(255,255,255,0.08), transparent 45%),
        linear-gradient(180deg, rgba(24,46,108,0.95), rgba(12,25,63,0.98));
      color:var(--text);
      flex-shrink:0;
    }

    .activity-text{
      min-width:0;
      flex:1;
    }

    .activity-title{
      font-size:14px;
      font-weight:900;
      color:var(--text);
      margin-bottom:4px;
      line-height:1.35;
    }

    .activity-detail{
      font-size:12px;
      color:var(--text-soft);
      line-height:1.5;
    }

    .activity-time{
      font-size:11px;
      color:var(--text-muted);
      font-weight:800;
      margin-top:6px;
      letter-spacing:0.2px;
    }

    .activity-right{
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }

    @media (max-width: 1380px){
      .analytics-grid{
        grid-template-columns:1fr;
      }
    }

    @media (max-width: 1320px){
      .stats{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .hero-strip{
        grid-template-columns: 1fr;
      }

      .controls-layout{
        grid-template-columns: 1fr;
      }

      .transactions-toolbar{
        grid-template-columns:1fr;
      }
    }

    @media (max-width: 1080px){
      body{
        grid-template-columns: 1fr;
        overflow:auto;
      }

      .sidebar{
        position:relative;
        height:auto;
      }

      .main{
        height:auto;
        overflow:visible;
      }

      .controls-left{
        grid-template-columns: 1fr;
      }

      .analytics-side{
        grid-template-columns:1fr;
      }
    }

    @media (max-width: 760px){
      .main{
        padding:16px;
      }

      .header,
      .analytics-top{
        flex-direction:column;
      }

      .header h2{
        font-size:34px;
      }

      .stats{
        grid-template-columns: 1fr;
      }

      thead{
        display:none;
      }

      table, tbody, tr, td{
        display:block;
        width:100%;
      }

      tbody td{
        padding:10px 16px;
        border-top:0;
      }

      tbody tr{
        padding:10px 0;
        border-top:1px solid rgba(255,255,255,0.06);
      }

      tbody td::before{
        content:attr(data-label);
        display:block;
        color:var(--text-muted);
        font-size:11px;
        font-weight:900;
        letter-spacing:0.8px;
        text-transform:uppercase;
        margin-bottom:4px;
      }

      .activity-item{
        flex-direction:column;
      }

      .activity-right{
        justify-content:flex-start;
      }
    }
  </style>
</head>
<body>

  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo-wrap">
        <img src="/college-logo" alt="Islington College Logo" class="brand-logo">
      </div>
      <div class="brand-divider"></div>
      <div class="brand-text">
        <h1 class="brand-title">CollegeWallet</h1>
        <p class="brand-subtitle">Merchant Portal</p>
      </div>
    </div>

    <nav class="nav">
      <button type="button" class="nav-link active" data-page-target="overviewPage">
        <span class="nav-left">
          <span class="nav-dot"></span>
          <span>Overview</span>
        </span>
        <span class="nav-right">Live</span>
      </button>

      <button type="button" class="nav-link" data-page-target="transactionsPage">
        <span class="nav-left">
          <span class="nav-dot"></span>
          <span>Transactions</span>
        </span>
        <span class="nav-right">Records</span>
      </button>

      <button type="button" class="nav-link" data-page-target="analyticsPage">
        <span class="nav-left">
          <span class="nav-dot"></span>
          <span>Analytics</span>
        </span>
        <span class="nav-right">Insights</span>
      </button>
    </nav>

    <div class="sidebar-card">
      <div class="card-label">System Status</div>

      <div class="status-list">
        <div class="status-row">
          <div class="status-left">
            <span class="signal-dot {% if is_active %}on{% else %}off{% endif %}" id="onlineSideDot"></span>
            <div class="status-name">Online Accepting</div>
          </div>
          <div class="status-text {% if is_active %}live{% else %}dead{% endif %}" id="statusText">
            {% if is_active %}Active{% else %}Inactive{% endif %}
          </div>
        </div>

        <div class="status-row">
          <div class="status-left">
            <span class="signal-dot off" id="offlineDot"></span>
            <div class="status-name">Offline Accepting</div>
          </div>
          <div class="status-text dead" id="offlineAcceptingState">Inactive</div>
        </div>
      </div>
    </div>

    <div class="sidebar-card">
      <div class="card-label">Merchant</div>
      <div class="merchant-name">{{ merchant.full_name }}</div>
      <div class="merchant-meta">
        Username: {{ merchant.username }}<br/>
        Merchant ID: {{ merchant.student_id }}
      </div>
    </div>

    <button type="button" class="logout-link" id="logoutBtn">Logout</button>
  </aside>

  <main class="main">

    <section class="page active" id="overviewPage">
      <section class="header">
        <div>
          <h2>Overview</h2>
        </div>

        <div class="header-right">
          <div class="top-chip">Merchant ID <b>{{ merchant.student_id }}</b></div>
          <div class="top-chip">Network <b>{{ network_id }}</b></div>
        </div>
      </section>

      <section class="hero-strip">
        <div class="hero-card">
          <div class="hero-label">Merchant Details</div>
          <div class="hero-main">{{ merchant.full_name }}</div>
          <div class="hero-sub">ID: {{ merchant.student_id }} &nbsp;•&nbsp; Username: {{ merchant.username }}</div>
        </div>

        <div class="hero-card">
          <div class="hero-label">Network</div>
          <div class="hero-main">{{ network_id }}</div>
          <div class="hero-sub">Current merchant network</div>
        </div>

        <div class="hero-card">
          <div class="hero-label">Dashboard State</div>
          <div class="hero-main" id="msg">System ready</div>
          <div class="hero-sub">Merchant operations available</div>
        </div>
      </section>

      <section class="stats">
        <div class="stat-card">
          <div class="stat-label">Wallet Balance</div>
          <div class="stat-value">{{ "%.2f"|format(merchant.balance) }}</div>
          <div class="stat-foot">Current merchant wallet balance</div>
          <div class="stat-rail"><span style="width:82%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">30 Day Revenue</div>
          <div class="stat-value">{{ "%.2f"|format(metrics.total_30) }}</div>
          <div class="stat-foot">Successful incoming transactions</div>
          <div class="stat-rail"><span style="width:68%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Average Ticket</div>
          <div class="stat-value">{{ "%.2f"|format(metrics.avg_tx) }}</div>
          <div class="stat-foot">Average successful payment amount</div>
          <div class="stat-rail"><span style="width:56%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Offline Queue</div>
          <div class="stat-value" id="offlinePendingCount">0</div>
          <div class="stat-foot">Pending records waiting for sync</div>
          <div class="stat-rail"><span style="width:38%;"></span></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3 class="panel-title">Payment Control Center</h3>
            <p class="panel-sub">Live payment controls and offline queue sync.</p>
          </div>
          <div class="head-tag">Controls</div>
        </div>

        <div class="controls-layout">
          <div class="controls-left">
            <div class="control-card">
              <div>
                <div class="control-top">
                  <div>
                    <h4>Online Payment</h4>
                    <div class="state-pill {% if is_active %}is-on{% else %}is-off{% endif %}" id="onlineStatusPill">
                      <span class="state-dot"></span>
                      <b id="onlineStatusChip">{% if is_active %}Active{% else %}Inactive{% endif %}</b>
                    </div>
                  </div>
                  <div class="mode-icon">NET</div>
                </div>

                <div class="control-body">
                  <div class="mode-note" id="onlineCardNote">
                    {% if is_active %}
                    Online payment is active. Students on the same network can connect and pay.
                    {% else %}
                    Online payment is inactive. Students cannot connect until accepting is started.
                    {% endif %}
                  </div>

                  <div class="mode-mini-grid">
                    <div class="mode-mini">
                      <div class="mode-mini-label">Visibility</div>
                      <div class="mode-mini-value">Same Network</div>
                    </div>
                    <div class="mode-mini">
                      <div class="mode-mini-label">Discovery</div>
                      <div class="mode-mini-value" id="onlineMiniState">{% if is_active %}Available{% else %}Hidden{% endif %}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="btn-row">
                <button class="btn start-btn" id="startBtn">Start Accepting</button>
                <button class="btn stop-btn" id="stopBtn">Stop Accepting</button>
              </div>
            </div>

            <div class="control-card">
              <div>
                <div class="control-top">
                  <div>
                    <h4>Offline Payment</h4>
                    <div class="state-pill is-off" id="offlineStatusPill">
                      <span class="state-dot"></span>
                      <b id="offlineStatusChip">Inactive</b>
                    </div>
                  </div>
                  <div class="mode-icon">BT</div>
                </div>

                <div class="control-body">
                  <div class="mode-note" id="offlineCardNote">
                    Offline tap is inactive. Nearby payments are not being accepted by the receiver.
                  </div>

                  <div class="mode-mini-grid">
                    <div class="mode-mini">
                      <div class="mode-mini-label">Receiver</div>
                      <div class="mode-mini-value" id="offlineMiniState">Stopped</div>
                    </div>
                    <div class="mode-mini">
                      <div class="mode-mini-label">Storage</div>
                      <div class="mode-mini-value">Local Queue</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="btn-row">
                <button class="btn start-btn" id="startOfflineBtn">Start Accepting</button>
                <button class="btn stop-btn" id="stopOfflineBtn">Stop Accepting</button>
              </div>
            </div>
          </div>

          <div class="sync-card">
            <div>
              <div class="control-top">
                <div>
                  <h4>Sync Queue</h4>
                  <div class="queue-badge" id="offlineQueueChip">0 Pending</div>
                </div>
                <div class="mode-icon sync">SYNC</div>
              </div>

              <div class="sync-summary">
                <div class="sync-mini">
                  <div class="sync-mini-label">Queue Status</div>
                  <div class="sync-mini-value">Offline records waiting for sync</div>
                </div>

                <div class="sync-mini">
                  <div class="sync-mini-label">Sync Output</div>
                  <div class="sync-mini-value" id="syncMessageBox">Queue ready.</div>
                </div>
              </div>
            </div>

            <div class="sync-actions">
              <button class="btn sync-btn" id="syncOfflineBtn">Sync Now</button>
            </div>
          </div>
        </div>
      </section>
    </section>

    <section class="page" id="transactionsPage">
      <section class="header">
        <div>
          <h2>Transaction History</h2>
          <div class="header-sub">Search, filter, and review online and offline payment records.</div>
        </div>

        <div class="header-right">
          <div class="table-chip">All Transactions</div>
        </div>
      </section>

      <section class="stats">
        <div class="stat-card">
          <div class="stat-label">Records Shown</div>
          <div class="stat-value" id="txRecordsShown">0</div>
          <div class="stat-foot">Visible rows after filters</div>
          <div class="stat-rail"><span style="width:72%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Filtered Amount</div>
          <div class="stat-value" id="txFilteredAmount">0.00</div>
          <div class="stat-foot">Visible transaction amount total</div>
          <div class="stat-rail"><span style="width:58%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Online Records</div>
          <div class="stat-value" id="txOnlineCount">0</div>
          <div class="stat-foot">Visible online transaction count</div>
          <div class="stat-rail"><span style="width:50%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Offline Records</div>
          <div class="stat-value" id="txOfflineCount">0</div>
          <div class="stat-foot">Visible offline transaction count</div>
          <div class="stat-rail"><span style="width:44%;"></span></div>
        </div>
      </section>

      <section class="table-panel">
        <div class="transactions-toolbar">
          <div class="search-box">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M21 21L16.65 16.65M11 18C7.13401 18 4 14.866 4 11C4 7.13401 7.13401 4 11 4C14.866 4 18 7.13401 18 11C18 14.866 14.866 18 11 18Z" stroke="#a6b8ea" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <input id="txSearchInput" type="text" placeholder="Search by payer, method, note, amount, or time...">
          </div>

          <div class="chip-group" id="methodFilters">
            <button class="filter-chip active" data-filter-type="method" data-filter-value="all">All</button>
            <button class="filter-chip" data-filter-type="method" data-filter-value="online">Online</button>
            <button class="filter-chip" data-filter-type="method" data-filter-value="offline">Offline</button>
          </div>

          <div class="chip-group" id="statusFilters">
            <button class="filter-chip active" data-filter-type="status" data-filter-value="all">Any Status</button>
            <button class="filter-chip" data-filter-type="status" data-filter-value="success">Success</button>
            <button class="filter-chip" data-filter-type="status" data-filter-value="failed">Failed</button>
            <button class="filter-chip" data-filter-type="status" data-filter-value="pending">Pending</button>
          </div>
        </div>

        <div class="table-shell">
          <table id="transactionsTable">
            <thead>
              <tr>
                <th>Time</th>
                <th>From</th>
                <th>To</th>
                <th>Amount</th>
                <th>Method</th>
                <th>Status</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {% if txs|length == 0 %}
                <tr>
                  <td colspan="7" class="empty-state">No transactions yet.</td>
                </tr>
              {% else %}
                {% for t in txs %}
                  <tr
                    data-tx-row="1"
                    data-created="{{ t.created_at }}"
                    data-from="{{ t.sender_username }}"
                    data-to="{{ t.receiver_username }}"
                    data-amount="{{ "%.2f"|format(t.amount) }}"
                    data-method="{{ (t.method or '')|lower }}"
                    data-status="{{ (t.status or '')|lower }}"
                    data-note="{{ t.note or '' }}"
                  >
                    <td data-label="Time">{{ t.created_at }}</td>
                    <td data-label="From" class="cell-strong">{{ t.sender_username }}</td>
                    <td data-label="To" class="cell-strong">{{ t.receiver_username }}</td>
                    <td data-label="Amount" class="amount">{{ "%.2f"|format(t.amount) }}</td>
                    <td data-label="Method">
                      <span class="method-badge {{ 'online' if (t.method or '')|lower == 'online' else 'offline' }}">
                        {{ t.method }}
                      </span>
                    </td>
                    <td data-label="Status">
                      {% if t.status == "SUCCESS" %}
                        <span class="status-badge success">Success</span>
                      {% elif t.status == "FAILED" %}
                        <span class="status-badge failed">Failed</span>
                      {% elif t.status == "PENDING" %}
                        <span class="status-badge pending">Pending</span>
                      {% else %}
                        <span class="status-badge default">{{ t.status }}</span>
                      {% endif %}
                    </td>
                    <td data-label="Note" class="note-text">{{ t.note or "-" }}</td>
                  </tr>
                {% endfor %}
              {% endif %}
            </tbody>
          </table>
        </div>
      </section>
    </section>

    <section class="page" id="analyticsPage">
      <section class="analytics-top">
        <div>
          <h2 style="margin:0; font-size:44px; font-weight:900; letter-spacing:-0.8px; line-height:1;">Analytics</h2>
          <div class="header-sub">Visual payment summary, method split, trends, and recent activity.</div>
        </div>

        <div class="analytics-chips">
          <div class="status-chip {% if is_active %}live{% endif %}" id="analyticsOnlineChip">Online: <b id="analyticsOnlineText">{% if is_active %}ACTIVE{% else %}INACTIVE{% endif %}</b></div>
          <div class="status-chip" id="analyticsOfflineChip">Offline: <b id="analyticsOfflineText">INACTIVE</b></div>
          <div class="status-chip live" id="analyticsQueueChip">Queue: <b id="analyticsQueueText">0</b></div>
        </div>
      </section>

      <section class="stats">
        <div class="stat-card">
          <div class="stat-label">Revenue (30 Days)</div>
          <div class="stat-value">{{ "%.2f"|format(metrics.total_30) }}</div>
          <div class="stat-foot">Successful incoming transaction value</div>
          <div class="stat-rail"><span style="width:74%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Average Transaction</div>
          <div class="stat-value">{{ "%.2f"|format(metrics.avg_tx) }}</div>
          <div class="stat-foot">Average successful payment amount</div>
          <div class="stat-rail"><span style="width:61%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Daily Transactions Avg</div>
          <div class="stat-value">{{ "%.1f"|format(metrics.daily_avg) }}</div>
          <div class="stat-foot">Average successful count across 30 days</div>
          <div class="stat-rail"><span style="width:47%;"></span></div>
        </div>

        <div class="stat-card">
          <div class="stat-label">Current Queue</div>
          <div class="stat-value" id="analyticsQueueCount">0</div>
          <div class="stat-foot">Pending offline records waiting for sync</div>
          <div class="stat-rail"><span style="width:38%;"></span></div>
        </div>
      </section>

      <section class="analytics-grid">
        <div class="chart-card">
          <h3 class="chart-title">Transactions by Day</h3>
          <div class="chart-sub">A visual breakdown from recent transaction records.</div>

          <div class="bars-wrap" id="barsWrap">
            <div class="bar-col"><div class="bar" id="barSun" style="height:20px;"></div><div class="bar-label">Sun</div></div>
            <div class="bar-col"><div class="bar" id="barMon" style="height:20px;"></div><div class="bar-label">Mon</div></div>
            <div class="bar-col"><div class="bar" id="barTue" style="height:20px;"></div><div class="bar-label">Tue</div></div>
            <div class="bar-col"><div class="bar" id="barWed" style="height:20px;"></div><div class="bar-label">Wed</div></div>
            <div class="bar-col"><div class="bar" id="barThu" style="height:20px;"></div><div class="bar-label">Thu</div></div>
            <div class="bar-col"><div class="bar" id="barFri" style="height:20px;"></div><div class="bar-label">Fri</div></div>
            <div class="bar-col"><div class="bar" id="barSat" style="height:20px;"></div><div class="bar-label">Sat</div></div>
          </div>
        </div>

        <div class="analytics-side">
          <div class="chart-card">
            <h3 class="chart-title">Method Split</h3>
            <div class="chart-sub">Online and offline payment volume.</div>

            <div class="donut-wrap">
              <div class="donut" id="methodDonut">
                <div class="donut-center">
                  <div class="donut-value" id="methodDonutTotal">0</div>
                  <div class="donut-label">Payments</div>
                </div>
              </div>
            </div>

            <div class="legend">
              <div class="legend-row">
                <div class="legend-left">
                  <span class="legend-dot" style="background:#4f8cff;"></span>
                  <span>Online</span>
                </div>
                <span id="legendOnlineCount">0</span>
              </div>

              <div class="legend-row">
                <div class="legend-left">
                  <span class="legend-dot" style="background:#35c4ff;"></span>
                  <span>Offline</span>
                </div>
                <span id="legendOfflineCount">0</span>
              </div>
            </div>
          </div>

          <div class="chart-card">
            <h3 class="chart-title">Status Split</h3>
            <div class="chart-sub">Outcome across recorded transactions.</div>

            <div class="donut-wrap">
              <div class="donut" id="statusDonut">
                <div class="donut-center">
                  <div class="donut-value" id="statusDonutTotal">0</div>
                  <div class="donut-label">Statuses</div>
                </div>
              </div>
            </div>

            <div class="legend">
              <div class="legend-row">
                <div class="legend-left">
                  <span class="legend-dot" style="background:#42d876;"></span>
                  <span>Success</span>
                </div>
                <span id="legendSuccessCount">0</span>
              </div>

              <div class="legend-row">
                <div class="legend-left">
                  <span class="legend-dot" style="background:#ff667d;"></span>
                  <span>Failed / Other</span>
                </div>
                <span id="legendFailedCount">0</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3 class="panel-title">Recent Activity</h3>
            <p class="panel-sub">Latest payment and operational events.</p>
          </div>
          <div class="head-tag">Last 10</div>
        </div>

        <div class="activity-list" id="recentActivityFeed"></div>
      </section>
    </section>

  </main>

    <div class="toast-wrap" id="toastWrap"></div>

  <div class="modal-backdrop" id="logoutModal">
    <div class="confirm-card">
      <h3>Confirm Logout</h3>
      <p>Are you sure you want to log out from the merchant dashboard?</p>

      <div class="confirm-actions">
        <button type="button" class="confirm-btn cancel-btn" id="cancelLogoutBtn">Cancel</button>
        <button type="button" class="confirm-btn logout-confirm-btn" id="confirmLogoutBtn">Logout</button>
      </div>
    </div>
  </div>

<script>
let timer = null;
const merchantUsername = "{{ merchant.username }}";
const networkId = "{{ network_id }}";

const toastWrap = document.getElementById("toastWrap");
const logoutModal = document.getElementById("logoutModal");
const logoutBtn = document.getElementById("logoutBtn");
const confirmLogoutBtn = document.getElementById("confirmLogoutBtn");
const cancelLogoutBtn = document.getElementById("cancelLogoutBtn");

function showToast(message, type = "success", title = "Notification") {
  if (!toastWrap || !message) return;

  const toast = document.createElement("div");
  toast.className = "toast " + type;
  toast.innerHTML = `
    <div class="toast-title">${title}</div>
    <div class="toast-text">${message}</div>
  `;

  toastWrap.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));

  setTimeout(() => {
    toast.classList.remove("show");
  }, 2600);

  setTimeout(() => {
    toast.remove();
  }, 3000);
}

function showPageToast() {
  const code = {{ request.args.get('toast', '')|tojson }};
  const map = {
    login_success: {
      title: "Login",
      message: "Logged in successfully ✅",
      type: "success"
    }
  };

  const item = map[code];
  if (item) {
    showToast(item.message, item.type, item.title);
  }
}

function openLogoutModal() {
  if (logoutModal) logoutModal.classList.add("show");
}

function closeLogoutModal() {
  if (logoutModal) logoutModal.classList.remove("show");
}

if (logoutBtn) {
  logoutBtn.addEventListener("click", openLogoutModal);
}

if (cancelLogoutBtn) {
  cancelLogoutBtn.addEventListener("click", closeLogoutModal);
}

if (confirmLogoutBtn) {
  confirmLogoutBtn.addEventListener("click", () => {
    window.location.href = "/merchant/logout";
  });
}

if (logoutModal) {
  logoutModal.addEventListener("click", (e) => {
    if (e.target === logoutModal) {
      closeLogoutModal();
    }
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeLogoutModal();
  }
});

showPageToast();
const ACTIVITY_STORAGE_KEY = "cw_activity_" + merchantUsername;

const recentPaymentActivities = [
  {% for t in txs[:10] %}
  {
    ts: {{ (t.created_at ~ '')|tojson }},
    title: {{ ((t.sender_username or '') ~ " → " ~ (t.receiver_username or ''))|tojson }},
    detail: {{ ("Amount " ~ ("%.2f"|format(t.amount)) ~ " · " ~ (t.method or '') ~ ((" · " ~ t.note) if t.note else ""))|tojson }},
    state: {{ ((t.status or 'success')|lower)|tojson }},
    badge: {{ (t.status or 'Recorded')|tojson }},
    icon: "TX"
  },
  {% endfor %}
];

function formatNumber(n) {
  return Number(n || 0).toFixed(2);
}

function parseDateValue(raw) {
  if (!raw) return null;
  let fixed = String(raw).trim().replace(" ", "T");
  let d = new Date(fixed);
  if (!isNaN(d.getTime())) return d;
  d = new Date(raw);
  if (!isNaN(d.getTime())) return d;
  return null;
}

function formatActivityTime(raw) {
  const d = parseDateValue(raw);
  if (!d) return raw || "--";
  return d.toLocaleString();
}

function loadStoredActivities() {
  try {
    const raw = localStorage.getItem(ACTIVITY_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveStoredActivities(items) {
  try {
    localStorage.setItem(ACTIVITY_STORAGE_KEY, JSON.stringify(items.slice(0, 10)));
  } catch (e) {}
}

function pushOperationalActivity(title, detail, state, badge, icon) {
  const items = loadStoredActivities();
  items.unshift({
    ts: new Date().toISOString(),
    title: title,
    detail: detail,
    state: state || "info",
    badge: badge || "Event",
    icon: icon || "EV"
  });
  saveStoredActivities(items.slice(0, 10));
  renderRecentActivity();
}

function getCombinedActivities() {
  const operational = loadStoredActivities();
  const combined = [...operational, ...recentPaymentActivities];

  combined.sort((a, b) => {
    const ta = parseDateValue(a.ts);
    const tb = parseDateValue(b.ts);
    const va = ta ? ta.getTime() : 0;
    const vb = tb ? tb.getTime() : 0;
    return vb - va;
  });

  return combined.slice(0, 10);
}

function renderRecentActivity() {
  const wrap = document.getElementById("recentActivityFeed");
  if (!wrap) return;

  const items = getCombinedActivities();

  if (!items.length) {
    wrap.innerHTML = '<div class="empty-state">No recent activity available.</div>';
    return;
  }

  wrap.innerHTML = items.map(item => {
    const stateClass = ["success", "failed", "pending", "info", "default"].includes((item.state || "").toLowerCase())
      ? item.state.toLowerCase()
      : "default";

    return `
      <div class="activity-item">
        <div class="activity-left">
          <div class="activity-icon">${item.icon || "EV"}</div>
          <div class="activity-text">
            <div class="activity-title">${item.title || "Activity"}</div>
            <div class="activity-detail">${item.detail || ""}</div>
            <div class="activity-time">${formatActivityTime(item.ts)}</div>
          </div>
        </div>
        <div class="activity-right">
          <span class="activity-badge ${stateClass}">${item.badge || "Event"}</span>
        </div>
      </div>
    `;
  }).join("");
}

function setPillState(pillId, textId, isActive) {
  const pill = document.getElementById(pillId);
  const text = document.getElementById(textId);

  if (pill) {
    pill.classList.remove("is-on", "is-off");
    pill.classList.add(isActive ? "is-on" : "is-off");
  }

  if (text) {
    text.innerText = isActive ? "Active" : "Inactive";
  }
}

function setSideState(dotId, textId, isActive) {
  const dot = document.getElementById(dotId);
  const text = document.getElementById(textId);

  if (dot) {
    dot.classList.remove("on", "off");
    dot.classList.add(isActive ? "on" : "off");
  }

  if (text) {
    text.classList.remove("live", "dead");
    text.classList.add(isActive ? "live" : "dead");
    text.innerText = isActive ? "Active" : "Inactive";
  }
}

function syncOnlineVisualState(isActive) {
  setSideState("onlineSideDot", "statusText", isActive);
  setPillState("onlineStatusPill", "onlineStatusChip", isActive);

  const analyticsOnlineChip = document.getElementById("analyticsOnlineChip");
  const analyticsOnlineText = document.getElementById("analyticsOnlineText");
  const onlineCardNote = document.getElementById("onlineCardNote");
  const onlineMiniState = document.getElementById("onlineMiniState");

  if (analyticsOnlineChip) analyticsOnlineChip.classList.toggle("live", !!isActive);
  if (analyticsOnlineText) analyticsOnlineText.innerText = isActive ? "ACTIVE" : "INACTIVE";
  if (onlineCardNote) {
    onlineCardNote.innerText = isActive
      ? "Online payment is active. Students on the same network can connect and pay."
      : "Online payment is inactive. Students cannot connect until accepting is started.";
  }
  if (onlineMiniState) {
    onlineMiniState.innerText = isActive ? "Available" : "Hidden";
  }
}

function syncOfflineVisualState(isActive) {
  const stateText = document.getElementById("offlineAcceptingState");
  const offlineCardNote = document.getElementById("offlineCardNote");
  const offlineMiniState = document.getElementById("offlineMiniState");

  const dot = document.getElementById("offlineDot");
  if (dot) {
    dot.classList.remove("on", "off");
    dot.classList.add(isActive ? "on" : "off");
  }

  if (stateText) {
    stateText.classList.remove("live", "dead");
    stateText.classList.add(isActive ? "live" : "dead");
    stateText.innerText = isActive ? "Active" : "Inactive";
  }

  setPillState("offlineStatusPill", "offlineStatusChip", isActive);

  if (offlineCardNote) {
    offlineCardNote.innerText = isActive
      ? "Offline tap is active. Nearby payments can be received and stored in the local queue."
      : "Offline tap is inactive. Nearby payments are not being accepted by the receiver.";
  }

  if (offlineMiniState) {
    offlineMiniState.innerText = isActive ? "Ready" : "Stopped";
  }

  const analyticsOfflineChip = document.getElementById("analyticsOfflineChip");
  const analyticsOfflineText = document.getElementById("analyticsOfflineText");
  if (analyticsOfflineChip) analyticsOfflineChip.classList.toggle("live", !!isActive);
  if (analyticsOfflineText) analyticsOfflineText.innerText = isActive ? "ACTIVE" : "INACTIVE";
}

async function checkin() {
  const msg = document.getElementById("msg");
  try {
    const res = await fetch("/merchant/checkin", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ merchant_username: merchantUsername, networkId: networkId })
    });
    const data = await res.json();

    if (data.status === "success") {
      syncOnlineVisualState(true);
      if (msg) msg.innerText = "Online active";
      pushOperationalActivity("Online payment active", "Students can now connect on " + networkId, "success", "Active", "NET");
      showToast("Online accepting started ✅", "success", "Online Payment");
    } else {
      if (msg) msg.innerText = "Online unavailable";
      pushOperationalActivity("Online payment update failed", "Merchant presence could not be activated.", "failed", "Failed", "NET");
      showToast(data.message || "Could not start online accepting.", "error", "Online Payment");
    }
  } catch (e) {
    if (msg) msg.innerText = "Online unreachable";
    pushOperationalActivity("Online payment unreachable", "Service could not be reached from the dashboard.", "failed", "Error", "NET");
    showToast("Backend not reachable for online accepting.", "error", "Online Payment");
  }
}

async function checkout() {
  const msg = document.getElementById("msg");
  try {
    const res = await fetch("/merchant/checkout", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ merchant_username: merchantUsername })
    });
    const data = await res.json();

    if (data.status === "success") {
      syncOnlineVisualState(false);
      if (msg) msg.innerText = "Online inactive";
      pushOperationalActivity("Online payment inactive", "Network payment acceptance was stopped.", "failed", "Inactive", "NET");
      showToast("Online accepting stopped ✅", "success", "Online Payment");
    } else {
      if (msg) msg.innerText = "Online stop failed";
      pushOperationalActivity("Online payment stop failed", "The dashboard could not stop online accepting.", "failed", "Failed", "NET");
      showToast(data.message || "Could not stop online accepting.", "error", "Online Payment");
    }
  } catch (e) {
    if (msg) msg.innerText = "Online unreachable";
    pushOperationalActivity("Online payment unreachable", "Service could not be reached from the dashboard.", "failed", "Error", "NET");
    showToast("Backend not reachable while stopping online accepting.", "error", "Online Payment");
  }
}


document.getElementById("startBtn").onclick = async () => {
  await checkin();
  if (timer) clearInterval(timer);
  timer = setInterval(checkin, 30000);
};

document.getElementById("stopBtn").onclick = async () => {
  if (timer) clearInterval(timer);
  timer = null;
  await checkout();
};

async function refreshOfflinePending() {
  try {
    const res = await fetch("/offline/queue/pending?merchant_username=" + encodeURIComponent(merchantUsername));
    const data = await res.json();
    const pending = data.pending || [];
    const count = pending.length;

    const pendingEl = document.getElementById("offlinePendingCount");
    const queueChip = document.getElementById("offlineQueueChip");
    const analyticsQueueCount = document.getElementById("analyticsQueueCount");
    const analyticsQueueText = document.getElementById("analyticsQueueText");

    if (pendingEl) pendingEl.innerText = count;
    if (queueChip) queueChip.innerText = count + " Pending";
    if (analyticsQueueCount) analyticsQueueCount.innerText = count;
    if (analyticsQueueText) analyticsQueueText.innerText = count;
  } catch (e) {}
}

document.getElementById("syncOfflineBtn").onclick = async () => {
  const syncBox = document.getElementById("syncMessageBox");
  const msg = document.getElementById("msg");

  if (syncBox) syncBox.innerText = "Sync in progress...";
  if (msg) msg.innerText = "Sync in progress";

  try {
    const res = await fetch("/offline/queue/sync", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ merchant_username: merchantUsername })
    });

    const text = await res.text();

    let data = null;
    try {
      data = JSON.parse(text);
    } catch (e) {
      if (syncBox) syncBox.innerText = "Invalid sync response.";
      if (msg) msg.innerText = "Sync failed";
      pushOperationalActivity("Queue sync failed", "Invalid response received from sync endpoint.", "failed", "Failed", "SYNC");
      showToast("Invalid sync response received.", "error", "Sync Queue");
      return;
    }

    if (res.ok && data.status === "success") {
      const results = data.results || [];
      const successCount = results.filter(r => r.status === "SUCCESS" || r.status === "DUPLICATE").length;
      const failCount = results.filter(r => r.status === "FAILED").length;
      const line = "Success: " + successCount + " | Failed: " + failCount;

      if (syncBox) syncBox.innerText = line;
      if (msg) msg.innerText = "Sync complete";

      await refreshOfflinePending();

      pushOperationalActivity(
        "Queue sync completed",
        successCount + " records synced" + (failCount ? " · " + failCount + " failed" : ""),
        failCount ? "pending" : "success",
        failCount ? "Partial" : "Synced",
        "SYNC"
      );

      if (failCount === 0) {
        showToast("All pending payments synced successfully ✅", "success", "Sync Queue");
      } else {
        showToast("Sync completed. Success: " + successCount + " | Failed: " + failCount, "pending", "Sync Queue");
      }
    } else {
      const message = data.message || ("HTTP " + res.status);
      if (syncBox) syncBox.innerText = message;
      if (msg) msg.innerText = "Sync failed";
      pushOperationalActivity("Queue sync failed", message, "failed", "Failed", "SYNC");
      showToast(message, "error", "Sync Queue");
    }
  } catch (e) {
    if (syncBox) syncBox.innerText = "Network error during sync.";
    if (msg) msg.innerText = "Sync failed";
    pushOperationalActivity("Queue sync failed", "Network error during queue sync.", "failed", "Failed", "SYNC");
    showToast("Network error during sync.", "error", "Sync Queue");
  }
};

async function refreshOfflineAcceptingStatus() {
  try {
    const res = await fetch("/offline/accepting/status?merchant_username=" + encodeURIComponent(merchantUsername));
    const data = await res.json();

    if (data.status === "success" && data.offline_accepting) {
      syncOfflineVisualState(true);
    } else {
      syncOfflineVisualState(false);
    }
  } catch (e) {}
}

document.getElementById("startOfflineBtn").onclick = async () => {
  const msg = document.getElementById("msg");

  try {
    const res = await fetch("/offline/accepting/start", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ merchant_username: merchantUsername })
    });

    const data = await res.json();

    if (data.status === "success") {
      syncOfflineVisualState(true);
      if (msg) msg.innerText = "Offline active";
      pushOperationalActivity("Offline tap active", "Receiver is ready for nearby payments.", "success", "Active", "BT");
      showToast("Offline tapping started ✅", "success", "Offline Payment");
    } else {
      syncOfflineVisualState(false);
      if (msg) msg.innerText = "Offline start failed";
      pushOperationalActivity("Offline tap start failed", data.message || "Receiver could not be started.", "failed", "Failed", "BT");
      showToast(data.message || "Could not start offline tapping.", "error", "Offline Payment");
    }

    await refreshOfflineAcceptingStatus();
  } catch (e) {
    if (msg) msg.innerText = "Offline start failed";
    pushOperationalActivity("Offline tap start failed", "Receiver could not be started.", "failed", "Failed", "BT");
    showToast("Receiver could not be started.", "error", "Offline Payment");
  }
};

document.getElementById("stopOfflineBtn").onclick = async () => {
  const msg = document.getElementById("msg");

  try {
    const res = await fetch("/offline/accepting/stop", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ merchant_username: merchantUsername })
    });

    const data = await res.json();

    if (data.status === "success") {
      syncOfflineVisualState(false);
      if (msg) msg.innerText = "Offline inactive";
      pushOperationalActivity("Offline tap inactive", "Receiver was stopped from the dashboard.", "failed", "Inactive", "BT");
      showToast("Offline tapping stopped ✅", "success", "Offline Payment");
    } else {
      if (msg) msg.innerText = "Offline stop failed";
      pushOperationalActivity("Offline tap stop failed", data.message || "Receiver could not be stopped.", "failed", "Failed", "BT");
      showToast(data.message || "Could not stop offline tapping.", "error", "Offline Payment");
    }

    await refreshOfflineAcceptingStatus();
  } catch (e) {
    if (msg) msg.innerText = "Offline stop failed";
    pushOperationalActivity("Offline tap stop failed", "Receiver could not be stopped.", "failed", "Failed", "BT");
    showToast("Receiver could not be stopped.", "error", "Offline Payment");
  }
};

function setupNavigation() {
  const navButtons = document.querySelectorAll(".nav-link");
  const pages = document.querySelectorAll(".page");

  navButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-page-target");

      navButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      pages.forEach(page => page.classList.remove("active"));
      const targetPage = document.getElementById(targetId);
      if (targetPage) {
        targetPage.classList.add("active");
        document.querySelector(".main").scrollTop = 0;
      }
    });
  });
}

let currentMethodFilter = "all";
let currentStatusFilter = "all";

function getTxRows() {
  return Array.from(document.querySelectorAll("#transactionsTable tbody tr[data-tx-row='1']"));
}

function applyTransactionFilters() {
  const rows = getTxRows();
  const searchValue = (document.getElementById("txSearchInput")?.value || "").trim().toLowerCase();

  let shownCount = 0;
  let filteredAmount = 0;
  let onlineCount = 0;
  let offlineCount = 0;

  rows.forEach(row => {
    const method = (row.dataset.method || "").toLowerCase();
    const status = (row.dataset.status || "").toLowerCase();
    const created = (row.dataset.created || "").toLowerCase();
    const fromUser = (row.dataset.from || "").toLowerCase();
    const toUser = (row.dataset.to || "").toLowerCase();
    const amount = parseFloat(row.dataset.amount || "0");
    const note = (row.dataset.note || "").toLowerCase();

    const searchText = [created, fromUser, toUser, String(amount.toFixed(2)), method, status, note].join(" ");

    const methodMatch = currentMethodFilter === "all" || method === currentMethodFilter;
    const statusMatch = currentStatusFilter === "all" || status === currentStatusFilter;
    const searchMatch = !searchValue || searchText.includes(searchValue);

    const visible = methodMatch && statusMatch && searchMatch;
    row.style.display = visible ? "" : "none";

    if (visible) {
      shownCount += 1;
      filteredAmount += amount;
      if (method === "online") onlineCount += 1;
      if (method === "offline") offlineCount += 1;
    }
  });

  const shownEl = document.getElementById("txRecordsShown");
  const amountEl = document.getElementById("txFilteredAmount");
  const onlineEl = document.getElementById("txOnlineCount");
  const offlineEl = document.getElementById("txOfflineCount");

  if (shownEl) shownEl.innerText = shownCount;
  if (amountEl) amountEl.innerText = formatNumber(filteredAmount);
  if (onlineEl) onlineEl.innerText = onlineCount;
  if (offlineEl) offlineEl.innerText = offlineCount;
}

function setupTransactionFilters() {
  const searchInput = document.getElementById("txSearchInput");
  const methodButtons = document.querySelectorAll("[data-filter-type='method']");
  const statusButtons = document.querySelectorAll("[data-filter-type='status']");

  methodButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      methodButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentMethodFilter = btn.getAttribute("data-filter-value");
      applyTransactionFilters();
    });
  });

  statusButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      statusButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentStatusFilter = btn.getAttribute("data-filter-value");
      applyTransactionFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", applyTransactionFilters);
  }

  applyTransactionFilters();
}

function setupAnalytics() {
  const rows = getTxRows();

  let onlineCount = 0;
  let offlineCount = 0;
  let successCount = 0;
  let failedOtherCount = 0;

  const weekdayCounts = [0,0,0,0,0,0,0];

  rows.forEach(row => {
    const method = (row.dataset.method || "").toLowerCase();
    const status = (row.dataset.status || "").toLowerCase();
    const rawDate = row.dataset.created || "";

    if (method === "online") onlineCount += 1;
    if (method === "offline") offlineCount += 1;

    if (status === "success") {
      successCount += 1;
    } else {
      failedOtherCount += 1;
    }

    const parsed = parseDateValue(rawDate);
    if (parsed) weekdayCounts[parsed.getDay()] += 1;
  });

  const totalPayments = onlineCount + offlineCount;
  const totalStatuses = successCount + failedOtherCount;

  const methodDonut = document.getElementById("methodDonut");
  const statusDonut = document.getElementById("statusDonut");

  const onlinePct = totalPayments ? Math.round((onlineCount / totalPayments) * 100) : 0;
  const successPct = totalStatuses ? Math.round((successCount / totalStatuses) * 100) : 0;

  if (methodDonut) {
    methodDonut.style.background =
      "conic-gradient(#4f8cff 0% " + onlinePct + "%, #35c4ff " + onlinePct + "% 100%)";
  }

  if (statusDonut) {
    statusDonut.style.background =
      "conic-gradient(#42d876 0% " + successPct + "%, #ff667d " + successPct + "% 100%)";
  }

  const methodDonutTotal = document.getElementById("methodDonutTotal");
  const statusDonutTotal = document.getElementById("statusDonutTotal");
  const legendOnlineCount = document.getElementById("legendOnlineCount");
  const legendOfflineCount = document.getElementById("legendOfflineCount");
  const legendSuccessCount = document.getElementById("legendSuccessCount");
  const legendFailedCount = document.getElementById("legendFailedCount");

  if (methodDonutTotal) methodDonutTotal.innerText = totalPayments;
  if (statusDonutTotal) statusDonutTotal.innerText = totalStatuses;
  if (legendOnlineCount) legendOnlineCount.innerText = onlineCount;
  if (legendOfflineCount) legendOfflineCount.innerText = offlineCount;
  if (legendSuccessCount) legendSuccessCount.innerText = successCount;
  if (legendFailedCount) legendFailedCount.innerText = failedOtherCount;

  const barIds = ["barSun","barMon","barTue","barWed","barThu","barFri","barSat"];
  const maxVal = Math.max(...weekdayCounts, 1);

  weekdayCounts.forEach((count, index) => {
    const bar = document.getElementById(barIds[index]);
    if (!bar) return;
    const minHeight = 12;
    const maxHeight = 160;
    const height = count === 0 ? minHeight : Math.max(minHeight, Math.round((count / maxVal) * maxHeight));
    bar.style.height = height + "px";
  });
}

refreshOfflinePending();
refreshOfflineAcceptingStatus();
setInterval(refreshOfflineAcceptingStatus, 3000);

setupNavigation();
setupTransactionFilters();
setupAnalytics();
renderRecentActivity();

{% if is_active %}
timer = setInterval(checkin, 30000);
{% endif %}
</script>
</body>
</html>
"""


@app.route("/merchant", methods=["GET"])
def merchant_home():
    return """
    <h2>Merchant Portal</h2>
    <ul>
      <li><a href="/merchant/merchantlogin">Merchant Login</a></li>
      <li><a href="/merchant/Canteen">Canteen Dashboard (requires login)</a></li>
      <li><a href="/merchant/coffeespot">Coffee Spot Dashboard (requires login)</a></li>
      <li><a href="/merchant/stationery">Stationery Dashboard (requires login)</a></li>
    </ul>
    """


@app.route("/merchant/<merchant_username>", methods=["GET"])
@merchant_login_required
def merchant_dashboard(merchant_username):
    logged_in = session.get("merchant_username")
    if not logged_in:
        return redirect("/merchant/merchantlogin")

    if logged_in.lower() != merchant_username.lower():
        return redirect(f"/merchant/{logged_in}")

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            "SELECT id, username, full_name, student_id, balance, role FROM users WHERE username=%s",
            (logged_in,)
        )
        merchant = cur.fetchone()
        if not merchant or merchant.get("role") != "merchant":
            session.pop("merchant_username", None)
            return redirect("/merchant/merchantlogin")

        merchant_id = merchant["id"]
        merchant["balance"] = float(merchant.get("balance") or 0.0)

        remote_ip = request.remote_addr or ""
        network_id = ip_to_network_id(remote_ip)

        cur.execute("SELECT last_seen FROM merchant_presence WHERE merchant_username=%s", (logged_in,))
        pres = cur.fetchone()
        is_active = pres is not None

        cur.execute(
            """
            SELECT
                t.id,
                t.amount,
                t.method,
                t.status,
                t.note,
                t.created_at,
                u1.username AS sender_username,
                u2.username AS receiver_username
            FROM transactions t
            JOIN users u1 ON u1.id = t.sender_user_id
            JOIN users u2 ON u2.id = t.receiver_user_id
            WHERE t.sender_user_id=%s OR t.receiver_user_id=%s
            ORDER BY t.created_at DESC
            """,
            (merchant_id, merchant_id)
        )
        txs = cur.fetchall() or []
        for t in txs:
            t["amount"] = float(t["amount"])

        cur.execute(
            """
            SELECT
              COALESCE(SUM(t.amount), 0) AS total_30,
              COALESCE(AVG(t.amount), 0) AS avg_tx,
              COALESCE(COUNT(*), 0) AS cnt_tx
            FROM transactions t
            WHERE t.receiver_user_id=%s
              AND t.status='SUCCESS'
              AND t.created_at >= (NOW() - INTERVAL 30 DAY)
            """,
            (merchant_id,)
        )
        m = cur.fetchone() or {}
        total_30 = float(m.get("total_30") or 0.0)
        avg_tx = float(m.get("avg_tx") or 0.0)
        cnt_tx = float(m.get("cnt_tx") or 0.0)
        daily_avg = cnt_tx / 30.0

        metrics = {
            "total_30": total_30,
            "avg_tx": avg_tx,
            "daily_avg": daily_avg
        }

        return render_template_string(
            MERCHANT_DASHBOARD_HTML,
            merchant=merchant,
            network_id=network_id,
            is_active=is_active,
            txs=txs,
            metrics=metrics
        )

    finally:
        cur.close()
        conn.close()


# -------------------- OFFLINE QUEUE (SQLite on merchant laptop) --------------------
OFFLINE_DB_PATH = os.path.join(os.path.dirname(__file__), "offline_queue.db")


def offline_db():
    conn = sqlite3.connect(OFFLINE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def offline_init_db():
    conn = offline_db()
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


def process_offline_sync(merchant_username, payments):
    if not merchant_username:
        return {"status": "failure", "message": "merchant_username required"}, 400
    if not isinstance(payments, list):
        return {"status": "failure", "message": "payments must be a list"}, 400

    ensure_offline_token_table()

    conn0 = get_conn()
    cur0 = conn0.cursor(dictionary=True)
    try:
        cur0.execute("SELECT id, username, role FROM users WHERE username=%s", (merchant_username,))
        merchant = cur0.fetchone()
        if not merchant:
            return {"status": "failure", "message": "Merchant user not found"}, 404
        if merchant.get("role") != "merchant":
            return {"status": "failure", "message": "User is not a merchant"}, 403
        merchant_id = merchant["id"]
    finally:
        cur0.close()
        conn0.close()

    results = []

    for p in payments:
        p = p or {}

        client_tx_id = (p.get("client_tx_id") or "").strip()
        sender_username = (p.get("sender_username") or "").strip()
        note = p.get("note")
        amount = p.get("amount")

        offline_token_id = (p.get("offline_token_id") or "").strip()
        offline_token_nonce = (p.get("offline_token_nonce") or "").strip()
        offline_token_expires_at = (p.get("offline_token_expires_at") or "").strip()
        offline_token_signature = (p.get("offline_token_signature") or "").strip()

        if not client_tx_id or not sender_username:
            log_audit_event(
                event_type="offline_sync_item",
                outcome="FAILED",
                merchant_username=merchant_username,
                sender_username=sender_username,
                client_tx_id=client_tx_id,
                details={"message": "client_tx_id and sender_username required"}
            )
            results.append({
                "client_tx_id": client_tx_id,
                "status": "FAILED",
                "message": "client_tx_id and sender_username required"
            })
            continue

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            log_audit_event(
                event_type="offline_sync_item",
                outcome="FAILED",
                merchant_username=merchant_username,
                sender_username=sender_username,
                client_tx_id=client_tx_id,
                details={"message": "amount must be a number"}
            )
            results.append({
                "client_tx_id": client_tx_id,
                "status": "FAILED",
                "message": "amount must be a number"
            })
            continue

        if amount <= 0:
            log_audit_event(
                event_type="offline_sync_item",
                outcome="FAILED",
                merchant_username=merchant_username,
                sender_username=sender_username,
                amount=amount,
                client_tx_id=client_tx_id,
                details={"message": "amount must be > 0"}
            )
            results.append({
                "client_tx_id": client_tx_id,
                "status": "FAILED",
                "message": "amount must be > 0"
            })
            continue

        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        try:
            conn.start_transaction()

            cur.execute("SELECT id, status FROM transactions WHERE client_tx_id=%s LIMIT 1", (client_tx_id,))
            existing = cur.fetchone()
            if existing:
                conn.rollback()

                log_audit_event(
                    event_type="offline_sync_item",
                    outcome="DUPLICATE",
                    merchant_username=merchant_username,
                    sender_username=sender_username,
                    amount=amount,
                    client_tx_id=client_tx_id,
                    details={"message": "Already synced", "transaction_id": existing["id"], "db_status": existing["status"]}
                )

                results.append({
                    "client_tx_id": client_tx_id,
                    "status": "DUPLICATE",
                    "message": "Already synced",
                    "transaction_id": existing["id"],
                    "db_status": existing["status"]
                })
                continue

            token_row = None
            max_amount = None

            if offline_token_id:
                cur.execute(
                    """
                    SELECT token_id, sender_username, nonce, max_amount, expires_at, status, signature, client_tx_id
                    FROM offline_payment_tokens
                    WHERE token_id=%s
                    FOR UPDATE
                    """,
                    (offline_token_id,)
                )
                token_row = cur.fetchone()

                if not token_row:
                    conn.rollback()

                    log_audit_event(
                        event_type="offline_token_sync_rejected",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={"reason": "Offline token not found", "offline_token_id": offline_token_id}
                    )

                    results.append({
                        "client_tx_id": client_tx_id,
                        "status": "FAILED",
                        "message": "Offline token not found"
                    })
                    continue

                token_status = (token_row.get("status") or "").upper()
                if token_status != "ISSUED":
                    conn.rollback()

                    msg = "Offline token already used" if token_status == "USED" else f"Offline token status is {token_status}"

                    log_audit_event(
                        event_type="offline_token_sync_rejected",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={"reason": msg, "offline_token_id": offline_token_id}
                    )

                    results.append({
                        "client_tx_id": client_tx_id,
                        "status": "FAILED",
                        "message": msg
                    })
                    continue

                db_sender = (token_row.get("sender_username") or "").strip()
                db_nonce = (token_row.get("nonce") or "").strip()
                db_signature = (token_row.get("signature") or "").strip()
                db_expires_at_str = offline_token_dt_to_str(token_row.get("expires_at"))
                max_amount = float(token_row.get("max_amount") or 0.0)

                if db_sender.lower() != sender_username.lower():
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='REJECTED', reject_reason=%s, client_tx_id=%s
                        WHERE token_id=%s
                        """,
                        ("Sender mismatch", client_tx_id, offline_token_id)
                    )
                    conn.commit()

                    log_audit_event(
                        event_type="offline_token_sync_rejected",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={"reason": "Sender mismatch", "offline_token_id": offline_token_id}
                    )

                    results.append({
                        "client_tx_id": client_tx_id,
                        "status": "FAILED",
                        "message": "Offline token sender mismatch"
                    })
                    continue

                token_expires_dt = token_row.get("expires_at")
                if token_expires_dt and token_expires_dt <= datetime.utcnow():
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='EXPIRED', reject_reason=%s, client_tx_id=%s
                        WHERE token_id=%s
                        """,
                        ("Offline token expired", client_tx_id, offline_token_id)
                    )
                    conn.commit()

                    log_audit_event(
                        event_type="offline_token_sync_expired",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={"reason": "Offline token expired", "offline_token_id": offline_token_id}
                    )

                    results.append({
                        "client_tx_id": client_tx_id,
                        "status": "FAILED",
                        "message": "Offline token expired"
                    })
                    continue

                expected_signature = build_offline_token_signature(
                    sender_username=db_sender,
                    token_id=offline_token_id,
                    nonce=db_nonce,
                    expires_at_str=db_expires_at_str,
                    max_amount=max_amount
                )

                if (
                    offline_token_nonce != db_nonce or
                    offline_token_expires_at != db_expires_at_str or
                    offline_token_signature != db_signature or
                    offline_token_signature != expected_signature
                ):
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='REJECTED', reject_reason=%s, client_tx_id=%s
                        WHERE token_id=%s
                        """,
                        ("Offline token signature mismatch", client_tx_id, offline_token_id)
                    )
                    conn.commit()

                    log_audit_event(
                        event_type="offline_token_sync_signature_failed",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={"reason": "Offline token signature mismatch", "offline_token_id": offline_token_id}
                    )

                    results.append({
                        "client_tx_id": client_tx_id,
                        "status": "FAILED",
                        "message": "Offline token signature mismatch"
                    })
                    continue

                if amount > max_amount:
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='REJECTED', reject_reason=%s, client_tx_id=%s
                        WHERE token_id=%s
                        """,
                        ("Amount exceeds offline token limit", client_tx_id, offline_token_id)
                    )
                    conn.commit()

                    log_audit_event(
                        event_type="offline_token_sync_rejected",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={
                            "reason": "Amount exceeds offline token limit",
                            "offline_token_id": offline_token_id,
                            "max_amount": max_amount
                        }
                    )

                    results.append({
                        "client_tx_id": client_tx_id,
                        "status": "FAILED",
                        "message": "Amount exceeds offline token limit"
                    })
                    continue

            cur.execute("SELECT id, role, balance FROM users WHERE username=%s FOR UPDATE", (sender_username,))
            sender = cur.fetchone()

            cur.execute("SELECT id, role, balance FROM users WHERE id=%s FOR UPDATE", (merchant_id,))
            receiver = cur.fetchone()

            if not sender:
                if offline_token_id:
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='REJECTED', reject_reason=%s, client_tx_id=%s
                        WHERE token_id=%s
                        """,
                        ("Sender not found", client_tx_id, offline_token_id)
                    )

                cur.execute(
                    """
                    INSERT INTO transactions (sender_user_id, receiver_user_id, amount, method, status, note, client_tx_id)
                    VALUES (%s, %s, %s, 'OFFLINE', 'FAILED', %s, %s)
                    """,
                    (merchant_id, merchant_id, amount, note, client_tx_id)
                )
                conn.commit()

                log_audit_event(
                    event_type="offline_sync_item",
                    outcome="FAILED",
                    merchant_username=merchant_username,
                    sender_username=sender_username,
                    amount=amount,
                    client_tx_id=client_tx_id,
                    details={"message": "Sender not found"}
                )

                results.append({"client_tx_id": client_tx_id, "status": "FAILED", "message": "Sender not found"})
                continue

            if sender.get("role") != "student":
                if offline_token_id:
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='REJECTED', reject_reason=%s, client_tx_id=%s
                        WHERE token_id=%s
                        """,
                        ("Sender must be student", client_tx_id, offline_token_id)
                    )

                cur.execute(
                    """
                    INSERT INTO transactions (sender_user_id, receiver_user_id, amount, method, status, note, client_tx_id)
                    VALUES (%s, %s, %s, 'OFFLINE', 'FAILED', %s, %s)
                    """,
                    (sender["id"], merchant_id, amount, note, client_tx_id)
                )
                conn.commit()

                log_audit_event(
                    event_type="offline_sync_item",
                    outcome="FAILED",
                    merchant_username=merchant_username,
                    sender_username=sender_username,
                    amount=amount,
                    client_tx_id=client_tx_id,
                    details={"message": "Sender must be student"}
                )

                results.append({"client_tx_id": client_tx_id, "status": "FAILED", "message": "Sender must be student"})
                continue

            sender_balance = float(sender.get("balance") or 0.0)
            receiver_balance = float(receiver.get("balance") or 0.0)

            if sender_balance < amount:
                if offline_token_id:
                    cur.execute(
                        """
                        UPDATE offline_payment_tokens
                        SET status='REJECTED', reject_reason=%s, client_tx_id=%s,
                            used_merchant_username=%s, used_amount=%s
                        WHERE token_id=%s
                        """,
                        ("Insufficient balance", client_tx_id, merchant_username, amount, offline_token_id)
                    )

                cur.execute(
                    """
                    INSERT INTO transactions (sender_user_id, receiver_user_id, amount, method, status, note, client_tx_id)
                    VALUES (%s, %s, %s, 'OFFLINE', 'FAILED', %s, %s)
                    """,
                    (sender["id"], merchant_id, amount, note, client_tx_id)
                )
                conn.commit()

                if offline_token_id:
                    log_audit_event(
                        event_type="offline_token_sync_rejected",
                        outcome="FAILED",
                        merchant_username=merchant_username,
                        sender_username=sender_username,
                        amount=amount,
                        client_tx_id=client_tx_id,
                        details={"reason": "Insufficient balance", "offline_token_id": offline_token_id}
                    )

                log_audit_event(
                    event_type="offline_sync_item",
                    outcome="FAILED",
                    merchant_username=merchant_username,
                    sender_username=sender_username,
                    amount=amount,
                    client_tx_id=client_tx_id,
                    details={"message": "Insufficient balance"}
                )

                results.append({"client_tx_id": client_tx_id, "status": "FAILED", "message": "Insufficient balance"})
                continue

            new_sender_balance = sender_balance - amount
            new_receiver_balance = receiver_balance + amount

            cur.execute("UPDATE users SET balance=%s WHERE id=%s", (new_sender_balance, sender["id"]))
            cur.execute("UPDATE users SET balance=%s WHERE id=%s", (new_receiver_balance, merchant_id))

            cur.execute(
                """
                INSERT INTO transactions (sender_user_id, receiver_user_id, amount, method, status, note, client_tx_id)
                VALUES (%s, %s, %s, 'OFFLINE', 'SUCCESS', %s, %s)
                """,
                (sender["id"], merchant_id, amount, note, client_tx_id)
            )
            tx_id = cur.lastrowid

            if offline_token_id:
                cur.execute(
                    """
                    UPDATE offline_payment_tokens
                    SET status='USED',
                        used_merchant_username=%s,
                        used_amount=%s,
                        client_tx_id=%s,
                        used_at=UTC_TIMESTAMP(),
                        reject_reason=NULL
                    WHERE token_id=%s
                    """,
                    (merchant_username, amount, client_tx_id, offline_token_id)
                )

            conn.commit()

            if offline_token_id:
                log_audit_event(
                    event_type="offline_token_sync_used",
                    outcome="SUCCESS",
                    merchant_username=merchant_username,
                    sender_username=sender_username,
                    amount=amount,
                    client_tx_id=client_tx_id,
                    details={
                        "offline_token_id": offline_token_id,
                        "transaction_id": tx_id
                    }
                )

            log_audit_event(
                event_type="offline_sync_item",
                outcome="SUCCESS",
                merchant_username=merchant_username,
                sender_username=sender_username,
                amount=amount,
                client_tx_id=client_tx_id,
                details={"transaction_id": tx_id}
            )

            results.append({
                "client_tx_id": client_tx_id,
                "status": "SUCCESS",
                "transaction_id": tx_id,
                "sender_new_balance": round(new_sender_balance, 2),
                "receiver_new_balance": round(new_receiver_balance, 2)
            })

        except Exception as e:
            print("ERROR in offline sync processing:", repr(e))
            try:
                conn.rollback()
            except Exception:
                pass

            log_audit_event(
                event_type="offline_sync_item",
                outcome="FAILED",
                merchant_username=merchant_username,
                sender_username=sender_username,
                amount=amount if isinstance(amount, (int, float)) else None,
                client_tx_id=client_tx_id,
                details={"message": f"Server error: {str(e)}"}
            )

            results.append({
                "client_tx_id": client_tx_id,
                "status": "FAILED",
                "message": f"Server error: {str(e)}"
            })
        finally:
            cur.close()
            conn.close()

    return {
        "status": "success",
        "merchant_username": merchant_username,
        "results": results
    }, 200


# -------------------- OFFLINE SYNC API --------------------
@app.route("/offline/sync", methods=["POST"])
def offline_sync():
    data = request.json or {}
    merchant_username = data.get("merchant_username")
    payments = data.get("payments")

    log_audit_event(
        event_type="offline_sync_request",
        outcome="REQUESTED",
        merchant_username=merchant_username,
        actor_username=merchant_username,
        details={
            "payments_count": len(payments) if isinstance(payments, list) else None,
            "ip": request.remote_addr
        }
    )

    payload, code = process_offline_sync(merchant_username, payments)

    log_audit_event(
        event_type="offline_sync_request",
        outcome="SUCCESS" if code == 200 else "FAILED",
        merchant_username=merchant_username,
        actor_username=merchant_username,
        details={
            "payments_count": len(payments) if isinstance(payments, list) else None,
            "result_count": len((payload or {}).get("results", [])) if isinstance(payload, dict) else None,
            "http_code": code,
            "ip": request.remote_addr
        }
    )

    return jsonify(payload), code


@app.route("/offline/accepting/status", methods=["GET"])
@merchant_login_required
def offline_accepting_status():
    merchant_username = request.args.get("merchant_username") or session.get("merchant_username")
    if not merchant_username:
        return jsonify({"status": "failure", "message": "merchant_username required"}), 400

    if (session.get("merchant_username") or "").lower() != merchant_username.lower():
        return jsonify({"status": "failure", "message": "Unauthorized merchant status access"}), 403

    receiver = get_receiver_status()
    is_accepting = bool(
        receiver.get("running") and
        (receiver.get("merchant_username") or "").lower() == merchant_username.lower()
    )

    OFFLINE_ACCEPTING_STATE[merchant_username.lower()] = is_accepting

    return jsonify({
        "status": "success",
        "merchant_username": merchant_username,
        "offline_accepting": is_accepting,
        "receiver_pid": receiver.get("pid")
    }), 200


@app.route("/offline/accepting/start", methods=["POST"])
@merchant_login_required
def offline_accepting_start():
    data = request.json or {}
    merchant_username = data.get("merchant_username") or session.get("merchant_username")

    if not merchant_username:
        return jsonify({"status": "failure", "message": "merchant_username required"}), 400

    if (session.get("merchant_username") or "").lower() != merchant_username.lower():
        return jsonify({"status": "failure", "message": "Unauthorized merchant start"}), 403

    result = start_receiver(merchant_username)

    is_accepting = bool(result.get("ok"))
    OFFLINE_ACCEPTING_STATE[merchant_username.lower()] = is_accepting

    if result.get("ok"):
        log_audit_event(
            event_type="offline_accepting_start",
            outcome="SUCCESS",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"receiver_pid": result.get("pid"), "ip": request.remote_addr}
        )
        return jsonify({
            "status": "success",
            "message": result.get("message", "Offline accepting started"),
            "merchant_username": merchant_username,
            "offline_accepting": True,
            "receiver_pid": result.get("pid")
        }), 200

    log_audit_event(
        event_type="offline_accepting_start",
        outcome="FAILED",
        actor_username=merchant_username,
        merchant_username=merchant_username,
        details={"message": result.get("message", "Could not start receiver"), "ip": request.remote_addr}
    )

    return jsonify({
        "status": "failure",
        "message": result.get("message", "Could not start receiver"),
        "merchant_username": merchant_username,
        "offline_accepting": False
    }), 500


@app.route("/offline/accepting/stop", methods=["POST"])
@merchant_login_required
def offline_accepting_stop():
    data = request.json or {}
    merchant_username = data.get("merchant_username") or session.get("merchant_username")

    if not merchant_username:
        return jsonify({"status": "failure", "message": "merchant_username required"}), 400

    if (session.get("merchant_username") or "").lower() != merchant_username.lower():
        return jsonify({"status": "failure", "message": "Unauthorized merchant stop"}), 403

    result = stop_receiver()
    OFFLINE_ACCEPTING_STATE[merchant_username.lower()] = False

    if result.get("ok"):
        log_audit_event(
            event_type="offline_accepting_stop",
            outcome="SUCCESS",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"ip": request.remote_addr}
        )
        return jsonify({
            "status": "success",
            "message": result.get("message", "Offline accepting stopped"),
            "merchant_username": merchant_username,
            "offline_accepting": False
        }), 200

    log_audit_event(
        event_type="offline_accepting_stop",
        outcome="FAILED",
        actor_username=merchant_username,
        merchant_username=merchant_username,
        details={"message": result.get("message", "Could not stop receiver"), "ip": request.remote_addr}
    )

    return jsonify({
        "status": "failure",
        "message": result.get("message", "Could not stop receiver"),
        "merchant_username": merchant_username,
        "offline_accepting": True
    }), 500


@app.route("/offline/queue/pending", methods=["GET"])
@merchant_login_required
def offline_queue_pending():
    merchant_username = request.args.get("merchant_username")
    if not merchant_username:
        return jsonify({"status": "failure", "message": "merchant_username required"}), 400

    if (session.get("merchant_username") or "").lower() != merchant_username.lower():
        return jsonify({"status": "failure", "message": "Unauthorized merchant queue access"}), 403

    offline_init_db()
    conn = offline_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT client_tx_id, sender_username, amount, note, status, last_error, created_at
        FROM offline_payments
        WHERE merchant_username=? AND status='PENDING'
        ORDER BY id ASC
    """, (merchant_username,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({"status": "success", "merchant_username": merchant_username, "pending": rows}), 200


@app.route("/offline/queue/sync", methods=["POST"])
@merchant_login_required
def offline_queue_sync():
    data = request.json or {}
    merchant_username = data.get("merchant_username")
    if not merchant_username:
        return jsonify({"status": "failure", "message": "merchant_username required"}), 400

    if (session.get("merchant_username") or "").lower() != merchant_username.lower():
        return jsonify({"status": "failure", "message": "Unauthorized merchant queue sync"}), 403

    offline_init_db()

    conn = offline_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT client_tx_id, sender_username, amount, note,
               offline_token_id, offline_token_nonce, offline_token_expires_at, offline_token_signature
        FROM offline_payments
        WHERE merchant_username=? AND status='PENDING'
        ORDER BY id ASC
    """, (merchant_username,))
    pending = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not pending:
        log_audit_event(
            event_type="offline_queue_sync",
            outcome="SUCCESS",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"message": "No pending offline payments", "ip": request.remote_addr}
        )
        return jsonify({"status": "success", "message": "No pending offline payments", "results": []}), 200

    sync_payload, sync_code = process_offline_sync(merchant_username, pending)

    if sync_code != 200:
        log_audit_event(
            event_type="offline_queue_sync",
            outcome="FAILED",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={"message": sync_payload.get("message"), "ip": request.remote_addr}
        )
        return jsonify(sync_payload), sync_code

    results = sync_payload.get("results", [])

    conn2 = offline_db()
    cur2 = conn2.cursor()

    for r in results:
        txid = r.get("client_tx_id")
        st = r.get("status")
        msg = r.get("message")

        if st in ("SUCCESS", "DUPLICATE"):
            cur2.execute(
                "UPDATE offline_payments SET status='SYNCED', last_error=NULL WHERE client_tx_id=?",
                (txid,)
            )
        else:
            cur2.execute(
                "UPDATE offline_payments SET status='FAILED', last_error=? WHERE client_tx_id=?",
                (msg or "FAILED", txid)
            )

    conn2.commit()
    conn2.close()

    success_count = len([r for r in results if r.get("status") in ("SUCCESS", "DUPLICATE")])
    failed_count = len([r for r in results if r.get("status") == "FAILED"])

    log_audit_event(
        event_type="offline_queue_sync",
        outcome="SUCCESS" if failed_count == 0 else "PARTIAL",
        actor_username=merchant_username,
        merchant_username=merchant_username,
        details={
            "success_count": success_count,
            "failed_count": failed_count,
            "results_count": len(results),
            "ip": request.remote_addr
        }
    )

    return jsonify({
        "status": "success",
        "merchant_username": merchant_username,
        "results": results
    }), 200


EVIDENCE_DEBUG_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Evidence Logs | CollegeWallet</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body{font-family:Arial,sans-serif;background:#07112e;color:#fff;margin:0;padding:20px;}
    h1,h2{margin:0 0 12px 0;}
    .sub{color:#c8d2f6;margin-bottom:18px;}
    .panel{background:#0d1d4b;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:16px;margin-bottom:20px;overflow:auto;}
    table{width:100%;border-collapse:collapse;min-width:900px;}
    th,td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.08);text-align:left;vertical-align:top;font-size:13px;}
    th{font-size:11px;text-transform:uppercase;color:#c8d2f6;}
    .mono{font-family:Consolas,monospace;white-space:pre-wrap;word-break:break-word;}
  </style>
</head>
<body>
  <h1>Evidence Logs</h1>
  <div class="sub">Backend audit logs + offline receiver logs</div>

  {% if filter_client_tx_id %}
    <div class="sub">Filtered by client_tx_id: <b>{{ filter_client_tx_id }}</b></div>
  {% endif %}

  <div class="panel">
    <h2>Backend Audit Events</h2>
    {% if backend_rows %}
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Time</th>
          <th>Event</th>
          <th>Outcome</th>
          <th>Actor</th>
          <th>Merchant</th>
          <th>Sender</th>
          <th>Receiver</th>
          <th>Amount</th>
          <th>Client Tx ID</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {% for row in backend_rows %}
        <tr>
          <td>{{ row.id }}</td>
          <td>{{ row.created_at }}</td>
          <td>{{ row.event_type }}</td>
          <td>{{ row.outcome }}</td>
          <td>{{ row.actor_username or '-' }}</td>
          <td>{{ row.merchant_username or '-' }}</td>
          <td>{{ row.sender_username or '-' }}</td>
          <td>{{ row.receiver_username or '-' }}</td>
          <td>{{ row.amount if row.amount is not none else '-' }}</td>
          <td>{{ row.client_tx_id or '-' }}</td>
          <td class="mono">{{ row.details_json or '{}' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      <div>No backend audit events found.</div>
    {% endif %}
  </div>

  <div class="panel">
    <h2>Offline Receiver Events</h2>
    {% if offline_rows %}
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Time</th>
          <th>Event</th>
          <th>Outcome</th>
          <th>Merchant</th>
          <th>Sender</th>
          <th>Amount</th>
          <th>Client Tx ID</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {% for row in offline_rows %}
        <tr>
          <td>{{ row.id }}</td>
          <td>{{ row.created_at }}</td>
          <td>{{ row.event_type }}</td>
          <td>{{ row.outcome }}</td>
          <td>{{ row.merchant_username or '-' }}</td>
          <td>{{ row.sender_username or '-' }}</td>
          <td>{{ row.amount if row.amount is not none else '-' }}</td>
          <td>{{ row.client_tx_id or '-' }}</td>
          <td class="mono">{{ row.details_json or '{}' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      <div>No offline receiver events found.</div>
    {% endif %}
  </div>
</body>
</html>
"""


@app.route("/debug/evidence", methods=["GET"])
def debug_evidence():
    ensure_audit_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, event_type, outcome, actor_username, merchant_username, sender_username,
               receiver_username, amount, client_tx_id, details_json, created_at
        FROM audit_events
        ORDER BY id DESC
        LIMIT 200
    """)
    backend_rows = cur.fetchall() or []
    cur.close()
    conn.close()

    offline_rows = []
    try:
        offline_init_db()
        conn2 = offline_db()
        cur2 = conn2.cursor()
        cur2.execute("""
            CREATE TABLE IF NOT EXISTS offline_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'INFO',
                merchant_username TEXT,
                sender_username TEXT,
                amount REAL,
                client_tx_id TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn2.commit()

        cur2.execute("""
            SELECT id, event_type, outcome, merchant_username, sender_username, amount, client_tx_id, details_json, created_at
            FROM offline_audit_events
            ORDER BY id DESC
            LIMIT 200
        """)
        offline_rows = [dict(r) for r in cur2.fetchall()]
        conn2.close()
    except Exception as e:
        print("WARN debug_evidence offline read failed:", repr(e))

    return render_template_string(
        EVIDENCE_DEBUG_HTML,
        backend_rows=backend_rows,
        offline_rows=offline_rows,
        filter_client_tx_id=None
    )


@app.route("/debug/evidence/<client_tx_id>", methods=["GET"])
def debug_evidence_by_tx(client_tx_id):
    ensure_audit_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, event_type, outcome, actor_username, merchant_username, sender_username,
               receiver_username, amount, client_tx_id, details_json, created_at
        FROM audit_events
        WHERE client_tx_id=%s
        ORDER BY id DESC
        LIMIT 200
    """, (client_tx_id,))
    backend_rows = cur.fetchall() or []
    cur.close()
    conn.close()

    offline_rows = []
    try:
        offline_init_db()
        conn2 = offline_db()
        cur2 = conn2.cursor()
        cur2.execute("""
            CREATE TABLE IF NOT EXISTS offline_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'INFO',
                merchant_username TEXT,
                sender_username TEXT,
                amount REAL,
                client_tx_id TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn2.commit()

        cur2.execute("""
            SELECT id, event_type, outcome, merchant_username, sender_username, amount, client_tx_id, details_json, created_at
            FROM offline_audit_events
            WHERE client_tx_id=?
            ORDER BY id DESC
            LIMIT 200
        """, (client_tx_id,))
        offline_rows = [dict(r) for r in cur2.fetchall()]
        conn2.close()
    except Exception as e:
        print("WARN debug_evidence_by_tx offline read failed:", repr(e))

    return render_template_string(
        EVIDENCE_DEBUG_HTML,
        backend_rows=backend_rows,
        offline_rows=offline_rows,
        filter_client_tx_id=client_tx_id
    )
@app.route("/debug/token/<token_id>", methods=["GET"])
def debug_token_details(token_id):
    ensure_online_token_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, merchant_username, amount, note, nonce,
                   expires_at, status, signature, transaction_id, reject_reason,
                   used_at, created_at
            FROM online_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (token_id,)
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"status": "failure", "message": "Token not found"}), 404

        expires_at_str = token_dt_to_str(row.get("expires_at"))
        used_at_str = token_dt_to_str(row.get("used_at")) if row.get("used_at") else None
        created_at_str = token_dt_to_str(row.get("created_at")) if row.get("created_at") else None

        return jsonify({
            "status": "success",
            "token": {
                "token_id": row.get("token_id"),
                "sender_username": row.get("sender_username"),
                "merchant_username": row.get("merchant_username"),
                "amount": float(row.get("amount") or 0.0),
                "note": row.get("note"),
                "nonce": row.get("nonce"),
                "expires_at": expires_at_str,
                "status": row.get("status"),
                "signature": row.get("signature"),
                "transaction_id": row.get("transaction_id"),
                "reject_reason": row.get("reject_reason"),
                "used_at": used_at_str,
                "created_at": created_at_str
            },
            "replay_test_payload": {
                "token_id": row.get("token_id"),
                "nonce": row.get("nonce"),
                "expires_at": expires_at_str,
                "signature": row.get("signature")
            }
        }), 200

    except Exception as e:
        print("ERROR in /debug/token/<token_id>:", repr(e))
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()

@app.route("/debug/replay-token/<token_id>", methods=["GET"])
def debug_replay_token(token_id):
    ensure_online_token_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, merchant_username, amount, note,
                   nonce, expires_at, status, signature, transaction_id,
                   reject_reason, used_at, created_at
            FROM online_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (token_id,)
        )
        row = cur.fetchone()

        if not row:
            return f"<h3>Token not found: {token_id}</h3>", 404

        payload = {
            "token_id": row["token_id"],
            "nonce": row["nonce"],
            "expires_at": token_dt_to_str(row["expires_at"]),
            "signature": row["signature"]
        }

        page_html = """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8"/>
          <title>Replay Token Test</title>
          <meta name="viewport" content="width=device-width, initial-scale=1"/>
          <style>
            body{
              font-family: Arial, sans-serif;
              background:#07112e;
              color:#fff;
              margin:0;
              padding:24px;
            }
            .card{
              max-width:980px;
              margin:0 auto;
              background:#0d1d4b;
              border:1px solid rgba(255,255,255,0.1);
              border-radius:18px;
              padding:20px;
            }
            h1,h2{
              margin:0 0 14px 0;
            }
            .muted{
              color:#c8d2f6;
              margin-bottom:18px;
            }
            .meta{
              display:grid;
              grid-template-columns:repeat(2,minmax(0,1fr));
              gap:12px;
              margin-bottom:18px;
            }
            .box{
              background:rgba(255,255,255,0.04);
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:12px;
            }
            .label{
              font-size:12px;
              color:#c8d2f6;
              text-transform:uppercase;
              margin-bottom:6px;
              font-weight:700;
            }
            pre{
              background:#06102b;
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:14px;
              overflow:auto;
              white-space:pre-wrap;
              word-break:break-word;
            }
            button{
              background:#4f8dff;
              color:white;
              border:none;
              border-radius:12px;
              padding:12px 18px;
              font-size:15px;
              font-weight:700;
              cursor:pointer;
            }
            #result{
              margin-top:18px;
            }
            .ok{
              color:#8ef0a7;
            }
            .bad{
              color:#ffb3b3;
            }
            a{
              color:#9ec5ff;
            }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Replay Token Test</h1>
            <div class="muted">
              This page replays the exact same token payload back to
              <b>/pay/online/tokenized</b> using your browser.
            </div>

            <div class="meta">
              <div class="box">
                <div class="label">Token ID</div>
                <div>{{ token_id }}</div>
              </div>
              <div class="box">
                <div class="label">Current Token Status</div>
                <div>{{ status }}</div>
              </div>
              <div class="box">
                <div class="label">Sender</div>
                <div>{{ sender_username }}</div>
              </div>
              <div class="box">
                <div class="label">Merchant</div>
                <div>{{ merchant_username }}</div>
              </div>
              <div class="box">
                <div class="label">Amount</div>
                <div>{{ amount }}</div>
              </div>
              <div class="box">
                <div class="label">Transaction ID</div>
                <div>{{ transaction_id or "-" }}</div>
              </div>
            </div>

            <h2>Replay Payload</h2>
            <pre id="payloadBox">{{ payload_json }}</pre>

            <button onclick="replayToken()">Replay Same Token</button>

            <div id="result"></div>

            <p style="margin-top:18px;">
              After replay, refresh:
              <a href="/debug/evidence/{{ token_id }}" target="_blank">/debug/evidence/{{ token_id }}</a>
            </p>
          </div>

          <script>
            const payload = {{ payload_json|safe }};

            async function replayToken() {
              const result = document.getElementById("result");
              result.innerHTML = "<p>Sending replay request...</p>";

              try {
                const res = await fetch("/pay/online/tokenized", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(payload)
                });

                const text = await res.text();
                let data = null;
                try {
                  data = JSON.parse(text);
                } catch (e) {}

                const cls = res.ok ? "ok" : "bad";

                result.innerHTML = `
                  <h2>Replay Result</h2>
                  <p class="${cls}"><b>HTTP ${res.status}</b></p>
                  <pre>${data ? JSON.stringify(data, null, 2) : text}</pre>
                `;
              } catch (e) {
                result.innerHTML = `
                  <h2>Replay Result</h2>
                  <p class="bad"><b>Browser request failed</b></p>
                  <pre>${e}</pre>
                `;
              }
            }
          </script>
        </body>
        </html>
        """

        return render_template_string(
            page_html,
            token_id=row["token_id"],
            status=row["status"],
            sender_username=row["sender_username"],
            merchant_username=row["merchant_username"],
            amount=float(row["amount"] or 0.0),
            transaction_id=row.get("transaction_id"),
            payload_json=json.dumps(payload, ensure_ascii=False, indent=2)
        )

    except Exception as e:
        print("ERROR in /debug/replay-token/<token_id>:", repr(e))
        return f"<h3>Server error: {str(e)}</h3>", 500

    finally:
        cur.close()
        conn.close()




@app.route("/debug/replay-offline-token/<offline_token_id>", methods=["GET"])
def debug_replay_offline_token(offline_token_id):
    ensure_offline_token_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, nonce, max_amount, expires_at, status, signature,
                   used_merchant_username, used_amount, client_tx_id, used_at
            FROM offline_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (offline_token_id,)
        )
        row = cur.fetchone()

        if not row:
            return f"<h3>Offline token not found: {offline_token_id}</h3>", 404

        merchant_username = (row.get("used_merchant_username") or "").strip()
        sender_username = (row.get("sender_username") or "").strip()
        used_amount = float(row.get("used_amount") or 0.0)
        status = (row.get("status") or "").upper()
        original_client_tx_id = row.get("client_tx_id") or ""

        if not merchant_username:
            return (
                "<h3>This offline token has not been used successfully before, "
                "so replay test cannot be created from it yet.</h3>",
                400
            )

        if used_amount <= 0:
            used_amount = min(float(row.get("max_amount") or 0.0), 1.0)

        payload = {
            "offline_token_id": row["token_id"],
            "merchant_username": merchant_username,
            "sender_username": sender_username,
            "amount": round(float(used_amount), 2),
            "offline_token_nonce": row["nonce"],
            "offline_token_expires_at": offline_token_dt_to_str(row["expires_at"]),
            "offline_token_signature": row["signature"],
            "original_client_tx_id": original_client_tx_id,
            "token_status": status
        }

        page_html = """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8"/>
          <title>Offline Replay Token Test</title>
          <meta name="viewport" content="width=device-width, initial-scale=1"/>
          <style>
            body{
              font-family: Arial, sans-serif;
              background:#07112e;
              color:#fff;
              margin:0;
              padding:24px;
            }
            .card{
              max-width:1000px;
              margin:0 auto;
              background:#0d1d4b;
              border:1px solid rgba(255,255,255,0.1);
              border-radius:18px;
              padding:20px;
            }
            h1,h2{
              margin:0 0 14px 0;
            }
            .muted{
              color:#c8d2f6;
              margin-bottom:18px;
            }
            .meta{
              display:grid;
              grid-template-columns:repeat(2,minmax(0,1fr));
              gap:12px;
              margin-bottom:18px;
            }
            .box{
              background:rgba(255,255,255,0.04);
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:12px;
            }
            .label{
              font-size:12px;
              color:#c8d2f6;
              text-transform:uppercase;
              margin-bottom:6px;
              font-weight:700;
            }
            pre{
              background:#06102b;
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:14px;
              overflow:auto;
              white-space:pre-wrap;
              word-break:break-word;
            }
            button{
              background:#4f8dff;
              color:white;
              border:none;
              border-radius:12px;
              padding:12px 18px;
              font-size:15px;
              font-weight:700;
              cursor:pointer;
            }
            button:disabled{
              opacity:0.65;
              cursor:not-allowed;
            }
            #result{
              margin-top:18px;
            }
            .ok{
              color:#8ef0a7;
            }
            .bad{
              color:#ffb3b3;
            }
            a{
              color:#9ec5ff;
            }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Offline Replay Token Test</h1>
            <div class="muted">
              This page queues a replay offline payment with the same already-used token,
              then immediately calls <b>/offline/queue/sync</b> from this browser session.
            </div>

            <div class="meta">
              <div class="box">
                <div class="label">Offline Token ID</div>
                <div>{{ offline_token_id }}</div>
              </div>
              <div class="box">
                <div class="label">Current Token Status</div>
                <div>{{ token_status }}</div>
              </div>
              <div class="box">
                <div class="label">Sender</div>
                <div>{{ sender_username }}</div>
              </div>
              <div class="box">
                <div class="label">Merchant</div>
                <div>{{ merchant_username }}</div>
              </div>
              <div class="box">
                <div class="label">Amount</div>
                <div>{{ amount }}</div>
              </div>
              <div class="box">
                <div class="label">Original Client Tx ID</div>
                <div>{{ original_client_tx_id or "-" }}</div>
              </div>
            </div>

            <h2>Replay Payload Basis</h2>
            <pre>{{ payload_json }}</pre>

            <button id="replayBtn" onclick="runReplay()">Replay Same Offline Token</button>

            <div id="result"></div>
          </div>

          <script>
            async function runReplay() {
              const btn = document.getElementById("replayBtn");
              const result = document.getElementById("result");
              btn.disabled = true;
              result.innerHTML = "<p>Queueing replay payment and running sync...</p>";

              try {
                const res = await fetch("/debug/replay-offline-token/{{ offline_token_id }}/run", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" }
                });

                const text = await res.text();
                let data = null;
                try {
                  data = JSON.parse(text);
                } catch (e) {}

                const cls = res.ok ? "ok" : "bad";

                let evidenceLink = "";
                if (data && data.replay_client_tx_id) {
                  evidenceLink = `
                    <p>
                      <a href="/debug/evidence/${data.replay_client_tx_id}" target="_blank">
                        Open replay evidence
                      </a>
                    </p>
                  `;
                }

                result.innerHTML = `
                  <h2>Replay Result</h2>
                  <p class="${cls}"><b>HTTP ${res.status}</b></p>
                  <pre>${data ? JSON.stringify(data, null, 2) : text}</pre>
                  ${evidenceLink}
                `;
              } catch (e) {
                result.innerHTML = `
                  <h2>Replay Result</h2>
                  <p class="bad"><b>Browser request failed</b></p>
                  <pre>${e}</pre>
                `;
              } finally {
                btn.disabled = false;
              }
            }
          </script>
        </body>
        </html>
        """

        return render_template_string(
            page_html,
            offline_token_id=row["token_id"],
            token_status=status,
            sender_username=sender_username,
            merchant_username=merchant_username,
            amount=round(float(used_amount), 2),
            original_client_tx_id=original_client_tx_id,
            payload_json=json.dumps(payload, ensure_ascii=False, indent=2)
        )

    except Exception as e:
        print("ERROR in /debug/replay-offline-token/<offline_token_id>:", repr(e))
        return f"<h3>Server error: {str(e)}</h3>", 500

    finally:
        cur.close()
        conn.close()


@app.route("/debug/replay-offline-token/<offline_token_id>/run", methods=["POST"])
@merchant_login_required
def debug_replay_offline_token_run(offline_token_id):
    ensure_offline_token_table()
    offline_init_db()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, nonce, max_amount, expires_at, status, signature,
                   used_merchant_username, used_amount, client_tx_id, used_at
            FROM offline_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (offline_token_id,)
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"status": "failure", "message": "Offline token not found"}), 404

        merchant_username = (row.get("used_merchant_username") or "").strip()
        sender_username = (row.get("sender_username") or "").strip()
        used_amount = float(row.get("used_amount") or 0.0)
        status = (row.get("status") or "").upper()
        original_client_tx_id = row.get("client_tx_id") or ""

        if not merchant_username:
            return jsonify({
                "status": "failure",
                "message": "This offline token has not been used successfully before."
            }), 400

        session_merchant = (session.get("merchant_username") or "").strip()
        if session_merchant.lower() != merchant_username.lower():
            return jsonify({
                "status": "failure",
                "message": f"Merchant session mismatch. Login as {merchant_username} first."
            }), 403

        if used_amount <= 0:
            used_amount = min(float(row.get("max_amount") or 0.0), 1.0)

        replay_client_tx_id = "BT-REPLAY-" + uuid.uuid4().hex[:12]
        created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        expires_at_str = offline_token_dt_to_str(row.get("expires_at"))

        conn2 = offline_db()
        cur2 = conn2.cursor()
        cur2.execute(
            """
            INSERT INTO offline_payments
            (client_tx_id, merchant_username, sender_username, amount, note, status, last_error, created_at,
             offline_token_id, offline_token_nonce, offline_token_expires_at, offline_token_signature)
            VALUES (?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?, ?, ?, ?)
            """,
            (
                replay_client_tx_id,
                merchant_username,
                sender_username,
                used_amount,
                "Replay test queued from debug route",
                created_at,
                row["token_id"],
                row["nonce"],
                expires_at_str,
                row["signature"]
            )
        )
        conn2.commit()
        conn2.close()

        log_audit_event(
            event_type="offline_token_replay_debug_queue",
            outcome="INFO",
            merchant_username=merchant_username,
            sender_username=sender_username,
            amount=used_amount,
            client_tx_id=replay_client_tx_id,
            details={
                "offline_token_id": offline_token_id,
                "original_client_tx_id": original_client_tx_id,
                "original_status": status,
                "message": "Replay test payment queued into local offline queue"
            }
        )

        sync_payload, sync_code = process_offline_sync(merchant_username, [{
            "client_tx_id": replay_client_tx_id,
            "sender_username": sender_username,
            "amount": used_amount,
            "note": "Replay test queued from debug route",
            "offline_token_id": row["token_id"],
            "offline_token_nonce": row["nonce"],
            "offline_token_expires_at": expires_at_str,
            "offline_token_signature": row["signature"]
        }])

        results = sync_payload.get("results", []) if isinstance(sync_payload, dict) else []

        conn3 = offline_db()
        cur3 = conn3.cursor()

        for r in results:
            txid = r.get("client_tx_id")
            st = r.get("status")
            msg = r.get("message")

            if st in ("SUCCESS", "DUPLICATE"):
                cur3.execute(
                    "UPDATE offline_payments SET status='SYNCED', last_error=NULL WHERE client_tx_id=?",
                    (txid,)
                )
            else:
                cur3.execute(
                    "UPDATE offline_payments SET status='FAILED', last_error=? WHERE client_tx_id=?",
                    (msg or "FAILED", txid)
                )

        conn3.commit()
        conn3.close()

        failed_count = len([r for r in results if r.get("status") == "FAILED"])
        success_count = len([r for r in results if r.get("status") in ("SUCCESS", "DUPLICATE")])

        log_audit_event(
            event_type="offline_queue_sync",
            outcome="SUCCESS" if failed_count == 0 else "PARTIAL",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={
                "success_count": success_count,
                "failed_count": failed_count,
                "results_count": len(results),
                "ip": request.remote_addr,
                "message": "Replay sync run from debug page"
            }
        )

        return jsonify({
            "status": "success" if sync_code == 200 else "failure",
            "message": "Offline replay queued and sync attempted",
            "replay_client_tx_id": replay_client_tx_id,
            "merchant_username": merchant_username,
            "sync_http_code": sync_code,
            "sync_payload": sync_payload,
            "evidence_url": f"/debug/evidence/{replay_client_tx_id}"
        }), 200 if sync_code == 200 else sync_code

    except Exception as e:
        print("ERROR in /debug/replay-offline-token/<offline_token_id>/run:", repr(e))
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


# ============================================================
# DEBUG EXPIRED TOKEN TESTING ROUTES
# ============================================================

@app.route("/debug/expire-token/<token_id>", methods=["GET"])
@merchant_login_required
def debug_expire_token(token_id):
    ensure_online_token_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, merchant_username, amount, note,
                   nonce, expires_at, status, signature, transaction_id,
                   reject_reason, used_at, created_at
            FROM online_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (token_id,)
        )
        row = cur.fetchone()

        if not row:
            return f"<h3>Token not found: {token_id}</h3>", 404

        session_merchant = (session.get("merchant_username") or "").strip()
        token_merchant = (row.get("merchant_username") or "").strip()

        if session_merchant.lower() != token_merchant.lower():
            return (
                f"<h3>Merchant session mismatch. Login as {token_merchant} first.</h3>",
                403
            )

        payload = {
            "token_id": row["token_id"],
            "nonce": row["nonce"],
            "expires_at": token_dt_to_str(row["expires_at"]),
            "signature": row["signature"]
        }

        page_html = """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8"/>
          <title>Online Expired Token Test</title>
          <meta name="viewport" content="width=device-width, initial-scale=1"/>
          <style>
            body{
              font-family: Arial, sans-serif;
              background:#07112e;
              color:#fff;
              margin:0;
              padding:24px;
            }
            .card{
              max-width:980px;
              margin:0 auto;
              background:#0d1d4b;
              border:1px solid rgba(255,255,255,0.1);
              border-radius:18px;
              padding:20px;
            }
            h1,h2{
              margin:0 0 14px 0;
            }
            .muted{
              color:#c8d2f6;
              margin-bottom:18px;
              line-height:1.5;
            }
            .meta{
              display:grid;
              grid-template-columns:repeat(2,minmax(0,1fr));
              gap:12px;
              margin-bottom:18px;
            }
            .box{
              background:rgba(255,255,255,0.04);
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:12px;
            }
            .label{
              font-size:12px;
              color:#c8d2f6;
              text-transform:uppercase;
              margin-bottom:6px;
              font-weight:700;
            }
            pre{
              background:#06102b;
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:14px;
              overflow:auto;
              white-space:pre-wrap;
              word-break:break-word;
            }
            button{
              background:#4f8dff;
              color:white;
              border:none;
              border-radius:12px;
              padding:12px 18px;
              font-size:15px;
              font-weight:700;
              cursor:pointer;
            }
            button:disabled{
              opacity:0.65;
              cursor:not-allowed;
            }
            #result{
              margin-top:18px;
            }
            .ok{
              color:#8ef0a7;
            }
            .bad{
              color:#ffb3b3;
            }
            a{
              color:#9ec5ff;
            }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Online Expired Token Test</h1>

            <div class="muted">
              This page forces the selected online token to expire in the backend,
              then sends the same token payload to <b>/pay/online/tokenized</b>.
              <br/><br/>
              Use this only on a fresh test token that has not been used yet.
            </div>

            <div class="meta">
              <div class="box">
                <div class="label">Token ID</div>
                <div>{{ token_id }}</div>
              </div>
              <div class="box">
                <div class="label">Current Status</div>
                <div>{{ status }}</div>
              </div>
              <div class="box">
                <div class="label">Sender</div>
                <div>{{ sender_username }}</div>
              </div>
              <div class="box">
                <div class="label">Merchant</div>
                <div>{{ merchant_username }}</div>
              </div>
              <div class="box">
                <div class="label">Amount</div>
                <div>{{ amount }}</div>
              </div>
              <div class="box">
                <div class="label">Current Expires At</div>
                <div>{{ expires_at }}</div>
              </div>
            </div>

            <h2>Payload That Will Be Sent</h2>
            <pre>{{ payload_json }}</pre>

            <button id="expireBtn" onclick="runExpiredTest()">Force Expire + Test Consume</button>

            <div id="result"></div>
          </div>

          <script>
            async function runExpiredTest() {
              const btn = document.getElementById("expireBtn");
              const result = document.getElementById("result");
              btn.disabled = true;
              result.innerHTML = "<p>Preparing expired token test...</p>";

              try {
                const prepRes = await fetch("/debug/expire-token/{{ token_id }}/run", {
                  method: "POST"
                });

                const prepText = await prepRes.text();
                let prepData = null;
                try {
                  prepData = JSON.parse(prepText);
                } catch (e) {}

                if (!prepRes.ok || !prepData || !prepData.payload) {
                  result.innerHTML = `
                    <h2>Prepare Result</h2>
                    <p class="bad"><b>HTTP ${prepRes.status}</b></p>
                    <pre>${prepData ? JSON.stringify(prepData, null, 2) : prepText}</pre>
                  `;
                  btn.disabled = false;
                  return;
                }

                result.innerHTML = `
                  <h2>Prepare Result</h2>
                  <p class="ok"><b>Token forced to expired state.</b></p>
                  <pre>${JSON.stringify(prepData, null, 2)}</pre>
                  <p>Now sending expired token to /pay/online/tokenized ...</p>
                `;

                const consumeRes = await fetch("/pay/online/tokenized", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(prepData.payload)
                });

                const consumeText = await consumeRes.text();
                let consumeData = null;
                try {
                  consumeData = JSON.parse(consumeText);
                } catch (e) {}

                const cls = consumeRes.ok ? "ok" : "bad";

                result.innerHTML += `
                  <h2>Consume Result</h2>
                  <p class="${cls}"><b>HTTP ${consumeRes.status}</b></p>
                  <pre>${consumeData ? JSON.stringify(consumeData, null, 2) : consumeText}</pre>
                  <p>
                    <a href="/debug/evidence/{{ token_id }}" target="_blank">
                      Open evidence for this token
                    </a>
                  </p>
                `;
              } catch (e) {
                result.innerHTML = `
                  <h2>Test Result</h2>
                  <p class="bad"><b>Browser request failed</b></p>
                  <pre>${e}</pre>
                `;
              } finally {
                btn.disabled = false;
              }
            }
          </script>
        </body>
        </html>
        """

        return render_template_string(
            page_html,
            token_id=row["token_id"],
            status=row["status"],
            sender_username=row["sender_username"],
            merchant_username=row["merchant_username"],
            amount=float(row["amount"] or 0.0),
            expires_at=token_dt_to_str(row["expires_at"]),
            payload_json=json.dumps(payload, ensure_ascii=False, indent=2)
        )

    except Exception as e:
        print("ERROR in /debug/expire-token/<token_id>:", repr(e))
        return f"<h3>Server error: {str(e)}</h3>", 500

    finally:
        cur.close()
        conn.close()


@app.route("/debug/expire-token/<token_id>/run", methods=["POST"])
@merchant_login_required
def debug_expire_token_run(token_id):
    ensure_online_token_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        cur.execute(
            """
            SELECT token_id, sender_username, merchant_username, amount, note,
                   nonce, expires_at, status, signature
            FROM online_payment_tokens
            WHERE token_id=%s
            FOR UPDATE
            """,
            (token_id,)
        )
        row = cur.fetchone()

        if not row:
            conn.rollback()
            return jsonify({"status": "failure", "message": "Token not found"}), 404

        session_merchant = (session.get("merchant_username") or "").strip()
        token_merchant = (row.get("merchant_username") or "").strip()

        if session_merchant.lower() != token_merchant.lower():
            conn.rollback()
            return jsonify({
                "status": "failure",
                "message": f"Merchant session mismatch. Login as {token_merchant} first."
            }), 403

        status = (row.get("status") or "").upper()
        if status != "ISSUED":
            conn.rollback()
            return jsonify({
                "status": "failure",
                "message": f"Token already expired. Current status: {status}"
            }), 400

        original_expires_at_str = token_dt_to_str(row.get("expires_at"))
        forced_expire_dt = datetime.utcnow() - timedelta(minutes=1)
        forced_expire_sql = forced_expire_dt.strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            UPDATE online_payment_tokens
            SET expires_at=%s
            WHERE token_id=%s
            """,
            (forced_expire_sql, token_id)
        )
        conn.commit()

        log_audit_event(
            event_type="online_token_expire_debug_prepare",
            outcome="INFO",
            sender_username=row.get("sender_username"),
            receiver_username=row.get("merchant_username"),
            merchant_username=row.get("merchant_username"),
            amount=float(row.get("amount") or 0.0),
            client_tx_id=token_id,
            details={
                "message": "Online token expiry forced by debug route",
                "original_expires_at": original_expires_at_str,
                "forced_expires_at": token_dt_to_str(forced_expire_dt),
                "ip": request.remote_addr
            }
        )

        payload = {
            "token_id": row["token_id"],
            "nonce": row["nonce"],
            "expires_at": original_expires_at_str,
            "signature": row["signature"]
        }

        return jsonify({
            "status": "success",
            "message": "Token forced to expired state. Ready to test consume.",
            "token_id": token_id,
            "original_expires_at": original_expires_at_str,
            "forced_expires_at": token_dt_to_str(forced_expire_dt),
            "payload": payload,
            "evidence_url": f"/debug/evidence/{token_id}"
        }), 200

    except Exception as e:
        print("ERROR in /debug/expire-token/<token_id>/run:", repr(e))
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()


@app.route("/debug/expire-offline-token/<offline_token_id>", methods=["GET"])
@merchant_login_required
def debug_expire_offline_token(offline_token_id):
    ensure_offline_token_table()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, nonce, max_amount, expires_at,
                   status, signature, used_merchant_username, used_amount,
                   client_tx_id, used_at
            FROM offline_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (offline_token_id,)
        )
        row = cur.fetchone()

        if not row:
            return f"<h3>Offline token not found: {offline_token_id}</h3>", 404

        merchant_username = (session.get("merchant_username") or "").strip()

        payload_preview = {
            "client_tx_id": "BT-EXPIRE-<auto-generated>",
            "merchant_username": merchant_username,
            "sender_username": row["sender_username"],
            "amount": round(min(float(row.get("max_amount") or 0.0), 1.0), 2),
            "note": "Expired offline token debug test",
            "offline_token_id": row["token_id"],
            "offline_token_nonce": row["nonce"],
            "offline_token_expires_at": offline_token_dt_to_str(row["expires_at"]),
            "offline_token_signature": row["signature"]
        }

        page_html = """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8"/>
          <title>Offline Expired Token Test</title>
          <meta name="viewport" content="width=device-width, initial-scale=1"/>
          <style>
            body{
              font-family: Arial, sans-serif;
              background:#07112e;
              color:#fff;
              margin:0;
              padding:24px;
            }
            .card{
              max-width:980px;
              margin:0 auto;
              background:#0d1d4b;
              border:1px solid rgba(255,255,255,0.1);
              border-radius:18px;
              padding:20px;
            }
            h1,h2{
              margin:0 0 14px 0;
            }
            .muted{
              color:#c8d2f6;
              margin-bottom:18px;
              line-height:1.5;
            }
            .meta{
              display:grid;
              grid-template-columns:repeat(2,minmax(0,1fr));
              gap:12px;
              margin-bottom:18px;
            }
            .box{
              background:rgba(255,255,255,0.04);
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:12px;
            }
            .label{
              font-size:12px;
              color:#c8d2f6;
              text-transform:uppercase;
              margin-bottom:6px;
              font-weight:700;
            }
            pre{
              background:#06102b;
              border:1px solid rgba(255,255,255,0.08);
              border-radius:12px;
              padding:14px;
              overflow:auto;
              white-space:pre-wrap;
              word-break:break-word;
            }
            button{
              background:#4f8dff;
              color:white;
              border:none;
              border-radius:12px;
              padding:12px 18px;
              font-size:15px;
              font-weight:700;
              cursor:pointer;
            }
            button:disabled{
              opacity:0.65;
              cursor:not-allowed;
            }
            #result{
              margin-top:18px;
            }
            .ok{
              color:#8ef0a7;
            }
            .bad{
              color:#ffb3b3;
            }
            a{
              color:#9ec5ff;
            }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Offline Expired Token Test</h1>

            <div class="muted">
              This page forces the selected offline token to expire in the backend,
              then queues one offline payment into the local SQLite queue and immediately runs sync.
              <br/><br/>
              Use this only on a fresh offline token that is still <b>ISSUED</b>.
            </div>

            <div class="meta">
              <div class="box">
                <div class="label">Offline Token ID</div>
                <div>{{ offline_token_id }}</div>
              </div>
              <div class="box">
                <div class="label">Current Status</div>
                <div>{{ token_status }}</div>
              </div>
              <div class="box">
                <div class="label">Sender</div>
                <div>{{ sender_username }}</div>
              </div>
              <div class="box">
                <div class="label">Merchant Session</div>
                <div>{{ merchant_username }}</div>
              </div>
              <div class="box">
                <div class="label">Max Amount</div>
                <div>{{ max_amount }}</div>
              </div>
              <div class="box">
                <div class="label">Current Expires At</div>
                <div>{{ expires_at }}</div>
              </div>
            </div>

            <h2>Queued Payload Preview</h2>
            <pre>{{ payload_json }}</pre>

            <button id="expireOfflineBtn" onclick="runExpiredOfflineTest()">Force Expire + Queue + Sync</button>

            <div id="result"></div>
          </div>

          <script>
            async function runExpiredOfflineTest() {
              const btn = document.getElementById("expireOfflineBtn");
              const result = document.getElementById("result");
              btn.disabled = true;
              result.innerHTML = "<p>Running expired offline token test...</p>";

              try {
                const res = await fetch("/debug/expire-offline-token/{{ offline_token_id }}/run", {
                  method: "POST"
                });

                const text = await res.text();
                let data = null;
                try {
                  data = JSON.parse(text);
                } catch (e) {}

                const cls = res.ok ? "ok" : "bad";

                let evidenceLink = "";
                if (data && data.expire_client_tx_id) {
                  evidenceLink = `
                    <p>
                      <a href="/debug/evidence/${data.expire_client_tx_id}" target="_blank">
                        Open expired-token evidence
                      </a>
                    </p>
                  `;
                }

                result.innerHTML = `
                  <h2>Expired Offline Test Result</h2>
                  <p class="${cls}"><b>HTTP ${res.status}</b></p>
                  <pre>${data ? JSON.stringify(data, null, 2) : text}</pre>
                  ${evidenceLink}
                `;
              } catch (e) {
                result.innerHTML = `
                  <h2>Expired Offline Test Result</h2>
                  <p class="bad"><b>Browser request failed</b></p>
                  <pre>${e}</pre>
                `;
              } finally {
                btn.disabled = false;
              }
            }
          </script>
        </body>
        </html>
        """

        return render_template_string(
            page_html,
            offline_token_id=row["token_id"],
            token_status=row["status"],
            sender_username=row["sender_username"],
            merchant_username=merchant_username,
            max_amount=round(float(row.get("max_amount") or 0.0), 2),
            expires_at=offline_token_dt_to_str(row["expires_at"]),
            payload_json=json.dumps(payload_preview, ensure_ascii=False, indent=2)
        )

    except Exception as e:
        print("ERROR in /debug/expire-offline-token/<offline_token_id>:", repr(e))
        return f"<h3>Server error: {str(e)}</h3>", 500

    finally:
        cur.close()
        conn.close()


@app.route("/debug/expire-offline-token/<offline_token_id>/run", methods=["POST"])
@merchant_login_required
def debug_expire_offline_token_run(offline_token_id):
    ensure_offline_token_table()
    offline_init_db()

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT token_id, sender_username, nonce, max_amount, expires_at,
                   status, signature
            FROM offline_payment_tokens
            WHERE token_id=%s
            LIMIT 1
            """,
            (offline_token_id,)
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"status": "failure", "message": "Offline token not found"}), 404

        status = (row.get("status") or "").upper()
        if status != "ISSUED":
            return jsonify({
                "status": "failure",
                "message": f"Token already expired. Current status: {status}"
            }), 400

        merchant_username = (session.get("merchant_username") or "").strip()
        sender_username = (row.get("sender_username") or "").strip()
        max_amount = float(row.get("max_amount") or 0.0)

        if max_amount <= 0:
            return jsonify({
                "status": "failure",
                "message": "Offline token max amount must be greater than 0"
            }), 400

        original_expires_at_str = offline_token_dt_to_str(row.get("expires_at"))
        forced_expire_dt = datetime.utcnow() - timedelta(minutes=1)
        forced_expire_sql = forced_expire_dt.strftime("%Y-%m-%d %H:%M:%S")
        amount = round(min(max_amount, 1.0), 2)

        cur.execute(
            """
            UPDATE offline_payment_tokens
            SET expires_at=%s
            WHERE token_id=%s
            """,
            (forced_expire_sql, offline_token_id)
        )
        conn.commit()

        log_audit_event(
            event_type="offline_token_expire_debug_prepare",
            outcome="INFO",
            merchant_username=merchant_username,
            sender_username=sender_username,
            amount=amount,
            client_tx_id=offline_token_id,
            details={
                "message": "Offline token expiry forced by debug route",
                "original_expires_at": original_expires_at_str,
                "forced_expires_at": offline_token_dt_to_str(forced_expire_dt),
                "offline_token_id": offline_token_id,
                "ip": request.remote_addr
            }
        )

        expire_client_tx_id = "BT-EXPIRE-" + uuid.uuid4().hex[:12]
        created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        conn2 = offline_db()
        cur2 = conn2.cursor()
        cur2.execute(
            """
            INSERT INTO offline_payments
            (client_tx_id, merchant_username, sender_username, amount, note, status, last_error, created_at,
             offline_token_id, offline_token_nonce, offline_token_expires_at, offline_token_signature)
            VALUES (?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?, ?, ?, ?)
            """,
            (
                expire_client_tx_id,
                merchant_username,
                sender_username,
                amount,
                "Expired offline token debug test",
                created_at,
                row["token_id"],
                row["nonce"],
                original_expires_at_str,
                row["signature"]
            )
        )
        conn2.commit()
        conn2.close()

        log_audit_event(
            event_type="offline_token_expire_debug_queue",
            outcome="INFO",
            merchant_username=merchant_username,
            sender_username=sender_username,
            amount=amount,
            client_tx_id=expire_client_tx_id,
            details={
                "message": "Expired offline token test payment queued into local offline queue",
                "offline_token_id": offline_token_id
            }
        )

        sync_payload, sync_code = process_offline_sync(merchant_username, [{
            "client_tx_id": expire_client_tx_id,
            "sender_username": sender_username,
            "amount": amount,
            "note": "Expired offline token debug test",
            "offline_token_id": row["token_id"],
            "offline_token_nonce": row["nonce"],
            "offline_token_expires_at": original_expires_at_str,
            "offline_token_signature": row["signature"]
        }])

        results = sync_payload.get("results", []) if isinstance(sync_payload, dict) else []

        conn3 = offline_db()
        cur3 = conn3.cursor()

        for r in results:
            txid = r.get("client_tx_id")
            st = r.get("status")
            msg = r.get("message")

            if st in ("SUCCESS", "DUPLICATE"):
                cur3.execute(
                    "UPDATE offline_payments SET status='SYNCED', last_error=NULL WHERE client_tx_id=?",
                    (txid,)
                )
            else:
                cur3.execute(
                    "UPDATE offline_payments SET status='FAILED', last_error=? WHERE client_tx_id=?",
                    (msg or "FAILED", txid)
                )

        conn3.commit()
        conn3.close()

        failed_count = len([r for r in results if r.get("status") == "FAILED"])
        success_count = len([r for r in results if r.get("status") in ("SUCCESS", "DUPLICATE")])

        log_audit_event(
            event_type="offline_queue_sync",
            outcome="SUCCESS" if failed_count == 0 else "PARTIAL",
            actor_username=merchant_username,
            merchant_username=merchant_username,
            details={
                "success_count": success_count,
                "failed_count": failed_count,
                "results_count": len(results),
                "ip": request.remote_addr,
                "message": "Expired offline token sync run from debug page"
            }
        )

        return jsonify({
            "status": "success" if sync_code == 200 else "failure",
            "message": "Expired offline token test queued and sync attempted",
            "expire_client_tx_id": expire_client_tx_id,
            "merchant_username": merchant_username,
            "sync_http_code": sync_code,
            "sync_payload": sync_payload,
            "evidence_url": f"/debug/evidence/{expire_client_tx_id}"
        }), 200 if sync_code == 200 else sync_code

    except Exception as e:
        print("ERROR in /debug/expire-offline-token/<offline_token_id>/run:", repr(e))
        return jsonify({"status": "failure", "message": f"Server error: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    ensure_password_hash_column()
    backfill_password_hashes()
    print("Starting Flask server...")
    app.run(host="0.0.0.0", port=5000, debug=True)