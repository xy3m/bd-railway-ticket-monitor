import time
import threading
import sys

# Native Windows sound
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


class SoundAlarm:
    def __init__(self, frequency=1800, duration_ms=300):
        self.frequency = frequency
        self.duration_ms = duration_ms
        self._is_alarming = False
        self._alarm_thread = None
        self._lock = threading.Lock()

    def _alarm_loop(self):
        # Beeps in bursts of 6 pulses, pauses, repeats up to 3 times, then self-silences
        bursts = 0
        while self._is_alarming and bursts < 3:
            bursts += 1
            for _ in range(6):
                if not self._is_alarming:
                    return
                if HAS_WINSOUND:
                    try:
                        winsound.Beep(self.frequency, self.duration_ms)
                        time.sleep(0.06)
                        winsound.Beep(int(self.frequency * 1.25), self.duration_ms)
                        time.sleep(0.12)
                    except Exception:
                        sys.stdout.write('\a')
                        sys.stdout.flush()
                        time.sleep(0.4)
                else:
                    sys.stdout.write('\a')
                    sys.stdout.flush()
                    time.sleep(0.4)

            # Short pause between bursts
            for _ in range(30):
                if not self._is_alarming:
                    return
                time.sleep(0.1)

        # Self-silence after bursts finish
        self._is_alarming = False

    def start_alarm(self):
        """Starts non-blocking repeating alarm."""
        with self._lock:
            if self._is_alarming:
                return
            self._is_alarming = True
            self._alarm_thread = threading.Thread(target=self._alarm_loop, daemon=True)
            self._alarm_thread.start()

    def stop_alarm(self):
        """Stops the repeating alarm."""
        with self._lock:
            self._is_alarming = False

    def is_alarming(self):
        return self._is_alarming

    def beep_once(self, freq=None, duration=None):
        """Plays a single short beep."""
        f = freq or self.frequency
        d = duration or self.duration_ms
        if HAS_WINSOUND:
            try:
                winsound.Beep(f, d)
            except Exception:
                sys.stdout.write('\a')
                sys.stdout.flush()
        else:
            sys.stdout.write('\a')
            sys.stdout.flush()


if __name__ == "__main__":
    print("Testing sound alarm for 3 seconds...")
    alarm = SoundAlarm()
    alarm.start_alarm()
    time.sleep(3)
    alarm.stop_alarm()
    print("Sound alarm test complete.")
