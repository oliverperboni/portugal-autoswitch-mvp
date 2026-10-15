"""Portugal AutoSwitch MVP backend. Stdlib only: http.server + sqlite3. Run: python3 app.py"""
import json
import sqlite3
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "autoswitch.db")
OFFERS_PATH = os.path.join(BASE, "offers.json")

import sys
sys.path.insert(0, BASE)
from compare import load_offers, rank_offers, annual_cost_ex_vat

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS contracts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, email TEXT, cpe TEXT UNIQUE,
        current_supplier TEXT, current_offer_id TEXT,
        power_kva REAL DEFAULT 4.6, tariff TEXT DEFAULT 'simples',
        annual_kwh REAL DEFAULT 3500, night_share REAL DEFAULT 0.4,
        contract_end TEXT, autoswitch INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS switches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER, from_offer TEXT, to_offer TEXT,
        saving_ex_vat REAL, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT,
        FOREIGN KEY(contract_id) REFERENCES contracts(id)
    )""")
    con.commit()
    con.close()

def contract_due(contract_end_str, window_days=30):
    if not contract_end_str:
        return True  # no end date = always eligible (no fidelity)
    try:
        end = date.fromisoformat(contract_end_str)
        return (end - date.today()).days <= window_days
    except Exception:
        return True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        if not ln:
            return {}
        return json.loads(self.rfile.read(ln).decode("utf-8") or "{}")

    def serve_static(self, path):
        public = os.path.join(BASE, "public")
        if path in ("/", "/index.html"):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(public, path.lstrip("/")))
        if not fp.startswith(public) or not os.path.isfile(fp):
            self.send_response(404); self.end_headers(); return
        ctype = "text/html" if fp.endswith(".html") else "application/javascript" if fp.endswith(".js") else "application/json" if fp.endswith(".json") else "text/plain"
        with open(fp, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/offers":
            offers, _ = load_offers(OFFERS_PATH)
            return self.send_json({"offers": offers})
        if u.path == "/api/contracts":
            con = db()
            rows = [dict(r) for r in con.execute("SELECT * FROM contracts ORDER BY id DESC").fetchall()]
            con.close()
            return self.send_json({"contracts": rows})
        if u.path == "/api/switches":
            con = db()
            rows = [dict(r) for r in con.execute("SELECT * FROM switches ORDER BY id DESC LIMIT 50").fetchall()]
            con.close()
            return self.send_json({"switches": rows})
        if u.path.startswith("/api/compare"):
            qs = parse_qs(u.query)
            try:
                cid = int(qs.get("contract_id", [0])[0])
            except ValueError:
                return self.send_json({"error": "invalid contract_id"}, 400)
            con = db()
            c = con.execute("SELECT * FROM contracts WHERE id=?", (cid,)).fetchone()
            con.close()
            if not c:
                return self.send_json({"error": "contract not found"}, 404)
            c = dict(c)
            offers, _ = load_offers(OFFERS_PATH)
            ranked, reco = rank_offers(offers, c["power_kva"], c["annual_kwh"], c["tariff"], c.get("current_offer_id"))
            return self.send_json({"contract": c, "ranked": ranked, "recommendation": reco,
                                   "due": contract_due(c.get("contract_end"))})
        self.serve_static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/contracts":
            data = self.read_json()
            if not data.get("cpe") or not data.get("email"):
                return self.send_json({"error": "cpe and email required"}, 400)
            if not data.get("consent"):
                return self.send_json({"error": "Explicit AutoSwitch mandate consent required (RGPD/ERSE)."}, 400)
            con = db()
            try:
                cur = con.execute("""INSERT INTO contracts(name,email,cpe,current_supplier,current_offer_id,
                    power_kva,tariff,annual_kwh,night_share,contract_end,autoswitch)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (data.get("name",""), data["email"], data["cpe"], data.get("current_supplier",""),
                     data.get("current_offer_id"), float(data.get("power_kva",4.6)),
                     data.get("tariff","simples"), float(data.get("annual_kwh",3500)),
                     float(data.get("night_share",0.4)), data.get("contract_end"),
                     1 if data.get("autoswitch", True) else 0))
                con.commit()
                cid = cur.lastrowid
            except sqlite3.IntegrityError:
                con.close()
                return self.send_json({"error": "CPE already registered"}, 409)
            con.close()
            return self.send_json({"ok": True, "id": cid}, 201)

        if u.path == "/api/cron/run":
            # AutoSwitch scan: for each autoswitch=1 contract, if due + saving>=threshold -> create pending switch
            data = self.read_json() if self.headers.get("Content-Length") else {}
            threshold = float(data.get("min_saving", 20.0)) if isinstance(data, dict) else 20.0
            offers, _ = load_offers(OFFERS_PATH)
            con = db()
            contracts = [dict(r) for r in con.execute("SELECT * FROM contracts WHERE autoswitch=1").fetchall()]
            created = []
            for c in contracts:
                if not contract_due(c.get("contract_end")):
                    continue
                _, reco = rank_offers(offers, c["power_kva"], c["annual_kwh"], c["tariff"],
                                     c.get("current_offer_id"), min_saving=threshold)
                if not reco:
                    continue
                # avoid duplicate pending for same target
                dup = con.execute("SELECT id FROM switches WHERE contract_id=? AND to_offer=? AND status='pending'",
                                  (c["id"], reco["offer"]["id"])).fetchone()
                if dup:
                    continue
                exp = (datetime.now() + timedelta(hours=48)).isoformat(timespec="seconds")
                cur = con.execute("INSERT INTO switches(contract_id,from_offer,to_offer,saving_ex_vat,status,expires_at) VALUES(?,?,?,?,?,?)",
                    (c["id"], c.get("current_offer_id",""), reco["offer"]["id"], reco["saving_ex_vat"], "pending", exp))
                created.append({"switch_id": cur.lastrowid, "contract_id": c["id"],
                                "to": reco["offer"]["id"], "saving": reco["saving_ex_vat"]})
            con.commit(); con.close()
            return self.send_json({"ok": True, "created": created})

        if u.path.startswith("/api/switches/"):
            # /api/switches/<id>/confirm | /cancel | /execute
            parts = u.path.split("/")
            try:
                sid = int(parts[3]); action = parts[4]
            except (IndexError, ValueError):
                return self.send_json({"error": "bad path"}, 400)
            con = db()
            sw = con.execute("SELECT * FROM switches WHERE id=?", (sid,)).fetchone()
            if not sw:
                con.close(); return self.send_json({"error": "not found"}, 404)
            sw = dict(sw)
            if action == "cancel":
                con.execute("UPDATE switches SET status='cancelled' WHERE id=?", (sid,))
            elif action == "confirm":
                con.execute("UPDATE switches SET status='confirmed' WHERE id=?", (sid,))
            elif action == "execute":
                # simulate execution: mark executed + update contract current_offer
                con.execute("UPDATE switches SET status='executed' WHERE id=?", (sid,))
                # update offer id + supplier name from offers.json
                offers, _ = load_offers(OFFERS_PATH)
                target = next((o for o in offers if o["id"] == sw["to_offer"]), None)
                if target:
                    con.execute("UPDATE contracts SET current_offer_id=?, current_supplier=? WHERE id=?",
                                (target["id"], target["supplier"], sw["contract_id"]))
            else:
                con.close(); return self.send_json({"error": "unknown action"}, 400)
            con.commit(); con.close()
            return self.send_json({"ok": True, "action": action})

        return self.send_json({"error": "not found"}, 404)

if __name__ == "__main__":
    init_db()
    port = 8787
    print(f"Portugal AutoSwitch MVP on http://localhost:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
