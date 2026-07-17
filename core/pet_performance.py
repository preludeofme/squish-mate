#!/usr/bin/env python3
"""
pet_performance.py — Centralized performance-mode registry, hardware detection,
Ollama communication, benchmarking, model installation management, and runtime resource adaptation.
"""

import os
import re
import sys
import json
import time
import shutil
import hashlib
import platform
import threading
import subprocess
import logging
from collections import deque

try:
    import psutil
except ImportError:
    psutil = None

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger("PipPerformance")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[PipPerformance] %(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(ch)

# Authoritative Performance Tiers Registry
PERFORMANCE_MODES = {
    "low": {
        "id": "low",
        "displayName": "Low",
        "model": "gemma4:e2b",
        "model_family": "gemma-4-E2B",
        "accelerationPolicy": "cpu_preferred",
        "minimumRamGb": 8.0,
        "preferredRamGb": 12.0,
        "minimumVramGb": 0.0,
        "preferredVramGb": 0.0,
        "minimumUnifiedMemoryGb": 0.0,
        "preferredUnifiedMemoryGb": 0.0,
        "minimumFreeDiskGb": 3.6, # model size (1.6G) + 2GB safety
        "numCtx": 2048,
        "numPredict": 64,
        "keepAlive": "30s",
        "visionEnabled": False,
        "maximumImageDimension": 0,
        "maximumConcurrentRequests": 1,
        "supportsCpuFallback": True,
        "options": {
            "num_ctx": 2048,
            "num_predict": 64,
            "temperature": 0.72,
            "top_k": 40,
            "top_p": 0.9,
            "min_p": 0.05,
            "repeat_penalty": 1.12,
            "repeat_last_n": 128
        }
    },
    "medium": {
        "id": "medium",
        "displayName": "Medium",
        "model": "gemma4:e2b",
        "model_family": "gemma-4-E2B",
        "accelerationPolicy": "auto",
        "minimumRamGb": 12.0,
        "preferredRamGb": 16.0,
        "minimumVramGb": 0.0,
        "preferredVramGb": 4.0,
        "minimumUnifiedMemoryGb": 12.0,
        "preferredUnifiedMemoryGb": 16.0,
        "minimumFreeDiskGb": 4.6, # model size (1.6G) + 3GB safety
        "numCtx": 3072,
        "numPredict": 64,
        "keepAlive": "2m",
        "visionEnabled": True,
        "maximumImageDimension": 640,
        "maximumConcurrentRequests": 1,
        "supportsCpuFallback": True,
        "options": {
            "num_ctx": 3072,
            "num_predict": 64,
            "temperature": 0.74,
            "top_k": 40,
            "top_p": 0.9,
            "min_p": 0.05,
            "repeat_penalty": 1.12,
            "repeat_last_n": 128
        }
    },
    "high": {
        "id": "high",
        "displayName": "High",
        "model": "gemma4:e4b",
        "model_family": "gemma-4-E4B",
        "accelerationPolicy": "gpu_preferred",
        "minimumRamGb": 16.0,
        "preferredRamGb": 24.0,
        "minimumVramGb": 6.0,
        "preferredVramGb": 8.0,
        "minimumUnifiedMemoryGb": 16.0,
        "preferredUnifiedMemoryGb": 24.0,
        "minimumFreeDiskGb": 6.8, # model size (2.8G) + 4GB safety
        "numCtx": 4096,
        "numPredict": 64,
        "keepAlive": "5m",
        "visionEnabled": True,
        "maximumImageDimension": 768,
        "maximumConcurrentRequests": 1,
        "supportsCpuFallback": True,
        "options": {
            "num_ctx": 4096,
            "num_predict": 64,
            "temperature": 0.76,
            "top_k": 40,
            "top_p": 0.9,
            "min_p": 0.05,
            "repeat_penalty": 1.12,
            "repeat_last_n": 192
        }
    },
    "extreme": {
        "id": "extreme",
        "displayName": "Extreme",
        "model": "gemma4:12b",
        "model_family": "gemma-4-12B",
        "accelerationPolicy": "gpu_strongly_preferred",
        "minimumRamGb": 32.0,
        "preferredRamGb": 32.0,
        "minimumVramGb": 12.0,
        "preferredVramGb": 16.0,
        "minimumUnifiedMemoryGb": 24.0,
        "preferredUnifiedMemoryGb": 32.0,
        "minimumFreeDiskGb": 13.6, # model size (7.6G) + 6GB safety
        "numCtx": 4096,
        "numPredict": 72,
        "keepAlive": "10m",
        "visionEnabled": True,
        "maximumImageDimension": 960,
        "maximumConcurrentRequests": 1,
        "supportsCpuFallback": True,
        "options": {
            "num_ctx": 4096,
            "num_predict": 72,
            "temperature": 0.76,
            "top_k": 40,
            "top_p": 0.9,
            "min_p": 0.05,
            "repeat_penalty": 1.12,
            "repeat_last_n": 192
        }
    }
}

# ---------------------------------------------------------------- Hardware Detection

def get_cpu_model():
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line or "Model" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            brand = winreg.QueryValueEx(key, "ProcessorNameString")[0]
            return brand.strip()
        except Exception:
            pass
    return platform.processor() or "Unknown CPU"

def check_low_power_cpu(cpu_model):
    cpu_model_lower = cpu_model.lower()
    if any(x in cpu_model_lower for x in ("atom", "celeron", "pentium", "n-series", "silvermont", "goldmont")):
        return True
    # Intel Core mobile low power suffixes (e.g. U, Y)
    m_intel = re.search(r'i[3579]-\d{3,5}([uy])', cpu_model_lower)
    if m_intel:
        return True
    # AMD Ryzen mobile low power suffixes
    m_amd = re.search(r'ryzen\s+[3579]\s+\d{3,5}([uy])', cpu_model_lower)
    if m_amd:
        return True
    return False

def get_gpu_info():
    gpu_vendor = "unknown"
    gpu_model = "unknown"
    gpu_vram_total = 0.0
    gpu_vram_free = 0.0
    is_unified = False

    # Check macOS Apple Silicon
    if platform.system() == "Darwin":
        try:
            # Check if apple silicon or intel mac
            brand = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
            if "Apple" in brand:
                is_unified = True
                gpu_vendor = "apple"
                gpu_model = brand
                if psutil:
                    gpu_vram_total = psutil.virtual_memory().total / (1024**3)
                    gpu_vram_free = psutil.virtual_memory().available / (1024**3)
                return gpu_vendor, gpu_model, gpu_vram_total, gpu_vram_free, is_unified
        except Exception:
            pass

    # Check NVIDIA via nvidia-smi
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            out = subprocess.check_output([
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits"
            ]).decode().strip()
            if out:
                parts = out.split(",")
                if len(parts) >= 3:
                    gpu_vendor = "nvidia"
                    gpu_model = parts[0].strip()
                    gpu_vram_total = float(parts[1].strip()) / 1024.0 # Convert MB to GB
                    gpu_vram_free = float(parts[2].strip()) / 1024.0
                    return gpu_vendor, gpu_model, gpu_vram_total, gpu_vram_free, is_unified
        except Exception:
            pass

    # Check AMD ROCm / Linux sysfs
    if platform.system() == "Linux":
        rocminfo = shutil.which("rocminfo")
        if rocminfo:
            try:
                out = subprocess.check_output([rocminfo]).decode()
                m = re.search(r'Name:\s+(gfx\d+)', out)
                if m:
                    gpu_vendor = "amd"
                    gpu_model = m.group(1)
                    # Check rocm-smi
                    rocm_smi = shutil.which("rocm-smi")
                    if rocm_smi:
                        smi_out = subprocess.check_output([rocm_smi, "--showmeminfo", "vram"]).decode()
                        m_mem = re.search(r'VRAM Total Memory \(B\):\s+(\d+)', smi_out)
                        if m_mem:
                            gpu_vram_total = float(m_mem.group(1)) / (1024**3)
                        m_free = re.search(r'VRAM Total Used Memory \(B\):\s+(\d+)', smi_out)
                        if m_free and m_mem:
                            gpu_vram_free = (float(m_mem.group(1)) - float(m_free.group(1))) / (1024**3)
                    
                    if gpu_vram_total == 0.0:
                        # Fallback to sysfs memory info if available
                        vram_path = "/sys/class/drm/card0/device/mem_info_vram_total"
                        vram_used_path = "/sys/class/drm/card0/device/mem_info_vram_used"
                        if os.path.exists(vram_path) and os.path.exists(vram_used_path):
                            with open(vram_path, "r") as f:
                                gpu_vram_total = float(f.read().strip()) / (1024**3)
                            with open(vram_used_path, "r") as f:
                                used = float(f.read().strip()) / (1024**3)
                                gpu_vram_free = max(0.0, gpu_vram_total - used)
                    return gpu_vendor, gpu_model, gpu_vram_total, gpu_vram_free, is_unified
            except Exception:
                pass

        # Try lspci check
        lspci = shutil.which("lspci")
        if lspci:
            try:
                out = subprocess.check_output([lspci]).decode()
                for line in out.splitlines():
                    if "VGA compatible controller" in line or "3D controller" in line:
                        if "NVIDIA" in line:
                            gpu_vendor = "nvidia"
                            gpu_model = line.split(":")[-1].strip()
                        elif "AMD" in line or "ATI" in line or "Radeon" in line:
                            gpu_vendor = "amd"
                            gpu_model = line.split(":")[-1].strip()
                        elif "Intel" in line:
                            gpu_vendor = "intel"
                            gpu_model = line.split(":")[-1].strip()
            except Exception:
                pass

    return gpu_vendor, gpu_model, gpu_vram_total, gpu_vram_free, is_unified

def get_battery_info():
    on_battery = False
    battery_saver = False
    if psutil:
        try:
            bat = psutil.sensors_battery()
            if bat is not None:
                on_battery = not bat.power_plugged
                if on_battery and bat.percent < 20:
                    battery_saver = True
        except Exception:
            pass

    if platform.system() == "Linux":
        try:
            out = subprocess.check_output(["powerprofilesctl", "get"], stderr=subprocess.DEVNULL).decode().strip()
            if out == "power-saver":
                battery_saver = True
        except Exception:
            pass

    return on_battery, battery_saver

def detect_hardware():
    """Detect detailed system hardware specifications cross-platform."""
    hw = {
        "os": platform.system(),
        "os_version": platform.release(),
        "cpu_arch": platform.machine(),
        "system_ram": 8.0,
        "available_ram": 4.0,
        "cpu_model": "Unknown CPU",
        "cpu_cores_physical": 2,
        "cpu_cores_logical": 2,
        "is_low_power_cpu": False,
        "gpu_vendor": "unknown",
        "gpu_model": "unknown",
        "gpu_vram_total": 0.0,
        "gpu_vram_free": 0.0,
        "is_unified_memory": False,
        "free_disk_space": 10.0,
        "on_battery": False,
        "battery_saver_active": False,
        "memory_pressure": 0.0
    }

    if psutil:
        try:
            mem = psutil.virtual_memory()
            hw["system_ram"] = mem.total / (1024**3)
            hw["available_ram"] = mem.available / (1024**3)
            hw["memory_pressure"] = mem.percent / 100.0
            
            hw["cpu_cores_physical"] = psutil.cpu_count(logical=False) or 2
            hw["cpu_cores_logical"] = psutil.cpu_count(logical=True) or 2
        except Exception:
            pass

    hw["cpu_model"] = get_cpu_model()
    hw["is_low_power_cpu"] = check_low_power_cpu(hw["cpu_model"])
    
    gpu_vendor, gpu_model, gpu_vram_total, gpu_vram_free, is_unified = get_gpu_info()
    hw["gpu_vendor"] = gpu_vendor
    hw["gpu_model"] = gpu_model
    hw["gpu_vram_total"] = gpu_vram_total
    hw["gpu_vram_free"] = gpu_vram_free
    hw["is_unified_memory"] = is_unified

    try:
        hw["free_disk_space"] = shutil.disk_usage(os.path.expanduser("~")).free / (1024**3)
    except Exception:
        pass

    on_bat, bat_save = get_battery_info()
    hw["on_battery"] = on_bat
    hw["battery_saver_active"] = bat_save

    logger.info(f"Hardware Detected: {hw['system_ram']:.1f} GB RAM, {hw['gpu_model']} ({hw['gpu_vram_total']:.1f} GB VRAM), OS: {hw['os']}")
    return hw

# -------------------------------------------------------- Recommendation Algorithm

def recommend_mode_static(hw):
    """Determine highest recommended performance tier statically based on hardware specs."""
    if hw["system_ram"] < 12.0 or hw["is_low_power_cpu"] or hw["gpu_vendor"] == "unknown":
        return "low"
        
    # High-end desktop workstation or M-series Apple Silicon
    if hw["system_ram"] >= 32.0:
        if hw["is_unified_memory"] and hw["system_ram"] >= 32.0:
            return "extreme"
        if hw["gpu_vram_total"] >= 12.0:
            return "extreme"
            
    if hw["system_ram"] >= 16.0:
        if hw["is_unified_memory"] and hw["system_ram"] >= 16.0:
            return "high"
        if hw["gpu_vram_total"] >= 6.0:
            return "high"
        return "medium"

    if hw["system_ram"] >= 12.0:
        return "medium"

    return "low"

def get_hardware_fingerprint(hw, ollama_version=""):
    data = f"{hw.get('cpu_model')}|{hw.get('system_ram'):.1f}|{hw.get('gpu_model')}|{hw.get('gpu_vram_total'):.1f}|{ollama_version}"
    return hashlib.md5(data.encode()).hexdigest()

# ------------------------------------------------------------- Ollama Interaction

class OllamaClient:
    def __init__(self, url="http://localhost:11434"):
        self.url = url.rstrip("/")

    def available(self):
        if requests is None:
            return False
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def get_version(self):
        try:
            r = requests.get(f"{self.url}/api/version", timeout=3)
            if r.status_code == 200:
                return r.json().get("version", "unknown")
        except Exception:
            pass
        return "unknown"

    def list_installed_models(self):
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=3)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def is_model_installed(self, model_name):
        installed = self.list_installed_models()
        for name in installed:
            if name == model_name:
                return True
            # Match without registry prefix or tag variations
            clean_m = model_name.split("/")[-1]
            clean_n = name.split("/")[-1]
            if clean_m == clean_n:
                return True
        return False

    def unload_model(self, model_name):
        """Unload model from Ollama memory using zero keep-alive request."""
        logger.info(f"Requesting Ollama unload for model: {model_name}")
        try:
            # Standard zero keep-alive endpoint call
            requests.post(
                f"{self.url}/api/generate",
                json={"model": model_name, "prompt": "", "keep_alive": 0},
                timeout=5
            )
            return True
        except Exception as e:
            logger.error(f"Failed to unload model: {e}")
            return False

    def get_running_model_info(self, model_name):
        """Query /api/ps to extract running details (size, VRAM size)."""
        try:
            r = requests.get(f"{self.url}/api/ps", timeout=3)
            if r.status_code == 200:
                models = r.json().get("models", [])
                for m in models:
                    if m["name"] == model_name or model_name.endswith(m["name"]) or m["name"].endswith(model_name):
                        return {
                            "size": m.get("size", 0),
                            "size_vram": m.get("size_vram", 0),
                            "context_length": m.get("context_length", 0)
                        }
        except Exception as e:
            logger.error(f"Error querying /api/ps: {e}")
        return None

# ------------------------------------------------------------- Benchmark Service

class BenchmarkService:
    def __init__(self, client):
        self.client = client

    def run_benchmark(self, model_name, progress_callback=None, cancel_event=None):
        """Runs cold and warm inference benchmarks to classify performance tier."""
        if not self.client.available():
            return {"success": False, "error": "Ollama unavailable"}

        # Validate that model is actually installed
        if not self.client.is_model_installed(model_name):
            return {"success": False, "error": "Model not installed"}

        prompt = "Context: User is editing code.\n\nReact in JSON format."
        system_prompt = "You are Pip, a tiny silly desktop pet. Output JSON."
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {
                "num_predict": 48,
                "temperature": 0.7
            }
        }

        # 1. First (potentially cold) run
        if progress_callback:
            progress_callback("Running initial inference request...")
        
        swap_start = psutil.swap_memory().used if psutil else 0
        start_time = time.time()
        
        try:
            r = requests.post(f"{self.client.url}/api/chat", json=payload, timeout=40)
            r.raise_for_status()
            initial_latency = time.time() - start_time
            initial_res = r.json()
        except Exception as e:
            return {"success": False, "error": f"Initial request failed: {e}"}

        if cancel_event and cancel_event.is_set():
            return {"success": False, "error": "Benchmark cancelled by user"}

        # 2. Second (warm) run
        if progress_callback:
            progress_callback("Running warm inference request...")
            
        start_warm = time.time()
        try:
            r_warm = requests.post(f"{self.client.url}/api/chat", json=payload, timeout=25)
            r_warm.raise_for_status()
            warm_latency = time.time() - start_warm
            warm_res = r_warm.json()
        except Exception as e:
            return {"success": False, "error": f"Warm request failed: {e}"}

        swap_end = psutil.swap_memory().used if psutil else 0
        paging_occurred = (swap_end - swap_start) > 50 * 1024 * 1024 # Swap increased by >50MB

        # Extract tokens per second
        gen_tokens_sec = 0.0
        eval_dur = warm_res.get("eval_duration", 0) / 1e9
        if eval_dur > 0:
            gen_tokens_sec = warm_res.get("eval_count", 0) / eval_dur

        prompt_tokens_sec = 0.0
        prompt_eval_dur = warm_res.get("prompt_eval_duration", 0) / 1e9
        if prompt_eval_dur > 0:
            prompt_tokens_sec = warm_res.get("prompt_eval_count", 0) / prompt_eval_dur

        content = warm_res.get("message", {}).get("content", "")
        valid_json = False
        try:
            json.loads(content)
            valid_json = True
        except Exception:
            pass

        # Query offload status from Ollama /api/ps
        offload_ratio = 1.0
        gpu_bytes = 0
        backend = "cpu"
        info = self.client.get_running_model_info(model_name)
        if info:
            size = info["size"]
            size_vram = info["size_vram"]
            gpu_bytes = size_vram
            if size > 0:
                offload_ratio = size_vram / size
            if size_vram > 0:
                backend = "gpu"

        # Classification
        classification = "failed"
        if valid_json and not paging_occurred:
            if warm_latency <= 2.5 or gen_tokens_sec >= 8.0:
                classification = "excellent"
            elif warm_latency <= 5.0 or gen_tokens_sec >= 4.0:
                classification = "good"
            elif warm_latency <= 10.0 or gen_tokens_sec >= 2.0:
                classification = "marginal"

        return {
            "success": True,
            "classification": classification,
            "cold_load_time": max(0.0, initial_latency - warm_latency),
            "warm_latency": warm_latency,
            "gen_tokens_sec": gen_tokens_sec,
            "prompt_tokens_sec": prompt_tokens_sec,
            "offload_ratio": offload_ratio,
            "gpu_offloaded_bytes": gpu_bytes,
            "backend": backend,
            "paging_occurred": paging_occurred,
            "valid_json": valid_json
        }

# ----------------------------------------------------------- Model Download Manager

class ModelManager:
    def __init__(self, client):
        self.client = client

    def check_disk_space_for_model(self, model_id):
        cfg = PERFORMANCE_MODES.get(model_id)
        if not cfg:
            return True
            
        try:
            free_gb = shutil.disk_usage(os.path.expanduser("~")).free / (1024**3)
            return free_gb >= cfg["minimumFreeDiskGb"]
        except Exception:
            return True

    def pull_model_progress(self, model_name, progress_callback, cancel_event):
        """Pulls a model from Ollama, reporting progress back to the UI dialog."""
        if not self.client.available():
            return False, "Ollama is not running"

        try:
            r = requests.post(
                f"{self.client.url}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=(15.0, 300.0)
            )
            r.raise_for_status()

            for line in r.iter_lines():
                if cancel_event.is_set():
                    r.close()
                    return False, "Download cancelled"

                if not line:
                    continue

                data = json.loads(line.decode())
                status = data.get("status", "")
                completed = data.get("completed", 0)
                total = data.get("total", 0)

                if "error" in data:
                    return False, data["error"]

                if total > 0:
                    pct = completed / total
                    progress_callback(status, pct, completed, total)
                else:
                    progress_callback(status, 0.0, 0, 0)

                if status == "success":
                    return True, "Download successful"

            return True, "Download successful"
        except Exception as e:
            return False, str(e)

# ------------------------------------------------------------- Request Queue

class BoundedRequestQueue:
    def __init__(self, maxsize=5):
        self.queue = []
        self.maxsize = maxsize
        self._lock = threading.Lock()

    def put(self, request):
        """
        Pushes a request onto the queue.
        request: {
            "type": "direct_message" | "ambient_comment" | "keystroke_commentary",
            "timestamp": float,
            "task": callable
        }
        Direct messages have priority and are placed at the front.
        Ambient comments replace existing ambient comments (deduplication of stale screen snapshots).
        """
        with self._lock:
            # If ambient comment, remove old ambient comments
            if request["type"] == "ambient_comment":
                self.queue = [r for r in self.queue if r["type"] == "direct_message"]

            # Merge duplicate tasks or enforce size limit
            if len(self.queue) >= self.maxsize:
                # Remove oldest ambient comment first
                ambients = [i for i, r in enumerate(self.queue) if r["type"] != "direct_message"]
                if ambients:
                    self.queue.pop(ambients[0])
                else:
                    self.queue.pop(0)

            # Prioritize direct messages
            if request["type"] == "direct_message":
                inserted = False
                for i, r in enumerate(self.queue):
                    if r["type"] != "direct_message":
                        self.queue.insert(i, request)
                        inserted = True
                        break
                if not inserted:
                    self.queue.append(request)
            else:
                self.queue.append(request)

    def get(self):
        with self._lock:
            if self.queue:
                return self.queue.pop(0)
            return None

    def clear(self):
        with self._lock:
            self.queue.clear()

    def size(self):
        with self._lock:
            return len(self.queue)

# ------------------------------------------------------- Runtime Adaptation Monitor

class RuntimeAdaptationMonitor:
    def __init__(self, engine, client):
        self.engine = engine
        self.client = client
        self._adaptation_lock = threading.Lock()

    def check_system_pressure(self):
        """
        Inspect available RAM, swap usage, CPU load, and battery saver status.
        Returns a dict of status flags.
        """
        pressure = {
            "low_memory": False,
            "high_cpu": False,
            "battery_saver": False,
            "battery_critical": False,
            "game_running": False,
            "needs_reduced_resources": False,
            "reason": ""
        }

        # Check battery
        on_bat, bat_save = get_battery_info()
        pressure["battery_saver"] = bat_save
        if on_bat:
            try:
                bat = psutil.sensors_battery()
                if bat and bat.percent < 10:
                    pressure["battery_critical"] = True
            except Exception:
                pass

        if psutil:
            try:
                mem = psutil.virtual_memory()
                # If less than 2.0 GB RAM available, trigger low_memory flag
                if mem.available / (1024**3) < 2.0:
                    pressure["low_memory"] = True
                
                # Check CPU load (5 second load average, or current system load)
                if psutil.cpu_percent(interval=None) > 85.0:
                    pressure["high_cpu"] = True
            except Exception:
                pass

        # Check full-screen game / heavy graphics process running
        pressure["game_running"] = self._detect_heavy_game()

        # Decide if we need to fall back to a lower resource level
        if pressure["battery_critical"]:
            pressure["needs_reduced_resources"] = True
            pressure["reason"] = "critical battery"
        elif pressure["low_memory"]:
            pressure["needs_reduced_resources"] = True
            pressure["reason"] = "low available memory"
        elif pressure["game_running"]:
            pressure["needs_reduced_resources"] = True
            pressure["reason"] = "gaming session active"
        elif pressure["battery_saver"]:
            pressure["needs_reduced_resources"] = True
            pressure["reason"] = "battery saver active"

        return pressure

    def _detect_heavy_game(self):
        """Best effort check for common running games or high GPU processes."""
        if not psutil:
            return False
            
        common_game_execs = ("csgo", "dota2", "minecraft", "steam", "cyberpunk", "witcher", "retroarch", "valheim", "genshin")
        try:
            for p in psutil.process_iter(attrs=["name", "cpu_percent"]):
                try:
                    pname = (p.info["name"] or "").lower()
                    if any(g in pname for g in common_game_execs):
                        # check if utilizing significant CPU
                        if p.info["cpu_percent"] and p.info["cpu_percent"] > 25.0:
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return False

    def apply_temporary_adaptation(self):
        """Temporarily scale down keep-alive or enforce CPU/engine-only fallback if system is stressed."""
        with self._adaptation_lock:
            pressure = self.check_system_pressure()
            perf_state = self.engine.state.get("performance", {})
            if not perf_state:
                return

            if pressure["needs_reduced_resources"]:
                current_mode = perf_state.get("selectedMode", "auto")
                if current_mode == "auto":
                    current_mode = perf_state.get("recommendedMode", "low")
                
                # Enforce lower resolved tier temporarily
                if current_mode in ("extreme", "high"):
                    perf_state["resolvedMode"] = "medium"
                elif current_mode == "medium":
                    perf_state["resolvedMode"] = "low"
                
                # If battery critical or RAM extremely low, force engine-only fallback
                if pressure["battery_critical"] or (pressure["low_memory"] and current_mode == "low"):
                    perf_state["resolvedMode"] = "engine_only"
                
                perf_state["temporaryFallbackState"] = pressure["reason"]
                logger.warning(f"Adaptation activated: {pressure['reason']}. Downshifted resolvedMode to {perf_state['resolvedMode']}")
            else:
                # Restore to normal selected tier
                selected = perf_state.get("selectedMode", "auto")
                if selected == "auto":
                    perf_state["resolvedMode"] = perf_state.get("recommendedMode", "low")
                else:
                    perf_state["resolvedMode"] = selected
                perf_state["temporaryFallbackState"] = None
                
            self.engine.save_state()
