"""Ustaxona ish kunining ssenariylari: qabul -> diagnostika -> qism -> tayyor -> topshirish, hujjatlar va hisobotlar,
shuningdek buzilgan baza, katta raqamlar va g'alati matnlar. Hammasi tmp_path (TEMP) da.
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from servis_jurnali.db import DB, open_or_recover, warranty_until


def _qt():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from uzkit import i18n
    import servis_jurnali.window  # noqa: matnlar ro'yxatga olinadi
    return i18n


def test_full_repair_day(tmp_path):
    i18n = _qt()
    from servis_jurnali import docs
    db = DB(str(tmp_path / "Ustaxona o'zbek" / "servis.db"))
    cid = db.add_client("Тошматов O'tkir <b>", "+998 (90) 123-45-67")
    assert db.find_client_by_phone("901234567")["id"] == cid
    did = db.add_device(cid, "laptop", "Lenovo", "IdeaPad 5", "PF2K8M3X", "", "Zaryadlovchi")
    oid = db.create_order(cid, did, "=Ekran yonmaydi", prepayment=100_000, received="2026-11-03 10:00")
    db.set_status(oid, "diagnosis", "2026-11-03 11:00")
    db.update_order(oid, diagnosis="Matritsa shleyfi", labor_price=150_000)
    db.add_part(oid, "Shleyf", 1, 85_000)
    db.add_part(oid, "Termopasta", 2, 12_500)
    db.set_status(oid, "ready", "2026-11-05 16:00")
    db.set_status(oid, "delivered", "2026-11-06 09:30")
    o = db.order(oid)
    assert o["parts_total"] == 110_000 and o["total"] == 260_000 and o["due"] == 160_000
    assert o["completed"].startswith("2026-11-05") and warranty_until(o) == "2026-12-06"
    assert [h["status"] for h in db.status_history(oid)] == ["received", "diagnosis", "ready", "delivered"]
    assert dict(db.revenue_by_month(2, date(2026, 11, 20)))["2026-11"] == 260_000
    assert db.clients()[0]["spent"] == 260_000

    s = docs.shop(db)
    for lang in ("uz", "ru", "en"):
        i18n.set_language(lang)
        html = docs.act_html(o, db.parts(oid), s)
        assert "&lt;b&gt;" in html and "<b>Тошматов" not in html
        out = tmp_path / "Hujjatlar" / f"{o['number']}_akt_{lang}.pdf"
        out.parent.mkdir(exist_ok=True)
        docs.save_pdf(html, str(out), "A5", qr=docs.qr_image(docs.qr_text(o, s)))
        assert out.read_bytes()[:4] == b"%PDF"
    x = tmp_path / "Hisobot noyabr.xlsx"
    docs.export_excel(db.orders(), str(x), "so'm")
    from openpyxl import load_workbook
    ws = load_workbook(x).active
    assert ws["G2"].value == "=Ekran yonmaydi" and ws["G2"].data_type == "s"   # formula emas
    assert ws["K2"].value == 260_000
    db.delete_order(oid)
    assert db.parts(oid) == [] and db.status_history(oid) == []
    db.close()


def test_numbering_past_9999(tmp_path):
    db = DB(str(tmp_path / "n.db"))
    cid = db.add_client("A")
    db.con.execute("INSERT INTO orders(number, client_id) VALUES('2026-9999', ?)", (cid,))
    db.con.commit()
    assert db.next_number(2026) == "2026-10000"
    db.create_order(cid, None, received="2026-12-01 10:00")
    assert db.next_number(2026) == "2026-10001"
    assert db.next_number(2027) == "2027-0001"
    db.close()


def test_corrupt_database_is_recovered_from_backup(tmp_path):
    path = tmp_path / "servis.db"
    db = DB(str(path))
    db.add_client("Saqlangan mijoz")
    (tmp_path / "backups").mkdir()
    db.backup(str(tmp_path / "backups" / "servis_20261101_100000.db"))
    db.close()
    path.write_bytes(b"bu baza emas" * 100)
    db, state = open_or_recover(str(path))
    assert state == "restored:servis_20261101_100000.db"
    assert [c["name"] for c in db.clients()] == ["Saqlangan mijoz"]
    assert len(list(tmp_path.glob("servis.db.buzilgan_*"))) == 1
    db.close()


def test_corrupt_database_without_backup(tmp_path):
    path = tmp_path / "servis.db"
    path.write_bytes(os.urandom(5000))
    db, state = open_or_recover(str(path))
    assert state == "new" and db.clients() == []
    db.close()
    db, state = open_or_recover(str(path))
    assert state == ""
    db.close()
