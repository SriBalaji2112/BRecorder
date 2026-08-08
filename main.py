import sys
import cv2
import numpy as np
import cv2
import subprocess
import time
import os
import json
from datetime import datetime
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QComboBox,
                             QListWidget, QMessageBox, QInputDialog, QProgressDialog,
                             QListWidgetItem, QFileDialog, QTabWidget, QHeaderView,
                             QTableWidget, QTableWidgetItem, QAbstractItemView,
                             QSizePolicy, QFrame, QGroupBox, QTreeWidget, QTreeWidgetItem,
                             QLineEdit, QCheckBox, QScrollArea, QStackedWidget,
                             QGraphicsDropShadowEffect, QSpinBox, QSlider)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QSize, QPropertyAnimation, QRect, QEasingCurve
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette, QPixmap, QPainter, QBrush, QPen, QCursor

# Sound support
try:
    import winsound
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

# Win32
try:
    import win32gui
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


# ---------------------------------------------------------------------------
# Folder layout
# ---------------------------------------------------------------------------
BASE_FOLDER  = Path.home() / "Documents" / "BRecorder"
RAW_FOLDER   = BASE_FOLDER / "raw"
VIDEO_FOLDER = BASE_FOLDER / "videos"
SETTINGS_FILE = BASE_FOLDER / "settings.json"

for _d in (BASE_FOLDER, RAW_FOLDER, VIDEO_FOLDER):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Settings Manager  – persists to Documents/BRecorder/settings.json
# ---------------------------------------------------------------------------
class SettingsManager:
    _defaults = {
        "watermark": {
            "enabled": False,
            "text": "© BRecorder",
            "opacity": 80,        # 0–100
            "font_size_pct": 2,   # % of video height (h*0.XX)
            "position": "center", # center | top-left | top-right | bottom-left | bottom-right
        },
        "alert": {
            "enabled": False,
            "timer_sec": 60,
            "repeat_sec": 10
        },
        "access": {
            "allowed": True,
            "last_verified_time": 0.0
        }
    }

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._data: dict = {}
        self.load()

    def load(self):
        try:
            if self.filepath.exists():
                with open(self.filepath, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Deep-merge defaults
                self._data = self._merge(self._defaults, loaded)
            else:
                self._data = json.loads(json.dumps(self._defaults))
        except Exception:
            self._data = json.loads(json.dumps(self._defaults))

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"Settings save failed: {e}")

    def get(self, *keys):
        node = self._data
        for k in keys:
            node = node.get(k, {})
        return node

    def set(self, value, *keys):
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()

    @staticmethod
    def _merge(defaults: dict, overrides: dict) -> dict:
        result = json.loads(json.dumps(defaults))
        for k, v in overrides.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = SettingsManager._merge(result[k], v)
            else:
                result[k] = v
        return result


# ---------------------------------------------------------------------------
# Sound helpers
# ---------------------------------------------------------------------------
def _play_start_beep():
    if SOUND_AVAILABLE:
        try:
            winsound.Beep(1200, 150)
            time.sleep(0.05)
            winsound.Beep(1200, 150)
        except Exception:
            pass


def _play_stop_beep():
    if SOUND_AVAILABLE:
        try:
            winsound.Beep(800, 300)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _get_video_duration(filepath: str, ffprobe_path: str) -> str:
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [ffprobe_path, "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             filepath],
            capture_output=True, text=True, timeout=10, creationflags=creationflags
        )
        secs = float(result.stdout.strip())
        h, remainder = divmod(int(secs), 3600)
        m, s = divmod(remainder, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return "--:--:--"


def _recorded_time(filepath: str) -> str:
    try:
        ts = os.path.getmtime(filepath)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown"


def _create_session_folder(base_folder: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_folder = base_folder / timestamp
    session_folder.mkdir(parents=True, exist_ok=True)
    return session_folder


def _get_session_folders(base_folder: Path) -> list:
    folders = [f for f in base_folder.iterdir() if f.is_dir()]
    return sorted(folders, key=lambda x: x.stat().st_mtime, reverse=True)


# ---------------------------------------------------------------------------
# MetadataFetcher
# ---------------------------------------------------------------------------
class MetadataFetcher(QThread):
    done = pyqtSignal(list)

    def __init__(self, root_folder: Path, ffprobe_path: str):
        super().__init__()
        self.root_folder  = root_folder
        self.ffprobe_path = ffprobe_path
        self._cancelled   = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        rows = []
        try:
            session_folders = _get_session_folders(self.root_folder)
        except Exception:
            self.done.emit(rows)
            return

        for folder in session_folders:
            if self._cancelled:
                break
            try:
                videos = sorted(folder.glob("*.mp4"), key=os.path.getmtime, reverse=True)
            except Exception:
                continue
            for fp in videos:
                if self._cancelled:
                    break
                rows.append({
                    "path":     str(fp),
                    "duration": _get_video_duration(str(fp), self.ffprobe_path),
                })
        self.done.emit(rows)


# ---------------------------------------------------------------------------
# Settings Panel  (in-window overlay)
# ---------------------------------------------------------------------------

class _SideTabButton(QPushButton):
    """Vertical tab button for the left rail of the settings panel."""
    def __init__(self, icon_char: str, label: str, parent=None):
        super().__init__(parent)
        self.icon_char = icon_char
        self.label     = label
        self._active   = False
        self.setFixedSize(90, 76)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._update_style()

    def setActive(self, active: bool):
        self._active = active
        self._update_style()

    def _update_style(self):
        if self._active:
            bg     = "#1e3a52"
            border = "border-left: 3px solid #3a9fd8;"
            color  = "#e0f0ff"
            ic_col = "#3a9fd8"
        else:
            bg     = "transparent"
            border = "border-left: 3px solid transparent;"
            color  = "#666"
            ic_col = "#555"

        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                {border}
                color: {color};
                border-right: none;
                border-top: none;
                border-bottom: none;
                padding: 0px;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 0.4px;
            }}
            QPushButton:hover {{
                background: #1a2e40;
                color: #aacce0;
            }}
        """)
        # Rebuild text as multiline via HTML isn't easy in QPushButton,
        # so we set it directly and use paintEvent.

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QColor, QFont
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        icon_color = QColor("#3a9fd8") if self._active else QColor("#555")
        text_color = QColor("#e0f0ff") if self._active else QColor("#666")

        # Icon
        icon_font = QFont("Segoe UI Emoji", 18)
        painter.setFont(icon_font)
        painter.setPen(QPen(icon_color))
        icon_rect = QRect(rect.x(), rect.y() + 8, rect.width(), 32)
        painter.drawText(icon_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.icon_char)

        # Label
        lbl_font = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(lbl_font)
        painter.setPen(QPen(text_color))
        lbl_rect = QRect(rect.x(), rect.y() + 44, rect.width(), 20)
        painter.drawText(lbl_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.label)
        painter.end()


class WatermarkSettingsPanel(QWidget):
    """Right-side content panel for watermark settings."""

    settings_changed = pyqtSignal()

    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._build_ui()
        self._load_from_settings()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        # ── Section title ──────────────────────────────────────────────
        title = QLabel("Watermark")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #e0e0e0; margin-bottom: 4px;")
        layout.addWidget(title)

        desc = QLabel(
            "Apply a scrolling text watermark to exported videos. "
            "The text drifts across the frame at half opacity."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; font-size: 11px; line-height: 1.5;")
        layout.addWidget(desc)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #2a2a2a; background: #2a2a2a; max-height: 1px;")
        layout.addWidget(div)

        # ── Enable toggle ──────────────────────────────────────────────
        toggle_row = QHBoxLayout()
        toggle_lbl = QLabel("Enable Watermark")
        toggle_lbl.setStyleSheet("color: #ccc; font-size: 13px; font-weight: 600;")
        toggle_row.addWidget(toggle_lbl)
        toggle_row.addStretch()

        self.enable_toggle = _ToggleSwitch()
        self.enable_toggle.toggled_signal.connect(self._on_enable_changed)
        toggle_row.addWidget(self.enable_toggle)
        layout.addLayout(toggle_row)

        # ── Settings container (disabled when toggle is off) ────────────
        self.settings_container = QWidget()
        self.settings_container.setEnabled(False)
        sc_layout = QVBoxLayout()
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(16)

        # Watermark text
        sc_layout.addWidget(self._field_label("Watermark Text"))
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("e.g.  © My Company  or  CONFIDENTIAL")
        self.text_input.setStyleSheet("""
            QLineEdit {
                background: #1e1e1e;
                color: #ddd;
                border: 1px solid #333;
                border-radius: 5px;
                padding: 9px 12px;
                font-size: 13px;
                font-family: 'Consolas', monospace;
            }
            QLineEdit:focus {
                border-color: #3a9fd8;
            }
        """)
        self.text_input.textChanged.connect(self._on_text_changed)
        sc_layout.addWidget(self.text_input)

        # Opacity
        sc_layout.addWidget(self._field_label("Opacity"))
        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(80)
        self.opacity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a2a2a;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3a9fd8;
                width: 16px; height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #3a9fd8;
                border-radius: 3px;
            }
        """)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self.opacity_slider)

        self.opacity_val_lbl = QLabel("80%")
        self.opacity_val_lbl.setFixedWidth(38)
        self.opacity_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.opacity_val_lbl.setStyleSheet("color: #3a9fd8; font-size: 12px; font-weight: 600;")
        opacity_row.addWidget(self.opacity_val_lbl)
        sc_layout.addLayout(opacity_row)

        # Font size
        sc_layout.addWidget(self._field_label("Font Size  (% of video height)"))
        fs_row = QHBoxLayout()
        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setRange(1, 8)
        self.font_size_slider.setValue(2)
        self.font_size_slider.setStyleSheet(self.opacity_slider.styleSheet())
        self.font_size_slider.valueChanged.connect(self._on_fontsize_changed)
        fs_row.addWidget(self.font_size_slider)

        self.font_size_val_lbl = QLabel("2%")
        self.font_size_val_lbl.setFixedWidth(38)
        self.font_size_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.font_size_val_lbl.setStyleSheet("color: #3a9fd8; font-size: 12px; font-weight: 600;")
        fs_row.addWidget(self.font_size_val_lbl)
        sc_layout.addLayout(fs_row)

        # Preview
        self.preview_label = QLabel()
        self.preview_label.setFixedHeight(60)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("""
            background: #111;
            border: 1px solid #2a2a2a;
            border-radius: 5px;
            color: rgba(255,255,255,0.8);
            font-family: Arial;
        """)
        sc_layout.addWidget(self.preview_label)

        self.settings_container.setLayout(sc_layout)
        layout.addWidget(self.settings_container)
        layout.addStretch()

        # Save indicator
        self.save_lbl = QLabel("✓  Settings saved automatically")
        self.save_lbl.setStyleSheet("color: #3a7d44; font-size: 10px;")
        self.save_lbl.setAlignment(Qt.AlignRight)
        self.save_lbl.setVisible(False)
        layout.addWidget(self.save_lbl)

        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: self.save_lbl.setVisible(False))

        self.setLayout(layout)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase;")
        return lbl

    def _load_from_settings(self):
        wm = self.settings.get("watermark")
        enabled   = wm.get("enabled", False)
        text      = wm.get("text", "© BRecorder")
        opacity   = wm.get("opacity", 80)
        font_size = wm.get("font_size_pct", 2)

        self.enable_toggle.setChecked(enabled)
        self.settings_container.setEnabled(enabled)
        self.text_input.setText(text)
        self.opacity_slider.setValue(opacity)
        self.font_size_slider.setValue(font_size)
        self._update_preview()

    def _on_enable_changed(self, checked: bool):
        self.settings_container.setEnabled(checked)
        self.settings.set(checked, "watermark", "enabled")
        self._show_saved()
        self.settings_changed.emit()

    def _on_text_changed(self, text: str):
        self.settings.set(text, "watermark", "text")
        self._update_preview()
        self._show_saved()
        self.settings_changed.emit()

    def _on_opacity_changed(self, val: int):
        self.opacity_val_lbl.setText(f"{val}%")
        self.settings.set(val, "watermark", "opacity")
        self._update_preview()
        self._show_saved()
        self.settings_changed.emit()

    def _on_fontsize_changed(self, val: int):
        self.font_size_val_lbl.setText(f"{val}%")
        self.settings.set(val, "watermark", "font_size_pct")
        self._update_preview()
        self._show_saved()
        self.settings_changed.emit()

    def _update_preview(self):
        text      = self.text_input.text() or "Watermark Text"
        opacity   = self.opacity_slider.value() / 100.0
        font_size = max(10, self.font_size_slider.value() * 3)
        alpha_val = int(opacity * 255)
        self.preview_label.setStyleSheet(f"""
            background: #111;
            border: 1px solid #2a2a2a;
            border-radius: 5px;
            color: rgba(255,255,255,{opacity:.2f});
            font-family: Arial;
            font-size: {font_size}px;
        """)
        self.preview_label.setText(text)

    def _show_saved(self):
        self.save_lbl.setVisible(True)
        self._save_timer.start(2500)


class _ToggleSwitch(QWidget):
    """Animated iOS-style toggle switch."""
    toggled_signal = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self.setFixedSize(48, 26)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def isChecked(self):
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.toggled_signal.emit(self._checked)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Track
        track_color = QColor("#3a9fd8") if self._checked else QColor("#3a3a3a")
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 3, 48, 20, 10, 10)
        # Thumb
        thumb_x = 25 if self._checked else 3
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(thumb_x, 5, 18, 16)
        painter.end()


class AlertSettingsPanel(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._build_ui()
        self._load_from_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        # Title
        title = QLabel("Recording Alert Timer")
        title.setStyleSheet("color: #fff; font-size: 22px; font-weight: 700; font-family: 'Segoe UI', Arial;")
        layout.addWidget(title)

        desc = QLabel("Set a time limit. When the recording reaches this duration, an audio alert will play.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 13px; line-height: 1.4;")
        layout.addWidget(desc)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #2a2a30;")
        layout.addWidget(line)

        # Enable Toggle
        header_row = QHBoxLayout()
        lbl = QLabel("Enable Timer Alert")
        lbl.setStyleSheet("color: #ddd; font-size: 14px; font-weight: 600;")
        header_row.addWidget(lbl)
        header_row.addStretch()

        self.enable_toggle = _ToggleSwitch()
        self.enable_toggle.toggled_signal.connect(self._on_enable_changed)
        header_row.addWidget(self.enable_toggle)
        layout.addLayout(header_row)

        self.settings_container = QWidget()
        sc_layout = QVBoxLayout(self.settings_container)
        sc_layout.setContentsMargins(0, 8, 0, 0)
        sc_layout.setSpacing(16)

        # Timer input
        sc_layout.addWidget(self._field_label("Timer Limit (Seconds)"))
        
        self.timer_spinbox = QSpinBox()
        self.timer_spinbox.setRange(1, 36000)
        self.timer_spinbox.setValue(60)
        self.timer_spinbox.setStyleSheet("""
            QSpinBox { background: #111; color: #fff; border: 1px solid #2a2a2a; border-radius: 4px; padding: 6px; font-size: 13px; }
            QSpinBox::up-button, QSpinBox::down-button { width: 0px; }
        """)
        self.timer_spinbox.valueChanged.connect(self._on_timer_changed)
        sc_layout.addWidget(self.timer_spinbox)

        sc_layout.addWidget(self._field_label("Repeat Alert Every (Seconds, 0 to disable)"))
        self.repeat_spinbox = QSpinBox()
        self.repeat_spinbox.setRange(0, 36000)
        self.repeat_spinbox.setValue(10)
        self.repeat_spinbox.setStyleSheet(self.timer_spinbox.styleSheet())
        self.repeat_spinbox.valueChanged.connect(self._on_repeat_changed)
        sc_layout.addWidget(self.repeat_spinbox)

        self.settings_container.setLayout(sc_layout)
        layout.addWidget(self.settings_container)
        layout.addStretch()

        # Save indicator
        self.save_lbl = QLabel("✓  Settings saved automatically")
        self.save_lbl.setStyleSheet("color: #3a7d44; font-size: 10px;")
        self.save_lbl.setAlignment(Qt.AlignRight)
        self.save_lbl.setVisible(False)
        layout.addWidget(self.save_lbl)

        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: self.save_lbl.setVisible(False))

        self.setLayout(layout)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase;")
        return lbl

    def _load_from_settings(self):
        al = self.settings.get("alert")
        enabled = al.get("enabled", False)
        timer_sec = al.get("timer_sec", 60)
        repeat_sec = al.get("repeat_sec", 10)

        self.enable_toggle.setChecked(enabled)
        self.settings_container.setEnabled(enabled)
        self.timer_spinbox.setValue(timer_sec)
        self.repeat_spinbox.setValue(repeat_sec)

    def _on_enable_changed(self, checked: bool):
        self.settings_container.setEnabled(checked)
        self.settings.set(checked, "alert", "enabled")
        self._show_saved()
        self.settings_changed.emit()

    def _on_timer_changed(self, val: int):
        self.settings.set(val, "alert", "timer_sec")
        self._show_saved()
        self.settings_changed.emit()

    def _on_repeat_changed(self, val: int):
        self.settings.set(val, "alert", "repeat_sec")
        self._show_saved()
        self.settings_changed.emit()

    def _show_saved(self):
        self.save_lbl.setVisible(True)
        self._save_timer.start(2500)


class SettingsWindow(QWidget):
    """
    Full-screen transparent overlay that sits on top of the main window content.
    Left side = semi-transparent dimmed backdrop (click to close).
    Right side = opaque settings panel with tab rail + content area.
    """
    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings = settings
        # Make the overlay itself fully transparent – only children paint
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent;")
        self._build_ui()
        self.hide()

    def _build_ui(self):
        # No layout on self – we position children manually via _layout_children()

        # ── Dimmed backdrop (semi-transparent black) ────────────────────
        self.backdrop = QWidget(self)
        self.backdrop.setAttribute(Qt.WA_StyledBackground, True)
        self.backdrop.setStyleSheet("background-color: rgba(0, 0, 0, 160);")
        self.backdrop.mousePressEvent = lambda e: self.close_panel()

        # ── Slide-in panel ──────────────────────────────────────────────
        self.panel = QWidget(self)
        self.panel.setAttribute(Qt.WA_StyledBackground, True)
        self.panel.setStyleSheet("background-color: #1a1a1f;")

        panel_layout = QHBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # Left tab rail
        self.rail = QWidget()
        self.rail.setFixedWidth(100)
        self.rail.setAttribute(Qt.WA_StyledBackground, True)
        self.rail.setStyleSheet("background-color: #141418; border-right: 1px solid #222228;")

        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(0, 16, 0, 0)
        rail_layout.setSpacing(4)

        rail_title = QLabel("SETTINGS")
        rail_title.setAlignment(Qt.AlignCenter)
        rail_title.setStyleSheet(
            "color: #444; font-size: 9px; font-weight: 700; "
            "letter-spacing: 1.2px; padding-bottom: 12px; "
            "background: transparent;"
        )
        rail_layout.addWidget(rail_title)

        self.tab_watermark = _SideTabButton("💧", "Watermark")
        self.tab_watermark.setActive(True)
        self.tab_watermark.clicked.connect(lambda: self._switch_tab(0))
        rail_layout.addWidget(self.tab_watermark)
        
        self.tab_alert = _SideTabButton("🔔", "Alert")
        self.tab_alert.setActive(False)
        self.tab_alert.clicked.connect(lambda: self._switch_tab(1))
        rail_layout.addWidget(self.tab_alert)
        
        rail_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(100, 44)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #555;
                border: none;
                font-size: 17px;
            }
            QPushButton:hover { color: #e05555; }
        """)
        close_btn.clicked.connect(self.close_panel)
        rail_layout.addWidget(close_btn)

        panel_layout.addWidget(self.rail)

        # Content stack
        self.content_stack = QStackedWidget()
        self.content_stack.setAttribute(Qt.WA_StyledBackground, True)
        self.content_stack.setStyleSheet("background-color: #1a1a1f;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea          { border: none; background-color: #1a1a1f; }
            QScrollBar:vertical  { width: 6px; background: #111; border: none; }
            QScrollBar::handle:vertical { background: #333; border-radius: 3px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self.watermark_panel = WatermarkSettingsPanel(self.settings)
        scroll.setWidget(self.watermark_panel)
        self.content_stack.addWidget(scroll)

        scroll_alert = QScrollArea()
        scroll_alert.setWidgetResizable(True)
        scroll_alert.setStyleSheet(scroll.styleSheet())
        self.alert_panel = AlertSettingsPanel(self.settings)
        scroll_alert.setWidget(self.alert_panel)
        self.content_stack.addWidget(scroll_alert)

        panel_layout.addWidget(self.content_stack)
        self._tabs = [self.tab_watermark, self.tab_alert]

    # ── Custom paint: draw the dim layer directly so rgba works ────────
    def paintEvent(self, event):
        # The overlay widget itself is transparent; backdrop child handles dim.
        pass

    def _switch_tab(self, idx: int):
        for i, t in enumerate(self._tabs):
            t.setActive(i == idx)
        self.content_stack.setCurrentIndex(idx)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_children()

    def _layout_children(self):
        if not hasattr(self, 'panel'):
            return
        w = self.width()
        h = self.height()
        panel_w = min(460, max(360, w // 2))
        backdrop_w = w - panel_w
        self.backdrop.setGeometry(0, 0, backdrop_w, h)
        self.panel.setGeometry(backdrop_w, 0, panel_w, h)

    def open_panel(self):
        self._layout_children()
        self.show()
        self.raise_()

    def close_panel(self):
        self.hide()


# ---------------------------------------------------------------------------
# Floating control panel
# ---------------------------------------------------------------------------
class FloatingWindow(QWidget):
    start_recording   = pyqtSignal()
    stop_recording    = pyqtSignal()
    pause_recording   = pyqtSignal()
    resume_recording  = pyqtSignal()
    delete_current    = pyqtSignal()
    close_and_process = pyqtSignal()

    def __init__(self, ffmpeg_path: str, settings):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.settings = settings
        self.is_recording = False
        self.is_paused    = False
        self.elapsed_time = 0
        self.timer        = QTimer()
        self.timer.timeout.connect(self._tick)
        self.dragging      = False
        self.drag_position = None
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("B Recorder – Controls")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = QWidget()
        title_bar.setStyleSheet("background-color:#1e1e1e; border-top-left-radius:6px; border-top-right-radius:6px;")
        title_bar.setFixedHeight(28)
        tb_layout = QHBoxLayout()
        tb_layout.setContentsMargins(12, 0, 12, 0)
        lbl = QLabel("B Recorder – Controls")
        lbl.setStyleSheet("color:#aaa; font-size:11px; letter-spacing:0.5px;")
        tb_layout.addWidget(lbl)
        tb_layout.addStretch()
        title_bar.setLayout(tb_layout)
        root.addWidget(title_bar)

        body = QWidget()
        body.setStyleSheet("background-color:#252525;")
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(14, 14, 14, 14)
        body_layout.setSpacing(12)

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setFont(QFont("Consolas", 20, QFont.Bold))
        self.timer_label.setStyleSheet(
            "color:#e53935; background:#1e1e1e; padding:8px; border-radius:4px;"
        )
        body_layout.addWidget(self.timer_label)

        self.audio_checkbox = QCheckBox("Record with System Audio")
        self.audio_checkbox.setStyleSheet("""
            QCheckBox { color: #ccc; font-size: 12px; }
            QCheckBox::indicator { width: 14px; height: 14px; }
        """)
        # Read from settings to remember state, defaulting to True
        saved_state = self.settings.get("system_audio_enabled")
        is_checked = True if isinstance(saved_state, dict) else bool(saved_state)
        
        # Silently validate: if it's checked but system doesn't have it, force it off
        if is_checked and not self._has_stereo_mix():
            is_checked = False
            self.settings.set(False, "system_audio_enabled")
            
        self.audio_checkbox.setChecked(is_checked)
        self.audio_checkbox.stateChanged.connect(self._on_audio_changed)
        body_layout.addWidget(self.audio_checkbox)

        btn_row = QHBoxLayout()
        self.start_btn  = self._make_btn("Start",  "#3a7d44", "#2e6b39")
        self.pause_btn  = self._make_btn("Pause",  "#c17f1a", "#a86d15")
        self.stop_btn   = self._make_btn("Stop",   "#c0392b", "#a93226")

        self.start_btn.clicked.connect(self._on_start)
        self.pause_btn.clicked.connect(self._on_pause_resume)
        self.stop_btn.clicked.connect(self._on_stop)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        for b in (self.start_btn, self.pause_btn, self.stop_btn):
            btn_row.addWidget(b)
        body_layout.addLayout(btn_row)

        sec_row = QHBoxLayout()
        self.delete_btn = self._make_btn("Delete", "#7a3b2e", "#653225", size=10)
        self.close_btn  = self._make_btn("Close & Process", "#2a5f8a", "#1e4f73", size=10)

        self.delete_btn.clicked.connect(self._on_delete)
        self.close_btn.clicked.connect(self._on_close)
        self.delete_btn.setEnabled(False)

        sec_row.addWidget(self.delete_btn)
        sec_row.addWidget(self.close_btn)
        body_layout.addLayout(sec_row)

        body.setLayout(body_layout)
        root.addWidget(body)
        self.setLayout(root)
        self.setFixedSize(340, 220)

    @staticmethod
    def _make_btn(text, bg, hover, size=12):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color:{bg}; color:#fff; border:none;
                padding:8px; border-radius:4px;
                font-size:{size}px; font-weight:600; letter-spacing:0.3px;
            }}
            QPushButton:hover  {{ background-color:{hover}; }}
            QPushButton:disabled {{ background-color:#3a3a3a; color:#666; }}
        """)
        return btn

    def _has_stereo_mix(self):
        try:
            import subprocess, os
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            r = subprocess.run([self.ffmpeg_path, "-list_devices", "true", "-f", "dshow", "-i", "dummy"], 
                               capture_output=True, text=True, creationflags=creationflags, timeout=3)
            return "Stereo Mix" in r.stderr or "virtual-audio-capturer" in r.stderr
        except Exception:
            return False

    def _on_audio_changed(self, state):
        if state == Qt.Checked:
            if not self._has_stereo_mix():
                self.audio_checkbox.blockSignals(True)
                self.audio_checkbox.setChecked(False)
                self.audio_checkbox.blockSignals(False)
                
                QMessageBox.warning(self, "System Audio Unavailable",
                    "Your computer is missing the 'Stereo Mix' feature required to capture system audio natively.\n\n"
                    "To fix this, you can:\n"
                    "1. Right-click the Speaker icon in your Windows taskbar -> Sounds -> Recording tab.\n"
                    "2. Right-click and check 'Show Disabled Devices'.\n"
                    "3. If 'Stereo Mix' appears, right-click and 'Enable' it.\n\n"
                    "If it doesn't appear, you'll need to install a free virtual audio driver (like 'VB-Audio Virtual Cable' or 'Screen Capturer Recorder') to use this feature."
                )
                self.settings.set(False, "system_audio_enabled")
                return
                
        self.settings.set(self.audio_checkbox.isChecked(), "system_audio_enabled")
        
    def get_audio_enabled(self):
        return self.audio_checkbox.isChecked()

    def showEvent(self, event):
        super().showEvent(event)
        if WIN32_AVAILABLE:
            try:
                import ctypes
                hwnd = int(self.winId())
                WDA_EXCLUDEFROMCAPTURE = 0x00000011
                ok = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
                if not ok:
                    extended = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                                           extended | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST)
            except Exception as e:
                print(f"Window-exclusion error: {e}")

    def _on_start(self):
        if self.is_recording:
            return
        _play_start_beep()
        self.start_recording.emit()
        self.is_recording = True
        self.elapsed_time = 0
        self.timer.start(1000)
        self.start_btn.setEnabled(False)
        self.audio_checkbox.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _on_pause_resume(self):
        if self.is_paused:
            self.resume_recording.emit()
            self.is_paused = False
            self.pause_btn.setText("Pause")
            self.timer.start(1000)
        else:
            self.pause_recording.emit()
            self.is_paused = True
            self.pause_btn.setText("Resume")
            self.timer.stop()

    def _on_stop(self):
        if not self.is_recording:
            return
        _play_stop_beep()
        self.is_recording = False
        self.is_paused    = False
        self.timer.stop()
        self.elapsed_time = 0
        self.timer_label.setText("00:00:00")
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(False)
        self.audio_checkbox.setEnabled(True)
        self.stop_recording.emit()

    def _on_delete(self):
        if not self.is_recording:
            return
        if QMessageBox.question(self, "Delete Recording",
                                "Delete the current recording?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.delete_current.emit()
            self._on_stop()

    def _on_close(self):
        if self.is_recording:
            QMessageBox.warning(self, "Recording in Progress",
                                "Stop the current recording before closing.")
            return
        self.close_and_process.emit()

    def _tick(self):
        self.elapsed_time += 1
        h  = self.elapsed_time // 3600
        m  = (self.elapsed_time % 3600) // 60
        s  = self.elapsed_time % 60
        self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")
        
        # Check alert timer
        alert_settings = self.settings.get("alert")
        if alert_settings.get("enabled"):
            target_sec = alert_settings.get("timer_sec", 60)
            repeat_sec = alert_settings.get("repeat_sec", 10)
            
            should_alert = False
            if self.elapsed_time == target_sec:
                should_alert = True
            elif self.elapsed_time > target_sec and repeat_sec > 0:
                if (self.elapsed_time - target_sec) % repeat_sec == 0:
                    should_alert = True
                    
            if should_alert:
                try:
                    from pathlib import Path
                    audio_path = Path(__file__).resolve().parent / "BRecorder" / "assets" / "timmer_audio.mp3"
                    if audio_path.exists():
                        from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
                        from PyQt5.QtCore import QUrl
                        if not hasattr(self, 'alert_player'):
                            self.alert_player = QMediaPlayer()
                        self.alert_player.setMedia(QMediaContent(QUrl.fromLocalFile(str(audio_path))))
                        self.alert_player.play()
                    else:
                        import winsound
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    pass

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging      = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
        event.accept()


# ---------------------------------------------------------------------------
# Recording thread
# ---------------------------------------------------------------------------
class RecorderThread(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, fps, width, height, session_folder: Path,
                 ffmpeg_path: str = "ffmpeg", watermark_enabled: bool = False,
                 output_folder: Path = None, audio_enabled: bool = False,
                 target_title: str = "desktop"):
        super().__init__()
        self.fps               = fps
        self.width             = width
        self.height            = height
        self.session_folder    = session_folder
        self.ffmpeg_path       = ffmpeg_path
        self.watermark_enabled = watermark_enabled
        self.output_folder     = output_folder
        self.audio_enabled     = audio_enabled
        self.target_title      = target_title
        self.is_paused         = False
        self.should_stop       = False
        self.should_delete     = False
        self._ffmpeg_proc      = None
        self.chunks            = []
        self.current_chunk_idx = 0
        self.dst_file          = None

    def run(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = f"recording_{datetime.now().strftime('%Y_%m_%d %H-%M-%S')}"
            
            if self.watermark_enabled or not self.output_folder:
                self.dst_file = str(self.session_folder / f"raw_{timestamp}.mp4")
            else:
                self.dst_file = str(self.output_folder / f"{stem}.mp4")

            self._start_chunk()

            while not self.should_stop:
                if not self.is_paused:
                    if self._ffmpeg_proc is None:
                        self._start_chunk()
                    time.sleep(0.1)
                else:
                    if self._ffmpeg_proc is not None:
                        self._stop_current_chunk()
                    time.sleep(0.1)

            if self._ffmpeg_proc is not None:
                self._stop_current_chunk()

            if self.should_delete:
                self._cleanup_chunks()
                if os.path.exists(self.dst_file):
                    try:
                        os.remove(self.dst_file)
                    except Exception:
                        pass
                self.finished.emit("")
                return

            # Filter out chunks that failed to create (e.g. ffmpeg crashed)
            valid_chunks = [c for c in self.chunks if os.path.exists(c)]
            if not valid_chunks:
                self.error.emit(
                    "Recording failed (no video generated). \n\n"
                    "If 'Record with System Audio' is checked, please ensure 'Stereo Mix' "
                    "is enabled in your Windows Sound Control Panel."
                )
                self._cleanup_chunks()
                return
            
            self.chunks = valid_chunks

            # Robust stitch/rename with retry for WinError 32
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    if len(self.chunks) > 1:
                        self._stitch_chunks()
                    elif len(self.chunks) == 1:
                        if os.path.exists(self.dst_file):
                            os.remove(self.dst_file)
                        os.rename(self.chunks[0], self.dst_file)
                    break
                except PermissionError as e:
                    if attempt == max_retries - 1:
                        self.error.emit(f"Failed to process chunk (file locked): {e}")
                        return
                    time.sleep(0.5)
                except Exception as e:
                    self.error.emit(f"Failed to process chunk: {e}")
                    return

            self._cleanup_chunks()
            self.finished.emit(self.dst_file)

        except Exception as e:
            self.error.emit(str(e))

    def _start_chunk(self):
        chunk_file = str(self.session_folder / f"chunk_{self.current_chunk_idx}.mp4")
        self.chunks.append(chunk_file)
        
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        if self.target_title == "desktop":
            cmd = [
                self.ffmpeg_path, "-y",
                "-f", "gdigrab",
                "-framerate", str(self.fps),
                "-offset_x", "0", "-offset_y", "0",
                "-video_size", f"{self.width}x{self.height}",
                "-i", "desktop"
            ]
        else:
            cmd = [
                self.ffmpeg_path, "-y",
                "-f", "gdigrab",
                "-framerate", str(self.fps),
                "-i", f"title={self.target_title}"
            ]
        
        if self.audio_enabled:
            # Hardcode Stereo Mix for system audio since we specifically do not want mic audio
            cmd.extend(["-f", "dshow", "-i", "audio=Stereo Mix", "-c:a", "aac", "-b:a", "192k"])
            
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "24",
            "-pix_fmt", "yuv420p",
            chunk_file
        ])
        
        self._ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _stop_current_chunk(self):
        if self._ffmpeg_proc:
            try:
                # Write 'q' to gracefully stop ffmpeg
                if self._ffmpeg_proc.poll() is None:
                    self._ffmpeg_proc.stdin.write(b'q\n')
                    self._ffmpeg_proc.stdin.flush()
                    self._ffmpeg_proc.wait(timeout=5)
            except Exception:
                pass
            finally:
                if self._ffmpeg_proc.poll() is None:
                    try:
                        self._ffmpeg_proc.kill()
                        self._ffmpeg_proc.wait(timeout=3)
                    except Exception:
                        pass
                if self._ffmpeg_proc.stdin:
                    try:
                        self._ffmpeg_proc.stdin.close()
                    except Exception:
                        pass
            self._ffmpeg_proc = None

    def pause(self):
        if not self.is_paused:
            self.is_paused = True

    def resume(self):
        if self.is_paused:
            self.is_paused = False
            self.current_chunk_idx += 1

    def stop(self):
        self.should_stop = True

    def delete_and_stop(self):
        self.should_delete = True
        self.should_stop = True

    def _stitch_chunks(self):
        concat_list_path = self.session_folder / "concat.txt"
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for chunk in self.chunks:
                chunk_name = os.path.basename(chunk)
                f.write(f"file '{chunk_name}'\n")

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        cmd = [
            self.ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            self.dst_file
        ]
        subprocess.run(
            cmd,
            cwd=str(self.session_folder),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        if os.path.exists(concat_list_path):
            try:
                os.remove(concat_list_path)
            except Exception:
                pass

    def _cleanup_chunks(self):
        for chunk in self.chunks:
            if os.path.exists(chunk):
                try:
                    os.remove(chunk)
                except Exception:
                    pass

# ---------------------------------------------------------------------------
# Re-extraction worker  (raw → H.264 mp4)  – now with optional watermark
# ---------------------------------------------------------------------------
import re as _re

_FFMPEG_TIME_RE        = _re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
_FFMPEG_OUT_TIME_US_RE = _re.compile(r"out_time_us=(\d+)")


def _parse_ffmpeg_time(line: str):
    m = _FFMPEG_OUT_TIME_US_RE.search(line)
    if m:
        return int(m.group(1)) / 1_000_000.0
    m = _FFMPEG_TIME_RE.search(line)
    if m:
        return int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/100.0
    return None


def _build_watermark_filter(wm_config: dict, duration: float) -> str:
    """
    Build the ffmpeg drawtext filter string for a scrolling watermark.
    wm_config keys: text, opacity (0-100), font_size_pct (1-8)
    duration: total video duration in seconds
    """
    text      = wm_config.get("text", "© BRecorder").replace("'", "\\'")
    opacity   = wm_config.get("opacity", 80) / 100.0
    font_pct  = wm_config.get("font_size_pct", 2) / 100.0

    # Escape colon for ffmpeg on Windows paths
    filter_str = (
        f"drawtext=text='{text}':"
        f"fontfile='C\\:/Windows/Fonts/arial.ttf':"
        f"fontcolor=white@{opacity:.2f}:"
        f"fontsize=h*{font_pct}:"
        f"x='(w-tw)*(t/{duration:.3f})':"
        f"y='(h-th)/2':"
        f"alpha=0.5"
    )
    return filter_str


class ReExtractWorker(QThread):
    progress       = pyqtSignal(int, int)
    file_started   = pyqtSignal(str)
    finished       = pyqtSignal()
    error          = pyqtSignal(str)

    def __init__(self, raw_paths: list, output_folder: Path,
                 ffmpeg_path: str, ffprobe_path: str = "ffprobe",
                 watermark_config: dict = None):
        super().__init__()
        self.raw_paths        = raw_paths
        self.output_folder    = output_folder
        self.ffmpeg_path      = ffmpeg_path
        self.ffprobe_path     = ffprobe_path
        self.watermark_config = watermark_config  # None → no watermark
        self.cancelled        = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        total_files = len(self.raw_paths)
        total_steps = total_files * 100

        for idx, src in enumerate(self.raw_paths):
            if self.cancelled:
                break
            if not src or not os.path.exists(src):
                self.progress.emit((idx + 1) * 100, total_steps)
                continue

            self.file_started.emit(Path(src).name)

            stem = Path(src).stem
            ts   = stem.replace("raw_", "")
            try:
                dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
                formatted_ts = dt.strftime("%Y_%m_%d %H-%M-%S")
            except ValueError:
                formatted_ts = ts
            dst = str(self.output_folder / f"recording_{formatted_ts}.mp4")

            total_duration = _get_video_duration_secs(src, self.ffprobe_path)

            # ── Build vf filter chain ───────────────────────────────────
            vf_parts = ["fps=30"]
            if self.watermark_config and self.watermark_config.get("enabled") and total_duration > 0:
                wm_filter = _build_watermark_filter(self.watermark_config, total_duration)
                vf_parts.append(wm_filter)
            vf_string = ",".join(vf_parts)

            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", src,
                    "-vf", vf_string,
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "24",
                    "-pix_fmt", "yuv420p",
                    "-progress", "pipe:2",
                    dst
                ]
                proc = subprocess.Popen(
                    cmd,
                    creationflags=creationflags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0
                )

                base_step     = idx * 100
                last_pct      = -1
                stderr_buffer = b""

                while True:
                    if self.cancelled:
                        proc.kill()
                        proc.wait()
                        break
                    chunk = proc.stderr.read(1)
                    if not chunk:
                        break
                    stderr_buffer += chunk
                    if chunk in (b'\n', b'\r'):
                        line = stderr_buffer.decode("utf-8", errors="replace")
                        stderr_buffer = b""
                        elapsed = _parse_ffmpeg_time(line)
                        if elapsed is not None and total_duration > 0:
                            pct = int((elapsed / total_duration) * 100)
                            if pct != last_pct:
                                last_pct = pct
                                self.progress.emit(base_step + pct, total_steps)

                proc.wait()

                if self.cancelled:
                    if os.path.exists(dst):
                        os.remove(dst)
                    break

                if proc.returncode != 0:
                    self.error.emit(f"ffmpeg exited {proc.returncode} for {Path(src).name}")
                else:
                    self.progress.emit((idx + 1) * 100, total_steps)
                    try:
                        os.remove(src)
                    except Exception:
                        pass

            except FileNotFoundError:
                self.error.emit("ffmpeg not found. Install ffmpeg or place it in bin/.")
                break
            except Exception as e:
                self.error.emit(f"Failed to convert {Path(src).name}: {e}")

        self.finished.emit()


def _get_video_duration_secs(filepath: str, ffprobe_path: str) -> float:
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [ffprobe_path, "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             filepath],
            capture_output=True, text=True, timeout=10, creationflags=creationflags
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Videos tab
# ---------------------------------------------------------------------------
class VideosTab(QWidget):
    def __init__(self, ffprobe_path: str):
        super().__init__()
        self.ffprobe_path  = ffprobe_path
        self._meta_fetcher = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Duration", "Recorded"])
        self.tree.setIndentation(20)
        self.tree.setRootIsDecorated(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background:#1e1e1e; color:#ccc;
                border:1px solid #333; border-radius:4px;
                font-size:12px; outline: none;
            }
            QTreeWidget::item { padding: 6px 4px; border: none; }
            QTreeWidget::item:selected { background:#2a5f8a; color:#fff; }
            QTreeWidget::item:hover { background:#2a2a2a; }
            QTreeWidget::branch { background: #1e1e1e; }
            QHeaderView::section {
                background:#252525; color:#888;
                border-bottom:1px solid #333; border-right:1px solid #2a2a2a;
                padding:8px 6px; font-weight:600; font-size:11px;
                text-transform:uppercase; letter-spacing:0.6px;
            }
            QHeaderView::section:last { border-right:none; }
        """)
        layout.addWidget(self.tree)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.play_btn   = self._btn("Play",   "#2a5f8a", "#1e4f73")
        self.rename_btn = self._btn("Rename", "#7a6a1a", "#665a16")
        self.delete_btn = self._btn("Delete", "#7a3b2e", "#653225")
        self.play_btn.clicked.connect(self._play)
        self.rename_btn.clicked.connect(self._rename)
        self.delete_btn.clicked.connect(self._delete)
        for b in (self.play_btn, self.rename_btn, self.delete_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.setLayout(layout)

    def refresh(self):
        if self._meta_fetcher and self._meta_fetcher.isRunning():
            self._meta_fetcher.cancel()
            self._meta_fetcher.wait()

        self.tree.clear()
        session_folders = _get_session_folders(VIDEO_FOLDER)
        for folder in session_folders:
            folder_name = folder.name.replace("_", " ")
            folder_item = QTreeWidgetItem([f"📁 {folder_name}", "", "", ""])
            folder_item.setData(0, Qt.UserRole,     str(folder))
            folder_item.setData(0, Qt.UserRole + 1, "folder")
            font = folder_item.font(0)
            font.setBold(True)
            folder_item.setFont(0, font)
            folder_item.setForeground(0, QColor("#9ab"))
            self.tree.addTopLevelItem(folder_item)

            videos = sorted(folder.glob("*.mp4"), key=os.path.getmtime, reverse=True)
            for video in videos:
                video_item = QTreeWidgetItem([
                    f"   {video.name}",
                    _human_size(video.stat().st_size),
                    "…",
                    _recorded_time(str(video)),
                ])
                video_item.setData(0, Qt.UserRole,     str(video))
                video_item.setData(0, Qt.UserRole + 1, "file")
                folder_item.addChild(video_item)

        self._meta_fetcher = MetadataFetcher(VIDEO_FOLDER, self.ffprobe_path)
        self._meta_fetcher.done.connect(self._on_metadata_ready)
        self._meta_fetcher.start()

    def _on_metadata_ready(self, rows: list):
        dur_map = {r["path"]: r.get("duration", "--:--:--") for r in rows}
        for i in range(self.tree.topLevelItemCount()):
            folder_item = self.tree.topLevelItem(i)
            for j in range(folder_item.childCount()):
                video_item = folder_item.child(j)
                path = video_item.data(0, Qt.UserRole)
                dur  = dur_map.get(path, "--:--:--")
                video_item.setText(2, dur)

    def _selected_item(self):
        items = self.tree.selectedItems()
        return items[0] if items else None

    def _play(self):
        item = self._selected_item()
        if not item:
            return
        if item.data(0, Qt.UserRole + 1) == "file":
            os.startfile(item.data(0, Qt.UserRole))

    def _rename(self):
        item = self._selected_item()
        if not item:
            return
        if item.data(0, Qt.UserRole + 1) == "file":
            path = item.data(0, Qt.UserRole)
            old  = Path(path)
            new_name, ok = QInputDialog.getText(self, "Rename", "New file name:", text=old.stem)
            if ok and new_name.strip():
                new_path = old.parent / f"{new_name.strip()}.mp4"
                try:
                    old.rename(new_path)
                    self.refresh()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Rename failed: {e}")

    def _delete(self):
        item = self._selected_item()
        if not item:
            return
        item_type = item.data(0, Qt.UserRole + 1)
        if item_type == "folder":
            folder_path = Path(item.data(0, Qt.UserRole))
            video_count = len(list(folder_path.glob("*.mp4")))
            if QMessageBox.question(self, "Delete Folder",
                                    f"Delete folder '{folder_path.name}' and all {video_count} video(s)?",
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                try:
                    import shutil
                    shutil.rmtree(folder_path)
                    self.refresh()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Delete failed: {e}")
        elif item_type == "file":
            path = item.data(0, Qt.UserRole)
            if QMessageBox.question(self, "Delete",
                                    f"Delete {Path(path).name}?",
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                try:
                    os.remove(path)
                    self.refresh()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Delete failed: {e}")

    @staticmethod
    def _btn(text, bg, hover):
        b = QPushButton(text)
        b.setStyleSheet(f"""
            QPushButton {{
                background-color:{bg}; color:#fff; border:none;
                padding:7px 18px; border-radius:4px;
                font-size:11px; font-weight:600; letter-spacing:0.4px;
            }}
            QPushButton:hover {{ background-color:{hover}; }}
        """)
        return b


# ---------------------------------------------------------------------------
# Raw tab
# ---------------------------------------------------------------------------
class RawTab(QWidget):
    def __init__(self, ffmpeg_path: str, ffprobe_path: str = "ffprobe",
                 settings: SettingsManager = None):
        super().__init__()
        self.ffmpeg_path        = ffmpeg_path
        self.ffprobe_path       = ffprobe_path
        self.settings           = settings
        self._refresh_videos_cb = None
        self._worker            = None
        self._progress          = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        info = QLabel(
            "Raw recordings are uncompressed captures.  "
            "Use \"Re-extract\" to convert them into H.264 videos."
        )
        info.setStyleSheet(
            "color:#7a9; background:#1a2a1e; border:1px solid #2a4a2e; "
            "border-radius:4px; padding:8px 10px; font-size:11px;"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Recorded", ""])
        self.tree.setIndentation(20)
        self.tree.setRootIsDecorated(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background:#1e1e1e; color:#ccc;
                border:1px solid #333; border-radius:4px;
                font-size:12px; outline: none;
            }
            QTreeWidget::item { padding: 6px 4px; border: none; }
            QTreeWidget::item:selected { background:#2a5f8a; color:#fff; }
            QTreeWidget::item:hover { background:#2a2a2a; }
            QTreeWidget::branch { background: #1e1e1e; }
            QHeaderView::section {
                background:#252525; color:#888;
                border-bottom:1px solid #333; border-right:1px solid #2a2a2a;
                padding:8px 6px; font-weight:600; font-size:11px;
                text-transform:uppercase; letter-spacing:0.6px;
            }
            QHeaderView::section:last { border-right:none; }
        """)
        layout.addWidget(self.tree)

        bulk_row = QHBoxLayout()
        bulk_row.setSpacing(8)
        self.extract_folder_btn = self._btn("Re-extract Selected Folder", "#3a7d44", "#2e6b39")
        self.extract_all_btn    = self._btn("Re-extract All",             "#3a7d44", "#2e6b39")
        self.delete_all_btn     = self._btn("Delete All Raw",             "#7a3b2e", "#653225")
        self.extract_folder_btn.clicked.connect(self._extract_selected_folder)
        self.extract_all_btn.clicked.connect(self._extract_all)
        self.delete_all_btn.clicked.connect(self._delete_all)
        bulk_row.addWidget(self.extract_folder_btn)
        bulk_row.addWidget(self.extract_all_btn)
        bulk_row.addWidget(self.delete_all_btn)
        bulk_row.addStretch()
        layout.addLayout(bulk_row)
        self.setLayout(layout)

    def _wm_config(self):
        """Return current watermark config dict from settings."""
        if self.settings:
            return dict(self.settings.get("watermark"))
        return {"enabled": False}

    def refresh(self):
        self.tree.clear()
        session_folders = _get_session_folders(RAW_FOLDER)
        for folder in session_folders:
            folder_name = folder.name.replace("_", " ")
            folder_item = QTreeWidgetItem([f"📁 {folder_name}", "", "", ""])
            folder_item.setData(0, Qt.UserRole,     str(folder))
            folder_item.setData(0, Qt.UserRole + 1, "folder")
            font = folder_item.font(0)
            font.setBold(True)
            folder_item.setFont(0, font)
            folder_item.setForeground(0, QColor("#9ab"))
            self.tree.addTopLevelItem(folder_item)

            raw_files = sorted(folder.glob("raw_*.mp4"), key=os.path.getmtime, reverse=True)
            for raw_file in raw_files:
                file_item = QTreeWidgetItem([
                    f"   {raw_file.name}",
                    _human_size(raw_file.stat().st_size),
                    _recorded_time(str(raw_file)),
                    ""
                ])
                file_item.setData(0, Qt.UserRole,     str(raw_file))
                file_item.setData(0, Qt.UserRole + 1, "file")

                btn = QPushButton("Re-extract")
                btn.setStyleSheet("""
                    QPushButton {
                        background:#2a5f8a; color:#fff; border:none;
                        padding:4px 12px; border-radius:3px;
                        font-size:11px; font-weight:600;
                    }
                    QPushButton:hover { background:#1e4f73; }
                """)
                btn.clicked.connect(lambda checked, it=file_item: self._extract_single_file(it))
                folder_item.addChild(file_item)
                self.tree.setItemWidget(file_item, 3, btn)

    def _extract_single_file(self, item):
        path = item.data(0, Qt.UserRole)
        if not path or not os.path.exists(path):
            return
        raw_file      = Path(path)
        output_folder = VIDEO_FOLDER / raw_file.parent.name
        output_folder.mkdir(parents=True, exist_ok=True)
        self._run_extraction([path], output_folder)

    def _extract_selected_folder(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "No Selection", "Please select a folder to extract.")
            return
        item      = items[0]
        item_type = item.data(0, Qt.UserRole + 1)
        if item_type != "folder":
            QMessageBox.information(self, "Invalid Selection", "Please select a folder, not a file.")
            return
        folder_path = Path(item.data(0, Qt.UserRole))
        raw_files   = list(folder_path.glob("raw_*.mp4"))
        if not raw_files:
            QMessageBox.information(self, "No Files", "No raw files found in this folder.")
            return
        output_folder = VIDEO_FOLDER / folder_path.name
        output_folder.mkdir(parents=True, exist_ok=True)
        self._run_extraction([str(f) for f in raw_files], output_folder)

    def _extract_all(self):
        pairs = []
        for folder in _get_session_folders(RAW_FOLDER):
            output_folder = VIDEO_FOLDER / folder.name
            output_folder.mkdir(parents=True, exist_ok=True)
            for raw_file in folder.glob("raw_*.mp4"):
                pairs.append((str(raw_file), output_folder))
        if not pairs:
            QMessageBox.information(self, "Nothing to do", "No raw files found.")
            return
        self._run_extraction_pairs(pairs)

    def _delete_all(self):
        folders = _get_session_folders(RAW_FOLDER)
        if not folders:
            return
        total_files = sum(len(list(f.glob("raw_*.mp4"))) for f in folders)
        if QMessageBox.question(self, "Delete All Raw",
                                f"Permanently delete {len(folders)} folder(s) with {total_files} raw file(s)?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            import shutil
            for folder in folders:
                try:
                    shutil.rmtree(folder)
                except OSError:
                    pass
            self.refresh()

    def _run_extraction(self, paths: list, output_folder: Path):
        total_steps = len(paths) * 100
        self._progress = QProgressDialog("Preparing…", "Cancel", 0, total_steps, self)
        self._progress.setWindowTitle("Re-extract")
        self._progress.setWindowModality(Qt.NonModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.show()

        self._worker = ReExtractWorker(
            paths, output_folder, self.ffmpeg_path, self.ffprobe_path,
            watermark_config=self._wm_config())
        self._worker.progress.connect(self._on_extract_progress)
        self._worker.file_started.connect(self._on_extract_file_started)
        self._worker.finished.connect(self._on_extract_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._progress.canceled.connect(self._worker.cancel)

        self._extract_file_count = len(paths)
        self._extract_file_idx   = 0
        self._worker.start()

    def _run_extraction_pairs(self, pairs: list):
        total_steps = len(pairs) * 100
        self._progress = QProgressDialog("Preparing…", "Cancel", 0, total_steps, self)
        self._progress.setWindowTitle("Re-extract All")
        self._progress.setWindowModality(Qt.NonModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.show()

        self._pairs       = pairs
        self._pairs_index = 0
        self._pairs_total = len(pairs)
        self._process_next_pair()

    def _process_next_pair(self):
        if self._pairs_index >= self._pairs_total or (
                self._progress and self._progress.wasCanceled()):
            if self._progress:
                self._progress.close()
            self.refresh()
            if self._refresh_videos_cb:
                self._refresh_videos_cb()
            QTimer.singleShot(100, lambda: QMessageBox.information(
                self, "Done", "Re-extraction complete."))
            return

        path, output_folder = self._pairs[self._pairs_index]
        self._progress.setLabelText(
            f"Converting {Path(path).name} "
            f"({self._pairs_index + 1} / {self._pairs_total})")

        self._worker = ReExtractWorker(
            [path], output_folder, self.ffmpeg_path, self.ffprobe_path,
            watermark_config=self._wm_config())
        self._worker.progress.connect(self._on_pairs_progress)
        self._worker.finished.connect(self._on_pair_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._worker.start()

    def _on_pairs_progress(self, step: int, _total: int):
        if self._progress and not self._progress.wasCanceled():
            overall = self._pairs_index * 100 + step
            self._progress.setValue(overall)

    def _on_pair_done(self):
        self._pairs_index += 1
        self._process_next_pair()

    def _on_extract_file_started(self, filename: str):
        self._extract_file_idx += 1
        if self._progress:
            self._progress.setLabelText(
                f"Converting  {filename}  "
                f"({self._extract_file_idx} / {self._extract_file_count})")

    def _on_extract_progress(self, step: int, total: int):
        if self._progress and not self._progress.wasCanceled():
            self._progress.setValue(step)

    def _on_extract_done(self):
        if self._progress:
            self._progress.close()
        self.refresh()
        if self._refresh_videos_cb:
            self._refresh_videos_cb()
        QTimer.singleShot(100, lambda: QMessageBox.information(
            self, "Done", "Re-extraction complete."))

    @staticmethod
    def _btn(text, bg, hover):
        b = QPushButton(text)
        b.setStyleSheet(f"""
            QPushButton {{
                background-color:{bg}; color:#fff; border:none;
                padding:7px 18px; border-radius:4px;
                font-size:11px; font-weight:600; letter-spacing:0.4px;
            }}
            QPushButton:hover {{ background-color:{hover}; }}
        """)
        return b


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, icon):
        super().__init__()
        self.icon                   = icon
        self.recorder_thread        = None
        self.floating_window        = None
        self.current_session_folder = None
        self.pending_raw            = []
        self.ffmpeg_path            = self._find_exec("ffmpeg")
        self.ffprobe_path           = self._find_exec("ffprobe")
        self._worker                = None
        self._session_progress      = None
        self.settings               = SettingsManager(SETTINGS_FILE)
        self._build_ui()
        self._refresh_all()

    # @staticmethod
    # def _find_exec(name: str) -> str:
    #     script_dir = os.path.dirname(os.path.abspath(__file__))
    #     local      = os.path.join(script_dir, "BRecorder", "bin", f"{name}.exe")
    #     return local if os.path.exists(local) else name
    
    @staticmethod
    def _find_exec(name: str) -> str:
        exe_name = f"{name}.exe" if os.name == "nt" else name
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
        else:
            exe_dir = Path(os.path.abspath(__file__)).parent
        candidates = [
            exe_dir / "BRecorder" / "bin" / exe_name,
            exe_dir / "bin" / exe_name,
            exe_dir / exe_name,
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return name

    def _build_ui(self):
        self.setWindowTitle("B Recorder")
        self.setWindowIcon(self.icon)
        self.setGeometry(100, 100, 0, 700)
        self.setStyleSheet("QMainWindow { background:#16161a; }")

        central = QWidget()
        self.setCentralWidget(central)

        # Normal content fills central widget directly.
        # The settings overlay is a transparent child widget that floats on top.
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_label = QLabel()
        pixmap = QPixmap("BRecorder/assets/bee_icon.png")
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
            icon_label.setFixedSize(80, 80)
            icon_label.setScaledContents(True)
            icon_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            icon_label.setAlignment(Qt.AlignCenter)
        else:
            icon_label.setText("🐝")
        header_layout.addWidget(icon_label)

        header = QLabel("B Recorder")
        header.setFont(QFont("Segoe UI", 20, QFont.Bold))
        header.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header.setStyleSheet("color:#e0e0e0; margin:0px;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        # ── Gear / Settings button ──────────────────────────────────────
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background: #252525;
                color: #777;
                border: 1px solid #333;
                border-radius: 8px;
                font-size: 18px;
                padding: 0px;
            }
            QPushButton:hover {
                background: #2e2e2e;
                color: #3a9fd8;
                border-color: #3a9fd8;
            }
            QPushButton:pressed {
                background: #1e1e1e;
            }
        """)
        self.settings_btn.clicked.connect(self._open_settings)
        header_layout.addWidget(self.settings_btn)

        header_container = QWidget()
        header_container.setLayout(header_layout)
        header_container.setFixedHeight(75)
        root.addWidget(header_container)

        sub = QLabel("Record  •  Manage  •  Re-extract")
        sub.setStyleSheet("color:#555; font-size:11px; letter-spacing:1px; margin-bottom:4px;")
        root.addWidget(sub)

        # Settings row
        settings_group = QGroupBox()
        settings_group.setStyleSheet("""
            QGroupBox { background:#1e1e1e; border:1px solid #2e2e2e;
                        border-radius:6px; padding:12px; margin-top:0; }
        """)
        sg_layout = QHBoxLayout()
        sg_layout.setSpacing(24)

        res_lbl = QLabel("Resolution")
        res_lbl.setStyleSheet("color:#777; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.8px;")
        self.resolution_combo = QComboBox()
        # Use QApplication primary screen to get resolution instead of mss
        screen = QApplication.primaryScreen()
        size = screen.size()
        sw, sh = size.width(), size.height()
        self.resolution_combo.addItem(f"Full Screen  ({sw}×{sh})", (sw, sh))
        self.resolution_combo.addItem("1920×1080", (1920, 1080))
        self.resolution_combo.addItem("1280×720",  (1280, 720))
        self.resolution_combo.addItem("854×480",   (854, 480))
        self.resolution_combo.setStyleSheet("""
            QComboBox { background:#252525; color:#ccc; border:1px solid #333;
                        border-radius:4px; padding:6px 10px; font-size:12px; min-width:180px; }
            QComboBox::drop-down { border:none; }
            QComboBox:hover { border-color:#555; }
        """)
        res_col = QVBoxLayout()
        res_col.setSpacing(4)
        res_col.addWidget(res_lbl)
        res_col.addWidget(self.resolution_combo)
        sg_layout.addLayout(res_col)

        fps_lbl = QLabel("Frame Rate")
        fps_lbl.setStyleSheet("color:#777; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.8px;")
        self.fps_combo = QComboBox()
        self.fps_combo.addItem("30 FPS  (Recommended)", 30)
        self.fps_combo.addItem("60 FPS  (High)",        60)
        self.fps_combo.addItem("20 FPS  (Smooth)",      20)
        self.fps_combo.addItem("15 FPS  (Low)",         15)
        self.fps_combo.setStyleSheet(self.resolution_combo.styleSheet())
        fps_col = QVBoxLayout()
        fps_col.setSpacing(4)
        fps_col.addWidget(fps_lbl)
        fps_col.addWidget(self.fps_combo)
        sg_layout.addLayout(fps_col)

        target_lbl = QLabel("Target Window")
        target_lbl.setStyleSheet("color:#777; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.8px;")
        
        self.target_combo = QComboBox()
        self.target_combo.setStyleSheet(self.resolution_combo.styleSheet())
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setStyleSheet("background:#333; color:#ccc; border-radius:4px; font-size:12px;")
        refresh_btn.clicked.connect(self._refresh_targets)
        
        target_h = QHBoxLayout()
        target_h.setSpacing(4)
        target_h.addWidget(self.target_combo)
        target_h.addWidget(refresh_btn)
        
        target_col = QVBoxLayout()
        target_col.setSpacing(4)
        target_col.addWidget(target_lbl)
        target_col.addLayout(target_h)
        sg_layout.addLayout(target_col)
        
        self._refresh_targets()

        status_col = QVBoxLayout()
        status_col.setSpacing(4)
        status_col.setAlignment(Qt.AlignVCenter)
        self.wm_status_lbl = QLabel()
        self.alert_status_lbl = QLabel()
        self._update_status_indicators()
        status_col.addWidget(self.wm_status_lbl)
        status_col.addWidget(self.alert_status_lbl)
        sg_layout.addLayout(status_col)

        sg_layout.addStretch()
        self.start_btn = QPushButton("Start Recording")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background:#3a7d44; color:#fff; border:none;
                padding:10px 28px; border-radius:5px;
                font-size:13px; font-weight:700; letter-spacing:0.4px;
            }
            QPushButton:hover { background:#2e6b39; }
        """)
        self.start_btn.clicked.connect(self._open_floating)
        sg_layout.addWidget(self.start_btn)
        settings_group.setLayout(sg_layout)
        root.addWidget(settings_group)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #16161a; top: 2px; }
            QTabBar::tab {
                background: #1e1e1e; color: #666;
                padding: 12px 20px; margin-right: 4px; min-width: 80px;
                border-radius: 8px 8px 0 0;
                font-size: 12px; font-weight: 600; letter-spacing: 0.4px;
            }
            QTabBar::tab:selected  { background: #252525; color: #ddd; border-bottom: 3px solid #3a7d44; }
            QTabBar::tab:hover     { color: #aaa; background: #2a2a2a; }
            QTabBar::tab:!selected { margin-top: 2px; }
        """)

        self.videos_tab = VideosTab(self.ffprobe_path)
        self.raw_tab    = RawTab(self.ffmpeg_path, self.ffprobe_path, self.settings)
        self.raw_tab._refresh_videos_cb = self.videos_tab.refresh

        self.tabs.addTab(self.videos_tab, "Videos")
        self.tabs.addTab(self.raw_tab,    "Raw")
        root.addWidget(self.tabs)

        self.status_lbl = QLabel(
            f"Output  →  {VIDEO_FOLDER} @created by Balaji S. <sribalaji2112@gmail.com>")
        self.status_lbl.setStyleSheet("color:#444; font-size:15px; padding-top:4px;")
        root.addWidget(self.status_lbl)

        # ── Settings overlay: transparent child that floats over everything ──
        # Created AFTER the layout is set so it sits on top in Z-order
        self._settings_overlay = SettingsWindow(self.settings, parent=central)
        self._settings_overlay.setGeometry(0, 0, central.width(), central.height())
        self._settings_overlay.watermark_panel.settings_changed.connect(self._update_status_indicators)
        self._settings_overlay.alert_panel.settings_changed.connect(self._update_status_indicators)

    def _refresh_targets(self):
        self.target_combo.clear()
        self.target_combo.addItem("Entire Screen", "desktop")
        
        if WIN32_AVAILABLE:
            titles = []
            def callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title and title not in ["Program Manager", "Settings"]:
                        titles.append(title)
            win32gui.EnumWindows(callback, None)
            for t in sorted(list(set(titles))):
                self.target_combo.addItem(t, t)

    def _update_status_indicators(self):
        wm = self.settings.get("watermark", "enabled")
        al = self.settings.get("alert", "enabled")
        
        # Handle case where the value wasn't found and it returned {}
        wm = bool(wm) if not isinstance(wm, dict) else False
        al = bool(al) if not isinstance(al, dict) else False
        
        if hasattr(self, 'wm_status_lbl'):
            self.wm_status_lbl.setText("💧 Watermark: ON" if wm else "💧 Watermark: OFF")
            self.wm_status_lbl.setStyleSheet("color: #3a9fd8; font-size: 11px; font-weight: bold;" if wm else "color: #777; font-size: 11px;")
        
        if hasattr(self, 'alert_status_lbl'):
            self.alert_status_lbl.setText("🔔 Timer Alert: ON" if al else "🔔 Timer Alert: OFF")
            self.alert_status_lbl.setStyleSheet("color: #e53935; font-size: 11px; font-weight: bold;" if al else "color: #777; font-size: 11px;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep overlay in sync with window size
        if hasattr(self, '_settings_overlay') and self.centralWidget():
            self._settings_overlay.setGeometry(self.centralWidget().rect())

    def _open_settings(self):
        if hasattr(self, '_settings_overlay') and self.centralWidget():
            self._settings_overlay.setGeometry(self.centralWidget().rect())
        self._settings_overlay.open_panel()

    def _refresh_all(self):
        self.videos_tab.refresh()
        self.raw_tab.refresh()

    def _open_floating(self):
        if not check_access(self.settings, parent_widget=self):
            return

        self.current_session_folder = _create_session_folder(RAW_FOLDER)
        if self.floating_window is None:
            self.floating_window = FloatingWindow(ffmpeg_path=self.ffmpeg_path, settings=self.settings)
            self.floating_window.start_recording.connect(self._start_recording)
            self.floating_window.stop_recording.connect(self._stop_recording)
            self.floating_window.pause_recording.connect(self._pause_recording)
            self.floating_window.resume_recording.connect(self._resume_recording)
            self.floating_window.delete_current.connect(self._delete_current)
            self.floating_window.close_and_process.connect(self._close_and_process)
        self.floating_window.setWindowIcon(self.icon)
        self.floating_window.show()
        self.floating_window.raise_()
        self.floating_window.activateWindow()
        self.showMinimized()

    def _start_recording(self):
        w, h = self.resolution_combo.currentData()
        fps  = self.fps_combo.currentData()
        if fps >= 60:
            if QMessageBox.warning(self, "High FPS",
                                   f"{fps} FPS may cause lag.\n\nContinue?",
                                   QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
                self.floating_window.stop_btn.click()
                return

        wm_enabled = self.settings.get("watermark", "enabled")  # bool
        audio_on   = self.floating_window.get_audio_enabled()

        # For live encoding, we need the output folder ready immediately
        output_folder = None
        if not wm_enabled:
            output_folder = VIDEO_FOLDER / self.current_session_folder.name
            output_folder.mkdir(parents=True, exist_ok=True)

        target_title = self.target_combo.currentData()
        
        self.recorder_thread = RecorderThread(
            fps, w, h, self.current_session_folder,
            ffmpeg_path=self.ffmpeg_path,
            watermark_enabled=bool(wm_enabled),
            output_folder=output_folder,
            audio_enabled=audio_on,
            target_title=target_title
        )
        self.recorder_thread.finished.connect(self._on_rec_finished)
        self.recorder_thread.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self.recorder_thread.start()

    def _stop_recording(self):
        if self.recorder_thread:
            self.recorder_thread.stop()

    def _pause_recording(self):
        if self.recorder_thread:
            self.recorder_thread.pause()

    def _resume_recording(self):
        if self.recorder_thread:
            self.recorder_thread.resume()

    def _delete_current(self):
        if self.recorder_thread:
            self.recorder_thread.delete_and_stop()

    def _on_rec_finished(self, raw_path: str):
        if raw_path:
            wm_enabled = self.settings.get("watermark", "enabled")
            if wm_enabled:
                # Raw file → needs post-processing
                self.pending_raw.append(raw_path)
                self.raw_tab.refresh()
            else:
                # Already encoded live → just refresh videos
                self.videos_tab.refresh()

    def _close_and_process(self):
        if self.floating_window:
            self.floating_window.close()
            self.floating_window = None

        if not self.pending_raw:
            self._refresh_all()
            return

        output_folder = VIDEO_FOLDER / self.current_session_folder.name
        output_folder.mkdir(parents=True, exist_ok=True)

        total_steps = len(self.pending_raw) * 100
        self._session_progress = QProgressDialog(
            "Preparing…", "Cancel", 0, total_steps, self)
        self._session_progress.setWindowTitle("Processing")
        self._session_progress.setWindowModality(Qt.NonModal)
        self._session_progress.setMinimumDuration(0)
        self._session_progress.setValue(0)
        self._session_progress.show()

        self._session_file_count = len(self.pending_raw)
        self._session_file_idx   = 0

        wm_cfg = dict(self.settings.get("watermark"))
        self._worker = ReExtractWorker(
            self.pending_raw, output_folder, self.ffmpeg_path, self.ffprobe_path,
            watermark_config=wm_cfg)
        self._worker.progress.connect(self._on_session_progress)
        self._worker.file_started.connect(self._on_session_file_started)
        self._worker.finished.connect(self._on_session_extract_done)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._session_progress.canceled.connect(self._worker.cancel)
        self._worker.start()

    def _on_session_file_started(self, filename: str):
        self._session_file_idx += 1
        if self._session_progress:
            self._session_progress.setLabelText(
                f"Converting  {filename}  "
                f"({self._session_file_idx} / {self._session_file_count})")

    def _on_session_progress(self, step: int, total: int):
        if self._session_progress and not self._session_progress.wasCanceled():
            self._session_progress.setValue(step)

    def _on_session_extract_done(self):
        if self._session_progress:
            self._session_progress.close()
        self.pending_raw.clear()
        self.current_session_folder = None
        self._refresh_all()
        QTimer.singleShot(100, lambda: QMessageBox.information(
            self, "Done", "All recordings have been processed."))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def check_access(settings_manager, parent_widget=None):
    import urllib.request, time, json, base64
    # Use GitHub API instead of raw URL to bypass the 5-minute CDN cache completely
    url = "https://api.github.com/repos/SriBalaji2112/BRecorder/contents/access_config.json"
    current_time = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BRecorder-App', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=3) as response:
            api_data = json.loads(response.read().decode())
            content_str = base64.b64decode(api_data['content']).decode()
            config_data = json.loads(content_str)
            
            has_access = config_data.get("Access", True)
            settings_manager.set(has_access, "access", "allowed")
            if has_access:
                settings_manager.set(current_time, "access", "last_verified_time")
            settings_manager.save()
            
            if not has_access and parent_widget:
                QMessageBox.critical(parent_widget, "Access Denied", 
                    "This application has been disabled by the administrator.\n\n"
                    "Please contact Balaji S. at sribalaji2112@gmail.com for access.")
            return has_access
            
    except Exception:
        # Offline or error
        has_access = settings_manager.get("access", "allowed")
        if not has_access:
            if parent_widget:
                QMessageBox.critical(parent_widget, "Access Denied", 
                    "This application has been disabled by the administrator.\n\n"
                    "Please contact Balaji S. at sribalaji2112@gmail.com for access.")
            return False
            
        last_verified = settings_manager.get("access", "last_verified_time")
        if not isinstance(last_verified, (int, float)):
            last_verified = 0.0
            
        elapsed = current_time - last_verified
        max_offline = 48 * 3600 # 48 hours
        
        if elapsed > max_offline:
            if parent_widget:
                QMessageBox.critical(parent_widget, "Offline Access Expired",
                    "Your offline access period (48 hours) has expired.\n\n"
                    "Please connect to the internet to verify your access.")
            return False
        else:
            if parent_widget:
                remaining = max_offline - elapsed
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                QMessageBox.warning(parent_widget, "Offline Mode",
                    f"You are currently offline.\nOffline access will expire in {hours} hours and {mins} minutes.")
            return True

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon = QIcon("BRecorder/assets/bee_icon.png")
    app.setWindowIcon(icon)

    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(30, 30, 30))
    pal.setColor(QPalette.WindowText,      QColor(200, 200, 200))
    pal.setColor(QPalette.Base,            QColor(22, 22, 26))
    pal.setColor(QPalette.AlternateBase,   QColor(26, 26, 30))
    pal.setColor(QPalette.Text,            QColor(200, 200, 200))
    pal.setColor(QPalette.Button,          QColor(37, 37, 37))
    pal.setColor(QPalette.ButtonText,      QColor(200, 200, 200))
    pal.setColor(QPalette.Highlight,       QColor(42, 95, 138))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    win = MainWindow(icon)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()