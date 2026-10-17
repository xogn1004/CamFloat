"""Small vector icons shared by the floating controls and context menus."""
from functools import lru_cache
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


@lru_cache(maxsize=64)
def icon(name, color='#e1eaf8'):
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    painter.setPen(QPen(QColor(color), 1.65, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    if name == 'refresh':
        painter.drawArc(QRectF(5, 5, 14, 14), 35 * 16, 285 * 16)
        line(19, 4, 19, 9); line(19, 9, 14, 9)
    elif name == 'camera':
        painter.drawRoundedRect(QRectF(3, 6, 13, 12), 2, 2)
        painter.drawPolygon(QPolygonF([QPointF(16, 10), QPointF(21, 7), QPointF(21, 17), QPointF(16, 14)]))
    elif name in ('volume', 'muted'):
        painter.drawPolygon(QPolygonF([QPointF(3, 9), QPointF(7, 9), QPointF(12, 5),
            QPointF(12, 19), QPointF(7, 15), QPointF(3, 15)]))
        if name == 'muted':
            line(16, 9, 21, 15); line(21, 9, 16, 15)
        else:
            painter.drawArc(QRectF(11, 7, 7, 10), -65 * 16, 130 * 16)
            painter.drawArc(QRectF(11, 3, 12, 18), -60 * 16, 120 * 16)
    elif name in ('fullscreen', 'restore'):
        if name == 'restore':
            painter.drawRoundedRect(QRectF(4, 8, 12, 12), 1, 1)
            line(8, 8, 8, 4); line(8, 4, 20, 4); line(20, 4, 20, 16); line(20, 16, 16, 16)
        else:
            for x, y, dx, dy in ((4, 4, 1, 1), (20, 4, -1, 1), (4, 20, 1, -1), (20, 20, -1, -1)):
                line(x, y, x + 5 * dx, y); line(x, y, x, y + 5 * dy)
    elif name in ('left', 'right', 'up', 'down'):
        points = {'left': [(15, 5), (8, 12), (15, 19)], 'right': [(9, 5), (16, 12), (9, 19)],
                  'up': [(5, 15), (12, 8), (19, 15)], 'down': [(5, 9), (12, 16), (19, 9)]}[name]
        painter.drawPolyline(QPolygonF([QPointF(*p) for p in points]))
    elif name == 'grid':
        for x in (4, 14):
            for y in (4, 14):
                painter.drawRoundedRect(QRectF(x, y, 6, 6), 1, 1)
    elif name == 'pin':
        line(8, 4, 16, 4); line(9, 4, 9, 10); line(15, 4, 15, 10)
        line(9, 10, 6, 14); line(15, 10, 18, 14); line(6, 14, 18, 14); line(12, 14, 12, 21)
    elif name == 'opacity':
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        painter.setBrush(QColor(color)); painter.drawPie(QRectF(7, 7, 10, 10), 90 * 16, 180 * 16)
    elif name == 'chip':
        painter.drawRect(QRectF(7, 7, 10, 10))
        for n in (8, 12, 16):
            line(n, 3, n, 6); line(n, 18, n, 21); line(3, n, 6, n); line(18, n, 21, n)
    elif name == 'close':
        line(6, 6, 18, 18); line(18, 6, 6, 18)
    elif name == 'minimize':
        line(5, 16, 19, 16)
    elif name == 'add':
        line(5, 12, 19, 12); line(12, 5, 12, 19)
    elif name == 'edit':
        line(6, 15, 16, 5); line(16, 5, 20, 9); line(20, 9, 10, 19)
        line(10, 19, 5, 20); line(5, 20, 6, 15)
    elif name == 'quality':
        painter.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
        painter.setFont(painter.font()); painter.drawText(QRectF(3, 5, 18, 14), Qt.AlignmentFlag.AlignCenter, 'HD')
    else:
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        line(12, 11, 12, 17); painter.drawPoint(QPointF(12, 7))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
