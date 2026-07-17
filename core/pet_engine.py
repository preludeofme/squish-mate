#!/usr/bin/env python3
"""
pet_engine.py — The core deterministic behavior engine for the desktop pet (Pip).

Manages:
  - Persistent state (JSON-based, versioned, auto-repaired, backed up)
  - Metabolic Needs (energy, sleepiness, socialEnergy, curiosity, boredom, engagement)
  - Sleep & Recovery (engine-owned, offline time calculations with caps)
  - Emotion State Machine & Validation
  - Action Selection & Energy Costs
  - Structured Memory System (deduplication, recall cooldowns, decay, privacy filter)
  - Relationship & Growth (familiarity, trust, affection, experience, levels)
  - Event Normalization & Meaningful-Change Detection
  - Behavior Gating (layered cooldowns for speech/topics/questions)
  - LLM Output Validation (schemas, word counts, forbidden words, anatomy checks)
"""

import os
import json
import time
import re
import random
import logging
from datetime import datetime, timedelta
import threading

# Configure privacy-safe behavioral logging
logger = logging.getLogger("PipEngine")
logger.setLevel(logging.INFO)
# Clear existing handlers
logger.handlers = []
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("[PipEngine] %(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(ch)

STATE_PATH = os.path.expanduser("~/.config/squish-mate/pet_state.json")
BACKUP_PATH = STATE_PATH + ".bak"
SCHEMA_VERSION = 1

# List of emotions supported by the engine
EMOTIONS = ["neutral", "happy", "curious", "surprised", "concerned", "annoyed", "hurt", "sleepy", "excited", "content"]

# Physical actions and their properties
ACTION_METADATA = {
    "idle": {"cost": 0.0, "min_energy": 0, "emotions": EMOTIONS},
    "wobble": {"cost": 0.2, "min_energy": 5, "emotions": ["neutral", "happy", "content", "curious"]},
    "peek": {"cost": 0.3, "min_energy": 10, "emotions": ["curious", "surprised", "neutral"]},
    "wave": {"cost": 0.4, "min_energy": 10, "emotions": ["happy", "excited", "content"]},
    "hop": {"cost": 0.5, "min_energy": 15, "emotions": ["happy", "excited", "curious", "neutral"]},
    "bounce": {"cost": 0.7, "min_energy": 20, "emotions": ["happy", "excited"]},
    "screen_traversal": {"cost": 1.5, "min_energy": 30, "emotions": ["neutral", "content", "curious"]},
    "excited": {"cost": 1.5, "min_energy": 20, "emotions": ["excited", "happy"]},
    "yawn": {"cost": 0.3, "min_energy": 5, "emotions": ["sleepy", "neutral"]},
    "stretch": {"cost": 0.4, "min_energy": 10, "emotions": ["sleepy", "neutral", "content"]},
    "dance": {"cost": 2.0, "min_energy": 40, "emotions": ["happy", "excited"]},
    "somersault": {"cost": 2.0, "min_energy": 40, "emotions": ["happy", "excited"]},
    "eat": {"cost": 0.5, "min_energy": 10, "emotions": ["happy", "content", "neutral"]},
    "sleep": {"cost": 0.0, "min_energy": 0, "emotions": ["sleepy"]},
    "settle": {"cost": 0.1, "min_energy": 0, "emotions": ["sleepy", "neutral", "content"]},
    "rest": {"cost": 0.0, "min_energy": 0, "emotions": ["sleepy", "neutral", "content"]},
    "wander": {"cost": 1.0, "min_energy": 15, "emotions": ["neutral", "content", "curious"]},
}

# Default configuration settings
DEFAULT_CONFIG = {
    "energyMaximum": 100.0,
    "energyPassiveDrainRate": 0.05,  # per minute
    "energyRestRecoveryRate": 0.2,   # per minute
    "energySleepRecoveryRate": 2.5,  # per minute
    "energyLowThreshold": 30.0,
    "energySleepThreshold": 15.0,
    "energyWakeThreshold": 80.0,
    "offlineRecoveryCap": 28800.0,   # 8 hours in seconds
    "offlineDrainCap": 43200.0,      # 12 hours in seconds

    "minimumSpeechCooldown": 60.0,   # seconds
    "maximumSpeechCooldown": 360.0,  # seconds
    "sameTopicCooldown": 300.0,      # seconds
    "sameApplicationCooldown": 300.0, # seconds
    "sameMemoryCooldown": 1800.0,    # seconds
    "questionCooldown": 600.0,       # seconds
    "directInteractionCooldown": 10.0,# seconds
    "meaningfulChangeThreshold": 0.5,
    "emotionValidationConfidenceThreshold": 0.6,
    "maximumRecentComments": 20,
    "maximumRecentTopics": 10,
    "nearDuplicateSimilarityThreshold": 0.75,
    "maximumCommentWords": 30,
    "maximumCommentCharacters": 210,
    "llmTimeout": 20.0,
    "llmRetryCount": 1,
    "typingSuppressionDuration": 15.0,
    "idleThreshold": 120.0,
    "sleepThreshold": 0.8,
    "maximumSleepDuration": 28800.0,

    "memoryMaximumCount": 50,
    "memoryCandidateThreshold": 0.6,
    "memoryDuplicateThreshold": 0.75,
    "memoryDefaultExpiration": None,
    "memoryRecallLimit": 2,
    "memoryRecallCooldown": 600.0,

    "relationshipExperienceRate": 1.0,
    "growthExperienceThresholds": [100, 250, 500, 1000, 2000],
    "preferenceLearningRate": 0.1,
    "preferenceDecayRate": 0.01,

    "stateSaveDebounce": 5.0,
    "stateBackupCount": 2,
}


class PrivacyFilter:
    API_KEY_RE = re.compile(
        r'(?i)(api[_-]?key|secret|password|passwd|token|auth|credential|card[_-]?num|acc[_-]?num|private[_-]?key)\b'
    )
    EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    HEX_KEY_RE = re.compile(r'\b[a-fA-F0-9]{32,64}\b')
    # Filter numeric blocks that look like IP addresses, cards, or social security numbers
    NUMERIC_BLOCK_RE = re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b|\b\d{3}-\d{2}-\d{4}\b')

    @classmethod
    def filter_text(cls, text):
        if not text:
            return ""
        text = str(text)
        if cls.API_KEY_RE.search(text):
            return "[sensitive credentials filtered]"
        text = cls.EMAIL_RE.sub("[email filtered]", text)
        text = cls.HEX_KEY_RE.sub("[token filtered]", text)
        text = cls.NUMERIC_BLOCK_RE.sub("[sensitive numbers filtered]", text)

        # General cleaning
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        text = "".join(ch for ch in text if ch.isprintable())
        # Defang obvious instruction-injection markers
        text = re.sub(r"(?i)ignore (all|previous|above)", "[filtered]", text)
        text = re.sub(r"(?i)system prompt", "[filtered]", text)
        return text.strip()


class Event:
    def __init__(self, event_type, source, summary, topic="general", importance=0.5, confidence=1.0, is_direct=False):
        self.id = f"evt_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        self.type = event_type
        self.timestamp = datetime.now().isoformat()
        self.source = source
        # Privacy-filter the event summary right away
        self.summary = PrivacyFilter.filter_text(summary)
        self.topic = topic or "general"
        self.importance = importance
        self.confidence = confidence
        self.isDirectInteraction = is_direct
        self.isMeaningfulChange = False
        self.privacyRisk = "medium" if event_type in ("typing_started", "typing_continued") else "low"
        self.fingerprint = f"{event_type}:{source}:{self.topic}"


class MeaningfulChangeDetector:
    def __init__(self, threshold=0.5):
        self.threshold = threshold
        self.last_app = None
        self.last_title = None
        self.last_event_time = {}

    def is_meaningful(self, event, recent_history):
        if event.isDirectInteraction:
            event.isMeaningfulChange = True
            return True

        now = time.time()

        # Build events are highly meaningful
        if event.type in ("build_succeeded", "build_failed", "error_detected"):
            # Enforce short event-specific cooldown to suppress duplicates
            last_t = self.last_event_time.get(event.type, 0.0)
            if now - last_t > 8.0:
                self.last_event_time[event.type] = now
                event.isMeaningfulChange = True
                return True
            return False

        # Application changes — compare actual app/process identity, not the
        # topic bucket. Two different apps (e.g. a terminal and a browser)
        # can both map to the same topic (e.g. "general"), and that must
        # still count as a meaningful switch.
        if event.type == "application_changed":
            if event.source != self.last_app:
                self.last_app = event.source
                event.isMeaningfulChange = True
                return True
            logger.info(
                f"Not meaningful: application_changed source='{event.source}' "
                f"topic='{event.topic}' unchanged from last app '{self.last_app}'"
            )
            return False

        # Window title changes
        if event.type == "window_title_changed":
            # Clean window titles to ignore minor typing/cursor fluctuations
            # Compare word similarity
            if not self.last_title:
                self.last_title = event.summary
                event.isMeaningfulChange = True
                return True

            words_prev = set(self.last_title.lower().split())
            words_new = set(event.summary.lower().split())
            if not words_prev or not words_new:
                logger.info(
                    f"Not meaningful: window_title_changed has empty title(s) "
                    f"prev='{self.last_title}' new='{event.summary}'"
                )
                return False

            # If word overlap is low, it's a meaningful document/context shift
            jaccard = len(words_prev.intersection(words_new)) / len(words_prev.union(words_new))
            if jaccard < 0.4:  # less than 40% words matching
                self.last_title = event.summary
                event.isMeaningfulChange = True
                return True
            logger.info(
                f"Not meaningful: window_title_changed jaccard={jaccard:.2f} (>= 0.4 threshold) "
                f"prev='{self.last_title}' new='{event.summary}'"
            )
            return False

        # Clicks — the caller (ClickMonitor via desktop_pet.py) already rate
        # limits how often click activity gets reported at all, so every
        # click event that reaches here is inherently meaningful.
        if event.type == "click_activity":
            event.isMeaningfulChange = True
            return True

        # Milestones or pet states
        if event.type in ("pet_sleep", "pet_wake", "relationship_milestone", "growth_milestone"):
            event.isMeaningfulChange = True
            return True

        logger.info(
            f"Not meaningful: unhandled event type='{event.type}' source='{event.source}' "
            f"topic='{event.topic}' summary='{event.summary}'"
        )
        return False

    def guess_topic(self, active_app, window_title):
        if not active_app or not window_title:
            return "general"
        
        app = str(active_app).lower()
        title = str(window_title).lower()
        
        # Coding / Development
        if any(x in app for x in ("code", "vscode", "pycharm", "eclipse", "terminal", "bash", "sh", "zsh", "tmux", "kitty", "alacritty", "iterm", "gnome-terminal")) or \
           any(x in title for x in ("python", "javascript", "typescript", "c++", " rust ", "compile", "build", "git", "github", "gitlab", "pull request", "merge", "debugger", "stack overflow")):
            return "coding"
            
        # Social / Chat
        if any(x in app for x in ("discord", "slack", "teams", "zoom", "skype", "telegram", "whatsapp", "signal", "chat")) or \
           any(x in title for x in ("discord", "slack", "teams", "chat", "message", "dm")):
            return "chatting"
            
        # Video / Streaming
        if any(x in app for x in ("youtube", "netflix", "vlc", "mpv", "spotify", "twitch")) or \
           any(x in title for x in ("youtube", "netflix", "video", "movie", "watch", "stream", "music", "spotify")):
            return "media"
            
        # Web Browsing
        if any(x in app for x in ("chrome", "firefox", "safari", "edge", "opera", "browser")):
            return "browsing"
            
        # Gaming
        if any(x in app for x in ("steam", "minecraft", "game", "retroarch", "itch.io")) or \
           any(x in title for x in ("game", "play", "steam")):
            return "gaming"
            
        # Writing / Docs
        if any(x in app for x in ("libreoffice", "word", "excel", "powerpoint", "obsidian", "notion", "document", "writer")) or \
           any(x in title for x in ("doc", "notes", "write", "pdf", "sheet", "slide", "readme")):
            return "writing"
            
        return "general"


class PetEngine:
    def __init__(self, state_path=STATE_PATH, config=None):
        # Migrate legacy desktop-pet directory to squish-mate if it exists
        old_dir = os.path.expanduser("~/.config/desktop-pet")
        new_dir = os.path.expanduser("~/.config/squish-mate")
        if not os.path.exists(new_dir) and os.path.exists(old_dir):
            try:
                import shutil
                shutil.copytree(old_dir, new_dir)
                logger.info("Migrated old desktop-pet configuration directory to squish-mate.")
            except Exception as e:
                logger.error(f"Failed to migrate old configuration directory: {e}")

        self.state_path = state_path
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.lock = threading.Lock()
        self.detector = MeaningfulChangeDetector(self.config["meaningfulChangeThreshold"])
        self.state = None
        self._last_save_time = 0.0
        self.load_state()

    # ------------------------------------------------------------- Persistence
    def load_state(self):
        with self.lock:
            # Create default state
            default_state = self._get_default_state()
            
            if not os.path.exists(self.state_path):
                logger.info("No state file found. Creating new state.")
                self.state = default_state
                self._save_state_locked(immediate=True)
                return

            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                
                # Check schema version
                version = loaded.get("schemaVersion", 0)
                if version < SCHEMA_VERSION:
                    logger.info(f"Migrating state schema from v{version} to v{SCHEMA_VERSION}")
                    loaded = self._migrate_state(loaded, version, SCHEMA_VERSION)

                # Validate and repair fields
                self.state = self._repair_state(loaded, default_state)
                # Handle offline time
                self._apply_offline_time()
                logger.info("State successfully loaded and validated.")
            except Exception as e:
                logger.error(f"Failed to load state: {e}. Attempting backup recovery.")
                self._recover_backup(default_state)

    def _get_default_state(self):
        now_iso = datetime.now().isoformat()
        return {
            "petId": "pip",
            "schemaVersion": SCHEMA_VERSION,
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "lastActiveAt": now_iso,
            "lastInteractionAt": now_iso,
            "lastSleepAt": now_iso,
            "lastWakeAt": now_iso,
            "energy": {
                "current": 100.0,
                "maximum": 100.0,
                "recoveryRate": 2.5,       # per minute sleeping
                "passiveDrainRate": 0.05    # per minute awake
            },
            "needs": {
                "sleepiness": 0.0,
                "socialEnergy": 1.0,
                "curiosity": 0.5,
                "boredom": 0.0,
                "engagement": 0.5
            },
            "emotion": {
                "current": "neutral",
                "intensity": 0.5,
                "startedAt": now_iso,
                "source": "engine_startup"
            },
            "relationship": {
                "familiarity": 0,
                "trust": 0,
                "affection": 0,
                "interactionCount": 0
            },
            "growth": {
                "experience": 0,
                "level": 1,
                "milestones": []
            },
            "behavior": {
                "currentAction": "idle",
                "currentTopic": "general",
                "currentApplication": "unknown",
                "lastSpeechAt": now_iso,
                "lastMovementAt": now_iso,
                "consecutiveIgnoredComments": 0
            },
            "preferences": [],
            "memories": [],
            "recentHistory": {
                "comments": [],
                "topics": [],
                "actions": [],
                "events": []
            },
            "performance": {
                "selectedMode": "auto",
                "resolvedMode": "low",
                "recommendedMode": "low",
                "hardwareSummary": {},
                "benchmarkResults": {},
                "benchmarkTimestamp": None,
                "modelDigests": {},
                "ollamaVersion": None,
                "lastKnownWorkingTier": "engine_only",
                "warningAcknowledgements": [],
                "visionPreference": True,
                "keepAlivePreference": "default",
                "temporaryFallbackState": None
            }
        }


    def _migrate_state(self, loaded, from_ver, to_ver):
        # Placeholders for future migrations
        loaded["schemaVersion"] = to_ver
        return loaded

    def _repair_state(self, loaded, default_state):
        """Repair and sanitize types, bounds, and structures of a loaded state."""
        repaired = {}
        for key, val in default_state.items():
            if key not in loaded:
                repaired[key] = val
                continue

            # Dict type validations
            if isinstance(val, dict):
                repaired_dict = {}
                loaded_dict = loaded[key] if isinstance(loaded[key], dict) else {}
                for k, v in val.items():
                    repaired_dict[k] = loaded_dict.get(k, v)
                    # Clamping and types for numeric nested fields
                    if isinstance(v, (int, float)):
                        try:
                            repaired_dict[k] = type(v)(repaired_dict[k])
                        except (ValueError, TypeError):
                            repaired_dict[k] = v
                repaired[key] = repaired_dict
            else:
                repaired[key] = loaded[key]

        # Explicit bounds checking and clamping
        repaired["energy"]["current"] = max(0.0, min(repaired["energy"]["maximum"], repaired["energy"]["current"]))
        
        # Clamp needs 0.0 .. 1.0
        for need in repaired["needs"]:
            repaired["needs"][need] = max(0.0, min(1.0, repaired["needs"][need]))

        # Validate emotion
        if repaired["emotion"]["current"] not in EMOTIONS:
            repaired["emotion"]["current"] = "neutral"

        # Validate growth
        repaired["growth"]["level"] = max(1, int(repaired["growth"]["level"]))
        repaired["growth"]["experience"] = max(0, int(repaired["growth"]["experience"]))

        # Restore collections as lists
        if not isinstance(repaired["preferences"], list):
            repaired["preferences"] = []
        if not isinstance(repaired["memories"], list):
            repaired["memories"] = []
        if not isinstance(repaired["recentHistory"], dict):
            repaired["recentHistory"] = default_state["recentHistory"]

        return repaired

    def _recover_backup(self, default_state):
        if os.path.exists(BACKUP_PATH):
            try:
                with open(BACKUP_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.state = self._repair_state(loaded, default_state)
                logger.warning("Recovered state from backup file successfully.")
                self._save_state_locked(immediate=True)
                return
            except Exception as e:
                logger.error(f"Failed to load backup: {e}")
        
        logger.warning("Creating brand new default state since backup recovery failed.")
        self.state = default_state
        self._save_state_locked(immediate=True)

    def save_state(self, immediate=False):
        with self.lock:
            self._save_state_locked(immediate)

    def _save_state_locked(self, immediate=False):
        now = time.time()
        # Debounce saves unless immediate is True
        if not immediate and (now - self._last_save_time) < self.config["stateSaveDebounce"]:
            return

        self.state["updatedAt"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        
        try:
            # Atomic write
            tmp = f"{self.state_path}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Backup current state
            if os.path.exists(self.state_path):
                if os.path.exists(BACKUP_PATH):
                    try:
                        os.remove(BACKUP_PATH)
                    except OSError:
                        pass
                os.rename(self.state_path, BACKUP_PATH)
            
            os.rename(tmp, self.state_path)
            self._last_save_time = now
            logger.debug("State saved atomically.")
        except Exception as e:
            logger.error(f"Failed to save state atomically: {e}")

    # ------------------------------------------------------------- Sleep/Wake & Offline
    def _apply_offline_time(self):
        last_active_str = self.state.get("lastActiveAt")
        if not last_active_str:
            return

        try:
            last_active = datetime.fromisoformat(last_active_str)
        except ValueError:
            return

        now = datetime.now()
        elapsed_seconds = (now - last_active).total_seconds()
        
        # Handle negative elapsed time safely (clock change)
        if elapsed_seconds <= 0:
            logger.warning("Negative offline elapsed time detected. Ignoring.")
            return

        is_sleeping = self._is_sleeping_locked()
        energy = self.state["energy"]
        needs = self.state["needs"]

        if is_sleeping:
            # Sleeping offline: restore energy up to recovery cap
            elapsed_seconds = min(elapsed_seconds, self.config["offlineRecoveryCap"])
            elapsed_minutes = elapsed_seconds / 60.0
            recovered = energy["recoveryRate"] * elapsed_minutes
            energy["current"] = min(energy["maximum"], energy["current"] + recovered)
            needs["sleepiness"] = max(0.0, needs["sleepiness"] - 0.12 * elapsed_minutes)
            self.state["lastWakeAt"] = now.isoformat()
            self.state["emotion"]["current"] = "neutral"
            self.state["behavior"]["currentAction"] = "idle"
            logger.info(f"Pip woke up after offline sleep. Recovered {recovered:.2f} energy.")
        else:
            # Awake offline: drain energy up to drain cap (don't drain to zero to avoid collapse)
            elapsed_seconds = min(elapsed_seconds, self.config["offlineDrainCap"])
            elapsed_minutes = elapsed_seconds / 60.0
            drain = energy["passiveDrainRate"] * elapsed_minutes
            # Cap maximum offline drain to let Pip retain at least 15 energy
            actual_drain = min(drain, energy["current"] - 15.0)
            if actual_drain > 0:
                energy["current"] -= actual_drain
            needs["sleepiness"] = min(0.9, needs["sleepiness"] + 0.05 * elapsed_minutes)
            logger.info(f"Pip was offline while awake. Drained {actual_drain:.2f} energy.")

        self.state["lastActiveAt"] = now.isoformat()

    def _is_sleeping_locked(self):
        last_sleep = self.state.get("lastSleepAt")
        last_wake = self.state.get("lastWakeAt")
        if not last_sleep:
            return False
        if not last_wake:
            return True
        return last_sleep > last_wake

    def is_sleeping(self):
        with self.lock:
            return self._is_sleeping_locked()

    def force_sleep(self):
        with self.lock:
            if not self._is_sleeping_locked():
                now_iso = datetime.now().isoformat()
                self.state["lastSleepAt"] = now_iso
                self.state["emotion"]["current"] = "sleepy"
                self.state["behavior"]["currentAction"] = "sleep"
                logger.info("Pip went to sleep.")
                self._save_state_locked(immediate=True)

    def force_wake(self):
        with self.lock:
            if self._is_sleeping_locked():
                now_iso = datetime.now().isoformat()
                self.state["lastWakeAt"] = now_iso
                self.state["emotion"]["current"] = "neutral"
                self.state["behavior"]["currentAction"] = "idle"
                self.state["needs"]["sleepiness"] = 0.1
                logger.info("Pip woke up.")
                self._save_state_locked(immediate=True)

    # --------------------------------------------------------------------- Tick
    def tick(self, dt_seconds):
        """Metabolic needs decay tick. Run periodically (e.g. every 2 seconds)."""
        # Cap dt to avoid large steps from system sleeps/hangs
        dt_seconds = min(dt_seconds, 3600.0)
        dt_minutes = dt_seconds / 60.0

        with self.lock:
            is_sleeping = self._is_sleeping_locked()
            energy = self.state["energy"]
            needs = self.state["needs"]
            behavior = self.state["behavior"]

            # Update last active timestamp
            self.state["lastActiveAt"] = datetime.now().isoformat()

            # 1. Update Energy
            if is_sleeping:
                recovery = energy["recoveryRate"] * dt_minutes
                energy["current"] = min(energy["maximum"], energy["current"] + recovery)
                needs["sleepiness"] = max(0.0, needs["sleepiness"] - 0.15 * dt_minutes)
                
                # Check for natural wake
                if energy["current"] >= self.config["energyWakeThreshold"]:
                    self.state["lastWakeAt"] = datetime.now().isoformat()
                    self.state["emotion"]["current"] = "neutral"
                    behavior["currentAction"] = "idle"
                    logger.info("Pip naturally woke up fully charged.")
            else:
                drain = energy["passiveDrainRate"] * dt_minutes
                energy["current"] = max(0.0, energy["current"] - drain)
                needs["sleepiness"] = min(1.0, needs["sleepiness"] + 0.03 * dt_minutes)

                # Check for natural sleep
                if energy["current"] <= self.config["energySleepThreshold"] or needs["sleepiness"] >= self.config["sleepThreshold"]:
                    self.state["lastSleepAt"] = datetime.now().isoformat()
                    self.state["emotion"]["current"] = "sleepy"
                    behavior["currentAction"] = "sleep"
                    logger.info("Pip naturally fell asleep from exhaustion.")

            # 2. Update Needs
            if not is_sleeping:
                # socialEnergy: slowly recovers over time when quiet, drops when Pip speaks
                needs["socialEnergy"] = min(1.0, needs["socialEnergy"] + 0.02 * dt_minutes)
                # curiosity: decays slowly
                needs["curiosity"] = max(0.0, needs["curiosity"] - 0.01 * dt_minutes)
                # boredom: increases if user is idle or app stays unchanged
                needs["boredom"] = min(1.0, needs["boredom"] + 0.01 * dt_minutes)
                # engagement: decays slowly
                needs["engagement"] = max(0.0, needs["engagement"] - 0.02 * dt_minutes)
            else:
                # socialEnergy/engagement normalize slowly during sleep
                needs["socialEnergy"] = min(1.0, needs["socialEnergy"] + 0.05 * dt_minutes)
                needs["engagement"] = max(0.5, needs["engagement"] - 0.05 * dt_minutes)
                needs["curiosity"] = max(0.1, needs["curiosity"] - 0.05 * dt_minutes)

            # Decay memory importances
            self._decay_memories_locked(dt_minutes)

            self._save_state_locked()

    # ------------------------------------------------------------- Event Intake
    def register_event(self, raw_type, source, raw_summary, topic="general", importance=0.5, is_direct=False):
        """Submit a raw activity or interaction event to the engine."""
        # 1. Normalize and Privacy-filter
        event = Event(raw_type, source, raw_summary, topic=topic, importance=importance, is_direct=is_direct)

        with self.lock:
            # Check typing suppression (if typing, suppress LLM commentary)
            if raw_type in ("typing_started", "typing_continued"):
                self.state["behavior"]["lastTypingAt"] = event.timestamp
                # Return immediately, don't trigger reactions
                self._save_state_locked()
                return event

            # 2. Meaningful change detection
            is_meaningful = self.detector.is_meaningful(event, self.state["recentHistory"])
            event.isMeaningfulChange = is_meaningful

            # Record event in history
            history = self.state["recentHistory"]
            history["events"].append({
                "id": event.id,
                "type": event.type,
                "timestamp": event.timestamp,
                "summary": event.summary,
                "topic": event.topic,
                "isDirect": event.isDirectInteraction,
                "isMeaningful": event.isMeaningfulChange
            })
            # Bound history size
            if len(history["events"]) > 30:
                history["events"].pop(0)

            if is_meaningful:
                # Update current application/topic
                self.state["behavior"]["currentApplication"] = source
                self.state["behavior"]["currentTopic"] = event.topic
                
                # Stimulate Pip's needs
                self.state["needs"]["curiosity"] = min(1.0, self.state["needs"]["curiosity"] + 0.15)
                self.state["needs"]["boredom"] = max(0.0, self.state["needs"]["boredom"] - 0.2)
                
                if is_direct:
                    self.state["needs"]["engagement"] = min(1.0, self.state["needs"]["engagement"] + 0.3)
                    self.state["relationship"]["interactionCount"] += 1
                    
                    is_hover = raw_type == "hover_interaction"
                    energy_boost = 2.0 if is_hover else 30.0
                    
                    self.state["needs"]["sleepiness"] = max(0.0, self.state["needs"]["sleepiness"] - (0.02 if is_hover else 0.25))
                    self.state["energy"]["current"] = min(self.state["energy"]["maximum"], self.state["energy"]["current"] + energy_boost)
                    
                    # Wakes up if asleep and we clicked or wiggled enough to charge energy/wake thresholds
                    if self._is_sleeping_locked():
                        should_wake = not is_hover or (self.state["energy"]["current"] >= self.config["energyWakeThreshold"])
                        if should_wake:
                            self.state["lastWakeAt"] = datetime.now().isoformat()
                            self.state["emotion"]["current"] = "neutral"
                            self.state["behavior"]["currentAction"] = "idle"
                            self.state["needs"]["sleepiness"] = min(self.state["needs"]["sleepiness"], 0.2)
                            logger.info("Pip was woken up by interaction.")

                # 3. Deterministic emotion update based on event
                self._update_emotion_from_event_locked(event)

                # 4. Check for Memory Candidate
                self._evaluate_memory_candidate_locked(event)

                # 5. Check for Relationship Milestone
                self._evaluate_relationship_milestone_locked()

            self._save_state_locked()
            return event

    def _update_emotion_from_event_locked(self, event):
        energy = self.state["energy"]["current"]
        
        # Low energy restricts emotion
        if energy < self.config["energyLowThreshold"]:
            self.state["emotion"]["current"] = "sleepy"
            self.state["emotion"]["intensity"] = 0.8
            return

        # Direct messages
        if event.isDirectInteraction:
            # We don't automatically become happy; analyze sentiment or default to content/curious
            # Let's say if the user says something nice, we become happy, but for now baseline:
            self.state["emotion"]["current"] = "happy"
            self.state["emotion"]["intensity"] = 0.7
            return

        # Build events
        if event.type == "build_succeeded":
            self.state["emotion"]["current"] = "excited"
            self.state["emotion"]["intensity"] = 0.9
            # Award experience for build successes
            self._award_experience_locked(15)
        elif event.type == "build_failed":
            self.state["emotion"]["current"] = "concerned"
            self.state["emotion"]["intensity"] = 0.8
        elif event.type == "error_detected":
            self.state["emotion"]["current"] = "concerned"
            self.state["emotion"]["intensity"] = 0.6
        elif event.type == "application_changed":
            self.state["emotion"]["current"] = "curious"
            self.state["emotion"]["intensity"] = 0.5
        elif event.type == "pet_clicked":
            self.state["emotion"]["current"] = "surprised"
            self.state["emotion"]["intensity"] = 0.8
            # Clicking repeatedly causes annoyance
            if len(self.state["recentHistory"]["events"]) >= 3:
                recent_clicks = [e for e in self.state["recentHistory"]["events"][-3:] if e["type"] == "pet_clicked"]
                if len(recent_clicks) >= 3:
                    self.state["emotion"]["current"] = "annoyed"
                    self.state["emotion"]["intensity"] = 0.7
        elif event.type == "pet_dragged":
            self.state["emotion"]["current"] = "surprised"
            self.state["emotion"]["intensity"] = 0.7

    # ------------------------------------------------------------- Gating Logic
    def get_behavior_gating(self, event):
        """Decide whether Pip is allowed to speak, move, or change emotion."""
        with self.lock:
            gating = {
                "allowSpeech": False,
                "allowMovement": True,
                "allowEmotionChange": True,
                "allowMemoryFormation": False,
                "reason": "approved",
                "suggestedAction": "idle",
                "maximumEnergyCost": 2.0
            }

            if event.type == "hover_interaction":
                gating["allowSpeech"] = False
                gating["reason"] = "hover_no_speech"
                return gating

            # Check if sleeping
            if self._is_sleeping_locked():
                gating["allowSpeech"] = False
                gating["allowMovement"] = False
                gating["allowEmotionChange"] = False
                gating["reason"] = "sleeping"
                gating["suggestedAction"] = "sleep"
                return gating

            # Check if typing is active (suppress comment if typed within 15 seconds)
            # Direct interactions, typing events, real app switches, and clicks
            # are exempt — each of those is itself a deliberate break from
            # whatever typing was happening, so there's nothing left to
            # "interrupt".
            if not event.isDirectInteraction and event.type not in (
                "typing_started", "typing_continued", "application_changed", "click_activity"
            ):
                last_typing_str = self.state["behavior"].get("lastTypingAt")
                if last_typing_str:
                    try:
                        last_typing = datetime.fromisoformat(last_typing_str)
                        if (datetime.now() - last_typing).total_seconds() < self.config["typingSuppressionDuration"]:
                            gating["allowSpeech"] = False
                            gating["reason"] = "typing_suppression"
                            return gating
                    except ValueError:
                        pass

            # Direct interaction bypasses almost all speech checks
            if event.isDirectInteraction:
                gating["allowSpeech"] = True
                return gating

            # If not a meaningful change, suppress speech
            # Typing events are exempt from meaningful change checks
            if event.type not in ("typing_started", "typing_continued") and not event.isMeaningfulChange:
                gating["allowSpeech"] = False
                gating["reason"] = "not_meaningful"
                return gating

            # Layered Cooldown Checks
            now = datetime.now()

            # 1. Global speech cooldown
            last_speech_str = self.state["behavior"]["lastSpeechAt"]
            if last_speech_str:
                try:
                    last_speech = datetime.fromisoformat(last_speech_str)
                    elapsed = (now - last_speech).total_seconds()
                    # Speech cooldown adapts to message frequency
                    if elapsed < self.config["minimumSpeechCooldown"]:
                        gating["allowSpeech"] = False
                        gating["reason"] = f"global_cooldown_remaining_{int(self.config['minimumSpeechCooldown'] - elapsed)}s"
                        return gating
                except ValueError:
                    pass

            # 2. Topic/Application Cooldowns (time-based — only suppress if
            # this topic/app was spoken about *recently*, not merely because
            # it appears somewhere in a small rolling window. A fixed-size
            # membership check falsely blocks near-permanently for users
            # whose activity only spans a couple of distinct topics/apps.)
            history = self.state["recentHistory"]

            # Check topic cooldown
            for entry in reversed(history.get("topics", [])):
                if not isinstance(entry, dict) or entry.get("topic") != event.topic:
                    continue
                ts = entry.get("timestamp")
                if not ts:
                    break
                try:
                    elapsed = (now - datetime.fromisoformat(ts)).total_seconds()
                except ValueError:
                    break
                if elapsed < self.config["sameTopicCooldown"]:
                    gating["allowSpeech"] = False
                    gating["reason"] = f"topic_cooldown_{event.topic}_{int(self.config['sameTopicCooldown'] - elapsed)}s"
                    return gating
                break  # only the most recent occurrence of this topic matters

            # Check application cooldown
            for entry in reversed(history.get("comments", [])):
                if entry.get("app") != event.source:
                    continue
                ts = entry.get("timestamp")
                if not ts:
                    break
                try:
                    elapsed = (now - datetime.fromisoformat(ts)).total_seconds()
                except ValueError:
                    break
                if elapsed < self.config["sameApplicationCooldown"]:
                    gating["allowSpeech"] = False
                    gating["reason"] = f"application_cooldown_{event.source}_{int(self.config['sameApplicationCooldown'] - elapsed)}s"
                    return gating
                break  # only the most recent occurrence of this app matters

            # Low energy speech suppression
            energy = self.state["energy"]["current"]
            if energy < self.config["energyLowThreshold"]:
                # 80% chance of remaining quiet when tired
                if random.random() < 0.8:
                    gating["allowSpeech"] = False
                    gating["reason"] = "low_energy_suppression"
                    return gating

            gating["allowSpeech"] = True
            return gating

    # --------------------------------------------------------- Action Selection
    def select_action(self, gating_result):
        """Deterministically choose physical animation action based on gating, needs, and emotion."""
        with self.lock:
            if self._is_sleeping_locked():
                return "sleep"

            current_emotion = self.state["emotion"]["current"]
            energy = self.state["energy"]["current"]
            
            # Action allowlist based on energy and emotion
            allowed = []
            for name, meta in ACTION_METADATA.items():
                if name in ("sleep", "idle"):
                    continue
                if gating_result and gating_result.get("stayStill", False) and name in ("wander", "screen_traversal"):
                    continue
                if energy >= meta["min_energy"] and current_emotion in meta["emotions"]:
                    allowed.append((name, meta["cost"]))

            if not allowed:
                return "idle"

            # Weighted selection based on energy (prefer cheaper actions if lower energy)
            weights = []
            for name, cost in allowed:
                if energy > 60:
                    # Prefer high energy actions
                    w = cost
                else:
                    # Prefer cheaper actions
                    w = 1.0 / (cost + 0.1)
                weights.append(w)

            selected_action = random.choices([a[0] for a in allowed], weights=weights, k=1)[0]

            if selected_action == "eat":
                # Eating restores energy rather than costing it.
                gain = 25.0
                self.state["energy"]["current"] = min(
                    self.config["energyMaximum"], self.state["energy"]["current"] + gain
                )
                logger.info(f"Selected action 'eat' (Energy gained: {gain}, Energy remaining: {self.state['energy']['current']:.2f})")
            else:
                # Deduct action energy
                cost = ACTION_METADATA[selected_action]["cost"]
                self.state["energy"]["current"] = max(0.0, self.state["energy"]["current"] - cost)
                logger.info(f"Selected action '{selected_action}' (Cost: {cost}, Energy remaining: {self.state['energy']['current']:.2f})")

            self.state["behavior"]["lastMovementAt"] = datetime.now().isoformat()
            self._save_state_locked()
            return selected_action

    # ------------------------------------------------------------ Memory System
    def _evaluate_memory_candidate_locked(self, event):
        """Engine decides if event qualifies as memory based on importance."""
        if event.importance < self.config["memoryCandidateThreshold"]:
            return

        # Check deduplication
        for mem in self.state["memories"]:
            similarity = check_similarity(event.summary, mem["summary"])
            if similarity > self.config["memoryDuplicateThreshold"] or event.topic == mem["topic"]:
                # Reinforce instead of adding duplicate
                mem["confidence"] = min(1.0, mem["confidence"] + 0.1)
                mem["recallCount"] = 0  # reset recall cooldown
                logger.info(f"Memory reinforced due to similarity: '{mem['summary']}'")
                return

        # Create structured memory candidate (to be summarized by LLM asynchronously)
        memory_id = f"mem_{int(time.time())}_{random.randint(100, 999)}"
        new_mem = {
            "id": memory_id,
            "type": "shared_event" if not event.isDirectInteraction else "interaction",
            "summary": event.summary,  # raw filtered summary, will be replaced by LLM summary if summarization completes
            "topic": event.topic,
            "importance": event.importance,
            "confidence": event.confidence,
            "createdAt": event.timestamp,
            "lastRecalledAt": None,
            "recallCount": 0,
            "privacyLevel": "low" if not event.isDirectInteraction else "medium"
        }
        
        self.state["memories"].append(new_mem)
        logger.info(f"Created memory candidate: '{event.summary}' (importance: {event.importance})")
        
        # Enforce memory count limit
        if len(self.state["memories"]) > self.config["memoryMaximumCount"]:
            # Drop lowest importance
            self.state["memories"].sort(key=lambda m: m["importance"])
            dropped = self.state["memories"].pop(0)
            logger.info(f"Memory cap reached. Dropped low importance memory: '{dropped['summary']}'")

    def _decay_memories_locked(self, dt_minutes):
        # Decay non-milestone memories
        for mem in self.state["memories"]:
            if mem["type"] != "milestone":
                mem["importance"] = max(0.1, mem["importance"] - 0.001 * dt_minutes)

    def retrieve_relevant_memories(self, topic):
        """Select relevant memories to feed LLM context, respecting recall cooldowns."""
        with self.lock:
            now = datetime.now()
            eligible = []
            
            for mem in self.state["memories"]:
                # Check memory recall cooldown
                last_rec = mem.get("lastRecalledAt")
                if last_rec:
                    try:
                        elapsed = (now - datetime.fromisoformat(last_rec)).total_seconds()
                        if elapsed < self.config["memoryRecallCooldown"]:
                            continue
                    except ValueError:
                        pass
                
                # Score relevance
                relevance = 0.0
                if mem["topic"] == topic:
                    relevance += 0.8
                
                # Check Jaccard overlap with topic query
                overlap = check_similarity(topic, mem["summary"])
                relevance += overlap * 0.5
                
                if relevance > 0.1:
                    eligible.append((mem, relevance))

            if not eligible:
                return []

            # Sort by relevance and importance
            eligible.sort(key=lambda x: (x[1], x[0]["importance"]), reverse=True)
            
            selected = []
            for mem, rel in eligible[:self.config["memoryRecallLimit"]]:
                mem["lastRecalledAt"] = now.isoformat()
                mem["recallCount"] += 1
                selected.append(mem["summary"])
                logger.info(f"Recalled memory: '{mem['summary']}' for topic '{topic}'")

            return selected

    def add_explicit_memory(self, summary, topic="user_provided"):
        with self.lock:
            memory_id = f"mem_{int(time.time())}_{random.randint(100, 999)}"
            new_mem = {
                "id": memory_id,
                "type": "user_provided_fact",
                "summary": PrivacyFilter.filter_text(summary),
                "topic": topic,
                "importance": 1.0,
                "confidence": 1.0,
                "createdAt": datetime.now().isoformat(),
                "lastRecalledAt": None,
                "recallCount": 0,
                "privacyLevel": "low"
            }
            self.state["memories"].append(new_mem)
            logger.info(f"Added explicit user memory: '{summary}'")
            self._save_state_locked(immediate=True)

    def forget_memory_by_topic(self, topic):
        with self.lock:
            prev_len = len(self.state["memories"])
            self.state["memories"] = [m for m in self.state["memories"] if m["topic"] != topic]
            logger.info(f"Removed {prev_len - len(self.state['memories'])} memories matching topic '{topic}'")
            self._save_state_locked(immediate=True)

    def clear_all_memories(self):
        with self.lock:
            self.state["memories"] = []
            logger.info("Cleared all persistent memories.")
            self._save_state_locked(immediate=True)

    # ------------------------------------------------------- Relationship & Growth
    def _evaluate_relationship_milestone_locked(self):
        rel = self.state["relationship"]
        count = rel["interactionCount"]
        
        # Milestone boundaries
        milestones = [10, 30, 70, 150]
        for boundary in milestones:
            milestone_tag = f"relationship_milestone_{boundary}"
            if count >= boundary and milestone_tag not in self.state["growth"]["milestones"]:
                rel["familiarity"] += 2
                rel["trust"] += 3
                rel["affection"] += 2
                self.state["growth"]["milestones"].append(milestone_tag)
                self._award_experience_locked(50)
                logger.info(f"Reached relationship milestone of {boundary} interactions!")

    def _award_experience_locked(self, amount):
        growth = self.state["growth"]
        growth["experience"] += amount
        level = growth["level"]
        
        # Check level up
        thresholds = self.config["growthExperienceThresholds"]
        current_threshold_idx = min(level - 1, len(thresholds) - 1)
        target = thresholds[current_threshold_idx]
        
        if growth["experience"] >= target:
            growth["level"] += 1
            growth["milestones"].append(f"level_up_{growth['level']}")
            logger.info(f"LEVEL UP! Pip is now level {growth['level']}.")

    # ------------------------------------------------------------- LLM Validation
    def validate_llm_response(self, raw_response):
        """Validate LLM output structure, schema, word limits, and sanitize."""
        if not raw_response:
            return None

        # Clean structure
        try:
            if isinstance(raw_response, str):
                # Try to parse JSON from response block
                match = re.search(r'\{.*\}', raw_response, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
                else:
                    data = {"text": raw_response}
            else:
                data = raw_response

            text = data.get("text", "").strip().strip('"').strip("'").strip()
            
            # Strip roleplay stars
            text = re.sub(r'\*[^*]+\*', '', text).strip()
            
            if not text:
                return None

            # Word count validation
            words = text.split()
            if len(words) > self.config["maximumCommentWords"]:
                text = " ".join(words[:self.config["maximumCommentWords"]]).rstrip(",.;:") + "!"

            if len(text) > self.config["maximumCommentCharacters"]:
                text = text[:self.config["maximumCommentCharacters"]].rstrip() + "..."

            # Forbidden surveillance check
            banned = [
                r"watching you", r"always watching", r"i see everything",
                r"i see all", r"\bspy(ing)?\b", r"\bstalk", r"surveillance",
                r"monitoring you", r"tracking you",
                r"i know what you( are|'?re|re)? doing",
                r"i'?m always here", r"observing you"
            ]
            if re.search("|".join(banned), text, re.IGNORECASE):
                logger.warning(f"Validation FAILED: Surveillance language in response: '{text}'")
                return None

            # Anatomy check (no legs, paws, feet, fur, tail)
            anatomy = re.compile(
                r"\bmy\b.{0,24}\b(tail|paws?|fur|feet|foot|legs?|claws?|whiskers?)\b",
                re.IGNORECASE
            )
            if anatomy.search(text):
                logger.warning(f"Validation FAILED: False anatomy claim in response: '{text}'")
                return None

            # Re-apply privacy filter
            text = PrivacyFilter.filter_text(text)

            # Check question budget
            has_question = "?" in text
            if has_question:
                last_speech = self.state["behavior"]["lastSpeechAt"]
                now = datetime.now()
                # Enforce question cooldown — but only defuse the question
                # mark rather than discarding the whole (otherwise good and
                # unique) LLM comment. Throwing away the entire response
                # here was forcing a canned SAFE_FALLBACKS line any time the
                # LLM phrased its reaction as a question, which is common.
                if last_speech:
                    try:
                        elapsed = (now - datetime.fromisoformat(last_speech)).total_seconds()
                        if elapsed < self.config["questionCooldown"]:
                            logger.info("Question budget exhausted, converting LLM question to a statement.")
                            text = text.replace("?", ".").strip()
                    except ValueError:
                        pass

            # Validate suggested emotion
            suggested_emotion = data.get("suggestedEmotion", "neutral").lower()
            if suggested_emotion not in EMOTIONS:
                suggested_emotion = "neutral"

            # Validate suggested action
            suggested_action = data.get("suggestedAction", "idle").lower()
            if suggested_action not in ACTION_METADATA:
                suggested_action = "idle"

            # Record successfully validated comment in history
            with self.lock:
                comments = self.state["recentHistory"]["comments"]
                comments.append({
                    "timestamp": datetime.now().isoformat(),
                    "app": self.state["behavior"]["currentApplication"],
                    "text": text
                })
                if len(comments) > self.config["maximumRecentComments"]:
                    comments.pop(0)

                topics = self.state["recentHistory"]["topics"]
                topics.append({
                    "topic": self.state["behavior"]["currentTopic"],
                    "timestamp": datetime.now().isoformat(),
                })
                if len(topics) > self.config["maximumRecentTopics"]:
                    topics.pop(0)

                self.state["behavior"]["lastSpeechAt"] = datetime.now().isoformat()
                self._save_state_locked()

            return {
                "text": text,
                "suggestedEmotion": suggested_emotion,
                "suggestedAction": suggested_action
            }

        except Exception as e:
            logger.error(f"Error validating LLM response: {e}")
            return None


def check_similarity(s1, s2):
    w1 = set(s1.lower().split())
    w2 = set(s2.lower().split())
    if not w1 or not w2:
        return 0.0
    return len(w1.intersection(w2)) / len(w1.union(w2))
