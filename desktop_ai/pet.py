from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from .brain import PERSONALITIES, Reaction
from .motion import Motion


def draw_figure(painter: QPainter, motion: Motion, character: str, origin: QPointF, scale: float = 1.0):
    color, _, hollow = PERSONALITIES[character]
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(origin)
    painter.scale(scale, scale)
    # Ground shadow does not travel with a jump.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(12, 18, 29, 36))
    painter.drawEllipse(QRectF(-31, -2, 62, 7))
    painter.scale(motion.direction, 1)
    p = motion.pose
    pen = QPen(QColor(color), 6.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Far limbs first, slightly darker, to make crossing silhouettes readable.
    for side in ("l", "r"):
        shade = QColor(color).darker(115) if side == "l" else QColor(color)
        pen.setColor(shade)
        painter.setPen(pen)
        for root, bend, end in (("hip", side + "k", side + "f"), ("neck", side + "e", side + "h")):
            path = QPainterPath(QPointF(*p[root]))
            path.quadTo(QPointF(*p[bend]), QPointF(*p[end]))
            painter.drawPath(path)
    pen.setColor(QColor(color))
    painter.setPen(pen)
    painter.drawLine(QPointF(*p["neck"]), QPointF(*p["hip"]))
    # Stop the neck at the edge of the head so hollow characters stay hollow.
    hx, hy = p["head"]
    nx, ny = p["neck"]
    length = max(1, math.hypot(nx - hx, ny - hy))
    edge = QPointF(hx + (nx - hx) * 15 / length, hy + (ny - hy) * 15 / length)
    painter.drawLine(QPointF(nx, ny), edge)
    painter.setBrush(Qt.BrushStyle.NoBrush if hollow else QColor(color))
    painter.drawEllipse(QPointF(hx, hy), 13.5, 13.5)
    if motion.action in {"think", "sleep", "surprised"}:
        painter.scale(motion.direction, 1)  # Keep punctuation readable when mirrored.
        painter.setPen(QColor(color))
        painter.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        mark = {"think": "?", "sleep": "z", "surprised": "!"}[motion.action]
        painter.drawText(QPointF(29, -118), mark)
    painter.restore()


class PetWindow(QWidget):
    open_controls = Signal()
    dismiss = Signal()

    def __init__(self, screen, character: str = "Orange"):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(360, 310)
        self.character = character
        self.vision_active = False
        self.screen_area = screen.availableGeometry()
        self.motion = Motion()
        self.scale = 1.25
        self.speech = "¡Ey! ¿Qué hacemos hoy?"
        self.speech_until = time.monotonic() + 6
        self.drag_offset: QPoint | None = None
        self.vertical_offset = 0.0
        self.last_frame = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.reposition()

    def set_screen(self, screen):
        self.screen_area = screen.availableGeometry()
        self.reposition()

    def reposition(self):
        area = self.screen_area
        # Leave room for the bubble at both edges.
        span = max(1, area.width() - self.width())
        x = area.left() + round(self.motion.x * span)
        self.move(x, area.bottom() - self.height() + 1 + round(self.vertical_offset))

    def react(self, reaction: Reaction, target_global_x: float | None = None):
        target = None
        if target_global_x is not None:
            span = max(1, self.screen_area.width() - self.width())
            target = (target_global_x - self.screen_area.left() - self.width() / 2) / span
            target = max(0, min(1, target))
        self.motion.react(reaction.action, target)
        self.motion.emotion = reaction.emotion
        self.speech = reaction.speech
        self.speech_until = time.monotonic() + max(4, min(13, len(self.speech) * 0.065))
        self.update()

    def tick(self):
        now = time.monotonic()
        dt = max(0, min(0.05, now - self.last_frame))
        self.motion.tick(dt, max(1, self.screen_area.width() - self.width()))
        self.last_frame = now
        if not self.motion.dragging:
            self.vertical_offset *= math.exp(-7 * dt)
            self.reposition()
            cursor = QCursor.pos()
            # Quiet cursor awareness, except when an intentional gesture is playing.
            if self.motion.action == "idle" and abs(cursor.x() - (self.x() + 180)) > 60:
                self.motion.direction = 1 if cursor.x() > self.x() + 180 else -1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_figure(painter, self.motion, self.character, QPointF(180, 292), self.scale)
        if self.vision_active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#78e7b3"))
            painter.drawEllipse(QPointF(126, 297), 3, 3)
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            painter.setPen(QColor("#78e7b3"))
            painter.drawText(QPointF(135, 301), "VISIÓN")
        if self.speech and time.monotonic() < self.speech_until:
            painter.setFont(QFont("Segoe UI", 11))
            text_bounds = painter.fontMetrics().boundingRect(0, 0, 282, 150, Qt.TextFlag.TextWordWrap, self.speech)
            rect = QRectF(24, 12, 312, max(70, min(150, text_bounds.height() + 20)))
            painter.setPen(QPen(QColor("#46516a"), 1))
            painter.setBrush(QColor(24, 31, 47, 246))
            painter.drawRoundedRect(rect, 16, 16)
            tail = QPainterPath(QPointF(170, rect.bottom()))
            tail.lineTo(183, rect.bottom() + 12)
            tail.lineTo(195, rect.bottom())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(tail)
            painter.setPen(QColor("#f3f5fa"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(rect.adjusted(15, 9, -15, -9), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.speech)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
            self.motion.dragging = True
            self.motion.velocity = 0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None:
            destination = event.globalPosition().toPoint() - self.drag_offset
            area = self.screen_area
            self.move(max(area.left(), min(area.right() - self.width() + 1, destination.x())),
                      max(area.top(), min(area.bottom() - self.height() + 1, destination.y())))
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        if self.drag_offset is not None:
            self.drag_offset = None
            self.motion.dragging = False
            span = max(1, self.screen_area.width() - self.width())
            self.motion.x = max(0, min(1, (self.x() - self.screen_area.left()) / span))
            self.vertical_offset = self.y() - (self.screen_area.bottom() - self.height() + 1)
            self.motion.target = self.motion.x
            self.motion.react("wave")
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.open_controls.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Abrir controles", self.open_controls.emit)
        for label, action in (("Saludar", "wave"), ("Saltar", "jump"), ("Bailar", "dance"), ("Sentarse", "sit")):
            menu.addAction(label, lambda checked=False, a=action: self.motion.react(a))
        menu.addSeparator()
        menu.addAction("Salir", self.dismiss.emit)
        menu.exec(event.globalPos())
