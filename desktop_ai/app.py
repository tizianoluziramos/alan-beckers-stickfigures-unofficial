from __future__ import annotations

import html
import sys
import time
from urllib.parse import urlparse

from PySide6.QtCore import QPointF, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QSpinBox, QSystemTrayIcon, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QScrollArea,
    QMenu,
)

from .brain import BrainSettings, PERSONALITIES, Reaction, request_reaction
from .motion import Motion
from .pet import PetWindow, draw_figure
from .screen import RegionSelector, capture_screen

STYLE = """
QWidget { background: #111722; color: #edf1f8; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow { background: #111722; }
QLabel { background: transparent; }
QLabel#title { font-size: 26px; font-weight: 700; letter-spacing: 2px; }
QLabel#muted { color: #a6b2c7; }
QLabel#status { color: #ffb76c; font-weight: 600; padding: 8px 12px; background: #30271f; border-radius: 9px; }
QTabWidget::pane { border: 1px solid #303a4d; border-radius: 10px; padding: 12px; }
QTabBar::tab { background: #192130; color: #aebcd2; padding: 10px 18px; border-radius: 6px; margin: 0 6px 8px 0; }
QTabBar::tab:selected { background: #334156; color: #ffffff; }
QPushButton { background: #253248; border: 1px solid #3c4b63; padding: 8px 12px; border-radius: 7px; }
QPushButton:hover { background: #354761; }
QPushButton:pressed { background: #192331; }
QPushButton:disabled { color: #748097; border-color: #293245; background: #1a2230; }
QPushButton#primary { background: #ffad59; color: #20180e; border: none; font-weight: 700; }
QPushButton#primary:hover { background: #ffc181; }
QPushButton#primary:disabled { background: #66513d; color: #b4a08d; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextBrowser { background: #192130; border: 1px solid #3a465d; border-radius: 6px; padding: 7px; selection-background-color: #72523b; }
QLineEdit:focus, QComboBox:focus { border-color: #ffad59; }
QComboBox QAbstractItemView { background: #1c2739; selection-background-color: #3c4b63; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; background: #1b2638; border: 1px solid #52627e; border-radius: 4px; }
QCheckBox::indicator:checked { background: #ffad59; border-color: #ffad59; image: none; }
QScrollBar:vertical { background: #192130; width: 8px; margin: 0; border-radius: 4px; }
QScrollBar::handle:vertical { background: #455570; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #ffffff; background: #2a3549; border: 1px solid #566784; }
"""


class BrainWorker(QThread):
    result_ready = Signal(object, int)
    failed = Signal(str, int)

    def __init__(self, settings, character, message, screenshot, history, generation):
        super().__init__()
        self.args = (settings, character, message, screenshot, history)
        self.generation = generation

    def run(self):
        try:
            self.result_ready.emit(request_reaction(*self.args), self.generation)
        except Exception as exc:
            # Only controlled messages from the protocol layer reach the UI.
            self.failed.emit(str(exc) if isinstance(exc, ValueError) else "Error al consultar el modelo.", self.generation)
        finally:
            self.args = ()  # Release the in-memory capture and session key.


class Stage(QWidget):
    """A live preview using exactly the same renderer as the desktop window."""

    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.setFixedHeight(165)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#202c40"))
        gradient.setColorAt(1, QColor("#141c2b"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(self.rect(), 14, 14)
        p.setPen(QPen(QColor("#2c3c54"), 1))
        for x in range(0, self.width(), 30):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 30):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QColor("#a6b8d4"))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(20, 28, "VECTORES EN MOVIMIENTO")
        p.drawText(20, self.height() - 18, "Gestos · curiosidad · un poco de caos")
        draw_figure(p, self.pet.motion, self.pet.character,
                    QPointF(self.width() * 0.7, self.height() - 16), 0.95)
        p.setPen(QColor(PERSONALITIES[self.pet.character][0]))
        p.setFont(QFont("Segoe UI", 24, QFont.Weight.DemiBold))
        p.drawText(20, 91, self.pet.character)
        p.setPen(QColor("#a6b8d4"))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(20, 119, "Animación continua · escala nítida")


def note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class Controls(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stickfigures · Desktop AI (no oficial)")
        self.resize(690, min(830, QApplication.primaryScreen().availableGeometry().height() - 60))
        self.preferences = QSettings("StickfiguresUnofficial", "DesktopAI")
        self.setStyleSheet(STYLE)
        self.history: list[dict[str, str]] = []
        self.generation = 0
        self.worker: BrainWorker | None = None
        self.region = None
        self.request_bounds = None
        self.pending_message = ""
        self.pet = PetWindow(QApplication.primaryScreen())
        self.pet.open_controls.connect(self.show_controls)
        self.pet.dismiss.connect(self.shutdown)
        self.pet.show()
        self.tts = None
        self.setup_ui()
        self.restore_preferences()
        self.setup_voice()
        self.setup_tray()
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.auto_observe)
        self.auto_timer.start(1000)
        self.last_observed = time.monotonic()
        self.update_status()
        QApplication.instance().screenAdded.connect(self.refresh_screens)
        QApplication.instance().screenRemoved.connect(self.refresh_screens)

    def setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(23, 22, 23, 20)
        layout.setSpacing(13)
        top = QHBoxLayout()
        title = QLabel("STICKFIGURES")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        self.status = QLabel()
        self.status.setObjectName("status")
        top.addWidget(self.status)
        layout.addLayout(top)
        layout.addWidget(note("Tu escritorio tiene compañía. Elegí su carácter y enseñale qué estás viendo."))
        layout.addWidget(Stage(self.pet))
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(300)
        layout.addWidget(self.tabs, 1)
        self.setup_scene()
        self.setup_model()
        self.feedback = note("Listo para jugar. La IA es opcional y la visión empieza apagada.")
        self.feedback.setMinimumHeight(38)
        layout.addWidget(self.feedback)
        footer = QHBoxLayout()
        footer.addWidget(note("Proyecto fan no oficial · Doble clic en la figura para abrir controles"), 1)
        exit_button = QPushButton("Salir")
        exit_button.clicked.connect(self.shutdown)
        footer.addWidget(exit_button)
        layout.addLayout(footer)

    def setup_scene(self):
        tab = QWidget()
        box = QVBoxLayout(tab)
        form = QFormLayout()
        self.character = QComboBox()
        self.character.addItems(PERSONALITIES)
        self.character.currentTextChanged.connect(self.change_character)
        form.addRow("Personaje", self.character)
        self.scale_input = QDoubleSpinBox()
        self.scale_input.setRange(0.75, 1.6)
        self.scale_input.setSingleStep(0.05)
        self.scale_input.setValue(1.25)
        self.scale_input.setSuffix(" ×")
        self.scale_input.valueChanged.connect(lambda value: setattr(self.pet, "scale", value))
        form.addRow("Tamaño", self.scale_input)
        box.addLayout(form)
        self.autonomy = QCheckBox("Explorar y reaccionar al cursor")
        self.autonomy.setChecked(True)
        self.autonomy.toggled.connect(lambda value: setattr(self.pet.motion, "autonomy", value))
        box.addWidget(self.autonomy)
        actions = QGridLayout()
        for i, (label, action) in enumerate((("Saludar", "wave"), ("Saltar", "jump"), ("Bailar", "dance"),
                                             ("Pensar", "think"), ("Señalar", "point"), ("Sentarse", "sit"))):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, a=action: self.pet.motion.react(a))
            actions.addWidget(button, i // 3, i % 3)
        box.addLayout(actions)
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(False)
        self.transcript.setMinimumHeight(100)
        box.addWidget(self.transcript, 1)
        row = QHBoxLayout()
        self.message = QLineEdit()
        self.message.setMaxLength(2000)
        self.message.setPlaceholderText("Decile algo…")
        self.message.returnPressed.connect(self.send_message)
        row.addWidget(self.message, 1)
        self.send = QPushButton("Enviar")
        self.send.setObjectName("primary")
        self.send.clicked.connect(self.send_message)
        row.addWidget(self.send)
        clear = QPushButton("Olvidar")
        clear.setToolTip("Borrar el contexto de la conversación en memoria")
        clear.clicked.connect(self.clear_memory)
        row.addWidget(clear)
        box.addLayout(row)
        voice_row = QHBoxLayout()
        self.voice_enabled = QCheckBox("Leer bocadillos en voz alta")
        self.voice_enabled.toggled.connect(self.stop_voice)
        voice_row.addWidget(self.voice_enabled)
        self.voice_choice = QComboBox()
        self.voice_choice.setMinimumWidth(180)
        voice_row.addWidget(self.voice_choice, 1)
        box.addLayout(voice_row)
        self.add_scroll_tab(tab, "Compañero")

    def add_scroll_tab(self, widget, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def setup_model(self):
        tab = QWidget()
        box = QVBoxLayout(tab)
        form = QFormLayout()
        self.provider = QComboBox()
        self.provider.addItem("Ollama · servidor local", "ollama")
        self.provider.addItem("API compatible con OpenAI", "openai")
        form.addRow("Conexión", self.provider)
        self.endpoint = QLineEdit("http://localhost:11434")
        form.addRow("URL base", self.endpoint)
        self.model = QLineEdit("qwen2.5vl:7b")
        form.addRow("Modelo con visión", self.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Sólo esta sesión, o variable OPENAI_API_KEY")
        form.addRow("Clave de API", self.key)
        self.screens = QComboBox()
        self.populate_screens()
        form.addRow("Monitor", self.screens)
        box.addLayout(form)
        self.destination = note("")
        box.addWidget(self.destination)
        self.vision = QCheckBox("Permitir que el modelo vea este monitor o región")
        self.vision.setToolTip("Las capturas se envían al servidor configurado sólo durante las consultas. No se guardan en disco.")
        box.addWidget(self.vision)
        region_row = QHBoxLayout()
        self.region_button = QPushButton("Elegir región")
        self.region_button.clicked.connect(self.choose_region)
        region_row.addWidget(self.region_button)
        reset = QPushButton("Monitor completo")
        reset.clicked.connect(self.reset_region)
        region_row.addWidget(reset)
        self.region_label = note("Monitor completo")
        region_row.addWidget(self.region_label, 1)
        box.addLayout(region_row)
        continuous_row = QHBoxLayout()
        self.continuous = QCheckBox("Reaccionar automáticamente cada")
        continuous_row.addWidget(self.continuous)
        self.interval = QSpinBox()
        self.interval.setRange(5, 120)
        self.interval.setValue(20)
        self.interval.setSuffix(" s")
        continuous_row.addWidget(self.interval)
        continuous_row.addStretch()
        box.addLayout(continuous_row)
        self.observe_button = QPushButton("Mirar y reaccionar ahora")
        self.observe_button.setObjectName("primary")
        self.observe_button.clicked.connect(self.observe)
        box.addWidget(self.observe_button)
        self.thumbnail = QLabel("La vista previa aparecerá al consultar con visión.")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumHeight(80)
        self.thumbnail.setMaximumHeight(140)
        self.thumbnail.setObjectName("muted")
        box.addWidget(self.thumbnail, 1)
        box.addWidget(note("Podés pausar la visión en cualquier momento. Para conversar sin capturas, dejala apagada. El modelo sólo puede animar a la figura."))
        self.add_scroll_tab(tab, "Modelo y visión")
        self.provider.currentIndexChanged.connect(self.change_provider)
        for field in (self.endpoint, self.model, self.key):
            field.textChanged.connect(self.connection_changed)
        self.screens.currentIndexChanged.connect(self.screen_changed)
        self.vision.toggled.connect(self.vision_changed)
        self.continuous.toggled.connect(self.continuous_changed)

    def populate_screens(self):
        self.screens.clear()
        for i, screen in enumerate(QApplication.screens()):
            size = screen.geometry().size()
            self.screens.addItem(f"{i + 1} · {screen.name()} · {size.width()} × {size.height()}", screen)

    def refresh_screens(self, *_):
        self.vision.setChecked(False)
        self.screens.blockSignals(True)
        self.populate_screens()
        self.screens.blockSignals(False)
        self.screen_changed()

    def current_screen(self):
        return self.screens.currentData() or QApplication.primaryScreen()

    def restore_preferences(self):
        prefs = self.preferences
        provider = prefs.value("provider", "ollama")
        self.provider.setCurrentIndex(max(0, self.provider.findData(provider)))
        self.endpoint.setText(prefs.value("endpoint", self.endpoint.text()))
        self.model.setText(prefs.value("model", self.model.text()))
        self.character.setCurrentText(prefs.value("character", "Orange"))
        self.scale_input.setValue(float(prefs.value("scale", 1.25)))
        self.interval.setValue(int(prefs.value("interval", 20)))
        # Consent, automation, history, images and credentials never persist.

    def save_preferences(self):
        for key, value in {"provider": self.provider.currentData(), "endpoint": self.endpoint.text(),
                           "model": self.model.text(), "character": self.character.currentText(),
                           "scale": self.scale_input.value(), "interval": self.interval.value()}.items():
            self.preferences.setValue(key, value)

    def setup_voice(self):
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            if not QTextToSpeech.availableEngines():
                raise RuntimeError("No hay motor de voz")
            self.tts = QTextToSpeech(self)
            voices = self.tts.availableVoices()
            if not voices:
                raise RuntimeError("No hay voces instaladas")
            for voice in voices:
                self.voice_choice.addItem(f"{voice.name()} · {voice.locale().name()}", voice)
            spanish = next((i for i, v in enumerate(voices) if v.locale().name().startswith("es")), 0)
            self.voice_choice.setCurrentIndex(spanish)
        except (ImportError, RuntimeError):
            self.tts = None
            self.voice_enabled.setEnabled(False)
            self.voice_choice.setEnabled(False)
            self.voice_choice.addItem("Sin motor de voz del sistema")

    def stop_voice(self, *_):
        if self.tts:
            self.tts.stop()

    def setup_tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            icon = QPixmap(32, 32)
            icon.fill(Qt.GlobalColor.transparent)
            p = QPainter(icon)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#ffad59"), 4))
            p.drawEllipse(6, 6, 20, 20)
            p.end()
            self.tray = QSystemTrayIcon(QIcon(icon), self)
            self.tray.setToolTip("Stickfigures · visión apagada")
            menu = QMenu()
            menu.addAction("Abrir controles", self.show_controls)
            menu.addAction("Pausar visión", lambda: self.vision.setChecked(False))
            menu.addAction("Salir", self.shutdown)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show_controls() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()

    def show_controls(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def invalidate(self):
        self.generation += 1
        self.history.clear()
        self.stop_voice()
        if hasattr(self, "transcript"):
            self.transcript.clear()
        if hasattr(self, "thumbnail"):
            self.thumbnail.clear()

    def change_character(self, character):
        self.invalidate()
        self.pet.character = character
        self.pet.react(Reaction("¡Acá estoy!", "wave", "happy"))
        if hasattr(self, "transcript"):
            self.transcript.clear()

    def change_provider(self, *_):
        local = self.provider.currentData() == "ollama"
        self.endpoint.setText("http://localhost:11434" if local else "https://api.openai.com/v1")
        self.model.setText("qwen2.5vl:7b" if local else "gpt-4.1-mini")
        self.key.setEnabled(not local)
        self.connection_changed()

    def connection_changed(self, *_):
        self.invalidate()
        # Changing the destination requires a new explicit vision opt-in.
        self.vision.setChecked(False)
        self.continuous.setChecked(False)
        self.update_status()

    def screen_changed(self, *_):
        self.vision.setChecked(False)
        self.invalidate()
        self.reset_region()
        self.pet.set_screen(self.current_screen())

    def vision_changed(self, enabled):
        self.invalidate()
        if not enabled:
            self.continuous.setChecked(False)
            self.thumbnail.clear()
            self.thumbnail.setText("Visión apagada. No se harán nuevas capturas.")
        self.update_status()
        if hasattr(self, "feedback"):
            self.feedback.setText("Visión habilitada para las consultas." if enabled else "Visión pausada. Las respuestas pendientes se descartan.")

    def continuous_changed(self, enabled):
        self.last_observed = time.monotonic()
        if not enabled:
            self.invalidate()
        self.update_status()

    def update_status(self):
        if not hasattr(self, "vision"):
            return
        active = self.vision.isChecked()
        self.pet.vision_active = active
        automatic = active and self.continuous.isChecked()
        self.status.setText("● VISIÓN AUTO" if automatic else "● VISIÓN ACTIVA" if active else "○ SIN VISIÓN")
        self.status.setStyleSheet("color: #78e7b3; background: #1c392f;" if active else "")
        try:
            destination = urlparse(self.endpoint.text()).hostname or "el servidor configurado"
        except ValueError:
            destination = "URL no válida"
        self.destination.setText(f"Destino de las consultas y capturas: {destination}. Las capturas no se guardan en disco.")
        self.observe_button.setEnabled(active and self.worker is None)
        self.continuous.setEnabled(active)
        self.key.setEnabled(self.provider.currentData() != "ollama")
        if getattr(self, "tray", None):
            self.tray.setToolTip(f"Stickfigures · {'visión automática' if automatic else 'visión habilitada' if active else 'visión apagada'}")

    def reset_region(self):
        self.vision.setChecked(False)
        self.region = None
        self.invalidate()
        self.region_label.setText("Monitor completo")

    def choose_region(self):
        # Changing scope pauses capture, so the new area can be reviewed first.
        self.vision.setChecked(False)
        selector = RegionSelector(self.current_screen(), self)
        def selected(rect):
            self.region = rect
            self.invalidate()
            self.region_label.setText(f"{rect.width()} × {rect.height()} · ({rect.x()}, {rect.y()})")
        selector.selected.connect(selected)
        selector.exec()

    def append_message(self, speaker: str, text: str):
        self.transcript.append(f'<p><b style="color:#ffb76c">{html.escape(speaker)}</b> {html.escape(text)}</p>')

    def send_message(self):
        message = self.message.text().strip()
        if not message or self.worker is not None:
            return
        if self.start_request(message, self.vision.isChecked()):
            self.append_message("Vos", message)
            self.message.clear()

    def observe(self):
        if self.vision.isChecked():
            self.start_request("Reaccioná a lo que ves ahora. Si no hay nada nuevo, hacé un gesto tranquilo y podés quedarte en silencio.", True)

    def auto_observe(self):
        if self.vision.isChecked() and self.continuous.isChecked() and self.worker is None:
            if time.monotonic() - self.last_observed >= self.interval.value():
                self.observe()

    def start_request(self, message: str, with_vision: bool) -> bool:
        if self.worker is not None:
            return False
        settings = BrainSettings(self.provider.currentData(), self.endpoint.text().strip(), self.model.text().strip(), self.key.text())
        try:
            settings.validate()
            screenshot = None
            self.request_bounds = None
            if with_vision and self.vision.isChecked():
                screenshot, image, self.request_bounds = capture_screen(self.current_screen(), self.region)
                self.thumbnail.setPixmap(QPixmap.fromImage(image).scaled(290, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.pending_message = message
            self.worker = BrainWorker(settings, self.character.currentText(), message, screenshot, list(self.history), self.generation)
            self.worker.result_ready.connect(self.receive_reaction)
            self.worker.failed.connect(self.request_failed)
            self.worker.finished.connect(self.request_finished)
            self.send.setEnabled(False)
            self.feedback.setText("Observando y pensando…" if screenshot else "Pensando… (sin captura)")
            self.update_status()
            self.worker.start()
            return True
        except ValueError as exc:
            self.request_failed(str(exc), self.generation)
            return False

    def receive_reaction(self, reaction: Reaction, generation: int):
        if generation != self.generation:
            return
        self.history.extend([{"role": "user", "content": self.pending_message},
                             {"role": "assistant", "content": reaction.as_json()}])
        self.history = self.history[-12:]
        target = None
        if reaction.target_x is not None and self.request_bounds is not None:
            target = self.request_bounds.left() + self.request_bounds.width() * reaction.target_x
        self.pet.react(reaction, target)
        if reaction.speech:
            self.append_message(self.character.currentText(), reaction.speech)
            if self.voice_enabled.isChecked() and self.tts:
                self.tts.setVoice(self.voice_choice.currentData())
                self.tts.say(reaction.speech)
        action_text = {"idle": "observa tranquilo", "walk": "se acerca", "wave": "te saluda", "jump": "da un salto",
                       "dance": "se pone a bailar", "sit": "se toma un descanso", "think": "está pensando",
                       "point": "señala algo", "celebrate": "lo celebra", "surprised": "se sorprende", "sleep": "se duerme"}
        self.feedback.setText(f"{self.character.currentText()} {action_text[reaction.action]}.")

    def request_failed(self, message: str, generation: int):
        if generation != self.generation:
            return
        self.continuous.setChecked(False)  # No repeated paid requests after a failure.
        self.feedback.setText(message)

    def request_finished(self):
        finished_worker = self.worker
        self.worker = None
        if finished_worker:
            finished_worker.deleteLater()
        self.last_observed = time.monotonic()
        self.send.setEnabled(True)
        self.update_status()

    def clear_memory(self):
        self.invalidate()
        self.transcript.clear()
        self.pet.speech = ""
        self.thumbnail.clear()
        self.feedback.setText("Contexto y vista previa borrados. La conversación no se guarda en disco.")

    def closeEvent(self, event):
        # Close pauses vision, then leaves the draggable pet and tray available.
        self.vision.setChecked(False)
        self.save_preferences()
        event.ignore()
        self.hide()

    def shutdown(self):
        self.vision.setChecked(False)
        self.invalidate()
        self.auto_timer.stop()
        self.save_preferences()
        self.pet.hide()
        self.hide()
        if self.tray:
            self.tray.hide()
        if self.worker is not None and self.worker.isRunning():
            # Never destroy an active QThread or freeze the UI while HTTP times out.
            self.feedback.setText("Cerrando la conexión pendiente…")
            self.worker.finished.connect(QApplication.instance().quit)
        else:
            QApplication.instance().quit()


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Stickfigures Desktop AI")
    application.setQuitOnLastWindowClosed(False)
    controls = Controls()
    controls.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
