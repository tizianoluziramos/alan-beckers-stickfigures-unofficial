"""Run with QT_QPA_PLATFORM=offscreen, or under X11 to exercise real capture."""

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QRect
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from desktop_ai.app import Controls
from desktop_ai.brain import Reaction
from desktop_ai.screen import capture_screen


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings = QSettings(self.temp.name + "/preferences.ini", QSettings.Format.IniFormat)
        with patch("desktop_ai.app.QSettings", return_value=settings), patch.object(Controls, "setup_voice"), patch.object(Controls, "setup_tray"):
            self.controls = Controls()
        self.controls.tray = None

    def tearDown(self):
        self.controls.auto_timer.stop()
        self.controls.pet.timer.stop()
        self.controls.pet.hide()
        self.controls.hide()
        self.controls.pet.deleteLater()
        self.controls.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_for_request(self):
        deadline = time.monotonic() + 5
        while self.controls.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(self.controls.worker)

    def test_text_only_chat_never_captures_and_handles_worker_result(self):
        with patch("desktop_ai.app.capture_screen") as capture, patch("desktop_ai.app.request_reaction", return_value=Reaction("¡Hola!", "wave")):
            self.controls.message.setText("Hola")
            self.controls.send_message()
            self.wait_for_request()
            capture.assert_not_called()
        self.assertIn("¡Hola!", self.controls.transcript.toPlainText())
        self.assertEqual(self.controls.pet.motion.action, "wave")
        self.assertEqual(len(self.controls.history), 2)

    def test_pausing_discards_inflight_result_and_clears_context(self):
        generation = self.controls.generation
        self.controls.vision.setChecked(True)
        generation = self.controls.generation
        self.controls.vision.setChecked(False)
        self.controls.receive_reaction(Reaction("stale result", "dance"), generation)
        self.assertNotIn("stale result", self.controls.transcript.toPlainText())
        self.assertFalse(self.controls.history)
        self.assertFalse(self.controls.pet.vision_active)

    def test_pending_network_does_not_block_animation_and_stale_reply_is_discarded(self):
        release = threading.Event()
        def slow_model(*_):
            release.wait(2)
            return Reaction("late reply", "dance")
        with patch("desktop_ai.app.request_reaction", side_effect=slow_model):
            self.controls.message.setText("Hola")
            self.controls.send_message()
            clock_before = self.controls.pet.motion.clock
            deadline = time.monotonic() + 0.12
            while time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertGreater(self.controls.pet.motion.clock, clock_before + 0.05)
            self.controls.clear_memory()
            release.set()
            self.wait_for_request()
        self.assertFalse(self.controls.history)
        self.assertNotIn("late reply", self.controls.transcript.toPlainText())

    def test_destination_change_resets_vision_consent_and_automation(self):
        self.controls.vision.setChecked(True)
        self.controls.continuous.setChecked(True)
        self.controls.endpoint.setText("http://another-model:11434")
        self.assertFalse(self.controls.vision.isChecked())
        self.assertFalse(self.controls.continuous.isChecked())

    def test_region_coordinates_map_to_global_desktop(self):
        self.controls.request_bounds = QRect(-1200, 200, 800, 500)
        with patch.object(self.controls.pet, "react") as react:
            self.controls.receive_reaction(Reaction("Por ahí", "point", "curious", 0.75), self.controls.generation)
            self.assertEqual(react.call_args.args[1], -600)

    def test_automatic_error_stops_repeated_requests(self):
        self.controls.vision.setChecked(True)
        self.controls.continuous.setChecked(True)
        self.controls.request_failed("HTTP 429", self.controls.generation)
        self.assertFalse(self.controls.continuous.isChecked())
        self.assertIn("HTTP 429", self.controls.feedback.text())

    def test_credentials_capture_and_consent_are_not_saved(self):
        self.controls.key.setText("do-not-save")
        self.controls.vision.setChecked(True)
        self.controls.save_preferences()
        self.controls.preferences.sync()
        text = Path(self.controls.preferences.fileName()).read_text(encoding="utf-8")
        self.assertNotIn("do-not-save", text)
        self.assertNotIn("vision", text)

    def test_capture_encodes_only_the_selected_region_in_memory(self):
        screen = unittest.mock.Mock()
        screen.geometry.return_value = QRect(-1600, 0, 1600, 900)
        pixmap = QPixmap(200, 100)
        pixmap.fill(QColor("#22aa66"))
        screen.grabWindow.return_value = pixmap
        data, image, absolute = capture_screen(screen, QRect(30, 40, 200, 100))
        screen.grabWindow.assert_called_once_with(0, 30, 40, 200, 100)
        self.assertEqual(data[:2], b"\xff\xd8")
        self.assertEqual((image.width(), image.height()), (200, 100))
        self.assertEqual(absolute, QRect(-1570, 40, 200, 100))

    def test_capture_failure_is_reported(self):
        screen = unittest.mock.Mock()
        screen.geometry.return_value = QRect(0, 0, 800, 600)
        screen.grabWindow.return_value = QPixmap()
        with self.assertRaisesRegex(ValueError, "no permitió capturar"):
            capture_screen(screen)

    @unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM") == "xcb", "Requires an X11 display")
    def test_real_x11_capture_produces_jpeg(self):
        self.controls.show()
        self.app.processEvents()
        data, image, bounds = capture_screen(self.app.primaryScreen(), QRect(10, 20, 420, 300))
        self.assertEqual(data[:2], b"\xff\xd8")
        self.assertEqual((image.width(), image.height()), (420, 300))


if __name__ == "__main__":
    unittest.main()
