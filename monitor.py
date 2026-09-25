import json
import os
import sys
import time
import random
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

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


def prompt_user_for_session() -> Dict[str, str]:
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

    while True:
        print("\nPaste the copied JSON (or paste your Bearer token string), then press Enter:")
        lines = []
        try:
            line = input().strip()
            if not line:
                continue
            lines.append(line)
            # If line is JSON start '{', read until matching '}'
            if line.startswith("{") and not line.endswith("}"):
                while True:
                    next_line = input().strip()
                    lines.append(next_line)
                    if next_line.endswith("}"):
                        break
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(0)

        raw_input = "\n".join(lines).strip()

        # Try parsing as JSON
        try:
            parsed = json.loads(raw_input)
            if isinstance(parsed, dict) and "token" in parsed and "uudid" in parsed:
                session_data = {
                    "token": str(parsed["token"]).strip(),
                    "uudid": str(parsed["uudid"]).strip(),
                    "ssdk": str(parsed.get("ssdk", "")).strip()
                }
                save_session(session_data)
                return session_data
        except Exception:
            pass

        # If user just pasted raw token
        if len(raw_input) > 30 and (" " not in raw_input or raw_input.startswith("eyJ")):
            session_data = {
                "token": raw_input.replace("Bearer ", "").strip(),
                "uudid": "manual-device-id",
                "ssdk": ""
            }
            save_session(session_data)
            return session_data

        print("[!] Input could not be parsed as valid session JSON. Please try again.")


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
        self.dates = self.config.get("journey_dates", ["26-Sep-2026", "27-Sep-2026"])
        self.seat_class = self.config.get("seat_class", "SNIGDHA")
        self.check_all_classes = self.config.get("check_all_classes", False)
        self.poll_interval = float(self.config.get("poll_interval_seconds", 1.0))

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
        print(f" Target Dates : {', '.join(self.dates)}")
        class_desc = "ALL SEATS (Snigdha, S_Chair, Shovon, AC Berth, AC Chair)" if self.check_all_classes or self.seat_class.upper() == "ALL" else self.seat_class
        print(f" Target Class : {class_desc}")
        print(f" Interval     : {self.poll_interval:.1f} second(s)")
        print(f" Email Alert  : {self.config.get('email', {}).get('recipient')}")
        print(f" Sound Alert  : Windows Speaker Alarm (winsound.Beep)")
        print("=" * 76)
        print(" Press Ctrl+C at any time to stop monitoring.\n")

    def run(self):
        self.print_banner()

        # Start input listener thread for stopping alarm
        input_thread = threading.Thread(target=self._listen_for_alarm_stop, daemon=True)
        input_thread.start()

        date_idx = 0
        consecutive_errors = 0

        while self.running:
            target_date = self.dates[date_idx % len(self.dates)]
            date_idx += 1
            self.stats["checks_count"] += 1
            now_str = datetime.now().strftime("%H:%M:%S")

            # Default URL for manual access
            default_class = "SNIGDHA" if self.seat_class.upper() in ["ALL", "ANY", ""] else self.seat_class
            booking_url = (
                f"https://eticket.railway.gov.bd/booking/train/search"
                f"?fromcity={self.from_city}&tocity={self.to_city}&doj={target_date}&class={default_class}"
            )

            try:
                available_matches, all_trains, latency = self.api_client.search_trips(
                    from_city=self.from_city,
                    to_city=self.to_city,
                    date_of_journey=target_date,
                    seat_class=self.seat_class,
                    check_all_classes=self.check_all_classes
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
                    target_class_label = "ALL SEATS" if self.check_all_classes or self.seat_class.upper() == "ALL" else self.seat_class
                    print(
                        f"[{now_str}] Check #{self.stats['checks_count']:04d} | "
                        f"{target_date} | {self.from_city}->{self.to_city} | "
                        f"{latency:.0f}ms | Seats: 0 ({target_class_label}) | {train_summary}"
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
        sys.exit(0)
