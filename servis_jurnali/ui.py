"""Kichik grafik yordamchilar: chiziqli SVG belgilar va rangli holat nuqtalari (emoji o'rniga)."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24 chiziqli belgilar (stroke = currentColor o'rniga {c})
_PATHS = {
    "folder": '<path d="M3 7.5V18a1.5 1.5 0 0 0 1.5 1.5h15A1.5 1.5 0 0 0 21 18V9a1.5 1.5 0 0 0-1.5-1.5h-7.2L10.5 5H4.5A1.5 1.5 0 0 0 3 6.5z"/>',
    "scan": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    "play": '<path d="M7 5l12 7-12 7z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="5"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
    "shield": '<path d="M12 3l7 3v5c0 5-3.2 8.3-7 10-3.8-1.7-7-5-7-10V6z"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="5" cy="6" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="5" cy="18" r="1"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "cross": '<path d="M6 6l12 12M18 6L6 18"/>',
    "alert": '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.3" r=".6"/>',
    "tweak": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "box": '<path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "print": '<path d="M7 9V3.5h10V9"/><rect x="3.5" y="9" width="17" height="8" rx="1.5"/><path d="M7 14h10v6.5H7z"/>',
    "message": '<path d="M4 5h16v11H9l-5 4z"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "sheet": '<rect x="4" y="3.5" width="16" height="17" rx="1.5"/><path d="M4 9h16M4 14.5h16M10 9v11.5"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    "chart": '<path d="M4 20h16"/><rect x="6" y="11" width="3" height="7"/><rect x="11" y="6" width="3" height="12"/><rect x="16" y="13" width="3" height="5"/>',
    "users": '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 20c.5-3.5 3.2-5.5 6.5-5.5s6 2 6.5 5.5"/><path d="M15.5 5.5a3.5 3.5 0 0 1 0 6.5M18 14.8c2 .8 3.2 2.6 3.5 5.2"/>',
    "user": '<circle cx="12" cy="8.5" r="4"/><path d="M4.5 20.5c.6-4 3.6-6.5 7.5-6.5s6.9 2.5 7.5 6.5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
}


def svg_icon(name: str, color: str = "#5f6675", size: int = 24) -> QIcon:
    body = _PATHS.get(name, "")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}" '
           f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
           f'{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for s in (16, 20, 24, 32, 48):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, s, s))
        p.end()
        icon.addPixmap(pm)
    return icon


def dot_icon(color: str, size: int = 10) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(size * 0.5, size * 0.5, size, size))
    p.end()
    return QIcon(pm)
