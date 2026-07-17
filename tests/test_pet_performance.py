#!/usr/bin/env python3
"""
Unit tests for the Adaptive AI Performance System (core/pet_performance.py).
"""

import unittest
from unittest.mock import patch, MagicMock
import time
import os
import sys

# Add project path to python imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pet_performance import (
    PERFORMANCE_MODES,
    detect_hardware,
    recommend_mode_static,
    BoundedRequestQueue,
    RuntimeAdaptationMonitor,
    OllamaClient,
    ModelManager
)
from core.pet_engine import PetEngine


class TestPetPerformance(unittest.TestCase):
    def setUp(self):
        # Create a mock engine with default performance state
        self.test_state_path = os.path.expanduser("~/.config/squish-mate/pet_state_perf_test.json")
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)
        self.engine = PetEngine(state_path=self.test_state_path)
        
        # Verify performance state is initialized
        self.assertIn("performance", self.engine.state)

    def tearDown(self):
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)
        backup_path = self.test_state_path + ".bak"
        if os.path.exists(backup_path):
            os.remove(backup_path)

    @patch("psutil.virtual_memory")
    @patch("psutil.cpu_count")
    @patch("shutil.disk_usage")
    @patch("subprocess.run")
    def test_hardware_detection(self, mock_run, mock_disk, mock_cpu, mock_mem):
        # Mock 16GB system RAM
        mock_mem_obj = MagicMock()
        mock_mem_obj.total = 16 * 1024 * 1024 * 1024
        mock_mem.return_value = mock_mem_obj
        
        mock_cpu.return_value = 8
        
        # Mock 50GB disk free
        mock_disk_obj = MagicMock()
        mock_disk_obj.free = 50 * 1024 * 1024 * 1024
        mock_disk.return_value = mock_disk_obj
        
        # Mock no GPU found in lshw/nvidia-smi
        mock_proc = MagicMock()
        mock_proc.return_value.stdout = ""
        mock_run.return_value = mock_proc

        hw = detect_hardware()
        self.assertEqual(hw["system_ram"], 16.0)
        self.assertEqual(hw["cpu_cores_logical"], 8)
        self.assertEqual(hw["gpu_model"], "unknown")
        self.assertEqual(hw["gpu_vram_total"], 0.0)
        self.assertGreaterEqual(hw["free_disk_space"], 50.0)

    def test_static_recommendation(self):
        # Case 1: Low RAM
        hw_low = {
            "system_ram": 6.0,
            "gpu_vram_total": 0.0,
            "free_disk_space": 10.0,
            "battery_critical": False,
            "is_low_power_cpu": False,
            "gpu_vendor": "unknown",
            "is_unified_memory": False
        }
        self.assertEqual(recommend_mode_static(hw_low), "low")

        # Case 2: Good RAM but no GPU/unknown GPU
        hw_med_cpu = {
            "system_ram": 16.0,
            "gpu_vram_total": 0.0,
            "free_disk_space": 20.0,
            "battery_critical": False,
            "is_low_power_cpu": False,
            "gpu_vendor": "unknown",
            "is_unified_memory": False
        }
        self.assertEqual(recommend_mode_static(hw_med_cpu), "low")

        # Case 3: Medium GPU & good RAM
        hw_med_gpu = {
            "system_ram": 16.0,
            "gpu_vram_total": 4.5,
            "free_disk_space": 20.0,
            "battery_critical": False,
            "is_low_power_cpu": False,
            "gpu_vendor": "nvidia",
            "is_unified_memory": False
        }
        self.assertEqual(recommend_mode_static(hw_med_gpu), "medium")

        # Case 4: High GPU & high RAM
        hw_high = {
            "system_ram": 24.0,
            "gpu_vram_total": 8.0,
            "free_disk_space": 40.0,
            "battery_critical": False,
            "is_low_power_cpu": False,
            "gpu_vendor": "nvidia",
            "is_unified_memory": False
        }
        self.assertEqual(recommend_mode_static(hw_high), "high")

    def test_bounded_request_queue(self):
        queue = BoundedRequestQueue(maxsize=3)
        
        # Add ambient tasks (putting task2 should deduplicate and remove task1)
        task1 = {"type": "ambient_comment", "timestamp": time.time(), "task": lambda: None}
        task2 = {"type": "ambient_comment", "timestamp": time.time(), "task": lambda: None}
        task3 = {"type": "direct_message", "timestamp": time.time(), "task": lambda: None}
        
        queue.put(task1)
        self.assertEqual(queue.size(), 1)
        
        queue.put(task2)
        # Deduplication of ambient comments keeps only the latest one
        self.assertEqual(queue.size(), 1)
        
        queue.put(task3)
        self.assertEqual(queue.size(), 2)
        
        # Test prioritizing direct messages (gets returned first)
        res1 = queue.get()
        self.assertEqual(res1["type"], "direct_message")
        
        res2 = queue.get()
        self.assertEqual(res2["type"], "ambient_comment")

    @patch("psutil.virtual_memory")
    @patch("psutil.sensors_battery")
    def test_runtime_adaptation_monitor(self, mock_battery, mock_mem):
        # Setup initial state
        with self.engine.lock:
            self.engine.state["performance"]["selectedMode"] = "auto"
            self.engine.state["performance"]["recommendedMode"] = "medium"
            self.engine.state["performance"]["resolvedMode"] = "medium"
        
        mock_client = MagicMock()
        monitor = RuntimeAdaptationMonitor(self.engine, mock_client)
        
        # Test Case 1: Safe memory and battery
        mock_mem_obj = MagicMock()
        mock_mem_obj.percent = 50.0  # 50% used
        mock_mem_obj.available = 8.0 * (1024**3)
        mock_mem.return_value = mock_mem_obj
        
        mock_bat_obj = MagicMock()
        mock_bat_obj.percent = 80.0
        mock_bat_obj.power_plugged = True
        mock_battery.return_value = mock_bat_obj
        
        monitor.apply_temporary_adaptation()
        
        # Mode should still resolve to recommended
        self.assertEqual(self.engine.state["performance"]["resolvedMode"], "medium")
        self.assertIsNone(self.engine.state["performance"]["temporaryFallbackState"])
        
        # Test Case 2: Battery critical (5% left, not plugged in)
        mock_bat_obj.percent = 5.0
        mock_bat_obj.power_plugged = False
        
        monitor.apply_temporary_adaptation()
        
        # Mode should fall back to engine_only
        self.assertEqual(self.engine.state["performance"]["resolvedMode"], "engine_only")
        self.assertEqual(self.engine.state["performance"]["temporaryFallbackState"], "critical battery")

        # Test Case 3: Out-of-memory pressure (less than 2.0 GB RAM available)
        mock_bat_obj.percent = 100.0
        mock_bat_obj.power_plugged = True
        mock_mem_obj.percent = 96.0
        mock_mem_obj.available = 1.0 * (1024**3) # 1GB available
        
        monitor.apply_temporary_adaptation()
        
        # Mode should fall back to low (since recommended was medium, downshifts to low;
        # wait! Let's check:
        # if current_mode == "medium", resolvedMode = "low".
        # then low_memory is True, but current_mode was medium, not low, so it goes to "low".
        # Let's check our implementation:
        # current_mode = "medium" -> resolves to "low".
        # Let's assert:
        self.assertEqual(self.engine.state["performance"]["resolvedMode"], "low")
        self.assertEqual(self.engine.state["performance"]["temporaryFallbackState"], "low available memory")


if __name__ == "__main__":
    unittest.main()
