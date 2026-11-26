"""Servis jurnali ma'lumotlar bazasi (SQLite): mijozlar, qurilmalar, buyurtmalar, ehtiyot qismlar, ustalar."""
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

STATUSES = ["received", "diagnosis", "waiting_parts", "ready", "delivered"]
OPEN_STATUSES = ("received", "diagnosis", "waiting_parts")
DEVICE_TYPES = ["laptop", "desktop", "monoblock", "monitor", "printer", "phone", "tablet", "other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', phone2 TEXT DEFAULT '',
    address TEXT DEFAULT '', note TEXT DEFAULT '', created TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY, client_id INTEGER REFERENCES clients(id), type TEXT DEFAULT 'laptop',
    brand TEXT DEFAULT '', model TEXT DEFAULT '', serial TEXT DEFAULT '', password TEXT DEFAULT '',
    accessories TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS technicians (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, number TEXT UNIQUE, client_id INTEGER REFERENCES clients(id),
    device_id INTEGER REFERENCES devices(id), technician_id INTEGER REFERENCES technicians(id),
    received TEXT, due_date TEXT, problem TEXT DEFAULT '', diagnosis TEXT DEFAULT '', work_done TEXT DEFAULT '',
    labor_price REAL DEFAULT 0, prepayment REAL DEFAULT 0, status TEXT DEFAULT 'received',
    warranty_days INTEGER DEFAULT 30, completed TEXT, delivered TEXT, note TEXT DEFAULT '', updated TEXT
);
CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    name TEXT NOT NULL, qty REAL DEFAULT 1, price REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS status_log (
    id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE, status TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS ix_clients_phone ON clients(phone);
CREATE INDEX IF NOT EXISTS ix_devices_serial ON devices(serial);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today() -> str:
    return date.today().isoformat()


def digits(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


class DB:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self):
        self.con.close()

    def q(self, sql, args=()) -> List[sqlite3.Row]:
        return self.con.execute(sql, args).fetchall()

    def one(self, sql, args=()) -> Optional[sqlite3.Row]:
        return self.con.execute(sql, args).fetchone()

    # ------------------------------------------------------------------ sozlamalar
    def get_setting(self, key: str, default: str = "") -> str:
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r and r["value"] is not None else default

    def set_setting(self, key: str, value: str):
        self.con.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))
        self.con.commit()

    # ------------------------------------------------------------------ mijozlar
    def add_client(self, name, phone="", phone2="", address="", note="") -> int:
        cur = self.con.execute("INSERT INTO clients(name, phone, phone2, address, note, created) VALUES(?,?,?,?,?,?)",
                               (name.strip(), phone.strip(), phone2.strip(), address.strip(), note.strip(), now()))
        self.con.commit()
        return cur.lastrowid

    def update_client(self, cid: int, **kw):
        self._update("clients", cid, kw, ("name", "phone", "phone2", "address", "note"))

    def find_client_by_phone(self, phone: str) -> Optional[sqlite3.Row]:
        d = digits(phone)
        if len(d) < 7:
            return None
        for r in self.q("SELECT * FROM clients"):
            if digits(r["phone"]).endswith(d[-9:]) or (r["phone2"] and digits(r["phone2"]).endswith(d[-9:])):
                return r
        return None

    def clients(self, search: str = "") -> List[dict]:
        rows = self.q("""SELECT c.*, COUNT(o.id) AS orders,
                         COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.labor_price +
                             (SELECT COALESCE(SUM(p.qty*p.price),0) FROM parts p WHERE p.order_id=o.id) END), 0) AS spent,
                         MAX(o.received) AS last_visit
                         FROM clients c LEFT JOIN orders o ON o.client_id=c.id GROUP BY c.id ORDER BY c.name""")
        out = [dict(r) for r in rows]
        if search:
            s, d = search.lower().strip(), digits(search)
            out = [c for c in out if s in c["name"].lower() or (d and (d in digits(c["phone"]) or d in digits(c["phone2"])))]
        return out

    def client(self, cid: int) -> Optional[dict]:
        r = self.one("SELECT * FROM clients WHERE id=?", (cid,))
        return dict(r) if r else None

    # ------------------------------------------------------------------ qurilmalar
    def add_device(self, client_id, type="laptop", brand="", model="", serial="", password="", accessories="",
                   note="") -> int:
        cur = self.con.execute("INSERT INTO devices(client_id, type, brand, model, serial, password, accessories, note) "
                               "VALUES(?,?,?,?,?,?,?,?)",
                               (client_id, type, brand.strip(), model.strip(), serial.strip(), password, accessories.strip(),
                                note.strip()))
        self.con.commit()
        return cur.lastrowid

    def update_device(self, did: int, **kw):
        self._update("devices", did, kw, ("type", "brand", "model", "serial", "password", "accessories", "note"))

    def devices_of(self, client_id: int) -> List[dict]:
        return [dict(r) for r in self.q("SELECT * FROM devices WHERE client_id=? ORDER BY id DESC", (client_id,))]

    # ------------------------------------------------------------------ ustalar
    def add_technician(self, name, phone="") -> int:
        cur = self.con.execute("INSERT INTO technicians(name, phone) VALUES(?,?)", (name.strip(), phone.strip()))
        self.con.commit()
        return cur.lastrowid

    def technicians(self, active_only=True) -> List[dict]:
        sql = "SELECT * FROM technicians" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
        return [dict(r) for r in self.q(sql)]

    def set_technician_active(self, tid: int, active: bool):
        self.con.execute("UPDATE technicians SET active=? WHERE id=?", (1 if active else 0, tid))
        self.con.commit()

    # ------------------------------------------------------------------ buyurtmalar
    def next_number(self, year: int = None) -> str:
        year = year or date.today().year
        r = self.one("SELECT number FROM orders WHERE number LIKE ? ORDER BY number DESC LIMIT 1", (f"{year}-%",))
        n = int(r["number"].split("-")[1]) + 1 if r else 1
        return f"{year}-{n:04d}"

    def create_order(self, client_id, device_id, problem="", technician_id=None, prepayment=0.0, due_date=None,
                     warranty_days=30, received=None, note="") -> int:
        received = received or now()
        number = self.next_number(int(received[:4]))
        cur = self.con.execute(
            "INSERT INTO orders(number, client_id, device_id, technician_id, received, due_date, problem, prepayment, "
            "status, warranty_days, note, updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, client_id, device_id, technician_id, received, due_date, problem.strip(), float(prepayment or 0),
             "received", int(warranty_days), note, now()))
        oid = cur.lastrowid
        self.con.execute("INSERT INTO status_log(order_id, status, at) VALUES(?,?,?)", (oid, "received", received))
        self.con.commit()
        return oid

    def update_order(self, oid: int, **kw):
        kw["updated"] = now()
        self._update("orders", oid, kw, ("technician_id", "due_date", "problem", "diagnosis", "work_done", "labor_price",
                                         "prepayment", "warranty_days", "note", "updated", "received"))

    def set_status(self, oid: int, status: str, at: str = None):
        if status not in STATUSES:
            raise ValueError(status)
        at = at or now()
        o = self.one("SELECT status, completed FROM orders WHERE id=?", (oid,))
        if o is None or o["status"] == status:
            return
        fields = {"status": status, "updated": at}
        if status == "ready" and not o["completed"]:
            fields["completed"] = at
        if status == "delivered":
            fields["delivered"] = at
            if not o["completed"]:
                fields["completed"] = at
        if status in OPEN_STATUSES:
            fields["delivered"] = None
        sets = ", ".join(f"{k}=?" for k in fields)
        self.con.execute(f"UPDATE orders SET {sets} WHERE id=?", (*fields.values(), oid))
        self.con.execute("INSERT INTO status_log(order_id, status, at) VALUES(?,?,?)", (oid, status, at))
        self.con.commit()

    def delete_order(self, oid: int):
        self.con.execute("DELETE FROM orders WHERE id=?", (oid,))
        self.con.commit()

    _ORDER_SQL = """SELECT o.*, c.name AS client_name, c.phone AS client_phone, d.type AS device_type,
        d.brand, d.model, d.serial, d.password, d.accessories, t.name AS technician,
        (SELECT COALESCE(SUM(p.qty*p.price),0) FROM parts p WHERE p.order_id=o.id) AS parts_total
        FROM orders o LEFT JOIN clients c ON c.id=o.client_id LEFT JOIN devices d ON d.id=o.device_id
        LEFT JOIN technicians t ON t.id=o.technician_id"""

    @staticmethod
    def _enrich(r) -> dict:
        d = dict(r)
        d["total"] = round((d.get("labor_price") or 0) + (d.get("parts_total") or 0), 2)
        d["due"] = round(d["total"] - (d.get("prepayment") or 0), 2)
        d["device"] = " ".join(x for x in (d.get("brand"), d.get("model")) if x)
        return d

    def order(self, oid: int) -> Optional[dict]:
        r = self.one(self._ORDER_SQL + " WHERE o.id=?", (oid,))
        return self._enrich(r) if r else None

    def orders(self, search: str = "", status: str = "", limit: int = 2000) -> List[dict]:
        where, args = [], []
        if status == "open":
            where.append(f"o.status IN ({','.join('?' * len(OPEN_STATUSES))})")
            args += list(OPEN_STATUSES)
        elif status == "overdue":
            where.append(f"o.status IN ({','.join('?' * len(OPEN_STATUSES))}) AND o.due_date IS NOT NULL AND o.due_date < ?")
            args += list(OPEN_STATUSES) + [today()]
        elif status:
            where.append("o.status=?")
            args.append(status)
        if search.strip():
            s = f"%{search.strip().lower()}%"
            dg = digits(search)
            cond = ["lower(c.name) LIKE ?", "lower(d.serial) LIKE ?", "lower(o.number) LIKE ?",
                    "lower(d.brand || ' ' || d.model) LIKE ?"]
            args += [s, s, s, s]
            if len(dg) >= 3:
                cond.append("replace(replace(replace(replace(c.phone,' ',''),'-',''),'+',''),'(','') LIKE ?")
                args.append(f"%{dg}%")
            where.append("(" + " OR ".join(cond) + ")")
        sql = self._ORDER_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY o.id DESC LIMIT ?"
        args.append(limit)
        return [self._enrich(r) for r in self.q(sql, args)]

    def status_history(self, oid: int) -> List[dict]:
        return [dict(r) for r in self.q("SELECT status, at FROM status_log WHERE order_id=? ORDER BY id", (oid,))]

    # ------------------------------------------------------------------ ehtiyot qismlar
    def add_part(self, oid: int, name: str, qty: float = 1, price: float = 0) -> int:
        cur = self.con.execute("INSERT INTO parts(order_id, name, qty, price) VALUES(?,?,?,?)",
                               (oid, name.strip(), float(qty), float(price)))
        self.con.execute("UPDATE orders SET updated=? WHERE id=?", (now(), oid))
        self.con.commit()
        return cur.lastrowid

    def parts(self, oid: int) -> List[dict]:
        return [dict(r) for r in self.q("SELECT * FROM parts WHERE order_id=? ORDER BY id", (oid,))]

    def delete_part(self, pid: int):
        self.con.execute("DELETE FROM parts WHERE id=?", (pid,))
        self.con.commit()

    # ------------------------------------------------------------------ statistika
    def stats(self, on: date = None) -> Dict[str, float]:
        on = on or date.today()
        open_n = self.one(f"SELECT COUNT(*) n FROM orders WHERE status IN ({','.join('?' * 3)})", OPEN_STATUSES)["n"]
        ready_n = self.one("SELECT COUNT(*) n FROM orders WHERE status='ready'")["n"]
        overdue = self.one(f"SELECT COUNT(*) n FROM orders WHERE status IN ({','.join('?' * 3)}) AND due_date IS NOT NULL "
                           "AND due_date < ?", (*OPEN_STATUSES, on.isoformat()))["n"]
        month = on.strftime("%Y-%m")
        rev = self.revenue_by_month(1, on)
        return {"open": open_n, "ready": ready_n, "overdue": overdue,
                "month_revenue": rev[0][1] if rev else 0.0,
                "month_orders": self.one("SELECT COUNT(*) n FROM orders WHERE substr(received,1,7)=?", (month,))["n"]}

    def revenue_by_month(self, months: int = 12, on: date = None) -> List[tuple]:
        """[(YYYY-MM, daromad)] — topshirilgan buyurtmalar (topshirilgan oy bo'yicha), eskidan yangiga."""
        on = on or date.today()
        keys = []
        y, m = on.year, on.month
        for _ in range(months):
            keys.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        keys.reverse()
        rows = self.q("""SELECT substr(o.delivered,1,7) AS ym,
                         SUM(o.labor_price + (SELECT COALESCE(SUM(p.qty*p.price),0) FROM parts p WHERE p.order_id=o.id)) AS s
                         FROM orders o WHERE o.status='delivered' AND o.delivered IS NOT NULL GROUP BY ym""")
        m = {r["ym"]: r["s"] or 0 for r in rows}
        return [(k, float(m.get(k, 0))) for k in keys]

    # ------------------------------------------------------------------ zaxira
    def backup(self, path: str) -> str:
        dst = sqlite3.connect(path)
        with dst:
            self.con.backup(dst)
        dst.close()
        return path

    # ------------------------------------------------------------------ ichki
    def _update(self, table: str, rid: int, kw: dict, allowed):
        kw = {k: v for k, v in kw.items() if k in allowed}
        if not kw:
            return
        sets = ", ".join(f"{k}=?" for k in kw)
        self.con.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*kw.values(), rid))
        self.con.commit()


def warranty_until(order: dict) -> Optional[str]:
    base = order.get("delivered") or order.get("completed")
    if not base or not order.get("warranty_days"):
        return None
    d = datetime.strptime(base[:10], "%Y-%m-%d").date() + timedelta(days=int(order["warranty_days"]))
    return d.isoformat()


def fmt_money(v: float, currency: str = "") -> str:
    s = f"{v:,.0f}".replace(",", " ") if abs(v - round(v)) < 0.005 else f"{v:,.2f}".replace(",", " ")
    return f"{s} {currency}".strip()


def fill_demo(db: DB):
    """Skrinshot va namoyish uchun namunaviy ma'lumot (vaqtinchalik bazaga yoziladi)."""
    t1 = db.add_technician("Bahtiyor H.")
    t2 = db.add_technician("Sardor A.")
    today_d = date.today()
    sample = [
        ("Alisher Karimov", "+998 90 123 45 67", "laptop", "Lenovo", "IdeaPad 5 14IIL05", "PF2K8M3X", "Zaryadlovchi, sumka",
         "Ekran yonmaydi, kuchli qiziydi", "delivered", 32, 150000, [("Termopasta Arctic MX-4", 1, 40000)], t1),
        ("Dilnoza Rahimova", "+998 93 555 12 34", "desktop", "HP", "ProDesk 400 G6", "CZC1234ABC", "Faqat sistemniy blok",
         "Windows yuklanmaydi", "delivered", 25, 120000, [("SSD Kingston A400 480GB", 1, 360000)], t2),
        ("Javohir To'raev", "+998 97 700 80 90", "laptop", "ASUS", "TUF Gaming F15", "N2NRKD01234", "Zaryadlovchi",
         "Klaviatura ishlamaydi", "ready", 4, 100000, [("Klaviatura ASUS FX506", 1, 450000)], t1),
        ("Malika Yusupova", "+998 91 234 56 78", "printer", "Canon", "i-SENSYS MF3010", "KSR0045678", "Kabel",
         "Qog'oz tortmaydi", "waiting_parts", 6, 0, [], t2),
        ("Rustam Aliyev", "+998 99 876 54 32", "laptop", "Acer", "Aspire 7 A715", "NHQ8RER00912", "Yo'q",
         "Suv to'kilgan, yoqilmaydi", "diagnosis", 2, 0, [], t1),
        ("Nodira Saidova", "+998 94 111 22 33", "monoblock", "Lenovo", "IdeaCentre AIO 3", "MP1XYZ77", "Klaviatura, sichqoncha",
         "Sekin ishlaydi, viruslar", "received", 0, 0, [], None),
        ("Bekzod Nazarov", "+998 95 404 50 60", "laptop", "HP", "Pavilion 15", "5CD1234XYZ", "Zaryadlovchi",
         "Batareya zaryad olmaydi", "ready", 9, 80000, [("Batareya HP HT03XL", 1, 520000)], t2),
        ("Sevara Qodirova", "+998 90 909 09 09", "phone", "Samsung", "Galaxy A52", "R58R12ABCD", "Chexol",
         "Ekran singan", "waiting_parts", 12, 0, [], t1),
    ]
    # o'tgan oylar daromadi (grafik uchun): avval eski buyurtmalar
    names = ["Otabek Ergashev", "Gulnora Ismoilova", "Sherzod Mahmudov", "Kamola Tursunova", "Aziz Rahmonov",
             "Feruza Xolmatova", "Ulug'bek Sobirov", "Madina Hasanova", "Jasur Qosimov", "Zarina Umarova",
             "Doniyor Valiyev"]
    devices = [("laptop", "Dell", "Latitude 5490"), ("laptop", "HP", "ProBook 450 G8"), ("desktop", "Lenovo", "ThinkCentre M70s"),
               ("laptop", "ASUS", "VivoBook 15"), ("printer", "HP", "LaserJet Pro M15a"), ("laptop", "Acer", "Nitro 5")]
    amounts = [2.1, 3.4, 2.8, 4.2, 3.9, 5.1, 4.6, 6.0, 5.4, 6.8, 7.2]
    for k, amt in enumerate(amounts):
        y, m = today_d.year, today_d.month - (len(amounts) - k)
        while m <= 0:
            y, m = y - 1, m + 12
        cid = db.add_client(names[k], f"+998 9{k % 10} {300 + k * 7} {10 + k:02d} {40 + k:02d}")
        typ, br, mo = devices[k % len(devices)]
        did = db.add_device(cid, typ, br, mo, f"SN{k:03d}X{y}")
        at = f"{y:04d}-{m:02d}-15 12:00"
        oid = db.create_order(cid, did, "Profilaktika, tozalash", t1, received=at)
        db.update_order(oid, labor_price=amt * 1_000_000, work_done="Tozalandi, termopasta almashtirildi")
        db.set_status(oid, "delivered", at)
    for i, (name, phone, typ, brand, model, serial, acc, prob, st, days_ago, labor, parts, tech) in enumerate(sample):
        cid = db.add_client(name, phone)
        did = db.add_device(cid, typ, brand, model, serial, "1234" if typ == "laptop" else "", acc)
        rec = (datetime.now() - timedelta(days=days_ago, hours=i)).strftime("%Y-%m-%d %H:%M")
        due = (today_d - timedelta(days=days_ago) + timedelta(days=3 if st != "waiting_parts" else 5)).isoformat()
        oid = db.create_order(cid, did, prob, tech, prepayment=100000 if parts else 0, due_date=due, received=rec)
        db.update_order(oid, labor_price=labor, diagnosis="" if st == "received" else "Tekshiruv o'tkazildi",
                        work_done="Ta'mirlandi, sinovdan o'tkazildi" if st in ("ready", "delivered") else "")
        for p in parts:
            db.add_part(oid, *p)
        for s in STATUSES[1:STATUSES.index(st) + 1]:
            db.set_status(oid, s, (datetime.now() - timedelta(days=max(0, days_ago - 2))).strftime("%Y-%m-%d %H:%M"))
