"""Hujjatlar: qabul kvitansiyasi, bajarilgan ishlar akti (PDF), SMS matni, Excel eksport."""
import html
import os
from datetime import datetime
from typing import List

from uzkit.i18n import tr

from .db import STATUSES, fmt_money, warranty_until

CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; color: #222; }
td, th { padding: 3px 5px; vertical-align: top; }
th { background: #eef1ea; text-align: left; }
.muted { color: #6b6b6b; }
.box { border: 1px solid #bbb; }
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def shop(db) -> dict:
    return {k: db.get_setting(k, "") for k in ("shop_name", "shop_phone", "shop_address", "shop_logo", "currency",
                                                "receipt_terms", "act_terms")}


def device_type_text(t: str) -> str:
    return tr("dt_" + t) if t else ""


def qr_image(text: str, scale: int = 6):
    """QR kod (qrcode kutubxonasi matritsasi) -> QImage. Kutubxona bo'lmasa None."""
    try:
        import qrcode
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPainter
    except ImportError:
        return None
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    img = QImage(n * scale, n * scale, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * scale, y * scale, scale, scale)
    p.end()
    return img


def qr_text(o: dict, s: dict) -> str:
    return f"{s.get('shop_name', '')} | {tr('order_no')} {o['number']} | {s.get('shop_phone', '')}"


def _header(s: dict, title: str, o: dict, with_qr: bool) -> str:
    logo = "<img src='logo' height='54'>" if s.get("shop_logo") and os.path.exists(s["shop_logo"]) else ""
    qr = "<img src='qr' width='86' height='86'>" if with_qr else ""
    return (f"<table width='100%' cellspacing='0'><tr>"
            + (f"<td width='64'>{logo}</td>" if logo else "") +
            f"<td><span style='font-size:15pt; font-weight:700;'>{_e(s.get('shop_name'))}</span><br>"
            f"<span class='muted'>{_e(s.get('shop_address'))}</span><br><b>{_e(s.get('shop_phone'))}</b></td>"
            f"<td align='right' width='92'>{qr}</td></tr></table>"
            f"<table width='100%' cellspacing='0' bgcolor='#2b4a2f'><tr>"
            f"<td style='color:white; padding:6px; font-size:12pt; font-weight:600;'>{_e(title)}</td>"
            f"<td align='right' style='color:white; padding:6px;'>{_e(tr('order_no'))} <b>{_e(o['number'])}</b></td>"
            f"</tr></table>")


def _kv(rows) -> str:
    out = ["<table width='100%' cellspacing='0'>"]
    for k, v in rows:
        if v not in (None, ""):
            out.append(f"<tr><td width='34%' class='muted'>{_e(k)}</td><td>{_e(v)}</td></tr>")
    out.append("</table>")
    return "".join(out)


def _sig() -> str:
    return (f"<br><table width='100%' cellspacing='0'><tr>"
            f"<td width='50%'>{_e(tr('sig_shop'))}: ______________</td>"
            f"<td width='50%' align='right'>{_e(tr('sig_client'))}: ______________</td></tr></table>")


def receipt_html(o: dict, s: dict, with_qr: bool = True) -> str:
    cur = s.get("currency") or ""
    rows = [(tr("f_received"), o.get("received")), (tr("f_client"), o.get("client_name")),
            (tr("f_phone"), o.get("client_phone")),
            (tr("f_device"), " ".join(x for x in (device_type_text(o.get("device_type")), o.get("device")) if x)),
            (tr("f_serial"), o.get("serial")), (tr("f_accessories"), o.get("accessories")),
            (tr("f_problem"), o.get("problem")), (tr("f_due_date"), o.get("due_date")),
            (tr("f_prepayment"), fmt_money(o.get("prepayment") or 0, cur) if o.get("prepayment") else ""),
            (tr("f_technician"), o.get("technician"))]
    terms = s.get("receipt_terms") or tr("default_receipt_terms")
    return (f"<html><head><style>{CSS}</style></head><body>" + _header(s, tr("doc_receipt"), o, with_qr) +
            "<br>" + _kv(rows) +
            f"<p class='muted' style='font-size:8pt;'>{_e(terms).replace(chr(10), '<br>')}</p>" + _sig() +
            "</body></html>")


def act_html(o: dict, parts: List[dict], s: dict, with_qr: bool = True) -> str:
    cur = s.get("currency") or ""
    rows = [(tr("f_received"), o.get("received")), (tr("f_completed"), o.get("completed") or o.get("delivered")),
            (tr("f_client"), o.get("client_name")), (tr("f_phone"), o.get("client_phone")),
            (tr("f_device"), " ".join(x for x in (device_type_text(o.get("device_type")), o.get("device")) if x)),
            (tr("f_serial"), o.get("serial")), (tr("f_problem"), o.get("problem")),
            (tr("f_diagnosis"), o.get("diagnosis")), (tr("f_work_done"), o.get("work_done")),
            (tr("f_technician"), o.get("technician"))]
    tbl = [f"<table width='100%' cellspacing='0' class='box'><tr><th>#</th><th>{_e(tr('p_name'))}</th>"
           f"<th align='right'>{_e(tr('p_qty'))}</th><th align='right'>{_e(tr('p_price'))}</th>"
           f"<th align='right'>{_e(tr('p_sum'))}</th></tr>"]
    for i, p in enumerate(parts, 1):
        tbl.append(f"<tr><td>{i}</td><td>{_e(p['name'])}</td><td align='right'>{p['qty']:g}</td>"
                   f"<td align='right'>{_e(fmt_money(p['price'], cur))}</td>"
                   f"<td align='right'>{_e(fmt_money(p['qty'] * p['price'], cur))}</td></tr>")
    n = len(parts) + 1
    tbl.append(f"<tr><td>{n}</td><td>{_e(tr('labor'))}</td><td align='right'>1</td>"
               f"<td align='right'>{_e(fmt_money(o.get('labor_price') or 0, cur))}</td>"
               f"<td align='right'>{_e(fmt_money(o.get('labor_price') or 0, cur))}</td></tr>")
    tbl.append(f"<tr><td></td><td colspan='3' align='right'><b>{_e(tr('total'))}</b></td>"
               f"<td align='right'><b>{_e(fmt_money(o['total'], cur))}</b></td></tr>")
    if o.get("prepayment"):
        tbl.append(f"<tr><td></td><td colspan='3' align='right'>{_e(tr('f_prepayment'))}</td>"
                   f"<td align='right'>{_e(fmt_money(o['prepayment'], cur))}</td></tr>"
                   f"<tr><td></td><td colspan='3' align='right'><b>{_e(tr('to_pay'))}</b></td>"
                   f"<td align='right'><b>{_e(fmt_money(o['due'], cur))}</b></td></tr>")
    tbl.append("</table>")
    until = warranty_until(o)
    warranty = tr("warranty_line", days=o.get("warranty_days") or 0, until=until or "") if o.get("warranty_days") else ""
    terms = s.get("act_terms") or tr("default_act_terms")
    return (f"<html><head><style>{CSS}</style></head><body>" + _header(s, tr("doc_act"), o, with_qr) +
            "<br>" + _kv(rows) + "<br>" + "".join(tbl) +
            (f"<p><b>{_e(warranty)}</b></p>" if warranty else "") +
            f"<p class='muted' style='font-size:8pt;'>{_e(terms).replace(chr(10), '<br>')}</p>" + _sig() +
            "</body></html>")


def save_pdf(html_text: str, path: str, page: str = "A5", logo: str = "", qr=None):
    from PySide6.QtCore import QMarginsF, QSizeF, QUrl
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.A4 if page == "A4" else QPageSize.A5))
    w.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Millimeter)
    w.setResolution(96)
    w.setCreator("Servis jurnali")
    doc = QTextDocument()
    if logo and os.path.exists(logo):
        doc.addResource(QTextDocument.ImageResource, QUrl("logo"), QImage(logo))
    if qr is not None:
        doc.addResource(QTextDocument.ImageResource, QUrl("qr"), qr)
    doc.setHtml(html_text)
    rect = w.pageLayout().paintRectPixels(w.resolution())
    doc.setPageSize(QSizeF(rect.width(), rect.height()))
    doc.print_(w)


def sms_text(o: dict, s: dict, template: str = "") -> str:
    key = {"ready": "sms_ready", "received": "sms_received", "waiting_parts": "sms_waiting",
           "diagnosis": "sms_diagnosis", "delivered": "sms_delivered"}.get(o.get("status"), "sms_received")
    tpl = template or tr(key)
    vals = {"name": o.get("client_name") or "", "device": o.get("device") or device_type_text(o.get("device_type")),
            "number": o.get("number"), "total": fmt_money(o.get("due") if o.get("prepayment") else o.get("total") or 0,
                                                          s.get("currency") or ""),
            "shop": s.get("shop_name") or "", "phone": s.get("shop_phone") or ""}
    try:
        return tpl.format(**vals)
    except (KeyError, IndexError, ValueError):
        return tpl


def export_excel(orders: List[dict], path: str, currency: str = ""):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = tr("page_orders")[:30]
    head = [tr("c_number"), tr("f_received"), tr("f_client"), tr("f_phone"), tr("f_device"), tr("f_serial"),
            tr("f_problem"), tr("c_status"), tr("labor"), tr("parts_total"), tr("total"), tr("f_prepayment"),
            tr("f_technician"), tr("f_completed"), tr("f_delivered")]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2B4A2F")
        c.alignment = Alignment(vertical="center")
    for o in orders:
        ws.append([o["number"], o.get("received"), o.get("client_name"), o.get("client_phone"),
                   " ".join(x for x in (device_type_text(o.get("device_type")), o.get("device")) if x), o.get("serial"),
                   o.get("problem"), tr("st_" + o["status"]) if o["status"] in STATUSES else o["status"],
                   o.get("labor_price") or 0, o.get("parts_total") or 0, o["total"], o.get("prepayment") or 0,
                   o.get("technician"), o.get("completed"), o.get("delivered")])
    widths = [11, 17, 22, 18, 26, 16, 36, 18, 12, 12, 12, 12, 16, 17, 17]
    for i, wdt in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = wdt
    for row in ws.iter_rows(min_row=2, min_col=9, max_col=12):
        for c in row:
            c.number_format = "# ##0"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)
