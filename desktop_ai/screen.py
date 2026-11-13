"""Capture only the selected display/region; keep encoded images in memory."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog


def capture_screen(screen, region: QRect | None = None) -> tuple[bytes, object, QRect]:
    geometry = screen.geometry()
    bounds = QRect(0, 0, geometry.width(), geometry.height())
    selected = region.intersected(bounds) if region is not None else bounds
    if selected.width() < 16 or selected.height() < 16:
        raise ValueError("Elegí una región de al menos 16 × 16 píxeles.")
    pixmap = screen.grabWindow(0, selected.x(), selected.y(), selected.width(), selected.height())
    if pixmap.isNull():
        raise ValueError("El sistema no permitió capturar la pantalla. Revisá los permisos de grabación de pantalla; en Linux usá una sesión X11.")
    image = pixmap.toImage()
    if max(image.width(), image.height()) > 1280:
        image = image.scaled(1280, 1280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "JPEG", 78):
        raise ValueError("No se pudo codificar la captura.")
    buffer.close()
    absolute = selected.translated(geometry.topLeft())
    return bytes(data), image, absolute


class RegionSelector(QDialog):
    selected = Signal(QRect)

    def __init__(self, screen, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start: QPoint | None = None
        self.selection = QRect()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 13, 22, 140))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(30, 40, "Arrastrá para elegir el área que verá el modelo · Esc para cancelar")
        if not self.selection.isNull():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.selection, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#ffb566"), 2))
            painter.drawRect(self.selection)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.selection = QRect(self.start, event.position().toPoint()).normalized().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.selection = QRect(self.start, event.position().toPoint()).normalized().intersected(self.rect())
            if self.selection.width() >= 16 and self.selection.height() >= 16:
                self.selected.emit(self.selection)
                self.accept()
            else:
                self.reject()
