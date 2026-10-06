import json
import os
import sys
import time
import random
import threading
import re
import ctypes
import atexit
from datetime import datetime
from typing import Dict, Any, List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

class WindowsSleepPreventer:
    """
    Multi-layer sleep prevention for Windows 10/11 (specifically Modern Standby S0 systems).
    Layer 1 (Kernel): SetThreadExecutionState with ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED,
                      and ES_AWAYMODE_REQUIRED to declare the system and display actively in use.
    Layer 2 (OS Heartbeat): Background thread sending a benign virtual F15 key tap every 30s
                            (the Caffeine method) to continuously reset the Windows user idle timer.
    """
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002
    ES_AWAYMODE_REQUIRED = 0x00000040
    VK_F15 = 0x7E
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self, interval_seconds: int = 30):
        self.interval_seconds = interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if sys.platform != "win32":
            return
        self._running = True
        self._apply_state()
        if not self._thread or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
            self._thread.start()

    def _apply_state(self):
        try:
            flags = (
                self.ES_CONTINUOUS
                | self.ES_SYSTEM_REQUIRED
                | self.ES_DISPLAY_REQUIRED
                | self.ES_AWAYMODE_REQUIRED
            )
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception:
            pass

    def _heartbeat_worker(self):
        """Periodically resets the Windows user idle timer to prevent S0 Modern Standby entry."""
        while self._running:
            try:
                self._apply_state()
                # Send invisible F15 key tap to reset Windows idle timer to 0
                ctypes.windll.user32.keybd_event(self.VK_F15, 0, 0, 0)
                ctypes.windll.user32.keybd_event(self.VK_F15, 0, self.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
            time.sleep(self.interval_seconds)

    def stop(self):
        if sys.platform != "win32":
            return
        self._running = False
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
        except Exception:
            pass


_sleep_preventer = WindowsSleepPreventer()


def prevent_windows_sleep():
    """Starts dual-layer sleep prevention."""
    _sleep_preventer.start()


def restore_windows_sleep():
    """Restores default Windows sleep settings."""
    _sleep_preventer.stop()


# Automatically restore system sleep on process exit
atexit.register(restore_windows_sleep)

from railway_api import RailwayApiClient, RailwayApiError, TokenExpiredError, RateLimitError
from sound_alert import SoundAlarm
from notifier import Notifier

CONFIG_PATH = "config.json"
SESSION_PATH = "session.json"


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Configuration file '{CONFIG_PATH}' not found.")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_session() -> Optional[Dict[str, str]]:
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("token") and data.get("uudid"):
                return data
    except Exception:
        pass
    return None


def save_session(session_data: Dict[str, str]):
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)
    print(f"\n[OK] Session saved to {SESSION_PATH}.")


def try_read_clipboard() -> Optional[str]:
    """Attempts to read text from system clipboard on Windows using tkinter or PowerShell."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        if text and len(text.strip()) > 20:
            return text.strip()
    except Exception:
        pass
    try:
        import subprocess
        res = subprocess.run(["powershell", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=2)
        if res.stdout and len(res.stdout.strip()) > 20:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def extract_session_from_text(text: str) -> Optional[Dict[str, str]]:
    """Extracts token, uudid, and ssdk from raw text via JSON or regex."""
    if not text:
        return None
    text = text.strip()

    # 1. Strict JSON parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "token" in parsed:
            return {
                "token": str(parsed["token"]).strip(),
                "uudid": str(parsed.get("uudid", "6f06c9e682494f2657d32e7a588d60eb")).strip(),
                "ssdk": str(parsed.get("ssdk", "")).strip()
            }
    except Exception:
        pass

    # 2. Regex search for token, uudid, ssdk in multi-line or fragmented pasted text
    t_match = re.search(r'["\']?token["\']?\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]+)', text)
    u_match = re.search(r'["\']?uudid["\']?\s*[:=]\s*["\']?([A-Za-z0-9_\-]+)', text)
    s_match = re.search(r'["\']?ssdk["\']?\s*[:=]\s*["\']?([A-Za-z0-9_\-]+)', text)

    if t_match and len(t_match.group(1)) > 30:
        return {
            "token": t_match.group(1).strip(),
            "uudid": u_match.group(1).strip() if u_match else "6f06c9e682494f2657d32e7a588d60eb",
            "ssdk": s_match.group(1).strip() if s_match else ""
        }

    # 3. Raw JWT token pasted directly
    cleaned = text.replace("Bearer ", "").strip()
    if len(cleaned) > 50 and cleaned.startswith("eyJ"):
        return {
            "token": cleaned,
            "uudid": "6f06c9e682494f2657d32e7a588d60eb",
            "ssdk": ""
        }

    return None


def prompt_user_for_session() -> Dict[str, str]:
    # 1. Check if clipboard ALREADY contains valid session JSON
    clip_text = try_read_clipboard()
    if clip_text:
        session_from_clip = extract_session_from_text(clip_text)
        if session_from_clip:
            print("\n[OK] Automatically detected session credentials from your clipboard!")
            save_session(session_from_clip)
            return session_from_clip

    print("\n" + "=" * 76)
    print("                BANGLADESH RAILWAY SESSION SETUP")
    print("=" * 76)
    print("Bangladesh Railway requires an active user session to search for tickets.")
    print("Follow these 3 quick steps:")
    print("  1. Open Chrome/Edge and go to: https://eticket.railway.gov.bd/login")
    print("  2. Log in with your mobile number and password.")
    print("  3. Press F12 to open Developer Tools -> click the 'Console' tab.")
    print("  4. Paste this command and hit Enter:\n")
    print("     copy(JSON.stringify({token: localStorage.token, uudid: localStorage.uudid, ssdk: localStorage.ssdk}, null, 2))\n")
    print("  5. Your session credentials are now in your clipboard!")
    print("=" * 76)

    accumulated = []

    while True:
        # Check clipboard again in case user just copied it
        clip_text = try_read_clipboard()
        if clip_text:
            session_from_clip = extract_session_from_text(clip_text)
            if session_from_clip:
                print("\n[OK] Automatically detected session credentials from clipboard!")
                save_session(session_from_clip)
                return session_from_clip

        print("\nPaste the copied JSON (or press Enter if copied to clipboard):")
        try:
            line = input().strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(0)

        if not line:
            # Re-check clipboard on Enter
            clip_text = try_read_clipboard()
            if clip_text:
                session_from_clip = extract_session_from_text(clip_text)
                if session_from_clip:
                    print("\n[OK] Loaded session credentials from clipboard.")
                    save_session(session_from_clip)
                    return session_from_clip
            continue

        accumulated.append(line)
        combined = "\n".join(accumulated)

        # Try parsing accumulated lines
        session_data = extract_session_from_text(combined) or extract_session_from_text(line)
        if session_data:
            save_session(session_data)
            return session_data

        if len(accumulated) > 10:
            accumulated = []
            print("[!] Could not parse session credentials. Please copy from browser console again.")


class RailwayTicketMonitor:
    def __init__(self):
        self.config = load_config()
        self.session = load_session()

        if not self.session:
            self.session = prompt_user_for_session()

        self.api_client = RailwayApiClient(
            token=self.session["token"],
            uudid=self.session["uudid"],
            ssdk=self.session.get("ssdk")
        )

        self.alarm = SoundAlarm(
            frequency=self.config.get("sound", {}).get("beep_frequency_hz", 1800),
            duration_ms=self.config.get("sound", {}).get("beep_duration_ms", 300)
        )
        self.notifier = Notifier(self.config)

        self.from_city = self.config.get("from_city", "Sylhet")
        self.to_city = self.config.get("to_city", "Dhaka")
        
        # Load journey targets with per-date train rules
        self.targets: List[Dict[str, Any]] = self.config.get("journey_targets", [])
        if not self.targets:
            legacy_dates = self.config.get("journey_dates", ["11-Oct-2026", "12-Oct-2026"])
            self.targets = [{"date": d, "trains": ["ALL"]} for d in legacy_dates]

        # Target seat classes (e.g. SNIGDHA, AC_S)
        if "seat_classes" in self.config and isinstance(self.config["seat_classes"], list):
            self.seat_classes = [c.strip().upper() for c in self.config["seat_classes"] if c.strip()]
        elif self.config.get("seat_class"):
            raw_c = str(self.config.get("seat_class", ""))
            self.seat_classes = [c.strip().upper() for c in raw_c.split(",") if c.strip()]
        else:
            self.seat_classes = ["SNIGDHA", "AC_S"]

        self.check_all_classes = self.config.get("check_all_classes", False)
        self.poll_interval = float(self.config.get("poll_interval_seconds", 2.5))
        self.prevent_sleep = bool(self.config.get("prevent_sleep", True))

        if self.prevent_sleep:
            prevent_windows_sleep()

        self.running = True
        self.stats = {
            "checks_count": 0,
            "tickets_found_count": 0,
            "last_latency_ms": 0,
            "start_time": time.time()
        }
        self.resume_event = threading.Event()

    def _listen_for_alarm_stop(self):
        """Background thread to allow user to press Enter to stop alarm or resume immediately."""
        while self.running:
            try:
                line = sys.stdin.readline()
                if self.alarm.is_alarming():
                    self.alarm.stop_alarm()
                    print("\n[ALARM SILENCED] Audio alarm stopped by user.\n")
                # Also signal resume from pause
                self.resume_event.set()
            except Exception:
                pass
            time.sleep(0.3)

    def _pause_after_alert(self, duration_seconds: int = 60):
        """Temporarily pauses API polling so the browser gets 100% clean bandwidth and unthrottled access."""
        print("=" * 76)
        print(f"⏸️  MONITOR PAUSED FOR {duration_seconds} SECONDS TO FREE UP BANDWIDTH FOR YOUR BROWSER!")
        print("   👉 Complete your booking in the browser now.")
        print("   👉 Press [ENTER] in this window anytime to resume monitoring immediately.")
        print("=" * 76 + "\n")
        self.resume_event.clear()
        self.resume_event.wait(timeout=duration_seconds)
        print("\n[▶] Resuming live ticket monitoring...\n")

    def print_banner(self):
        print("\n" + "=" * 76)
        print("      🚆 BANGLADESH RAILWAY LIVE TICKET MONITOR & ALERT SYSTEM")
        print("=" * 76)
        print(f" Route        : {self.from_city} -> {self.to_city}")
        for idx, t in enumerate(self.targets, 1):
            if t.get("rules"):
                rule_strs = []
                for r in t["rules"]:
                    tr = "All Trains" if "ALL" in [x.upper() for x in r.get("trains", ["ALL"])] else "/".join(r.get("trains", []))
                    cl = "/".join(r.get("seat_classes", []))
                    rule_strs.append(f"{tr} [{cl}]")
                summary = " + ".join(rule_strs)
            else:
                train_list = t.get("trains", ["ALL"])
                train_desc = "All Trains" if "ALL" in [tr.upper() for tr in train_list] else ", ".join(train_list)
                summary = f"{train_desc} [{', '.join(self.seat_classes)}]"
            note = f" ({t['description']})" if t.get("description") else ""
            print(f" Target #{idx}   : {t['date']} -> {summary}{note}")
        class_desc = "ALL SEATS" if self.check_all_classes else ", ".join(self.seat_classes)
        print(f" Monitored Cls: {class_desc}")
        print(f" Interval     : {self.poll_interval:.1f} second(s)")
        print(f" Email Alert  : {self.config.get('email', {}).get('recipient')}")
        print(f" Sound Alert  : Windows Speaker Alarm (winsound.Beep)")
        power_mode_str = "Active (Dual-Layer: Kernel Lock + F15 Heartbeat)" if self.prevent_sleep else "Disabled (System default)"
        print(f" Anti-Sleep   : {power_mode_str}")
        print("=" * 76)
        print(" Press Ctrl+C at any time to stop monitoring.\n")

    def run(self):
        self.print_banner()

        if self.prevent_sleep:
            prevent_windows_sleep()

        try:
            self._run_monitor_loop()
        finally:
            if self.prevent_sleep:
                restore_windows_sleep()

    def _run_monitor_loop(self):
        # Start input listener thread for stopping alarm
        input_thread = threading.Thread(target=self._listen_for_alarm_stop, daemon=True)
        input_thread.start()

        target_idx = 0
        consecutive_errors = 0

        while self.running:
            if self.prevent_sleep:
                prevent_windows_sleep()
            target = self.targets[target_idx % len(self.targets)]
            target_idx += 1
            target_date = target["date"]
            target_rules = target.get("rules")
            if not target_rules:
                target_rules = [{
                    "trains": target.get("trains", ["ALL"]),
                    "seat_classes": target.get("seat_classes", self.seat_classes)
                }]
            self.stats["checks_count"] += 1
            now_str = datetime.now().strftime("%H:%M:%S")

            # Default URL for manual access (uses first target class, e.g. SNIGDHA)
            default_class = "SNIGDHA"
            if target_rules and target_rules[0].get("seat_classes"):
                cand = str(target_rules[0]["seat_classes"][0]).strip().upper()
                if cand not in ["ALL", "ANY", ""]:
                    default_class = cand
            elif self.seat_classes:
                cand = str(self.seat_classes[0]).strip().upper()
                if cand not in ["ALL", "ANY", ""]:
                    default_class = cand

            booking_url = (
                f"https://eticket.railway.gov.bd/booking/train/search"
                f"?fromcity={self.from_city}&tocity={self.to_city}&doj={target_date}&class={default_class}"
            )

            try:
                available_matches, all_trains, latency = self.api_client.search_trips(
                    from_city=self.from_city,
                    to_city=self.to_city,
                    date_of_journey=target_date,
                    seat_classes=self.seat_classes,
                    seat_class=default_class,
                    check_all_classes=self.check_all_classes,
                    rules=target_rules
                )
                self.stats["last_latency_ms"] = latency
                consecutive_errors = 0

                # Check if tickets found
                if available_matches:
                    self.stats["tickets_found_count"] += 1
                    total_seats = sum(m["online_seats"] for m in available_matches)
                    
                    # Direct URL targeting the exact class where seats were found
                    matched_class = available_matches[0]["seat_class"]
                    booking_url = (
                        f"https://eticket.railway.gov.bd/booking/train/search"
                        f"?fromcity={self.from_city}&tocity={self.to_city}&doj={target_date}&class={matched_class}"
                    )

                    # 1. Beep alarm immediately
                    if not self.alarm.is_alarming():
                        self.alarm.start_alarm()

                    # 2. Print prominent alert banner
                    print("\n" + "*" * 76)
                    print(f"🚨 [TICKETS AVAILABLE!] {now_str} | Date: {target_date} | Total Seats: {total_seats}")
                    for m in available_matches:
                        print(f"   🚆 {m['train_name']} [{m['seat_class']}]: {m['online_seats']} Online Seats | Fare: ৳{m.get('fare', 'N/A')}")
                    print(f"   👉 BUY NOW: {booking_url}")
                    print("   🔊 Laptop speaker is beeping! Press [ENTER] to silence the alarm.")
                    print("*" * 76 + "\n")

                    # Log to persistent file
                    try:
                        with open("alerts.log", "a", encoding="utf-8") as log_f:
                            for m in available_matches:
                                log_f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {target_date} | {m['train_name']} [{m['seat_class']}]: {m['online_seats']} Online Seats | URL: {booking_url}\n")
                    except Exception:
                        pass

                    # 3. Dispatch Notifications (Email, Toast, ntfy, open browser)
                    self.notifier.dispatch_alert(
                        matches=available_matches,
                        from_city=self.from_city,
                        to_city=self.to_city,
                        doj=target_date,
                        booking_url=booking_url
                    )

                    # 4. PAUSE monitor so it doesn't compete with your browser for network or token quota!
                    self._pause_after_alert(duration_seconds=60)

                else:
                    # If previously alarming and seats dropped to 0, stop alarm
                    if self.alarm.is_alarming():
                        self.alarm.stop_alarm()

                    # Concise status output
                    train_summary = ", ".join([
                        f"{t['train_name'].split('(')[0].strip()}: 0"
                        for t in all_trains[:4]
                    ])
                    rule_labels = []
                    for r in target_rules:
                        tr = "All" if "ALL" in [x.upper() for x in r.get("trains", ["ALL"])] else "/".join(r.get("trains", []))
                        cl = "/".join(r.get("seat_classes", []))
                        rule_labels.append(f"{tr}:[{cl}]")
                    filter_summary = " & ".join(rule_labels)
                    print(
                        f"[{now_str}] Check #{self.stats['checks_count']:04d} | "
                        f"{target_date} ({filter_summary}) | {self.from_city}->{self.to_city} | "
                        f"{latency:.0f}ms | Seats: 0 | {train_summary}"
                    )

            except TokenExpiredError:
                print("\n[!] SESSION TOKEN EXPIRED!")
                self.alarm.beep_once(1000, 800)
                self.session = prompt_user_for_session()
                self.api_client.update_credentials(
                    token=self.session["token"],
                    uudid=self.session["uudid"],
                    ssdk=self.session.get("ssdk")
                )
                print("[OK] Resuming live monitoring...\n")
                continue

            except RateLimitError:
                print(f"[{now_str}] [!] Shohoz rate limit (429). Pausing for 8 seconds to cool down...")
                time.sleep(8)
                continue

            except RailwayApiError as e:
                consecutive_errors += 1
                print(f"[{now_str}] [API Notice] {e}")
                if consecutive_errors > 5:
                    print("[!] Consecutive errors detected. Pausing for 5 seconds...")
                    time.sleep(5)

            except Exception as e:
                print(f"[{now_str}] [Unexpected Error] {e}")

            # Sleep between requests with subtle human-like jitter (2.6s - 3.1s)
            jitter = random.uniform(0.1, 0.6)
            time.sleep(max(1.0, self.poll_interval + jitter))


if __name__ == "__main__":
    try:
        monitor = RailwayTicketMonitor()
        monitor.run()
    except KeyboardInterrupt:
        print("\n[!] Monitoring stopped by user. Exiting gracefully.")
    finally:
        restore_windows_sleep()
        sys.exit(0)
