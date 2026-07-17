#!/usr/bin/env python3
"""
Advanced Desktop Pet Activity Monitor
This script monitors user activity and provides context for the pet.
"""

import os
import re
import sys
import time
import json
import threading
from datetime import datetime
from collections import defaultdict, deque

# Platform-specific imports
if sys.platform.startswith('win'):
    import win32gui
    import win32process
    import psutil
    import win32api
    import win32con
    import win32clipboard
elif sys.platform == 'darwin':  # macOS
    import subprocess
    import AppKit
    import Quartz
elif sys.platform.startswith('linux'):
    import subprocess
    import psutil
    # Try to import x11 libraries for better window information
    try:
        import Xlib.display
        import Xlib.X
        import Xlib.Xatom
    except ImportError:
        pass
    
class AdvancedActivityMonitor:
    def __init__(self):
        self.current_activities = {
            'active_app': None,
            'window_title': None,
            'active_window': None,
            'process_id': None,
            'timestamp': None
        }
        self.activity_history = deque(maxlen=20)
        self.apps_seen = set()
        self._last_check = 0  # 0 so the very first call detects the window
        self._known_windows = None  # win_id -> app name; None until first poll
        
    def get_current_activity(self):
        """Get current user activity."""
        current_time = time.time()
        
        # For performance, check only every few seconds
        if current_time - self._last_check < 3:
            return self.current_activities
            
        try:
            if sys.platform.startswith('win'):
                activity = self._get_activity_windows()
            elif sys.platform == 'darwin':
                activity = self._get_activity_macos()
            elif sys.platform.startswith('linux'):
                activity = self._get_activity_linux()
            else:
                activity = {'active_app': 'unknown'}
                
            # Update current activities
            self.current_activities.update(activity)
            self.current_activities['timestamp'] = datetime.now().isoformat()
            
            # Add to history
            self.activity_history.append(self.current_activities.copy())
            
            self._last_check = current_time
            
        except Exception as e:
            print(f"Error getting activity: {e}")
            return self.current_activities
            
        return self.current_activities
    
    def _get_activity_windows(self):
        """Get activity info on Windows."""
        activity = {
            'active_app': 'unknown',
            'window_title': 'unknown',
            'active_window': None,
            'process_id': None
        }
        
        try:
            # Get active window
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                activity['active_window'] = hwnd
                
                # Get window title
                window_title = win32gui.GetWindowText(hwnd)
                activity['window_title'] = window_title if window_title else 'unknown'
                
                # Get process ID from window
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid:
                    activity['process_id'] = pid
                    
                    # Get process name  
                    try:
                        process = psutil.Process(pid)
                        process_name = process.name()
                        activity['active_app'] = process_name
                        
                        # Track seen applications
                        self.apps_seen.add(process_name)
                        
                        # Also try to get executable path for more info
                        try:
                            exe = process.exe()
                            if 'msedge' in exe.lower() or 'chrome' in exe.lower():
                                activity['active_app'] = 'browser'
                            elif 'notepad' in exe.lower():
                                activity['active_app'] = 'notepad'
                        except:
                            pass
                    except:
                        pass
            
        except Exception as e:
            print(f"Windows activity error: {e}")
            
        return activity
    
    def _get_activity_macos(self):
        """Get activity info on macOS."""
        activity = {
            'active_app': 'unknown',
            'window_title': 'unknown',
            'active_window': None,
            'process_id': None
        }
        
        try:
            # Get active application from system events
            result = subprocess.run([
                'osascript', '-e', 
                'tell application "System Events" to name of every application process whose frontmost is true'
            ], capture_output=True, text=True, timeout=5)
            
            if result.stdout.strip():
                app_name = result.stdout.strip().split('\n')[0]
                activity['active_app'] = app_name
                
                # Try to get more window information
                try:
                    result = subprocess.run([
                        'osascript', '-e', 
                        'tell application "System Events" to name of process 1'
                    ], capture_output=True, text=True, timeout=5)
                    if result.stdout.strip():
                        activity['window_title'] = result.stdout.strip()
                except:
                    pass
                    
                self.apps_seen.add(activity['active_app'])
                
        except Exception as e:
            print(f"macOS activity error: {e}")
            
        return activity
    
    def _get_activity_linux(self):
        """Get activity info on Linux.

        Note: `xdotool getwindowpid` reads `_NET_WM_PID`, which sandboxed
        apps (snap/flatpak Chromium, etc.) can report from their own PID
        namespace — on the host that PID sometimes collides with an
        unrelated process (even a kernel thread like "kthreadd"), which
        would mislabel active_app and cause spurious activity-change
        flapping. WM_CLASS is used as the primary, PID-independent app
        identifier; the PID-resolved process name only overrides it once
        validated (psutil can actually inspect it, i.e. it's a real,
        accessible, non-kernel process).
        """
        activity = {
            'active_app': 'unknown',
            'window_title': 'unknown',
            'active_window': None,
            'process_id': None
        }

        try:
            win_id = subprocess.run(
                ['xdotool', 'getactivewindow'],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if not win_id.isdigit():
                return activity
            activity['active_window'] = win_id

            title = subprocess.run(
                ['xdotool', 'getwindowname', win_id],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if title:
                activity['window_title'] = title

            app_name = 'unknown'
            xprop_out = subprocess.run(
                ['xprop', '-id', win_id, 'WM_CLASS'],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            classes = re.findall(r'"([^"]*)"', xprop_out)
            if classes:
                # Second quoted string is the general class (e.g. "Chromium"),
                # first is the more specific instance name — prefer instance.
                app_name = classes[0].lower()

            pid_str = subprocess.run(
                ['xdotool', 'getwindowpid', win_id],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                activity['process_id'] = pid
                try:
                    process = psutil.Process(pid)
                    process.exe()  # raises for kernel threads / bogus PIDs
                    app_name = process.name() or app_name
                except Exception:
                    pass  # untrustworthy PID — keep the WM_CLASS-derived name

            activity['active_app'] = app_name
            if app_name != 'unknown':
                self.apps_seen.add(app_name)

        except Exception as e:
            print(f"Linux activity error: {e}")

        return activity
    
    def _list_open_windows_linux(self):
        """id -> app name for all currently open, WM-managed windows. Cheap
        (~15-20ms) — used to detect windows CLOSING so the pet can react
        instantly instead of waiting on the LLM.

        Excludes the pet's OWN windows by PID (not by name): the pet is a
        single in-process Qt app, so `os.getpid()` is exactly the PID every
        one of its native windows (main blob window + speech bubble) reports
        via `_NET_WM_PID`. Matching by PID rather than by app/class name is
        deliberate — the pet's WM_CLASS can show up as generic things like
        "py"/"python3" depending on how it was launched, so a name-based
        filter both under- and over-matches. It's also what fixes the
        "goodbye py" spam: the speech bubble is its own top-level window
        that gets un-mapped (hidden) and re-mapped every time a bubble
        appears/disappears, which otherwise looks exactly like a window
        closing on every bubble dismissal. PID exclusion drops it from
        tracking entirely, so its show/hide cycle never gets diffed.
        """
        windows = {}
        try:
            own_pid = os.getpid()
            pid_out = subprocess.run(
                ['wmctrl', '-lp'], capture_output=True, text=True, timeout=3,
            ).stdout
            pid_by_id = {}
            for line in pid_out.splitlines():
                parts = line.split(None, 3)
                if len(parts) < 3 or not parts[2].isdigit():
                    continue
                pid_by_id[parts[0]] = int(parts[2])

            class_out = subprocess.run(
                ['wmctrl', '-lx'], capture_output=True, text=True, timeout=3,
            ).stdout
            for line in class_out.splitlines():
                parts = line.split(None, 4)
                if len(parts) < 3:
                    continue
                win_id, wm_class = parts[0], parts[2]
                pid = pid_by_id.get(win_id)
                if pid is not None and pid == own_pid:
                    continue  # our own window (main blob or speech bubble)
                app = wm_class.rsplit('.', 1)[-1] if '.' in wm_class else wm_class
                app = app.strip()
                if not app:
                    continue
                windows[win_id] = app
        except Exception:
            pass
        return windows

    def poll_closed_windows(self):
        """Call periodically (e.g. once per monitor-loop tick). Returns a
        list of app names for windows that have closed since the previous
        call. Linux-only for now (wmctrl); returns [] on other platforms."""
        if not sys.platform.startswith('linux'):
            return []
        current = self._list_open_windows_linux()
        if self._known_windows is None:
            # First call — just establish the baseline, no false positives.
            self._known_windows = current
            return []
        closed_ids = set(self._known_windows) - set(current)
        closed_apps = [self._known_windows[win_id] for win_id in closed_ids]
        self._known_windows = current
        return closed_apps

    def get_activity_summary(self):
        """Get a summary of recent activities."""
        if not self.activity_history:
            return "No recent activity"
        
        # Create a summary
        recent = list(self.activity_history)[-5:]  # Last 5 activities
        
        summary = "Recent activities:\n"
        for i, activity in enumerate(recent, 1):
            app = activity['active_app'] or 'unknown'
            title = activity['window_title'] or 'unknown'
            summary += f"{i}. {app} - {title}\n"
            
        return summary
    
    def get_apps_seen(self):
        """Get list of applications we've seen."""
        return list(self.apps_seen)
    
    def monitor(self, interval=2):
        """Monitor activity continuously."""
        print("Starting advanced desktop pet activity monitor...")
        print("Press Ctrl+C to stop.")
        
        try:
            while True:
                activity = self.get_current_activity()
                if activity['active_app'] != self.current_activities['active_app']:
                    print(f"Activity change: {activity['active_app']} - {activity['window_title'][:50]}")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\nActivity monitoring stopped.")
            print(self.get_activity_summary())

# Example usage and development helper
if __name__ == "__main__":
    print("Initializing advanced desktop pet monitor...")
    monitor = AdvancedActivityMonitor()
    
    print("Testing monitor functionality...")
    activity = monitor.get_current_activity()
    print(f"Current activity: {activity}")
    
    activity_summary = monitor.get_activity_summary()
    print(f"Activity summary: {activity_summary}")
    
    apps_seen = monitor.get_apps_seen()
    print(f"Applications seen: {apps_seen}")
    
    # Uncomment below to start continuous monitoring
    # monitor.monitor()