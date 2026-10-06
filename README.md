# 🚆 Bangladesh Railway Live Ticket Monitor & Alert System

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, automated ticket availability monitor and multi-channel alerting system for Bangladesh Railway ([eticket.railway.gov.bd](https://eticket.railway.gov.bd)).

It continuously queries the official ticketing API across target dates, checks for available seats in all or specified seat classes, and immediately alerts you via **laptop audio sirens**, **email notifications**, and **Windows desktop toasts**.

---

## ✨ Features

- **⚡ Direct API Polling:** Directly queries the Shohoz ticketing API (`/bookings/search-trips-v2`) in ~100ms without browser overhead.
- **📅 Dual & Multi-Date Monitoring:** Simultaneously tracks multiple dates (e.g., weekend returns 26/27 Sept).
- **💺 All-Class Tracking:** Evaluates Snigdha, Shovon Chair (S_CHAIR), Shovon, AC Berth (AC_B), and AC Chair (AC_S).
- **🔊 Native Audio Siren:** Blazes a loud, urgent dual-tone alarm through your laptop speakers via `winsound.Beep`. Automatically self-silences after 3 bursts so it never locks up your computer.
- **📧 Zero-Config Email Alerts:** Delivers formatted HTML alert emails with direct booking links via FormSubmit without requiring complex SMTP setup.
- **💻 Windows Toast Notifications:** Pops up native Windows 10/11 notification banners.
- **⏸️ Smart Auto-Pause:** Automatically pauses background polling for 60 seconds whenever tickets are found, ensuring 100% of your network connection and token quota is dedicated to loading your browser checkout.
- **💤 Dual-Layer Anti-Sleep Lock:** Combines Windows kernel execution locks (`ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED`) with a background virtual idle-reset heartbeat (the Caffeine method). This prevents Windows 10/11 Modern Standby (S0) from suspending the process when the display dims or turns off.
- **🛡️ Ethical & Rate-Limit Safe:** Includes human-like randomized jitter to protect your account and IP from rate-limit triggers.

---

## 🚀 Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/xy3m/bd-railway-ticket-monitor.git
cd bd-railway-ticket-monitor
pip install -r requirements.txt
```

### 2. Copy Your Session (One-Time)
1. Open Chrome or Edge and log in to [eticket.railway.gov.bd/login](https://eticket.railway.gov.bd/login).
2. Press **F12** (Developer Tools) and click the **Console** tab.
3. Paste this one line and press **Enter**:
   ```javascript
   copy(JSON.stringify({token: localStorage.token, uudid: localStorage.uudid, ssdk: localStorage.ssdk}, null, 2))
   ```
   *(Your session is now automatically copied to your clipboard)*

### 3. Run the Monitor
```bash
python monitor.py
```
*(or double-click `run_monitor.bat`)*

When prompted on the first run, right-click to paste your clipboard and hit Enter. The monitor will save it to `session.json` and start scanning immediately!

---

## ⚙️ Configuration (`config.json`)

Customize your route, dates, and alerts in `config.json`:

```json
{
  "from_city": "Sylhet",
  "to_city": "Dhaka",
  "journey_targets": [
    {
      "date": "11-Oct-2026",
      "description": "11th October - Parabat Express & Upaban Express (All Seats)",
      "rules": [
        {
          "trains": ["PARABAT EXPRESS", "UPABAN EXPRESS"],
          "seat_classes": ["ALL"]
        }
      ]
    },
    {
      "date": "12-Oct-2026",
      "description": "12th October - Kalni Express & Jayentika Express (All Seats)",
      "rules": [
        {
          "trains": ["KALNI EXPRESS", "JAYENTIKA EXPRESS"],
          "seat_classes": ["ALL"]
        }
      ]
    }
  ],
  "seat_classes": [
    "ALL"
  ],
  "check_all_classes": true,
  "poll_interval_seconds": 2.5,
  "open_browser_on_alert": true,
  "prevent_sleep": true,
  "email": {
    "enabled": true,
    "recipient": "abdullahomarsayeem@gmail.com"
  },
  "sound": {
    "enabled": true,
    "beep_frequency_hz": 1800,
    "beep_duration_ms": 300
  },
  "toast_notification": {
    "enabled": true
  }
}
```

---

## 🧪 Testing Your Alerts

You can test your laptop speaker, Windows toast notification, and email delivery at any time without waiting for real tickets:
```bash
python test_alerts.py
```

---

## ⚠️ Legal & Ethical Disclaimer

This project is for **personal notification and research purposes only**.
- It **does not** automate ticket booking, bypass payment gateways, or bypass CAPTCHA.
- All purchases must be completed manually by the user using their own NID-verified railway account.
- The authors do not endorse or support ticket black-marketing, scalping, or any activity in violation of the Railway Act 1890 or website Terms of Service.

---

## 📄 License

MIT License. Feel free to use and customize for your personal journeys.
