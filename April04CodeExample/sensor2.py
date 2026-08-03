# Posture Checker - CircuitPython
# Hardware: Adafruit ESP32-S3 Feather (8MB Flash, No PSRAM)
# Sensors:  FSR on A0, FSR on A1 (velostat/conductive sheet compatible)
# BLE:      Adafruit Bluefruit Connect app (UART mode)
#
# Wiring:
#   FSR1: one leg → 3.3V, other leg → A0; 10K pulldown from A0 → GND
#   FSR2: one leg → 3.3V, other leg → A1; 10K pulldown from A1 → GND
#   Velostat (optional swap-in): same wiring, just replace the FSR
#
# Required libraries in /lib:
#   adafruit_ble/
#   adafruit_bluefruit_connect/
#   neopixel.mpy

import time
import board
import analogio
import neopixel
import adafruit_ble
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

# ── Resistor config ──────────────────────────────────────────────────────────
PULLDOWN_OHMS  = 10_000
REFERENCE_OHMS = 10_000
SCALE = REFERENCE_OHMS / PULLDOWN_OHMS

# ── Calibration config ───────────────────────────────────────────────────────
CALIBRATION_SAMPLES   = 20    # number of readings averaged during calibration
CALIBRATION_DELAY     = 0.15  # seconds between each sample (~3 s total)
DEVIATION_THRESHOLD   = 0.20  # 20 % deviation from baseline triggers an alert

# ── Analog inputs ────────────────────────────────────────────────────────────
fsr1 = analogio.AnalogIn(board.A0)
fsr2 = analogio.AnalogIn(board.A1)

# ── Calibration state ────────────────────────────────────────────────────────
calibration = {
    "fsr1_baseline": None,
    "fsr2_baseline": None,
    "is_calibrated": False,
}

# ── BLE setup ────────────────────────────────────────────────────────────────
ble  = adafruit_ble.BLERadio()
uart = UARTService()
advertisement = ProvideServicesAdvertisement(uart)

# ── Onboard NeoPixel (ESP32-S3 Feather has one on NEOPIXEL pin) ──────────────
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=1.0, auto_write=True)

# Colour constants  (R, G, B)
COLOR_OFF        = (0,   0,   0)
COLOR_GOOD       = (0,   20,  0)    # dim green  — good posture
COLOR_ALERT      = (255, 0,   0)    # bright red — bad posture (flash ON phase)
COLOR_UNCALIB    = (0,   0,   20)   # dim blue   — not yet calibrated
COLOR_CALIBRATING= (255, 165, 0)    # orange     — calibration in progress

# Pulse state for the alert animation
import math
PULSE_PERIOD  = 1.5                 # seconds for one full breathe-in + breathe-out cycle
_pulse_start  = 0.0                 # set when posture_bad first becomes True


def led_good():
    """Steady dim green — posture is fine."""
    pixel.brightness = 1.0
    pixel[0] = COLOR_GOOD


def led_alert_tick():
    """
    Call this frequently inside the main loop when posture is bad.
    Smoothly pulses bright red using a sine wave (breathing effect).
    No blocking sleeps — safe to call every loop iteration.
    """
    phase      = (time.monotonic() - _pulse_start) / PULSE_PERIOD  # 0..1 per cycle
    brightness = (math.sin(phase * 2 * math.pi - math.pi / 2) + 1) / 2
    pixel.brightness = brightness
    pixel[0]   = COLOR_ALERT


def led_uncalibrated():
    """Dim blue — device is connected but not yet calibrated."""
    pixel.brightness = 1.0
    pixel[0] = COLOR_UNCALIB


def led_calibrating():
    """Orange — calibration is actively running."""
    pixel.brightness = 1.0
    pixel[0] = COLOR_CALIBRATING


def led_off():
    """All off — BLE disconnected / idle."""
    pixel.brightness = 1.0
    pixel[0] = COLOR_OFF


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_reading(pin):
    """Return a 10-bit FSR reading (0–1023) from a 16-bit analog pin."""
    return pin.value >> 6


def pressure_label(reading, thresholds):
    """
    Map a raw reading to a human-readable pressure label.
    thresholds: list of (scaled_limit, label) pairs in ascending order,
                plus a final fallback label.
    """
    for limit, label in thresholds:
        if reading < int(limit * SCALE):
            return label
    return thresholds[-1][1]   # fallback (highest bucket)


FSR1_THRESHOLDS = [
    (10,  "No pressure"),
    (250, "Light touch"),
    (400, "Light squeeze"),
    (900, "Medium squeeze"),
    (float("inf"), "Big squeeze"),
]

FSR2_THRESHOLDS = [
    (5,   "No pressure"),
    (100, "Light touch"),
    (250, "Light squeeze"),
    (450, "Medium squeeze"),
    (float("inf"), "Big squeeze"),
]


def uart_println(uart_svc, text):
    """Send a line of text over BLE UART."""
    uart_svc.write((text + "\r\n").encode())


def run_calibration(uart_svc):
    """
    Average CALIBRATION_SAMPLES readings for each sensor and store baselines.
    Sends progress updates over UART so the user can follow along.
    """
    uart_println(uart_svc, "")
    uart_println(uart_svc, "=== CALIBRATION STARTED ===")
    uart_println(uart_svc, "Sit in your comfortable rest/good-posture position.")
    uart_println(uart_svc, f"Taking {CALIBRATION_SAMPLES} samples over "
                           f"~{int(CALIBRATION_SAMPLES * CALIBRATION_DELAY)} seconds...")
    uart_println(uart_svc, "")

    led_calibrating()   # orange while sampling

    sum1 = 0
    sum2 = 0

    for i in range(1, CALIBRATION_SAMPLES + 1):
        sum1 += get_reading(fsr1)
        sum2 += get_reading(fsr2)

        # Simple progress bar every 5 samples
        if i % 5 == 0:
            pct = int((i / CALIBRATION_SAMPLES) * 100)
            bar = "#" * (pct // 10) + "." * (10 - pct // 10)
            uart_println(uart_svc, f"  [{bar}] {pct}%")

        time.sleep(CALIBRATION_DELAY)

    baseline1 = sum1 / CALIBRATION_SAMPLES
    baseline2 = sum2 / CALIBRATION_SAMPLES

    calibration["fsr1_baseline"]  = baseline1
    calibration["fsr2_baseline"]  = baseline2
    calibration["is_calibrated"]  = True

    uart_println(uart_svc, "")
    uart_println(uart_svc, "=== CALIBRATION COMPLETE ===")
    uart_println(uart_svc, f"  FSR1 baseline : {baseline1:.1f}  "
                           f"({pressure_label(int(baseline1), FSR1_THRESHOLDS)})")
    uart_println(uart_svc, f"  FSR2 baseline : {baseline2:.1f}  "
                           f"({pressure_label(int(baseline2), FSR2_THRESHOLDS)})")
    uart_println(uart_svc, f"  Alert threshold: ±{int(DEVIATION_THRESHOLD * 100)}% deviation")
    uart_println(uart_svc, "Monitoring will now begin.")
    uart_println(uart_svc, "")

    led_good()          # green — ready to monitor


def check_posture(uart_svc, r1, r2):
    """
    Compare current readings against calibrated baselines.
    Returns a list of alert strings (empty list = good posture).
    """
    alerts = []
    b1 = calibration["fsr1_baseline"]
    b2 = calibration["fsr2_baseline"]

    if b1 and b1 > 0:
        dev1 = abs(r1 - b1) / b1
        if dev1 > DEVIATION_THRESHOLD:
            direction = "increased" if r1 > b1 else "decreased"
            alerts.append(
                f"  ⚠ FSR1 pressure {direction} by {int(dev1 * 100)}% "
                f"(now {r1}, baseline {b1:.1f})"
            )

    if b2 and b2 > 0:
        dev2 = abs(r2 - b2) / b2
        if dev2 > DEVIATION_THRESHOLD:
            direction = "increased" if r2 > b2 else "decreased"
            alerts.append(
                f"  ⚠ FSR2 pressure {direction} by {int(dev2 * 100)}% "
                f"(now {r2}, baseline {b2:.1f})"
            )

    return alerts


# ── Main loop ────────────────────────────────────────────────────────────────

print("Posture Checker booting — advertising BLE...")
led_off()   # start dark while waiting for connection

while True:
    # ── Advertise until a client connects ────────────────────────────────────
    ble.start_advertising(advertisement)
    print("Waiting for BLE connection...")

    while not ble.connected:
        pass

    ble.stop_advertising()
    print("BLE connected.")

    # Show blue if uncalibrated, green if already calibrated from a prior session
    if calibration["is_calibrated"]:
        led_good()
    else:
        led_uncalibrated()

    uart_println(uart, "=== Posture Checker Connected ===")
    uart_println(uart, "Commands:")
    uart_println(uart, "  c  or  calibrate  → start calibration")
    uart_println(uart, "  s  or  status     → show current readings")
    uart_println(uart, "  r  or  reset      → clear calibration")
    uart_println(uart, "")

    if not calibration["is_calibrated"]:
        uart_println(uart, "⚠ Not yet calibrated. Send 'c' to calibrate.")

    last_monitor_time = 0
    MONITOR_INTERVAL  = 2.0   # seconds between posture checks during monitoring
    posture_bad       = False  # tracks current alert state for LED

    # ── Per-connection event loop ─────────────────────────────────────────────
    while ble.connected:

        # ── Handle incoming UART commands ─────────────────────────────────────
        if uart.in_waiting:
            raw = uart.readline()
            if raw:
                cmd = raw.decode("utf-8").strip().lower()

                if cmd in ("c", "calibrate"):
                    run_calibration(uart)
                    posture_bad = False   # reset alert state after calibration

                elif cmd in ("s", "status"):
                    r1 = get_reading(fsr1)
                    r2 = get_reading(fsr2)
                    uart_println(uart, "--- Current Readings ---")
                    uart_println(uart, f"  FSR1: {r1}  ({pressure_label(r1, FSR1_THRESHOLDS)})")
                    uart_println(uart, f"  FSR2: {r2}  ({pressure_label(r2, FSR2_THRESHOLDS)})")
                    if calibration["is_calibrated"]:
                        uart_println(uart, f"  Baseline → FSR1: {calibration['fsr1_baseline']:.1f}  "
                                           f"FSR2: {calibration['fsr2_baseline']:.1f}")
                    else:
                        uart_println(uart, "  (not calibrated yet)")
                    uart_println(uart, "")

                elif cmd in ("r", "reset"):
                    calibration["fsr1_baseline"]  = None
                    calibration["fsr2_baseline"]  = None
                    calibration["is_calibrated"]  = False
                    posture_bad = False
                    led_uncalibrated()   # back to blue — needs recalibration
                    uart_println(uart, "Calibration reset. Send 'c' to recalibrate.")

                else:
                    uart_println(uart, f"Unknown command: '{cmd}'")
                    uart_println(uart, "Valid commands: c/calibrate  s/status  r/reset")

        # ── Periodic posture monitoring (only after calibration) ───────────────
        now = time.monotonic()
        if calibration["is_calibrated"] and (now - last_monitor_time >= MONITOR_INTERVAL):
            last_monitor_time = now

            r1 = get_reading(fsr1)
            r2 = get_reading(fsr2)

            alerts = check_posture(uart, r1, r2)

            if alerts:
                if not posture_bad:
                    posture_bad = True
                    global _pulse_start
                    _pulse_start = time.monotonic()   # start pulse from zero
                uart_println(uart, "--- POSTURE ALERT ---")
                for a in alerts:
                    uart_println(uart, a)
                uart_println(uart, "")
            else:
                if posture_bad:
                    posture_bad = False  # returning to good posture
                    led_good()           # immediately restore green
                # Good posture: silent (no spam). Send 's' anytime to check manually.

        # ── LED tick — runs every loop iteration for smooth flashing ──────────
        if posture_bad:
            led_alert_tick()             # non-blocking red flash

    led_off()   # BLE dropped — go dark
    print("BLE disconnected. Re-advertising...")