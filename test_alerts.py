import json
import time
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sound_alert import SoundAlarm
from notifier import Notifier

def run_test():
    config_file = "config.json"
    if not os.path.exists(config_file):
        print(f"Error: {config_file} not found.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)

    print("=" * 60)
    print("  BANGLADESH RAILWAY MONITOR - ALERT SYSTEM SELF-TEST")
    print("=" * 60)

    # 1. Test Sound Alarm
    print("\n[1/3] Testing Laptop Beeping Sound (3 seconds)...")
    alarm = SoundAlarm(
        frequency=config.get("sound", {}).get("beep_frequency_hz", 1800),
        duration_ms=config.get("sound", {}).get("beep_duration_ms", 300)
    )
    alarm.start_alarm()
    time.sleep(3)
    alarm.stop_alarm()
    print("  -> Beeping sound completed.")

    # 2. Test Notifier (Toast & Push)
    print("\n[2/3] Testing Windows Toast Notification...")
    notifier = Notifier(config)
    notifier.show_windows_toast(
        "Test Ticket Alert",
        "Self-test: Laptop speaker and notification system are working!"
    )
    print("  -> Windows Toast sent.")

    # 3. Test Email via FormSubmit
    recipient = config.get("email", {}).get("recipient", "your_email@example.com")
    print(f"\n[3/3] Sending Test Email to {recipient}...")
    success = notifier.send_formsubmit_email(
        "🚨 BD Railway Ticket Alert Test",
        {
            "Test Message": "This is a verification test from your Bangladesh Railway Monitor.",
            "Status": "System is active and monitoring.",
            "Route": f"{config.get('from_city')} -> {config.get('to_city')}",
            "Targets": "; ".join([
                f"{t['date']} ({t.get('description', '')})" if t.get("description") else f"{t['date']}"
                for t in config.get("journey_targets", [])
            ]) if config.get("journey_targets") else ", ".join(config.get("journey_dates", [])),
            "Target Classes": ", ".join(config.get("seat_classes", [])) if config.get("seat_classes") else config.get("seat_class", "SNIGDHA, AC_S")
        }
    )
    if success:
        print(f"  -> Test email successfully delivered to {recipient}!")
    else:
        print(f"  -> FormSubmit notice: Check your inbox ({recipient}) for an initial 'Activate Form' confirmation email if this is the first time.")

    print("\n" + "=" * 60)
    print("Self-test complete! Run 'python monitor.py' to begin live monitoring.")
    print("=" * 60)

if __name__ == "__main__":
    run_test()
