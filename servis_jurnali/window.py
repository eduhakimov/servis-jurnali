"""Asosiy oyna: buyurtmalar jurnali, ko'rsatkichlar, mijozlar, sozlamalar."""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDateEdit, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from uzkit import app as appmod
from uzkit.i18n import language, register, tr
from uzkit.paths import data_dir, documents_dir
from uzkit.widgets import Card, ask, error, header, info, open_path, primary_button, warn
from uzkit.window import BaseMainWindow

from . import docs
from .db import DB, DEVICE_TYPES, OPEN_STATUSES, STATUSES, fill_demo, fmt_money, today
from .strings import STRINGS
from .ui import dot_icon, svg_icon

register(STRINGS)

DEMO = "--screenshot" in sys.argv
SLUG = "servis-jurnali"
STATUS_COLORS = {"received": "#1971c2", "diagnosis": "#7048e8", "waiting_parts": "#e8590c", "ready": "#2b8a3e",
                 "delivered": "#868e96"}


def _table(cols, stretch) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    t.setShowGrid(False)
    t.verticalHeader().setDefaultSectionSize(30)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    h.setSectionResizeMode(stretch, QHeaderView.Stretch)
    h.setHighlightSections(False)
    return t


def _it(text, data=None, align=None) -> QTableWidgetItem:
    it = QTableWidgetItem("" if text is None else str(text))
    if data is not None:
        it.setData(Qt.UserRole, data)
    if align:
        it.setTextAlignment(align)
    return it


def money_box(maxv=999_999_999) -> QDoubleSpinBox:
    b = QDoubleSpinBox()
    b.setRange(0, maxv)
    b.setDecimals(0)
    b.setSingleStep(10000)
    b.setGroupSeparatorShown(True)
    b.setButtonSymbols(QDoubleSpinBox.NoButtons)
    b.setAlignment(Qt.AlignRight)
    return b


def type_combo() -> QComboBox:
    c = QComboBox()
    for t in DEVICE_TYPES:
        c.addItem(tr("dt_" + t), t)
    return c


def short_date(s: str) -> str:
    if not s:
        return ""
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return s


# =========================================================================== yangi buyurtma
class NewOrderDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.db = win.db
        self.client_id = None
        self.setWindowTitle(tr("new_order"))
        self.setMinimumWidth(560)
        l = QVBoxLayout(self)
        f = QFormLayout()
        f.setVerticalSpacing(8)
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("+998 90 123 45 67")
        self.name = QLineEdit()
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        names = [c["name"] for c in self.db.clients()]
        comp = QCompleter(names, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.name.setCompleter(comp)
        self.dtype = type_combo()
        self.brand = QLineEdit()
        self.model = QLineEdit()
        self.serial = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.acc = QLineEdit()
        self.problem = QPlainTextEdit()
        self.problem.setMaximumHeight(80)
        self.prepay = money_box()
        self.due = QDateEdit(QDate.currentDate().addDays(3))
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("dd.MM.yyyy")
        self.tech = QComboBox()
        self.tech.addItem(tr("no_technician"), None)
        for t in self.db.technicians():
            self.tech.addItem(t["name"], t["id"])
        bm = QHBoxLayout()
        bm.addWidget(self.brand)
        bm.addWidget(self.model)
        self.brand.setPlaceholderText(tr("f_brand"))
        self.model.setPlaceholderText(tr("f_model"))
        f.addRow(tr("f_phone"), self.phone)
        f.addRow("", self.hint)
        f.addRow(tr("f_client"), self.name)
        f.addRow(tr("f_device_type"), self.dtype)
        f.addRow(tr("f_device"), bm)
        f.addRow(tr("f_serial"), self.serial)
        f.addRow(tr("f_password"), self.password)
        f.addRow(tr("f_accessories"), self.acc)
        f.addRow(tr("f_problem"), self.problem)
        f.addRow(tr("f_prepayment"), self.prepay)
        f.addRow(tr("f_due_date"), self.due)
        f.addRow(tr("f_technician"), self.tech)
        l.addLayout(f)
        bb = QDialogButtonBox()
        ok = bb.addButton(tr("save"), QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self.phone.editingFinished.connect(self._lookup)
        self.order_id = None

    def _lookup(self):
        c = self.db.find_client_by_phone(self.phone.text())
        self.client_id = c["id"] if c else None
        if c:
            self.hint.setText(tr("existing_client", name=c["name"]))
            if not self.name.text().strip():
                self.name.setText(c["name"])
            devs = self.db.devices_of(c["id"])
            if devs and not self.brand.text():
                d = devs[0]
                self.dtype.setCurrentIndex(max(0, self.dtype.findData(d["type"])))
                self.brand.setText(d["brand"])
                self.model.setText(d["model"])
                self.serial.setText(d["serial"])
        else:
            self.hint.setText("")

    def _ok(self):
        name = self.name.text().strip()
        if not name:
            warn(self, tr("required_name"))
            return
        if not self.problem.toPlainText().strip():
            warn(self, tr("required_problem"))
            return
        self._lookup()
        db = self.db
        cid = self.client_id
        if cid is None:
            cid = db.add_client(name, self.phone.text())
        did = None
        serial = self.serial.text().strip()
        for d in db.devices_of(cid):
            if (serial and d["serial"] == serial) or (not serial and d["brand"] == self.brand.text().strip()
                                                      and d["model"] == self.model.text().strip() and d["model"]):
                did = d["id"]
                db.update_device(did, type=self.dtype.currentData(), password=self.password.text(),
                                 accessories=self.acc.text())
                break
        if did is None:
            did = db.add_device(cid, self.dtype.currentData(), self.brand.text(), self.model.text(), serial,
                                self.password.text(), self.acc.text())
        warranty = int(db.get_setting("default_warranty", "30") or 30)
        self.order_id = db.create_order(cid, did, self.problem.toPlainText(), self.tech.currentData(),
                                        self.prepay.value(), self.due.date().toString("yyyy-MM-dd"), warranty)
        self.accept()


# =========================================================================== buyurtma paneli
class OrderPanel(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.win = page.win
        self.db = page.win.db
        self.oid = None
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        self.empty = QLabel(tr("select_order"))
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        self.body = QWidget()
        b = QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(10)
        lay.addWidget(self.body)

        self.number = QLabel("")
        self.number.setObjectName("OrderNumber")
        self.number.setWordWrap(True)
        b.addWidget(self.number)
        self.status = QComboBox()
        self.status.setObjectName("StatusCombo")
        for s in STATUSES:
            self.status.addItem(dot_icon(STATUS_COLORS[s]), tr("st_" + s), s)
        b.addWidget(self.status)
        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        b.addWidget(self.meta)

        def section(title):
            l = QLabel(title)
            l.setObjectName("Section")
            b.addWidget(l)

        section(tr("sec_client"))
        f1 = QFormLayout()
        f1.setVerticalSpacing(4)
        f1.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.c_name = QLineEdit()
        self.c_phone = QLineEdit()
        self.d_type = type_combo()
        self.d_brand = QLineEdit()
        self.d_model = QLineEdit()
        bm = QHBoxLayout()
        bm.addWidget(self.d_brand)
        bm.addWidget(self.d_model)
        self.d_serial = QLineEdit()
        pw = QHBoxLayout()
        self.d_pass = QLineEdit()
        self.d_pass.setEchoMode(QLineEdit.Password)
        self.pw_btn = QPushButton(tr("show_password"))
        self.pw_btn.setCheckable(True)
        pw.addWidget(self.d_pass, 1)
        pw.addWidget(self.pw_btn)
        self.d_acc = QLineEdit()
        f1.addRow(tr("f_client"), self.c_name)
        f1.addRow(tr("f_phone"), self.c_phone)
        f1.addRow(tr("f_device_type"), self.d_type)
        f1.addRow(tr("f_device"), bm)
        f1.addRow(tr("f_serial"), self.d_serial)
        f1.addRow(tr("f_password"), pw)
        f1.addRow(tr("f_accessories"), self.d_acc)
        b.addLayout(f1)

        section(tr("sec_repair"))
        f2 = QFormLayout()
        f2.setVerticalSpacing(4)
        f2.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.problem = QPlainTextEdit()
        self.diagnosis = QPlainTextEdit()
        self.work = QPlainTextEdit()
        for w in (self.problem, self.diagnosis, self.work):
            w.setFixedHeight(58)
        self.tech = QComboBox()
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("dd.MM.yyyy")
        self.warranty = QSpinBox()
        self.warranty.setRange(0, 3650)
        f2.addRow(tr("f_problem"), self.problem)
        f2.addRow(tr("f_diagnosis"), self.diagnosis)
        f2.addRow(tr("f_work_done"), self.work)
        f2.addRow(tr("f_technician"), self.tech)
        f2.addRow(tr("f_due_date"), self.due)
        f2.addRow(tr("f_warranty"), self.warranty)
        b.addLayout(f2)

        section(tr("sec_parts"))
        self.parts = _table([tr("p_name"), tr("p_qty"), tr("p_price"), tr("p_sum")], 0)
        self.parts.setFixedHeight(120)
        for i, w in enumerate([0, 60, 100, 100]):
            if w:
                self.parts.setColumnWidth(i, w)
        b.addWidget(self.parts)
        pr = QHBoxLayout()
        self.p_name = QLineEdit()
        self.p_name.setPlaceholderText(tr("p_name"))
        self.p_qty = QDoubleSpinBox()
        self.p_qty.setRange(0.01, 9999)
        self.p_qty.setValue(1)
        self.p_qty.setDecimals(2)
        self.p_price = money_box()
        self.p_price.setMinimumWidth(80)
        self.p_qty.setMaximumWidth(70)
        self.p_name.setMinimumWidth(60)
        add = QPushButton(svg_icon("plus", "#6b7280"), "")
        add.setToolTip(tr("add_part"))
        rem = QPushButton(svg_icon("minus", "#6b7280"), "")
        rem.setToolTip(tr("del_part"))
        pr.addWidget(self.p_name, 1)
        pr.addWidget(self.p_qty)
        pr.addWidget(self.p_price)
        pr.addWidget(add)
        pr.addWidget(rem)
        b.addLayout(pr)

        section(tr("sec_money"))
        f3 = QFormLayout()
        f3.setVerticalSpacing(6)
        self.labor = money_box()
        self.prepay = money_box()
        self.totals = QLabel("")
        self.totals.setObjectName("Totals")
        self.totals.setWordWrap(True)
        f3.addRow(tr("f_labor"), self.labor)
        f3.addRow(tr("f_prepayment"), self.prepay)
        f3.addRow("", self.totals)
        b.addLayout(f3)

        acts = QGridLayout()
        acts.setSpacing(8)
        self.b_receipt = QPushButton(svg_icon("print", "#6b7280"), tr("print_receipt"))
        self.b_act = QPushButton(svg_icon("print", "#6b7280"), tr("print_act"))
        self.b_sms = QPushButton(svg_icon("message", "#6b7280"), tr("sms_copy"))
        self.b_del = QPushButton(svg_icon("trash", "#c92a2a"), "")
        self.b_del.setToolTip(tr("delete_order"))
        self.b_save = primary_button(tr("save_changes"))
        acts.addWidget(self.b_receipt, 0, 0)
        acts.addWidget(self.b_act, 0, 1)
        acts.addWidget(self.b_sms, 1, 0)
        acts.addWidget(self.b_del, 1, 1)
        acts.addWidget(self.b_save, 2, 0, 1, 2)
        self.b_del.setText(tr("delete_order"))
        b.addLayout(acts)
        b.addStretch(1)
        self.body.setVisible(False)
        for cb in self.body.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)

        self.pw_btn.toggled.connect(lambda v: self.d_pass.setEchoMode(QLineEdit.Normal if v else QLineEdit.Password))
        self.status.currentIndexChanged.connect(self._status_changed)
        add.clicked.connect(self._add_part)
        rem.clicked.connect(self._del_part)
        self.labor.valueChanged.connect(self._update_totals)
        self.prepay.valueChanged.connect(self._update_totals)
        self.b_save.clicked.connect(self.save)
        self.b_receipt.clicked.connect(lambda: self.win.print_doc(self.oid, "receipt"))
        self.b_act.clicked.connect(lambda: self.win.print_doc(self.oid, "act"))
        self.b_sms.clicked.connect(self._sms)
        self.b_del.clicked.connect(self._delete)

    def load(self, oid):
        o = self.db.order(oid) if oid else None
        self.oid = o["id"] if o else None
        self.empty.setVisible(o is None)
        self.body.setVisible(o is not None)
        if not o:
            return
        self._loading = True
        self.order = o
        self.number.setText(f"{tr('order_no')} {o['number']}")
        self.status.setCurrentIndex(STATUSES.index(o["status"]) if o["status"] in STATUSES else 0)
        bits = [f"{tr('f_received')}: {short_date(o['received'])} {o['received'][11:16]}"]
        if o.get("completed"):
            bits.append(f"{tr('f_completed')}: {short_date(o['completed'])}")
        if o.get("delivered"):
            bits.append(f"{tr('f_delivered')}: {short_date(o['delivered'])}")
        self.meta.setText("   ".join(bits))
        self.c_name.setText(o.get("client_name") or "")
        self.c_phone.setText(o.get("client_phone") or "")
        self.d_type.setCurrentIndex(max(0, self.d_type.findData(o.get("device_type"))))
        self.d_brand.setText(o.get("brand") or "")
        self.d_model.setText(o.get("model") or "")
        self.d_serial.setText(o.get("serial") or "")
        self.d_pass.setText(o.get("password") or "")
        self.pw_btn.setChecked(False)
        self.d_acc.setText(o.get("accessories") or "")
        self.problem.setPlainText(o.get("problem") or "")
        self.diagnosis.setPlainText(o.get("diagnosis") or "")
        self.work.setPlainText(o.get("work_done") or "")
        self.tech.clear()
        self.tech.addItem(tr("no_technician"), None)
        for t in self.db.technicians(active_only=False):
            if t["active"] or t["id"] == o.get("technician_id"):
                self.tech.addItem(t["name"], t["id"])
        self.tech.setCurrentIndex(max(0, self.tech.findData(o.get("technician_id"))))
        d = QDate.fromString(o.get("due_date") or "", "yyyy-MM-dd")
        self.due.setDate(d if d.isValid() else QDate.currentDate())
        self.warranty.setValue(int(o.get("warranty_days") or 0))
        self.labor.setValue(o.get("labor_price") or 0)
        self.prepay.setValue(o.get("prepayment") or 0)
        self._fill_parts()
        self._loading = False

    def _fill_parts(self):
        cur = self.db.get_setting("currency", "")
        ps = self.db.parts(self.oid)
        self.parts.setRowCount(len(ps))
        for r, p in enumerate(ps):
            self.parts.setItem(r, 0, _it(p["name"], p["id"]))
            self.parts.setItem(r, 1, _it(f"{p['qty']:g}", align=Qt.AlignRight | Qt.AlignVCenter))
            self.parts.setItem(r, 2, _it(fmt_money(p["price"]), align=Qt.AlignRight | Qt.AlignVCenter))
            self.parts.setItem(r, 3, _it(fmt_money(p["qty"] * p["price"], cur), align=Qt.AlignRight | Qt.AlignVCenter))
        self.parts_sum = sum(p["qty"] * p["price"] for p in ps)
        self._update_totals()

    def _update_totals(self):
        cur = self.db.get_setting("currency", "")
        total = self.labor.value() + getattr(self, "parts_sum", 0)
        due = total - self.prepay.value()
        self.totals.setText(f"{tr('total')}: {fmt_money(total, cur)}     {tr('to_pay')}: {fmt_money(due, cur)}")

    def _add_part(self):
        if not self.oid or not self.p_name.text().strip():
            return
        self.db.add_part(self.oid, self.p_name.text(), self.p_qty.value(), self.p_price.value())
        self.p_name.clear()
        self.p_qty.setValue(1)
        self.p_price.setValue(0)
        self._fill_parts()
        self.page.refresh(keep=self.oid)

    def _del_part(self):
        r = self.parts.currentRow()
        if r < 0 or not self.oid:
            return
        self.db.delete_part(self.parts.item(r, 0).data(Qt.UserRole))
        self._fill_parts()
        self.page.refresh(keep=self.oid)

    def _status_changed(self):
        if self._loading or not self.oid:
            return
        self.save(silent=True)
        self.db.set_status(self.oid, self.status.currentData())
        self.page.refresh(keep=self.oid)
        self.load(self.oid)
        self.win.dirty()

    def save(self, silent=False):
        if not self.oid:
            return
        o = self.order
        if not self.c_name.text().strip():
            warn(self, tr("required_name"))
            return
        self.db.update_client(o["client_id"], name=self.c_name.text().strip(), phone=self.c_phone.text().strip())
        if o.get("device_id"):
            self.db.update_device(o["device_id"], type=self.d_type.currentData(), brand=self.d_brand.text().strip(),
                                  model=self.d_model.text().strip(), serial=self.d_serial.text().strip(),
                                  password=self.d_pass.text(), accessories=self.d_acc.text().strip())
        self.db.update_order(self.oid, problem=self.problem.toPlainText(), diagnosis=self.diagnosis.toPlainText(),
                             work_done=self.work.toPlainText(), technician_id=self.tech.currentData(),
                             due_date=self.due.date().toString("yyyy-MM-dd"), warranty_days=self.warranty.value(),
                             labor_price=self.labor.value(), prepayment=self.prepay.value())
        if not silent:
            self.page.refresh(keep=self.oid)
            self.win.status(tr("saved"))
            self.win.dirty()

    def _sms(self):
        if not self.oid:
            return
        self.save(silent=True)
        o = self.db.order(self.oid)
        s = docs.shop(self.db)
        tpl = self.db.get_setting("sms_ready_tpl", "") if o["status"] == "ready" else ""
        QGuiApplication.clipboard().setText(docs.sms_text(o, s, tpl))
        self.win.status(tr("sms_copied"))

    def _delete(self):
        if self.oid and ask(self, tr("delete_order_q", n=self.order["number"])):
            self.db.delete_order(self.oid)
            self.load(None)
            self.page.refresh()
            self.win.dirty()


# =========================================================================== buyurtmalar sahifasi
class OrdersPage(QWidget):
    COLS = ["c_number", "c_date", "c_client", "c_device", "c_status", "c_sum", "c_due"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.db = win.db
        self.rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("CommandBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search_ph"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(svg_icon("search", "#868e96"), QLineEdit.LeadingPosition)
        h.addWidget(self.search, 1)
        self.flt = QComboBox()
        self.flt.addItem(tr("flt_all"), "")
        self.flt.addItem(tr("flt_open"), "open")
        self.flt.addItem(tr("flt_overdue"), "overdue")
        for s in STATUSES:
            self.flt.addItem(dot_icon(STATUS_COLORS[s]), tr("st_" + s), s)
        self.flt.setMinimumWidth(190)
        h.addWidget(self.flt)
        self.b_xlsx = QPushButton(svg_icon("sheet", "#6b7280"), tr("export_xlsx"))
        h.addWidget(self.b_xlsx)
        self.b_new = primary_button(tr("new_order"))
        self.b_new.setIcon(svg_icon("plus", "#ffffff"))
        h.addWidget(self.b_new)
        lay.addWidget(bar)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 12, 8, 12)
        self.table = _table([tr(c) for c in self.COLS], 2)
        for i, w in enumerate([70, 76, 0, 112, 118, 80, 76]):
            if w:
                self.table.setColumnWidth(i, w)
        lv.addWidget(self.table, 1)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        lv.addWidget(self.count)
        split.addWidget(left)
        self.panel = OrderPanel(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.panel)
        sc.setObjectName("DetailScroll")
        sc.setMinimumWidth(400)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        split.addWidget(sc)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([680, 420])
        lay.addWidget(split, 1)

        self.search.textChanged.connect(lambda: self.refresh())
        self.flt.currentIndexChanged.connect(lambda: self.refresh())
        self.table.currentCellChanged.connect(self._select)
        self.b_new.clicked.connect(self.new_order)
        self.b_xlsx.clicked.connect(self._export)
        self.refresh()

    def refresh(self, keep=None):
        keep = keep if keep is not None else self.panel.oid
        self.rows = self.db.orders(self.search.text(), self.flt.currentData() or "")
        cur = self.db.get_setting("currency", "")
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(self.rows))
        tdy = today()
        sel = -1
        for r, o in enumerate(self.rows):
            t.setItem(r, 0, _it(o["number"], o["id"]))
            t.setItem(r, 1, _it(short_date(o["received"])))
            cl = _it(o["client_name"])
            cl.setToolTip(o.get("client_phone") or "")
            t.setItem(r, 2, cl)
            dv = _it(" ".join(x for x in (o.get("brand"), o.get("model")) if x) or tr("dt_" + (o.get("device_type") or "other")))
            dv.setToolTip((o.get("problem") or "").strip())
            t.setItem(r, 3, dv)
            st = _it(tr("st_" + o["status"]))
            st.setIcon(dot_icon(STATUS_COLORS.get(o["status"], "#868e96")))
            t.setItem(r, 4, st)
            t.setItem(r, 5, _it(fmt_money(o["total"]) if o["total"] else "", align=Qt.AlignRight | Qt.AlignVCenter))
            due = _it(short_date(o.get("due_date")))
            if o["status"] in OPEN_STATUSES and o.get("due_date") and o["due_date"] < tdy:
                due.setForeground(QColor("#c92a2a"))
                f = due.font()
                f.setBold(True)
                due.setFont(f)
            t.setItem(r, 6, due)
            if o["id"] == keep:
                sel = r
        t.blockSignals(False)
        self.count.setText(tr("orders_n", n=len(self.rows)) if self.rows else tr("empty_orders"))
        if sel >= 0:
            t.selectRow(sel)
        elif self.rows and self.panel.oid is None:
            t.selectRow(0)
            self.panel.load(self.rows[0]["id"])

    def _select(self, row, *a):
        if 0 <= row < len(self.rows):
            if self.rows[row]["id"] != self.panel.oid:
                self.panel.load(self.rows[row]["id"])

    def open_order(self, oid):
        self.search.clear()
        self.flt.setCurrentIndex(0)
        self.panel.load(oid)
        self.refresh(keep=oid)

    def new_order(self):
        d = NewOrderDialog(self.win)
        if d.exec() == QDialog.Accepted and d.order_id:
            self.open_order(d.order_id)
            self.win.dirty()
            o = self.db.order(d.order_id)
            if ask(self, tr("order_created", n=o["number"])):
                self.win.print_doc(d.order_id, "receipt")

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, tr("export_xlsx"),
                                           str(documents_dir() / f"buyurtmalar_{date.today():%Y%m%d}.xlsx"), "Excel (*.xlsx)")
        if not p:
            return
        try:
            docs.export_excel(self.db.orders(self.search.text(), self.flt.currentData() or "", limit=100000), p,
                              self.db.get_setting("currency", ""))
        except Exception as ex:
            appmod.log_exception(ex)
            error(self, str(ex))
            return
        self.win.status(tr("pdf_saved", p=p), 8000)
        open_path(p)


# =========================================================================== ko'rsatkichlar
class RevenueChart(QWidget):
    def __init__(self):
        super().__init__()
        self.data = []
        self.currency = ""
        self.setMinimumHeight(220)

    def set_data(self, data, currency=""):
        self.data, self.currency = data, currency
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        txt = pal.color(pal.ColorRole.WindowText)
        muted = pal.color(pal.ColorRole.PlaceholderText)
        accent = pal.color(pal.ColorRole.Highlight)
        w, h = self.width(), self.height()
        left, bottom, top = 64, 28, 12
        if not self.data:
            p.end()
            return
        mx = max(v for _, v in self.data) or 1
        # shkala
        step = 10 ** max(0, len(str(int(mx))) - 1)
        nice = step * (int(mx / step) + 1)
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        grid = QColor(muted)
        grid.setAlpha(60)
        for i in range(5):
            y = top + (h - top - bottom) * i / 4
            p.setPen(QPen(grid, 1))
            p.drawLine(left, int(y), w - 8, int(y))
            val = nice * (4 - i) / 4
            label = f"{val / 1e6:g}M" if nice >= 1e6 else f"{val / 1e3:g}K" if nice >= 1e3 else f"{val:g}"
            p.setPen(muted)
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignRight | Qt.AlignVCenter, label)
        n = len(self.data)
        slot = (w - left - 8) / n
        bw = max(6, slot * 0.58)
        months = {"uz": ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"],
                  "ru": ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"],
                  "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
        names = months.get(language(), months["en"])
        for i, (ym, v) in enumerate(self.data):
            x = left + slot * i + (slot - bw) / 2
            bh = (h - top - bottom) * (v / nice)
            c = QColor(accent)
            if i != n - 1:
                c.setAlpha(150)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, h - bottom - bh, bw, bh), 3, 3)
            p.setPen(txt if i == n - 1 else muted)
            p.drawText(QRectF(left + slot * i, h - bottom + 4, slot, 18), Qt.AlignCenter, names[int(ym[5:7]) - 1])
        p.end()


class Kpi(QFrame):
    def __init__(self, title, color):
        super().__init__()
        self.setObjectName("Kpi")
        self.setStyleSheet(f"QFrame#Kpi {{ border-top: 3px solid {color}; }}")
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 12, 16, 12)
        l.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("KpiTitle")
        self.value = QLabel("0")
        self.value.setObjectName("KpiValue")
        self.sub = QLabel("")
        self.sub.setObjectName("Muted")
        l.addWidget(t)
        l.addWidget(self.value)
        l.addWidget(self.sub)


class DashboardPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.db = win.db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)
        lay.addWidget(header(tr("dash_title")))
        g = QHBoxLayout()
        g.setSpacing(12)
        self.k_open = Kpi(tr("k_open"), STATUS_COLORS["received"])
        self.k_ready = Kpi(tr("k_ready"), STATUS_COLORS["ready"])
        self.k_over = Kpi(tr("k_overdue"), "#c92a2a")
        self.k_month = Kpi(tr("k_month"), "#2b4a2f")
        for k in (self.k_open, self.k_ready, self.k_over, self.k_month):
            g.addWidget(k, 1)
        lay.addLayout(g)
        cc = Card(tr("chart_title"))
        self.chart = RevenueChart()
        cc.add(self.chart)
        lay.addWidget(cc, 3)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.l_ready = QListWidget()
        self.l_over = QListWidget()
        for title, lw in ((tr("list_ready"), self.l_ready), (tr("list_overdue"), self.l_over)):
            c = Card(title)
            lw.setObjectName("PlainList")
            c.add(lw)
            row.addWidget(c, 1)
            lw.itemDoubleClicked.connect(lambda it: self.win.goto_order(it.data(Qt.UserRole)))
        lay.addLayout(row, 2)

    def refresh(self):
        s = self.db.stats()
        cur = self.db.get_setting("currency", "")
        self.k_open.value.setText(str(s["open"]))
        self.k_ready.value.setText(str(s["ready"]))
        self.k_over.value.setText(str(s["overdue"]))
        self.k_month.value.setText(fmt_money(s["month_revenue"]))
        self.k_month.sub.setText(cur)
        self.k_open.sub.setText(tr("k_month_orders", n=s["month_orders"]))
        self.chart.set_data(self.db.revenue_by_month(12), cur)
        for lw, st in ((self.l_ready, "ready"), (self.l_over, "overdue")):
            lw.clear()
            rows = self.db.orders(status=st, limit=200)
            for o in rows:
                text = f"{o['number']}   {o['client_name']}   {o['client_phone']}   {o.get('device') or ''}"
                if st == "overdue":
                    text += f"   ({short_date(o.get('due_date'))})"
                it = QListWidgetItem(dot_icon(STATUS_COLORS.get(o["status"], "#868e96")), text)
                it.setData(Qt.UserRole, o["id"])
                lw.addItem(it)
            if not rows:
                it = QListWidgetItem(tr("nothing_here"))
                it.setFlags(Qt.NoItemFlags)
                lw.addItem(it)


# =========================================================================== mijozlar
class ClientsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.db = win.db
        self.rows = []
        self.cid = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(header(tr("cl_title")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("cl_search"))
        self.search.setClearButtonEnabled(True)
        left.addWidget(self.search)
        self.table = _table([tr("f_client"), tr("f_phone"), tr("cl_orders"), tr("cl_spent"), tr("cl_last")], 0)
        for i, w in enumerate([0, 140, 100, 130, 100]):
            if w:
                self.table.setColumnWidth(i, w)
        left.addWidget(self.table, 1)
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        ec = Card(tr("cl_edit"))
        f = QFormLayout()
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.phone2 = QLineEdit()
        self.address = QLineEdit()
        self.note = QLineEdit()
        for k, w in (("f_client", self.name), ("f_phone", self.phone), ("phone2", self.phone2),
                     ("address", self.address), ("f_note", self.note)):
            f.addRow(tr(k), w)
        ec.add(f)
        sb = QHBoxLayout()
        sb.addStretch(1)
        self.b_save = QPushButton(tr("save"))
        sb.addWidget(self.b_save)
        ec.add(sb)
        right.addWidget(ec)
        dc = Card(tr("cl_devices"))
        self.devices = QListWidget()
        self.devices.setObjectName("PlainList")
        self.devices.setMaximumHeight(110)
        dc.add(self.devices)
        right.addWidget(dc)
        hc = Card(tr("cl_history"))
        self.history = QListWidget()
        self.history.setObjectName("PlainList")
        hc.add(self.history)
        right.addWidget(hc, 1)
        lay.addLayout(right, 2)

        self.search.textChanged.connect(self.refresh)
        self.table.currentCellChanged.connect(lambda r, *a: self._select(r))
        self.b_save.clicked.connect(self._save)
        self.history.itemDoubleClicked.connect(lambda it: self.win.goto_order(it.data(Qt.UserRole)))

    def refresh(self):
        self.rows = self.db.clients(self.search.text())
        cur = self.db.get_setting("currency", "")
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(self.rows))
        sel = 0
        for r, c in enumerate(self.rows):
            t.setItem(r, 0, _it(c["name"], c["id"]))
            t.setItem(r, 1, _it(c["phone"]))
            t.setItem(r, 2, _it(c["orders"], align=Qt.AlignCenter))
            t.setItem(r, 3, _it(fmt_money(c["spent"], cur) if c["spent"] else "", align=Qt.AlignRight | Qt.AlignVCenter))
            t.setItem(r, 4, _it(short_date(c["last_visit"] or "")))
            if c["id"] == self.cid:
                sel = r
        t.blockSignals(False)
        if self.rows:
            t.selectRow(sel)
            self._select(sel)
        else:
            self._select(-1)

    def _select(self, r):
        enabled = 0 <= r < len(self.rows)
        for w in (self.name, self.phone, self.phone2, self.address, self.note, self.b_save):
            w.setEnabled(enabled)
        self.devices.clear()
        self.history.clear()
        if not enabled:
            self.cid = None
            for w in (self.name, self.phone, self.phone2, self.address, self.note):
                w.clear()
            return
        c = self.rows[r]
        self.cid = c["id"]
        self.name.setText(c["name"])
        self.phone.setText(c["phone"])
        self.phone2.setText(c["phone2"])
        self.address.setText(c["address"])
        self.note.setText(c["note"])
        for d in self.db.devices_of(c["id"]):
            self.devices.addItem(" ".join(x for x in (tr("dt_" + d["type"]) if d["type"] else "", d["brand"], d["model"],
                                                       f"S/N {d['serial']}" if d["serial"] else "") if x))
        for o in self.db.orders(c["phone"] or c["name"]):
            if o["client_id"] != c["id"]:
                continue
            it = QListWidgetItem(dot_icon(STATUS_COLORS.get(o["status"], "#868e96")),
                                 f"{o['number']}   {short_date(o['received'])}   {o.get('device') or ''}   "
                                 f"{tr('st_' + o['status'])}")
            it.setData(Qt.UserRole, o["id"])
            self.history.addItem(it)

    def _save(self):
        if self.cid is None:
            return
        if not self.name.text().strip():
            warn(self, tr("required_name"))
            return
        self.db.update_client(self.cid, name=self.name.text().strip(), phone=self.phone.text().strip(),
                              phone2=self.phone2.text().strip(), address=self.address.text().strip(),
                              note=self.note.text().strip())
        self.refresh()
        self.win.status(tr("saved"))
        self.win.dirty()


# =========================================================================== sozlamalar
class SettingsPage(QWidget):
    KEYS = ["shop_name", "shop_phone", "shop_address", "currency"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.db = win.db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        sc.setWidget(holder)
        outer.addWidget(sc)
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)
        lay.addWidget(header(tr("page_settings")))
        row = QHBoxLayout()
        row.setSpacing(14)
        sc1 = Card(tr("set_shop"))
        f = QFormLayout()
        self.ed = {}
        for k in self.KEYS:
            e = QLineEdit()
            self.ed[k] = e
            f.addRow(tr(k), e)
        lg = QHBoxLayout()
        self.logo = QLineEdit()
        b_logo = QPushButton(tr("browse"))
        lg.addWidget(self.logo, 1)
        lg.addWidget(b_logo)
        f.addRow(tr("shop_logo"), lg)
        self.page_size = QComboBox()
        self.page_size.addItems(["A5", "A4"])
        f.addRow(tr("page_size"), self.page_size)
        self.qr = QCheckBox(tr("qr_on"))
        f.addRow("", self.qr)
        self.warranty = QSpinBox()
        self.warranty.setRange(0, 3650)
        f.addRow(tr("default_warranty"), self.warranty)
        sc1.add(f)
        row.addWidget(sc1, 3)
        tc = Card(tr("set_techs"))
        self.techs = QListWidget()
        self.techs.setObjectName("PlainList")
        tc.add(self.techs)
        tr_ = QHBoxLayout()
        self.t_name = QLineEdit()
        self.t_name.setPlaceholderText(tr("tech_name_ph"))
        b_add = QPushButton(tr("add"))
        b_rm = QPushButton(tr("deactivate"))
        tr_.addWidget(self.t_name, 1)
        tr_.addWidget(b_add)
        tc.add(tr_)
        tc.add(b_rm)
        row.addWidget(tc, 2)
        lay.addLayout(row)

        tc2 = Card(tr("receipt_terms"))
        self.r_terms = QPlainTextEdit()
        self.r_terms.setFixedHeight(80)
        tc2.add(self.r_terms)
        l2 = QLabel(tr("act_terms"))
        l2.setObjectName("SectionTitle")
        tc2.add(l2)
        self.a_terms = QPlainTextEdit()
        self.a_terms.setFixedHeight(70)
        tc2.add(self.a_terms)
        l3 = QLabel(tr("sms_templates"))
        l3.setObjectName("SectionTitle")
        tc2.add(l3)
        self.sms = QLineEdit()
        self.sms.setPlaceholderText(tr("sms_ready"))
        tc2.add(self.sms)
        h = QLabel(tr("sms_hint"))
        h.setObjectName("Muted")
        h.setWordWrap(True)
        tc2.add(h)
        lay.addWidget(tc2)

        dc = Card(tr("set_data"))
        self.db_label = QLabel(tr("db_path", p=self.db.path))
        self.db_label.setObjectName("Muted")
        self.db_label.setWordWrap(True)
        self.db_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dc.add(self.db_label)
        self.auto = QCheckBox(tr("auto_backup"))
        dc.add(self.auto)
        br = QHBoxLayout()
        b_bk = QPushButton(svg_icon("save", "#6b7280"), tr("backup_db"))
        b_open = QPushButton(svg_icon("folder", "#6b7280"), tr("open_data_folder"))
        br.addWidget(b_bk)
        br.addWidget(b_open)
        br.addStretch(1)
        dc.add(br)
        lay.addWidget(dc)
        sv = QHBoxLayout()
        sv.addStretch(1)
        self.b_save = primary_button(tr("save_settings"))
        sv.addWidget(self.b_save)
        lay.addLayout(sv)
        lay.addStretch(1)

        b_logo.clicked.connect(self._pick_logo)
        b_add.clicked.connect(self._add_tech)
        b_rm.clicked.connect(self._rm_tech)
        self.t_name.returnPressed.connect(self._add_tech)
        b_bk.clicked.connect(self._backup)
        b_open.clicked.connect(lambda: open_path(os.path.dirname(self.db.path)))
        self.b_save.clicked.connect(self._save)
        self.load()

    def load(self):
        defaults = {"shop_name": "Kompyuter ustasi", "currency": "so'm"}
        for k, e in self.ed.items():
            e.setText(self.db.get_setting(k, defaults.get(k, "")))
        self.logo.setText(self.db.get_setting("shop_logo", ""))
        self.page_size.setCurrentText(self.db.get_setting("page_size", "A5"))
        self.qr.setChecked(self.db.get_setting("qr", "1") == "1")
        self.warranty.setValue(int(self.db.get_setting("default_warranty", "30") or 30))
        self.r_terms.setPlainText(self.db.get_setting("receipt_terms", ""))
        self.r_terms.setPlaceholderText(tr("default_receipt_terms"))
        self.a_terms.setPlainText(self.db.get_setting("act_terms", ""))
        self.a_terms.setPlaceholderText(tr("default_act_terms"))
        self.sms.setText(self.db.get_setting("sms_ready_tpl", ""))
        self.auto.setChecked(self.db.get_setting("auto_backup", "1") == "1")
        self._fill_techs()

    def _fill_techs(self):
        self.techs.clear()
        for t in self.db.technicians():
            it = QListWidgetItem(svg_icon("user", "#868e96"), t["name"])
            it.setData(Qt.UserRole, t["id"])
            self.techs.addItem(it)

    def _pick_logo(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("shop_logo"), str(Path.home()), "Images (*.png *.jpg *.jpeg)")
        if p:
            self.logo.setText(os.path.normpath(p))

    def _add_tech(self):
        n = self.t_name.text().strip()
        if n:
            self.db.add_technician(n)
            self.t_name.clear()
            self._fill_techs()

    def _rm_tech(self):
        it = self.techs.currentItem()
        if it is not None:
            self.db.set_technician_active(it.data(Qt.UserRole), False)
            self._fill_techs()

    def _save(self):
        for k, e in self.ed.items():
            self.db.set_setting(k, e.text().strip())
        self.db.set_setting("shop_logo", self.logo.text().strip())
        self.db.set_setting("page_size", self.page_size.currentText())
        self.db.set_setting("qr", "1" if self.qr.isChecked() else "0")
        self.db.set_setting("default_warranty", str(self.warranty.value()))
        self.db.set_setting("receipt_terms", self.r_terms.toPlainText().strip())
        self.db.set_setting("act_terms", self.a_terms.toPlainText().strip())
        self.db.set_setting("sms_ready_tpl", self.sms.text().strip())
        self.db.set_setting("auto_backup", "1" if self.auto.isChecked() else "0")
        self.win.status(tr("saved"))
        self.win.dirty()

    def _backup(self):
        p, _ = QFileDialog.getSaveFileName(self, tr("backup_db"),
                                           str(documents_dir() / f"servis_jurnali_{datetime.now():%Y%m%d_%H%M}.db"),
                                           "SQLite (*.db)")
        if p:
            try:
                self.db.backup(p)
                info(self, tr("backup_done", p=p))
            except Exception as ex:
                appmod.log_exception(ex)
                error(self, str(ex))


# =========================================================================== asosiy oyna
class MainWindow(BaseMainWindow):
    def __init__(self):
        super().__init__()
        self.db = self._open_db()
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self._nav = QListWidget()
        self._nav.setObjectName("Rail")
        self._nav.setViewMode(QListWidget.IconMode)
        self._nav.setFlow(QListWidget.TopToBottom)
        self._nav.setMovement(QListWidget.Static)
        self._nav.setIconSize(QSize(24, 24))
        self._nav.setFixedWidth(110)
        self._nav.setSpacing(2)
        self._nav.setWordWrap(True)
        self._nav.setGridSize(QSize(102, 70))
        h.addWidget(self._nav)
        self._stack = QStackedWidget()
        h.addWidget(self._stack, 1)
        self.setCentralWidget(root)

        self.orders = OrdersPage(self)
        self.dashboard = DashboardPage(self)
        self.clients = ClientsPage(self)
        self.settings_page = SettingsPage(self)
        for w, title, ic in ((self.orders, "page_orders", "list"), (self.dashboard, "page_dashboard", "chart"),
                             (self.clients, "page_clients", "users"), (self.settings_page, "page_settings", "settings")):
            self._stack.addWidget(w)
            it = QListWidgetItem(svg_icon(ic, "#e6dccb"), tr(title))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setSizeHint(QSize(100, 66))
            self._nav.addItem(it)
        self._nav.currentRowChanged.connect(self._page_changed)
        self._nav.setCurrentRow(0)

    def _open_db(self) -> DB:
        if DEMO:
            path = os.path.join(tempfile.mkdtemp(prefix="servis_demo_"), "servis.db")
            db = DB(path)
            fill_demo(db)
            db.set_setting("shop_name", "Kompyuter ustasi")
            db.set_setting("shop_phone", "+998 99 000 00 00")
            db.set_setting("shop_address", "Toshkent sh., Chilonzor tumani")
            db.set_setting("currency", "so'm")
            return db
        base = self.settings.path.parent if self.settings is not None else data_dir(SLUG)
        db = DB(str(Path(base) / "servis.db"))
        if not db.technicians(active_only=False) and not db.get_setting("shop_name"):
            db.set_setting("shop_name", "Kompyuter ustasi")
            db.set_setting("currency", "so'm")
        return db

    def _page_changed(self, i):
        self._stack.setCurrentIndex(i)
        page = self._stack.widget(i)
        if hasattr(page, "refresh") and page is not self.orders:
            page.refresh()

    def set_page(self, i: int):
        if 0 <= i < self._nav.count():
            self._nav.setCurrentRow(i)

    def goto_order(self, oid):
        if not oid:
            return
        self.set_page(0)
        self.orders.open_order(oid)

    def dirty(self):
        """Ma'lumot o'zgardi: boshqa sahifalar keyingi ochilganda yangilanadi."""

    def print_doc(self, oid, kind: str):
        if not oid:
            return
        try:
            o = self.db.order(oid)
            s = docs.shop(self.db)
            qr_on = self.db.get_setting("qr", "1") == "1"
            if kind == "receipt":
                html_text = docs.receipt_html(o, s, qr_on)
            else:
                html_text = docs.act_html(o, self.db.parts(oid), s, qr_on)
            folder = documents_dir() / "Servis jurnali"
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{o['number']}_{'kvitansiya' if kind == 'receipt' else 'akt'}.pdf"
            path = str(folder / name)
            docs.save_pdf(html_text, path, self.db.get_setting("page_size", "A5"), s.get("shop_logo", ""),
                          docs.qr_image(docs.qr_text(o, s)) if qr_on else None)
        except Exception as ex:
            appmod.log_exception(ex)
            error(self, str(ex))
            return
        self.status(tr("pdf_saved", p=path), 8000)
        open_path(path)

    def _auto_backup(self):
        if DEMO or self.db.get_setting("auto_backup", "1") != "1":
            return
        try:
            folder = Path(self.db.path).parent / "backups"
            folder.mkdir(exist_ok=True)
            self.db.backup(str(folder / f"servis_{datetime.now():%Y%m%d_%H%M%S}.db"))
            olds = sorted(folder.glob("servis_*.db"))
            for f in olds[:-10]:
                f.unlink()
        except Exception as ex:
            appmod.log_exception(ex)

    def closeEvent(self, e):
        self._auto_backup()
        try:
            self.db.close()
        except Exception:
            pass
        super().closeEvent(e)
