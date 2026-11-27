"""Qurilma paroli bazada ochiq saqlanmasligi (Windows DPAPI)."""
import os
import sqlite3

import pytest

from servis_jurnali import db as dbm

pytestmark = pytest.mark.skipif(os.name != "nt", reason="DPAPI faqat Windows'da")


def raw_password(path, did):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT password FROM devices WHERE id=?", (did,)).fetchone()[0]
    finally:
        con.close()


def test_parol_shifrlangan_saqlanadi(tmp_path):
    p = str(tmp_path / "s.db")
    d = dbm.DB(p)
    cid = d.add_client("Sinov Mijoz", "+998 90 000 00 00")
    did = d.add_device(cid, "laptop", "HP", "ProBook", "SN1", "1234")
    oid = d.create_order(cid, did, "sinov")
    raw = raw_password(p, did)
    assert raw.startswith("dpapi:") and "1234" not in raw
    assert d.devices_of(cid)[0]["password"] == "1234"
    assert d.order(oid)["password"] == "1234"
    assert d.orders()[0]["password"] == "1234"
    d.update_device(did, password="9876")
    assert raw_password(p, did).startswith("dpapi:")
    assert d.devices_of(cid)[0]["password"] == "9876"
    d.close()


def test_eski_ochiq_parollar_shifrlanadi(tmp_path):
    p = str(tmp_path / "eski.db")
    d = dbm.DB(p)
    cid = d.add_client("Eski Mijoz")
    d.con.execute("INSERT INTO devices(client_id, type, password) VALUES(?, 'laptop', 'ochiq-parol')", (cid,))
    d.con.commit()
    d.close()
    d = dbm.DB(p)                      # qayta ochilganda shifrlanadi
    did = d.devices_of(cid)[0]["id"]
    assert raw_password(p, did).startswith("dpapi:")
    assert d.devices_of(cid)[0]["password"] == "ochiq-parol"
    d.close()


def test_ochilmaydigan_qiymat_xato_bermaydi():
    assert dbm.unprotect("dpapi:bu-noto-g-ri") == ""
    assert dbm.unprotect("") == ""
    assert dbm.protect("") == ""
