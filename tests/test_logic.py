import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from servis_jurnali.db import DB, STATUSES, fill_demo, fmt_money, warranty_until


@pytest.fixture
def db(tmp_path):
    d = DB(str(tmp_path / "t.db"))
    yield d
    d.close()


def _order(db, name="Ali Valiyev", phone="+998 90 123 45 67", serial="SN1", due=None):
    cid = db.add_client(name, phone)
    did = db.add_device(cid, "laptop", "HP", "Pavilion 15", serial, "1234", "Zaryadlovchi")
    return db.create_order(cid, did, "Yoqilmaydi", prepayment=50000, due_date=due)


def test_numbers_and_create(db):
    a = _order(db)
    b = _order(db, "Vali", "+998 91 000 00 00", "SN2")
    oa, ob = db.order(a), db.order(b)
    y = date.today().year
    assert oa["number"] == f"{y}-0001" and ob["number"] == f"{y}-0002"
    assert oa["status"] == "received" and oa["password"] == "1234" and oa["device"] == "HP Pavilion 15"
    assert db.next_number(2020) == "2020-0001"


def test_parts_totals_and_status(db):
    oid = _order(db)
    db.update_order(oid, labor_price=100000, diagnosis="Ona plata", work_done="Almashtirildi", warranty_days=60)
    db.add_part(oid, "SSD 480GB", 1, 350000)
    pid = db.add_part(oid, "Termopasta", 2, 20000)
    o = db.order(oid)
    assert o["parts_total"] == 390000 and o["total"] == 490000 and o["due"] == 440000
    db.delete_part(pid)
    assert db.order(oid)["total"] == 450000
    for s in STATUSES[1:]:
        db.set_status(oid, s)
    o = db.order(oid)
    assert o["status"] == "delivered" and o["completed"] and o["delivered"]
    assert [h["status"] for h in db.status_history(oid)] == STATUSES
    assert warranty_until(o) == (date.today() + timedelta(days=60)).isoformat()
    with pytest.raises(ValueError):
        db.set_status(oid, "bogus")


def test_search(db):
    _order(db, "Rustam Aliyev", "+998 99 876 54 32", "NHQ8RER")
    _order(db, "Malika", "+998 91 234 56 78", "KSR004")
    assert len(db.orders("rustam")) == 1
    assert len(db.orders("876 54")) == 1
    assert len(db.orders("998998765432")) == 1
    assert len(db.orders("ksr004")) == 1
    assert len(db.orders(f"{date.today().year}-0002")) == 1
    assert len(db.orders("nothing-like-this")) == 0
    assert db.find_client_by_phone("99 876-54-32")["name"] == "Rustam Aliyev"
    assert db.find_client_by_phone("12") is None
    assert len(db.clients("malika")) == 1


def test_filters_and_stats(db):
    old = (date.today() - timedelta(days=3)).isoformat()
    a = _order(db, due=old)
    b = _order(db, "B", "+998 93 111 11 11", "S2")
    db.update_order(b, labor_price=200000)
    db.set_status(b, "ready")
    c = _order(db, "C", "+998 93 222 22 22", "S3")
    db.update_order(c, labor_price=300000)
    db.set_status(c, "delivered")
    assert [o["id"] for o in db.orders(status="overdue")] == [a]
    assert {o["id"] for o in db.orders(status="open")} == {a}
    assert [o["id"] for o in db.orders(status="ready")] == [b]
    s = db.stats()
    assert s["open"] == 1 and s["ready"] == 1 and s["overdue"] == 1 and s["month_revenue"] == 300000
    rev = db.revenue_by_month(12)
    assert len(rev) == 12 and rev[-1][1] == 300000


def test_settings_backup_delete(db, tmp_path):
    db.set_setting("shop_name", "Usta")
    db.set_setting("shop_name", "Kompyuter ustasi")
    assert db.get_setting("shop_name") == "Kompyuter ustasi" and db.get_setting("x", "d") == "d"
    oid = _order(db)
    db.add_part(oid, "X", 1, 1)
    p = db.backup(str(tmp_path / "copy.db"))
    db2 = DB(p)
    assert len(db2.orders()) == 1
    db2.close()
    db.delete_order(oid)
    assert db.order(oid) is None and db.parts(oid) == []


def test_technicians(db):
    t = db.add_technician("Sardor")
    assert [x["name"] for x in db.technicians()] == ["Sardor"]
    db.set_technician_active(t, False)
    assert db.technicians() == [] and len(db.technicians(active_only=False)) == 1


def test_fmt_money():
    assert fmt_money(1250000, "so'm") == "1 250 000 so'm"
    assert fmt_money(12.5) == "12.50"
    assert fmt_money(0) == "0"


def test_demo_fill(db):
    fill_demo(db)
    assert len(db.orders()) >= 15
    assert db.stats()["ready"] == 2


def test_documents(db, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from uzkit import i18n
    import servis_jurnali.window  # noqa: matnlar
    from servis_jurnali import docs
    oid = _order(db)
    db.update_order(oid, labor_price=150000, work_done="Tozalandi")
    db.add_part(oid, "Termopasta", 1, 40000)
    db.set_status(oid, "ready")
    db.set_setting("shop_name", "Kompyuter ustasi")
    db.set_setting("currency", "so'm")
    o, s = db.order(oid), docs.shop(db)
    for lang in ("uz", "ru", "en"):
        i18n.set_language(lang)
        r = docs.receipt_html(o, s)
        a = docs.act_html(o, db.parts(oid), s)
        assert o["number"] in r and "Termopasta" in a and "190 000" in a
        sms = docs.sms_text(o, s)
        assert o["number"] in sms and "{" not in sms
    assert docs.sms_text(o, s, "{bad") == "{bad"
    qr = docs.qr_image("test 123")
    assert qr is not None and qr.width() > 50
    for page in ("A5", "A4"):
        p = tmp_path / f"r_{page}.pdf"
        docs.save_pdf(docs.receipt_html(o, s), str(p), page, qr=qr)
        assert p.read_bytes()[:4] == b"%PDF"
    x = tmp_path / "o.xlsx"
    docs.export_excel(db.orders(), str(x), "so'm")
    from openpyxl import load_workbook
    ws = load_workbook(x).active
    assert ws.max_row == 2 and ws["A2"].value == o["number"]
