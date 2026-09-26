#!/usr/bin/env python3
"""Create / extend customer accounts in the Cockpit panel's SQLite databases (CMTV local addition 2026-09-24).

Cockpit has no API and its admin needs 2FA, so billing writes the same rows Cockpit's own admin form writes.
Run as www-data (cockpit_service.py does this), so any SQLite -wal/-shm/-journal file stays writable by Cockpit.
Standard library only. Reads one JSON request on stdin, prints one JSON result on stdout.

Before every write the table layout is checked against what this code was written for; if Cockpit changes it,
nothing is written and an error comes back (the order is then flagged "Not provisioned" and the admin alerted).
"""
import json, sqlite3, sys, time
from datetime import datetime, timezone

MODULES = {
    # Stremio (Nuvio app). Cockpit creates the Nuvio cloud account itself at the customer's first app login.
    "nuvio": {
        "db": "/var/www/html/cockpit/panel/nuvio/includes/db/cockpit_nuvio.sqlite",
        "table": "nuvio_users",
        "columns": {"id", "username", "password_hash", "password_plain", "email", "display_name",
                    "status", "expires_at", "created_at", "updated_at"},
    },
    # CMTVpn (IPVanish app)
    "vpn": {
        "db": "/var/www/html/cockpit/panel/ipvanish/includes/db/cockpit_ipvanish.sqlite",
        "table": "ipvanish_clients",
        "columns": {"id", "username", "password", "expirey", "status"},
    },
}
RENEWABLE_STATUSES = {"active", "expired", "inactive", ""}   # never silently un-ban a banned/disabled account


def end_of_day_ts(day: str) -> int:
    """'2026-10-24' -> unix time of 23:59:59 UTC that day (how Cockpit's own form stores Nuvio expiry)"""
    d = datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    return int(d.timestamp())


def connect(mod):
    con = sqlite3.connect(mod["db"], timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 15000")
    cols = {r["name"] for r in con.execute(f'PRAGMA table_info("{mod["table"]}")')}
    if cols != mod["columns"]:
        raise RuntimeError(f"Cockpit's {mod['table']} table layout changed (expected {sorted(mod['columns'])}, "
                           f"found {sorted(cols)}); nothing was written")
    return con


def find(con, mod, username):
    return con.execute(f'SELECT * FROM "{mod["table"]}" WHERE lower(username) = lower(?)', (username,)).fetchone()


def expiry_of(module, row):
    if module == "nuvio":
        return datetime.fromtimestamp(int(row["expires_at"] or 0), timezone.utc).strftime("%Y-%m-%d")
    return (row["expirey"] or "")[:10]


def handle(req):
    module = req.get("module")
    mod = MODULES.get(module)
    if not mod:
        raise ValueError(f"unknown Cockpit module {module!r}")
    action, username = req.get("action"), (req.get("username") or "").strip()
    if not username and action != "list":
        raise ValueError("username is required")
    con = connect(mod)
    try:
        # CMTV local change 2026-09-26: list / set_expiry / set_password for billing's Admin > Add-ons page
        if action == "list":
            last_login = {}
            if module == "nuvio":
                try:   # when the customer last signed in to the app (Cockpit's own table; read only)
                    last_login = {r["user_id"]: r["last_login_at"] for r in
                                  con.execute("SELECT user_id, last_login_at FROM nuvio_user_mappings")}
                except sqlite3.Error:
                    pass
            users = []
            for row in con.execute(f'SELECT * FROM "{mod["table"]}" ORDER BY id'):
                users.append({"id": row["id"], "username": row["username"], "status": row["status"] or "",
                              "expires": expiry_of(module, row),
                              "password": row["password_plain"] if module == "nuvio" else row["password"],
                              "created_at": row["created_at"] if module == "nuvio" else None,
                              "last_login_at": last_login.get(row["id"])})
            return {"users": users}

        if action == "set_password":
            password = str(req.get("password") or "")
            if len(password) < 6:
                raise ValueError("password must be at least 6 characters")
            con.execute("BEGIN IMMEDIATE")
            row = find(con, mod, username)
            if not row:
                raise RuntimeError(f"username {username!r} not found in Cockpit ({module})")
            if module == "nuvio":
                pw_hash = req.get("password_hash") or ""
                if not pw_hash.startswith("$2y$") or len(pw_hash) != 60:
                    raise ValueError("password_hash must be a 60-character $2y$ bcrypt hash")
                con.execute('UPDATE nuvio_users SET password_hash = ?, password_plain = ?, updated_at = ? WHERE id = ?',
                            (pw_hash, password, int(time.time()), row["id"]))
            else:
                con.execute('UPDATE ipvanish_clients SET password = ? WHERE id = ?', (password, row["id"]))
            con.commit()
            return {"id": row["id"]}

        if action == "get":
            row = find(con, mod, username)
            return {"exists": bool(row), **({"id": row["id"], "status": row["status"], "expires": expiry_of(module, row)} if row else {})}

        expires = req.get("expires") or ""
        datetime.strptime(expires, "%Y-%m-%d")   # validates the date
        con.execute("BEGIN IMMEDIATE")
        row = find(con, mod, username)

        if action == "create":
            if row:
                raise RuntimeError(f"username {username!r} already exists in Cockpit ({module})")
            now = int(time.time())
            if module == "nuvio":
                pw_hash = req.get("password_hash") or ""
                if not pw_hash.startswith("$2y$") or len(pw_hash) != 60:
                    raise ValueError("password_hash must be a 60-character $2y$ bcrypt hash")
                cur = con.execute(
                    'INSERT INTO nuvio_users (username, password_hash, password_plain, email, display_name, status, '
                    'expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (username, pw_hash, req["password"], "", username, "active", end_of_day_ts(expires), now, now))
            else:
                cur = con.execute('INSERT INTO ipvanish_clients (username, password, expirey, status) VALUES (?, ?, ?, ?)',
                                  (username, req["password"], expires, "active"))
            con.commit()
            return {"id": cur.lastrowid, "expires": expires}

        if action == "extend":
            if not row:
                raise RuntimeError(f"username {username!r} not found in Cockpit ({module})")
            if (row["status"] or "").lower() not in RENEWABLE_STATUSES:
                raise RuntimeError(f"Cockpit account {username!r} is {row['status']!r}; not extended (unban it in Cockpit first)")
            if module == "nuvio":
                con.execute('UPDATE nuvio_users SET expires_at = ?, status = ?, updated_at = ? WHERE id = ?',
                            (end_of_day_ts(expires), "active", int(time.time()), row["id"]))
            else:
                con.execute('UPDATE ipvanish_clients SET expirey = ?, status = ? WHERE id = ?', (expires, "active", row["id"]))
            con.commit()
            return {"id": row["id"], "expires": expires, "previous_expires": expiry_of(module, row)}

        if action == "set_expiry":
            # exact end date, status left alone (billing's "switch off" = end date yesterday, the real date kept in billing)
            if not row:
                raise RuntimeError(f"username {username!r} not found in Cockpit ({module})")
            if module == "nuvio":
                con.execute('UPDATE nuvio_users SET expires_at = ?, updated_at = ? WHERE id = ?',
                            (end_of_day_ts(expires), int(time.time()), row["id"]))
            else:
                con.execute('UPDATE ipvanish_clients SET expirey = ? WHERE id = ?', (expires, row["id"]))
            con.commit()
            return {"id": row["id"], "expires": expires, "previous_expires": expiry_of(module, row)}

        raise ValueError(f"unknown action {action!r}")
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
        print(json.dumps({"success": True, **result}))
    except Exception as e:
        print(json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"}))
