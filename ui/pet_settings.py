#!/usr/bin/env python3
"""
pet_settings.py — right-click "Settings…" dialog.
Now updated with a Tabbed interface including general configurations and
an Adaptive AI Performance & Models tab.
"""

import os
import time
import json
import logging
import platform
import threading
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QButtonGroup,
    QGroupBox,
    QTextBrowser,
)

from ui.blob_renderer import DEFAULT_BODY_COLOR as DEFAULT_COLOR
from core.pet_performance import (
    PERFORMANCE_MODES,
    detect_hardware,
    recommend_mode_static,
    get_hardware_fingerprint,
    OllamaClient,
    BenchmarkService,
    ModelManager,
)

logger = logging.getLogger("PipSettings")

MOVE_FREQUENCY_PRESETS = {
    "calm":   {"hop": (14, 26), "wave": (35, 70), "wander": (40, 90)},
    "normal": {"hop": (8, 16),  "wave": (25, 50), "wander": (25, 60)},
    "hyper":  {"hop": (3, 8),   "wave": (12, 25), "wander": (10, 25)},
}

MESSAGE_FREQUENCY_PRESETS = {
    "quiet":  {"idle_range_s": (60, 150), "idle_prob": 0.15, "brain_cooldown": 60.0},
    "normal": {"idle_range_s": (25, 70),  "idle_prob": 0.30, "brain_cooldown": 30.0},
    "chatty": {"idle_range_s": (10, 30),  "idle_prob": 0.55, "brain_cooldown": 12.0},
}

MOVE_FREQUENCY_LABELS = [("calm", "Calm"), ("normal", "Normal"), ("hyper", "Hyper")]
MESSAGE_FREQUENCY_LABELS = [("quiet", "Quiet"), ("normal", "Normal"), ("chatty", "Chatty")]

# ------------------------------------------------------------- Background Workers

class DownloadWorker(QThread):
    progress = Signal(str, float, float, float)
    finished = Signal(bool, str)

    def __init__(self, model_manager, model_name):
        super().__init__()
        self.model_manager = model_manager
        self.model_name = model_name
        self.cancel_event = threading.Event()

    def run(self):
        success, msg = self.model_manager.pull_model_progress(
            self.model_name,
            self.progress.emit,
            self.cancel_event
        )
        self.finished.emit(success, msg)

    def cancel(self):
        self.cancel_event.set()


class AIDownloadDialog(QDialog):
    def __init__(self, model_manager, model_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downloading AI Model")
        self.setMinimumWidth(360)
        self.model_manager = model_manager
        self.model_name = model_name

        layout = QVBoxLayout(self)
        self.label = QLabel(f"Preparing to download {model_name}...\nThis may take several minutes depending on connection speed.")
        self.label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)

        layout.addWidget(self.label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_btn)

        self.worker = DownloadWorker(model_manager, model_name)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.download_finished)
        self.worker.start()

    def update_progress(self, status, pct, completed, total):
        pct_int = int(pct * 100)
        self.progress_bar.setValue(pct_int)
        
        comp_gb = completed / (1024**3)
        tot_gb = total / (1024**3)
        if total > 0:
            self.label.setText(f"Status: {status}\nProgress: {pct_int}% ({comp_gb:.2f} GB / {tot_gb:.2f} GB)")
        else:
            self.label.setText(f"Status: {status}...")

    def on_cancel(self):
        self.worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.label.setText("Cancelling download...")

    def download_finished(self, success, msg):
        if success:
            self.accept()
        else:
            self.reject()
            if msg != "Download cancelled":
                QMessageBox.critical(self, "Download Failed", f"Failed to download model:\n{msg}")


class BenchmarkWorker(QThread):
    progress = Signal(str)
    finished = Signal(dict)

    def __init__(self, benchmark_service, model_name):
        super().__init__()
        self.benchmark_service = benchmark_service
        self.model_name = model_name
        self.cancel_event = threading.Event()

    def run(self):
        res = self.benchmark_service.run_benchmark(
            self.model_name,
            self.progress.emit,
            self.cancel_event
        )
        self.finished.emit(res)

    def cancel(self):
        self.cancel_event.set()


class BenchmarkDialog(QDialog):
    def __init__(self, benchmark_service, model_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Running AI Performance Benchmark")
        self.setMinimumWidth(360)
        self.benchmark_service = benchmark_service
        self.model_name = model_name
        self.result = None

        layout = QVBoxLayout(self)
        self.label = QLabel("Initializing benchmark...\nThis will run a cold and warm request to test speeds.")
        self.label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)

        layout.addWidget(self.label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_btn)

        self.worker = BenchmarkWorker(benchmark_service, model_name)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.benchmark_finished)
        self.worker.start()

    def update_progress(self, status):
        self.label.setText(status)

    def on_cancel(self):
        self.worker.cancel()
        self.reject()

    def benchmark_finished(self, res):
        self.result = res
        if res.get("success"):
            self.accept()
        else:
            self.reject()
            QMessageBox.critical(self, "Benchmark Failed", f"Failed to complete benchmark:\n{res.get('error')}")

# ----------------------------------------------------------- Main Settings Dialog

class PetSettingsDialog(QDialog):
    def __init__(self, config, engine=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pet Settings")
        self.setMinimumWidth(480)
        self.config = config
        self.engine = engine

        # Setup Ollama client
        self.ollama_client = OllamaClient()
        self.model_manager = ModelManager(self.ollama_client)
        self.benchmark_service = BenchmarkService(self.ollama_client)

        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # Tab 1: General
        self.general_tab = QWidget()
        self._setup_general_tab()
        self.tabs.addTab(self.general_tab, "General")

        # Tab 2: AI Performance
        self.ai_tab = QWidget()
        self._setup_ai_tab()
        self.tabs.addTab(self.ai_tab, "AI Performance")

        self.layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.on_accept)
        buttons.rejected.connect(self.reject)
        self.layout.addWidget(buttons)

    def _setup_general_tab(self):
        layout = QVBoxLayout(self.general_tab)
        form = QFormLayout()

        self._color = QColor(self.config.get("color") or DEFAULT_COLOR)
        self._name = QLineEdit(self.config.get("name", "Pip"))

        self._color_btn = QPushButton()
        self._color_btn.clicked.connect(self._pick_color)
        self._update_color_btn()

        self._traits = QLineEdit(", ".join(self.config.get("personality_traits", [])))
        self._traits.setPlaceholderText("curious, goofy, mischievous")

        self._prompt = QTextEdit(self.config.get("initial_prompt", ""))
        self._prompt.setPlaceholderText(
            "Extra guidance for the pet's personality/behavior (optional)..."
        )
        self._prompt.setFixedHeight(80)

        self._move_freq = QComboBox()
        for key, label in MOVE_FREQUENCY_LABELS:
            self._move_freq.addItem(label, key)
        self._select_combo(self._move_freq, self.config.get("move_frequency", "normal"))

        self._msg_freq = QComboBox()
        for key, label in MESSAGE_FREQUENCY_LABELS:
            self._msg_freq.addItem(label, key)
        self._select_combo(self._msg_freq, self.config.get("message_frequency", "normal"))

        self._sleep_after = QSpinBox()
        self._sleep_after.setRange(30, 3600)
        self._sleep_after.setSuffix(" s")
        self._sleep_after.setValue(int(self.config.get("sleep_after", 120)))

        self._keystroke_commentary = QCheckBox("Occasionally comment on what I'm typing")
        self._keystroke_commentary.setChecked(
            bool(self.config.get("keystroke_commentary", False))
        )

        self._stay_still = QCheckBox("Stay in one place (no random movement)")
        self._stay_still.setChecked(
            bool(self.config.get("stay_still", False))
        )

        keystroke_note = QLabel(
            "Off by default — nothing is captured unless this is checked. "
            "When ON, the pet occasionally glances at a few recent "
            "keystrokes to react to the vibe of what you're typing (e.g. "
            "venting in an email). We are NOT recording, storing, or "
            "logging keystrokes anywhere — they live in a tiny in-memory "
            "buffer that's wiped the instant it's used. Nothing is ever written to disk."
        )
        keystroke_note.setWordWrap(True)
        keystroke_note.setStyleSheet("color: #666; font-size: 11px;")

        form.addRow("Name", self._name)
        form.addRow("Color", self._color_btn)
        form.addRow("Personality traits", self._traits)
        form.addRow("Initial prompt", self._prompt)
        form.addRow("Movement frequency", self._move_freq)
        form.addRow("Message frequency", self._msg_freq)
        form.addRow("Nap after (idle seconds)", self._sleep_after)
        form.addRow(self._keystroke_commentary)
        form.addRow(keystroke_note)
        form.addRow(self._stay_still)

        layout.addLayout(form)

    def _setup_ai_tab(self):
        layout = QVBoxLayout(self.ai_tab)
        
        # Load active performance state from engine
        self.perf_state = {
            "selectedMode": "auto",
            "resolvedMode": "low",
            "recommendedMode": "low",
            "hardwareSummary": {},
            "benchmarkResults": {},
            "benchmarkTimestamp": None,
            "visionPreference": True,
            "keepAlivePreference": "default",
            "warningAcknowledgements": []
        }
        if self.engine and "performance" in self.engine.state:
            self.perf_state.update(self.engine.state["performance"])

        # 1. Mode selection dropdown
        mode_select_layout = QHBoxLayout()
        mode_select_layout.addWidget(QLabel("Performance Tier:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Automatic (Recommended)", "auto")
        self.mode_combo.addItem("Low (2B CPU-optimized)", "low")
        self.mode_combo.addItem("Medium (2B GPU-accelerated)", "medium")
        self.mode_combo.addItem("High (4B GPU-preferred)", "high")
        self.mode_combo.addItem("Extreme (12B High-end GPU)", "extreme")
        self.mode_combo.addItem("Engine Only (Disable local AI)", "engine_only")
        
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_select_layout.addWidget(self.mode_combo)
        layout.addLayout(mode_select_layout)

        # 2. Details Box
        self.details_group = QGroupBox("Selected Tier Details")
        details_layout = QVBoxLayout(self.details_group)
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet("color: #444; font-size: 12px;")
        details_layout.addWidget(self.details_label)
        layout.addWidget(self.details_group)

        # 3. Exceed Warning Alert
        self.warning_label = QLabel("⚠️ Warning: Exceeds recommended system limits. Exceeding tier targets may freeze your system.")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 11px;")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        self.confirm_checkbox = QCheckBox("I acknowledge that running this mode exceeds recommendations and may degrade performance.")
        self.confirm_checkbox.setVisible(False)
        layout.addWidget(self.confirm_checkbox)

        # 4. Custom settings group
        custom_group = QGroupBox("AI Preferences")
        custom_layout = QFormLayout(custom_group)
        self.vision_checkbox = QCheckBox("Enable screen image analysis (Vision)")
        self.vision_checkbox.setChecked(self.perf_state.get("visionPreference", True))
        custom_layout.addRow(self.vision_checkbox)

        self.keepalive_combo = QComboBox()
        self.keepalive_combo.addItem("Default (keep model in memory per tier config)", "default")
        self.keepalive_combo.addItem("Aggressive Unloading (unload immediately to free memory)", "unload_immediate")
        self._select_combo(self.keepalive_combo, self.perf_state.get("keepAlivePreference", "default"))
        custom_layout.addRow("Keep-alive Policy:", self.keepalive_combo)
        layout.addWidget(custom_group)

        # 5. Diagnostics group
        diag_group = QGroupBox("System Diagnostics & Health")
        diag_layout = QVBoxLayout(diag_group)
        self.diag_info_label = QLabel("Detecting hardware status...")
        self.diag_info_label.setWordWrap(True)
        self.diag_info_label.setStyleSheet("font-family: monospace; font-size: 11px;")
        diag_layout.addWidget(self.diag_info_label)

        diag_btns = QHBoxLayout()
        self.btn_run_diagnostic = QPushButton("Re-run Benchmark")
        self.btn_run_diagnostic.clicked.connect(self.run_diagnostic_and_benchmark)
        self.btn_copy_diag = QPushButton("Copy Diagnostics")
        self.btn_copy_diag.clicked.connect(self.copy_diagnostics_to_clipboard)
        diag_btns.addWidget(self.btn_run_diagnostic)
        diag_btns.addWidget(self.btn_copy_diag)
        diag_layout.addLayout(diag_btns)
        layout.addWidget(diag_group)

        # Select currently stored mode
        self._select_combo(self.mode_combo, self.perf_state.get("selectedMode", "auto"))
        self.update_diag_display()

    @staticmethod
    def _select_combo(combo, key):
        idx = combo.findData(key)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _pick_color(self):
        color = QColorDialog.getColor(self._color, self, "Pick pet color")
        if color.isValid():
            self._color = color
            self._update_color_btn()

    def _update_color_btn(self):
        self._color_btn.setText(self._color.name())
        self._color_btn.setStyleSheet(
            f"background-color: {self._color.name()}; color: #222;"
        )

    def on_mode_changed(self, index):
        mode_id = self.mode_combo.currentData()
        rec_mode = self.perf_state.get("recommendedMode", "low")
        
        # Determine actual mode to describe
        target_mode = mode_id
        if mode_id == "auto":
            target_mode = rec_mode

        if target_mode == "engine_only":
            self.details_label.setText(
                "<b>Engine Only Fallback</b><br/>"
                "Local AI generation is completely disabled. Pip behaves according to the "
                "deterministic engine rules using pre-written canned lines. Minimal system footprint."
            )
            self.warning_label.setVisible(False)
            self.confirm_checkbox.setVisible(False)
            return

        cfg = PERFORMANCE_MODES.get(target_mode)
        if cfg:
            text = (
                f"<b>Model:</b> {cfg['model']}<br/>"
                f"<b>RAM Required:</b> {cfg['minimumRamGb']:.1f} GB min ({cfg['preferredRamGb']:.1f} GB preferred)<br/>"
                f"<b>GPU/VRAM Required:</b> "
                f"{'GPU Recommended' if cfg['minimumVramGb'] > 0 else 'CPU execution supported'}"
                f"{f' ({cfg['minimumVramGb']:.1f} GB min VRAM)' if cfg['minimumVramGb'] > 0 else ''}<br/>"
                f"<b>Vision (Screen Analysis):</b> {'Supported' if cfg['visionEnabled'] else 'Unsupported'}<br/>"
                f"<b>Keep-alive:</b> {cfg['keepAlive']}<br/>"
                f"<b>Description:</b> "
            )
            if target_mode == "low":
                text += "Extremely lightweight. Perfect for laptops, uses only CPU. Vision disabled."
            elif target_mode == "medium":
                text += "Balanced. Uses GPU if available, falls back to CPU if needed. Handles text and vision."
            elif target_mode == "high":
                text += "Higher quality creative text. Requires dedicated GPU acceleration."
            elif target_mode == "extreme":
                text += "Full creative capabilities. Requires high-end system with substantial VRAM."
                
            self.details_label.setText(text)

        # Check if selected mode exceeds recommended mode
        tiers_order = ["engine_only", "low", "medium", "high", "extreme"]
        try:
            sel_idx = tiers_order.index(target_mode)
            rec_idx = tiers_order.index(rec_mode)
        except ValueError:
            sel_idx = 0
            rec_idx = 0

        if sel_idx > rec_idx:
            self.warning_label.setVisible(True)
            self.confirm_checkbox.setVisible(True)
            # Checked if already acknowledged in perf_state
            self.confirm_checkbox.setChecked(target_mode in self.perf_state.get("warningAcknowledgements", []))
        else:
            self.warning_label.setVisible(False)
            self.confirm_checkbox.setVisible(False)

    def run_diagnostic_and_benchmark(self):
        """Re-run hardware detection and benchmark the currently resolved model."""
        self.btn_run_diagnostic.setEnabled(False)
        self.diag_info_label.setText("Running full hardware and backend diagnostic...")
        QGuiApplication.processEvents()

        # 1. Detect Hardware
        hw = detect_hardware()
        rec = recommend_mode_static(hw)
        self.perf_state["recommendedMode"] = rec
        self.perf_state["hardwareSummary"] = hw
        
        # 2. Check Ollama version
        ver = self.ollama_client.get_version()
        self.perf_state["ollamaVersion"] = ver

        # 3. Determine model to benchmark
        mode_id = self.mode_combo.currentData()
        target_mode = mode_id if mode_id != "auto" else rec
        
        if target_mode == "engine_only":
            QMessageBox.information(self, "Diagnostics Complete", "Diagnostics complete. Engine-only mode selected, skipping benchmark.")
            self.update_diag_display()
            self.btn_run_diagnostic.setEnabled(True)
            return

        cfg = PERFORMANCE_MODES.get(target_mode)
        model_name = cfg["model"] if cfg else None

        if not model_name:
            QMessageBox.warning(self, "Diagnostics Error", "Could not resolve model for benchmarking.")
            self.btn_run_diagnostic.setEnabled(True)
            return

        # Check if model is downloaded
        if not self.ollama_client.is_model_installed(model_name):
            dl = QMessageBox.question(
                self,
                "Model Not Downloaded",
                f"The model for the resolved tier ({model_name}) is not downloaded.\n"
                f"Do you want to download it now to run the benchmark?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if dl == QMessageBox.StandardButton.Yes:
                # Disk space check
                if not self.model_manager.check_disk_space_for_model(target_mode):
                    QMessageBox.warning(self, "Disk Space Warning", "You may not have enough free disk space. Attempting download anyway.")
                
                dlg = AIDownloadDialog(self.model_manager, model_name, self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    self.update_diag_display()
                    self.btn_run_diagnostic.setEnabled(True)
                    return
            else:
                self.update_diag_display()
                self.btn_run_diagnostic.setEnabled(True)
                return

        # Run Benchmark
        bench_dlg = BenchmarkDialog(self.benchmark_service, model_name, self)
        if bench_dlg.exec() == QDialog.DialogCode.Accepted and bench_dlg.result:
            res = bench_dlg.result
            self.perf_state["benchmarkResults"][target_mode] = res
            self.perf_state["benchmarkTimestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            # Save resolution backend
            if res.get("classification") == "failed":
                QMessageBox.warning(
                    self,
                    "Benchmark Warning",
                    f"Benchmark classified this tier as FAILED (latency: {res.get('warm_latency', 0.0):.2f}s). "
                    "You may experience sluggishness. We recommend a lower performance tier."
                )

        self.update_diag_display()
        self.btn_run_diagnostic.setEnabled(True)

    def update_diag_display(self):
        hw = self.perf_state.get("hardwareSummary") or {}
        if not hw:
            # First time load, detect statically
            hw = detect_hardware()
            self.perf_state["hardwareSummary"] = hw
            self.perf_state["recommendedMode"] = recommend_mode_static(hw)
            self.perf_state["ollamaVersion"] = self.ollama_client.get_version()

        rec = self.perf_state.get("recommendedMode", "low")
        ollama_ver = self.perf_state.get("ollamaVersion", "unknown")
        
        mode_id = self.mode_combo.currentData()
        target_mode = mode_id if mode_id != "auto" else rec
        
        bench = self.perf_state.get("benchmarkResults", {}).get(target_mode, {})

        text = (
            f"CPU: {hw.get('cpu_model', 'Unknown')}\n"
            f"System RAM: {hw.get('system_ram', 0.0):.1f} GB\n"
            f"GPU: {hw.get('gpu_model', 'None')} ({hw.get('gpu_vram_total', 0.0):.1f} GB VRAM)\n"
            f"Disk Free: {hw.get('free_disk_space', 0.0):.1f} GB\n"
            f"Ollama Version: {ollama_ver}\n"
            f"Recommended Tier: {rec.upper()}\n"
        )
        if bench:
            text += (
                f"\n--- Active Tier Benchmark ---\n"
                f"Classification: {bench.get('classification', 'untested').upper()}\n"
                f"Warm Latency: {bench.get('warm_latency', 0.0):.2f}s\n"
                f"Generation Speed: {bench.get('gen_tokens_sec', 0.0):.1f} tok/sec\n"
                f"VRAM Allocated: {bench.get('vram_allocated_gb', 0.0):.1f} GB\n"
                f"Backend: {bench.get('backend', 'cpu').upper()}"
            )
        else:
            text += "\nNo benchmark result for active tier yet. Run benchmark to verify."

        self.diag_info_label.setText(text)
        self.on_mode_changed(self.mode_combo.currentIndex())

    def copy_diagnostics_to_clipboard(self):
        text = "=== Squish-Mate Diagnostic Summary ===\n"
        hw = self.perf_state.get("hardwareSummary") or {}
        text += f"OS: {platform.system()} ({platform.release()})\n"
        text += f"CPU: {hw.get('cpu_model', 'Unknown')} ({hw.get('cpu_cores_logical', 2)} logical cores)\n"
        text += f"System RAM: {hw.get('system_ram', 0.0):.1f} GB\n"
        text += f"GPU: {hw.get('gpu_model', 'None')} ({hw.get('gpu_vram_total', 0.0):.1f} GB VRAM)\n"
        text += f"Disk Free Space: {hw.get('free_disk_space', 0.0):.1f} GB\n"
        text += f"Ollama Version: {self.perf_state.get('ollamaVersion', 'unknown')}\n"
        text += f"Recommended Tier: {self.perf_state.get('recommendedMode', 'low')}\n"
        text += f"Selected Mode: {self.perf_state.get('selectedMode', 'auto')} (Resolved: {self.perf_state.get('resolvedMode', 'low')})\n"
        
        benchmarks = self.perf_state.get("benchmarkResults", {})
        if benchmarks:
            text += "\n--- Benchmarks ---\n"
            for mode, b in benchmarks.items():
                text += (
                    f"Tier: {mode}\n"
                    f"  Classification: {b.get('classification')}\n"
                    f"  Warm Latency: {b.get('warm_latency', 0.0):.2f}s\n"
                    f"  Gen Speed: {b.get('gen_tokens_sec', 0.0):.1f} tok/s\n"
                    f"  Offload Ratio: {b.get('offload_ratio', 0.0)*100:.1f}%\n"
                    f"  Backend: {b.get('backend')}\n"
                )
        text += "======================================"
        
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Diagnostics Copied", "Diagnostic payload copied to clipboard.")

    def on_accept(self):
        mode_id = self.mode_combo.currentData()
        rec_mode = self.perf_state.get("recommendedMode", "low")
        
        target_mode = mode_id if mode_id != "auto" else rec_mode

        # Check if selected exceeds recommended
        tiers_order = ["engine_only", "low", "medium", "high", "extreme"]
        try:
            sel_idx = tiers_order.index(target_mode)
            rec_idx = tiers_order.index(rec_mode)
        except ValueError:
            sel_idx = 0
            rec_idx = 0

        if sel_idx > rec_idx:
            if not self.confirm_checkbox.isChecked():
                QMessageBox.warning(
                    self,
                    "Warning Checkbox Required",
                    "Please check the confirmation box acknowledging that running this performance tier exceeds recommended system resources."
                )
                return
            # Add to warningAcknowledgements
            warns = self.perf_state.get("warningAcknowledgements", [])
            if target_mode not in warns:
                warns.append(target_mode)
            self.perf_state["warningAcknowledgements"] = warns

        # Handle Model Download Prompt if not downloaded
        if target_mode != "engine_only":
            cfg = PERFORMANCE_MODES.get(target_mode)
            model_name = cfg["model"] if cfg else None
            if model_name and not self.ollama_client.is_model_installed(model_name):
                dl = QMessageBox.question(
                    self,
                    "Model Required",
                    f"The model for the selected tier ({model_name}) is not downloaded yet.\n"
                    "Would you like to download it now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if dl == QMessageBox.StandardButton.Yes:
                    # Disk space check
                    if not self.model_manager.check_disk_space_for_model(target_mode):
                        QMessageBox.warning(self, "Disk Space Warning", "You may not have enough free disk space. Attempting download anyway.")
                    
                    dlg = AIDownloadDialog(self.model_manager, model_name, self)
                    if dlg.exec() != QDialog.DialogCode.Accepted:
                        # User cancelled or failed
                        return
                else:
                    QMessageBox.warning(
                        self,
                        "Inference Warning",
                        "The model is not downloaded. Pip will run in engine-only fallback until the model is downloaded."
                    )

        # Update final perf_state fields
        self.perf_state["selectedMode"] = mode_id
        self.perf_state["visionPreference"] = self.vision_checkbox.isChecked()
        self.perf_state["keepAlivePreference"] = self.keepalive_combo.currentData()
        
        # Save last known working tier if resolved isn't engine_only and succeeds
        if target_mode != "engine_only" and self.ollama_client.is_model_installed(PERFORMANCE_MODES[target_mode]["model"]):
            self.perf_state["lastKnownWorkingTier"] = target_mode

        self.accept()

    def get_values(self):
        traits = [t.strip() for t in self._traits.text().split(",") if t.strip()]
        return {
            "general": {
                "name": self._name.text().strip() or "Pip",
                "color": self._color.name(),
                "personality_traits": traits,
                "initial_prompt": self._prompt.toPlainText().strip(),
                "move_frequency": self._move_freq.currentData(),
                "message_frequency": self._msg_freq.currentData(),
                "sleep_after": self._sleep_after.value(),
                "keystroke_commentary": self._keystroke_commentary.isChecked(),
                "stay_still": self._stay_still.isChecked(),
            },
            "performance": self.perf_state
        }
