import json
import time
import urllib.request
import urllib.parse
import subprocess
import webbrowser
from typing import List, Dict, Any

class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.email_config = config.get("email", {})
        self.recipient = self.email_config.get("recipient", "your_email@example.com")
        self.email_enabled = self.email_config.get("enabled", True)
        self.toast_enabled = config.get("toast_notification", {}).get("enabled", True)
        self.auto_open_browser = config.get("open_browser_on_alert", True)
        
        # Anti-flood tracking: {(train_name, doj, seat_class): (last_alert_timestamp, last_seats_count)}
        self.alert_history = {}
        self.cooldown_seconds = 180  # 3 minutes cooldown before re-emailing for identical seats

    def send_formsubmit_email(self, subject: str, data: Dict[str, Any]) -> bool:
        """Sends an HTML email to the recipient using FormSubmit without requiring manual API keys."""
        if not self.email_enabled or not self.recipient:
            return False

        endpoint = f"https://formsubmit.co/ajax/{self.recipient}"
        payload = {
            "_subject": subject,
            "_template": "table",
            "_captcha": "false",
            **data
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://eticket.railway.gov.bd",
            "Origin": "https://eticket.railway.gov.bd",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8", errors="ignore")
                res_json = json.loads(res_body)
                if res_json.get("success") == "true":
                    return True
                else:
                    # Could be pending activation message
                    print(f"[Email Notice] FormSubmit status: {res_json.get('message')}")
                    return False
        except Exception as e:
            print(f"[Email Error] Failed to send email via FormSubmit: {e}")
            return False

    def send_ntfy_push(self, title: str, message: str, click_url: str = "") -> bool:
        """Sends an instant push notification via ntfy.sh (viewable in browser or mobile app)."""
        topic = "bd_railway_ticket_alerts"
        url = f"https://ntfy.sh/{topic}"
        headers = {
            "Title": title,
            "Priority": "urgent",
            "Tags": "train,rotating_light,ticket"
        }
        if click_url:
            headers["Click"] = click_url

        try:
            req = urllib.request.Request(
                url,
                data=message.encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except Exception as e:
            # Silent fallback
            return False

    def show_windows_toast(self, title: str, message: str):
        """Displays a native Windows 10/11 Toast notification banner."""
        if not self.toast_enabled:
            return

        # Escape quotes for PowerShell XML template
        safe_title = title.replace('"', '`"').replace('<', '&lt;').replace('>', '&gt;')
        safe_message = message.replace('"', '`"').replace('<', '&lt;').replace('>', '&gt;')

        script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
    <visual>
        <binding template="ToastText02">
            <text id="1">{safe_title}</text>
            <text id="2">{safe_message}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("BD Railway Ticket Monitor").Show($toast)
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                timeout=5
            )
        except Exception:
            pass

    def open_booking_page(self, booking_url: str):
        """Opens the booking URL in browser, strictly throttled to at most ONE tab every 5 minutes."""
        now = time.time()
        if self.auto_open_browser and booking_url:
            if now - getattr(self, "last_browser_open_time", 0) > 300:
                self.last_browser_open_time = now
                try:
                    webbrowser.open(booking_url)
                    print("  👉 [Browser] Opened 1 tab to booking page. (Throttled to prevent flooding)")
                except Exception:
                    pass

    def dispatch_alert(
        self,
        matches: List[Dict[str, Any]],
        from_city: str,
        to_city: str,
        doj: str,
        booking_url: str
    ):
        """
        Dispatches all configured alerts for discovered tickets.
        Applies smart throttling so email is not spammed every second.
        """
        now = time.time()
        new_or_changed = []

        for m in matches:
            key = (m["train_name"], doj, m["seat_class"])
            last_time, last_seats = self.alert_history.get(key, (0, 0))
            current_seats = m["online_seats"]

            # If tickets just appeared, or seat count changed, or cooldown elapsed
            if current_seats > 0:
                if (now - last_time > self.cooldown_seconds) or (current_seats != last_seats):
                    self.alert_history[key] = (now, current_seats)
                    new_or_changed.append(m)

        if not new_or_changed:
            return  # Already alerted recently for this exact seat state

        # 1. Prepare alert text
        train_summaries = [
            f"{m['train_name']} ({m['seat_class']}): {m['online_seats']} SEATS (Fare: ৳{m.get('fare', 'N/A')})"
            for m in new_or_changed
        ]
        summary_text = "\n".join(train_summaries)
        subject = f"🚨 TICKET ALERT: {from_city} -> {to_city} ({doj})"

        print(f"\n[ALERT DISPATCHED] {subject}")
        for s in train_summaries:
            print(f"  -> {s}")
        print(f"  -> Booking Link: {booking_url}\n")

        # 2. Windows Toast
        toast_body = f"{doj}: " + ", ".join([f"{m['train_name']}: {m['online_seats']} seat(s)" for m in new_or_changed[:2]])
        self.show_windows_toast("BD Railway Ticket Available!", toast_body)

        # 3. Open Browser to Booking Page
        self.open_booking_page(booking_url)

        # 4. Instant ntfy Push Notification
        ntfy_body = f"Tickets found for {from_city} -> {to_city} on {doj}!\n\n{summary_text}\n\nBook immediately: {booking_url}"
        self.send_ntfy_push(subject, ntfy_body, click_url=booking_url)

        # 5. FormSubmit Email
        email_data = {
            "Alert": f"Tickets available on {doj}!",
            "Route": f"{from_city} to {to_city}",
            "Date of Journey": doj,
            "Available Trains": summary_text,
            "Direct Booking Link": booking_url,
            "Notice": "Please log in and complete your booking as quickly as possible before seats sell out."
        }
        self.send_formsubmit_email(subject, email_data)
