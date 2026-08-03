# Posture Checker - CircuitPython
# Hardware: Adafruit ESP32-S3 Feather (8MB Flash, No PSRAM)
# Sensors:  FSR on A0, FSR on A1, FSR on A2 (velostat/conductive sheet compatible)
# BLE:      Nordic UART Service (NUS) — connects to the Posture Checker Flutter app
#
# Wiring:
#   FSR1: one leg → 3.3V, other leg → A0; 10K pulldown from A0 → GND
#   FSR2: one leg → 3.3V, other leg → A1; 10K pulldown from A1 → GND
#   FSR3: one leg → 3.3V, other leg → A2; 10K pulldown from A2 → GND
#   Velostat (optional swap-in): same wiring, just replace the FSR
#
# Required libraries in /lib:
#   adafruit_ble/
#   adafruit_bluefruit_connect/
#   neopixel.mpy

import time
import math
import board
import analogio
import neopixel
import adafruit_ble
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

# ════════════════════════════════════════════════════════════════════════════
#  SENSOR CONFIGURATION  —  edit this section to tune your setup
# ════════════════════════════════════════════════════════════════════════════

# ── Resistor config ──────────────────────────────────────────────────────────
PULLDOWN_OHMS  = 10_000       # value of your pulldown resistors (ohms)
REFERENCE_OHMS = 10_000       # reference used when tuning thresholds below
SCALE = REFERENCE_OHMS / PULLDOWN_OHMS

# ── Calibration timing ───────────────────────────────────────────────────────
CALIBRATION_SAMPLES = 20      # total samples averaged  (more = smoother baseline)
CALIBRATION_DELAY   = 0.15    # seconds between samples (~3 s total at defaults)

# ── Sensor type assignment ───────────────────────────────────────────────────
# Set each channel to "circle", "square", or "velostat"
# This controls which deviation thresholds and pressure labels are applied.
SENSOR_TYPE = {
    "fsr1": "circle",         # A0 — circle FSR
    "fsr2": "square",         # A1 — square FSR
    "fsr3": "velostat",       # A2 — velostat / conductive sheet
}

# ── Per-type deviation thresholds ────────────────────────────────────────────
# Alert fires when reading deviates from baseline by more than these factors.
#   e.g. 0.25 = alert if reading is >125% or <75% of baseline
DEVIATION = {
    "circle":   0.25,         # ±25%  →  >1.25x or <0.75x baseline
    "square":   0.25,         # ±25%  →  >1.25x or <0.75x baseline
    "velostat": 0.10,         # ±10%  →  >1.10x or <0.90x baseline
}

# ── Pressure labels & ranges (raw 10-bit readings, 0–1023) ───────────────────
# Observed ranges from testing — update freely as you gather more data.
#
# Format: list of (upper_limit, label) pairs in ascending order.
# The last entry's limit is ignored (it's the catch-all "highest" bucket).
#
# CIRCLE FSR (A0)
#   Regular chair  — backseat 150-350, frontseat 5-50, lower back 0-50, upper back 0-250
#   Office chair   — backseat 100-250, frontseat 0-15, lower back 0-20, upper back 0-20
CIRCLE_THRESHOLDS = [
    (15,  "No contact"),       # below office-chair frontseat low end
    (50,  "Very light"),       # regular chair frontseat / lower-back range
    (150, "Light"),            # below regular chair backseat low end
    (250, "Moderate"),         # office chair backseat top / upper back
    (350, "Firm"),             # regular chair backseat top
    (float("inf"), "Heavy"),   # above all observed ranges
]

# SQUARE FSR (A1)
#   Office chair  — backseat 900-max, frontseat 350-800, lower back 500-700, upper 450-750
SQUARE_THRESHOLDS = [
    (350,  "No/minimal contact"),  # below frontseat low end
    (450,  "Light"),               # bottom of upper-back range
    (700,  "Moderate"),            # mid-range (lower back / upper back)
    (800,  "Firm"),                # top of frontseat range
    (900,  "High"),                # approaching backseat territory
    (float("inf"), "Max load"),    # backseat 900+
]

# VELOSTAT / CONDUCTIVE SHEET (A2)
#   ~650  = no pressure
#   750–850 = normal posture
#   850+  = too much pressure
VELOSTAT_THRESHOLDS = [
    (650,  "No pressure"),         # sensor at rest, no contact
    (750,  "Below normal"),        # between rest and good-posture band
    (850,  "Normal posture"),      # target zone
    (float("inf"), "Excess pressure"),  # over-compressed
]

# Map type names → their threshold lists (no need to edit this)
_THRESHOLDS = {
    "circle":   CIRCLE_THRESHOLDS,
    "square":   SQUARE_THRESHOLDS,
    "velostat": VELOSTAT_THRESHOLDS,
}

# ════════════════════════════════════════════════════════════════════════════
#  END OF SENSOR CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

# ── Analog inputs ────────────────────────────────────────────────────────────
fsr1 = analogio.AnalogIn(board.A0)
fsr2 = analogio.AnalogIn(board.A1)
fsr3 = analogio.AnalogIn(board.A2)

# ── Calibration state ────────────────────────────────────────────────────────
calibration = {
    "fsr1_baseline": None,
    "fsr2_baseline": None,
    "fsr3_baseline": None,
    "is_calibrated": False,
}

# ── BLE setup ────────────────────────────────────────────────────────────────
ble  = adafruit_ble.BLERadio()
ble.name = "Posture Check BT"
uart = UARTService()
advertisement = ProvideServicesAdvertisement(uart)

# ── Onboard NeoPixel (ESP32-S3 Feather has one on NEOPIXEL pin) ──────────────
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=1.0, auto_write=True)

# Colour constants  (R, G, B)
COLOR_OFF         = (0,   0,   0)
COLOR_GOOD        = (0,   20,  0)    # dim green  — good posture
COLOR_ALERT       = (255, 0,   0)    # bright red — bad posture (pulse ON phase)
COLOR_UNCALIB     = (0,   0,   20)   # dim blue   — not yet calibrated
COLOR_CALIBRATING = (255, 165, 0)    # orange     — calibration in progress

# Pulse state for the alert animation
PULSE_PERIOD = 1.5                   # seconds for one full breathe-in + breathe-out cycle
_pulse_start = 0.0                   # set when posture_bad first becomes True


def led_good():
    """Steady dim green — posture is fine."""
    pixel.brightness = 1.0
    pixel[0] = COLOR_GOOD


def led_alert_tick():
    """
    Call frequently inside the main loop when posture is bad.
    Smoothly pulses bright red using a sine wave (breathing effect).
    Non-blocking — safe to call every loop iteration.
    """
    phase      = (time.monotonic() - _pulse_start) / PULSE_PERIOD
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


def pressure_label(reading, sensor_type):
    """Return a human-readable pressure label for a raw reading."""
    thresholds = _THRESHOLDS.get(sensor_type, CIRCLE_THRESHOLDS)
    for limit, label in thresholds:
        if reading < limit:
            return label
    return thresholds[-1][1]


def uart_println(uart_svc, text):
    """Send a line of text over BLE UART."""
    uart_svc.write((text + "\r\n").encode())


def run_calibration(uart_svc):
    """
    Average CALIBRATION_SAMPLES readings for each sensor and store baselines.
    Sends progress updates over UART so the app can display a progress bar.
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
    sum3 = 0

    for i in range(1, CALIBRATION_SAMPLES + 1):
        sum1 += get_reading(fsr1)
        sum2 += get_reading(fsr2)
        sum3 += get_reading(fsr3)

        # Progress bar every 5 samples: [##....] 50%
        if i % 5 == 0:
            pct = int((i / CALIBRATION_SAMPLES) * 100)
            bar = "#" * (pct // 10) + "." * (10 - pct // 10)
            uart_println(uart_svc, f"  [{bar}] {pct}%")

        time.sleep(CALIBRATION_DELAY)

    baseline1 = sum1 / CALIBRATION_SAMPLES
    baseline2 = sum2 / CALIBRATION_SAMPLES
    baseline3 = sum3 / CALIBRATION_SAMPLES

    calibration["fsr1_baseline"] = baseline1
    calibration["fsr2_baseline"] = baseline2
    calibration["fsr3_baseline"] = baseline3
    calibration["is_calibrated"] = True

    uart_println(uart_svc, "")
    uart_println(uart_svc, "=== CALIBRATION COMPLETE ===")
    uart_println(uart_svc, f"  FSR1 ({SENSOR_TYPE['fsr1']}) baseline : {baseline1:.1f}  "
                           f"({pressure_label(int(baseline1), SENSOR_TYPE['fsr1'])})")
    uart_println(uart_svc, f"  FSR2 ({SENSOR_TYPE['fsr2']}) baseline : {baseline2:.1f}  "
                           f"({pressure_label(int(baseline2), SENSOR_TYPE['fsr2'])})")
    uart_println(uart_svc, f"  FSR3 ({SENSOR_TYPE['fsr3']}) baseline : {baseline3:.1f}  "
                           f"({pressure_label(int(baseline3), SENSOR_TYPE['fsr3'])})")
    uart_println(uart_svc, f"  Thresholds → circle ±{int(DEVIATION['circle']*100)}%  "
                           f"square ±{int(DEVIATION['square']*100)}%  "
                           f"velostat ±{int(DEVIATION['velostat']*100)}%")
    uart_println(uart_svc, "Monitoring will now begin.")
    uart_println(uart_svc, "")

    led_good()          # green — ready to monitor


def check_posture(r1, r2, r3):
    """
    Compare current readings against calibrated baselines.
    Returns a list of alert strings (empty list = good posture).
    """
    alerts = []

    sensors = [
        ("FSR1", r1, calibration["fsr1_baseline"], SENSOR_TYPE["fsr1"]),
        ("FSR2", r2, calibration["fsr2_baseline"], SENSOR_TYPE["fsr2"]),
        ("FSR3", r3, calibration["fsr3_baseline"], SENSOR_TYPE["fsr3"]),
    ]

    for name, reading, baseline, stype in sensors:
        if baseline is None or baseline == 0:
            continue

        threshold = DEVIATION[stype]
        ratio     = reading / baseline

        if ratio > (1 + threshold) or ratio < (1 - threshold):
            direction = "increased" if reading > baseline else "decreased"
            pct_off   = int(abs(ratio - 1) * 100)
            alerts.append(
                f"  \u26a0 {name} ({stype}) pressure {direction} by {pct_off}%  "
                f"(now {reading}, baseline {baseline:.1f}, "
                f"limit \u00b1{int(threshold * 100)}%)"
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
    uart_println(uart, "  c  or  calibrate  \u2192 start calibration")
    uart_println(uart, "  s  or  status     \u2192 show current readings")
    uart_println(uart, "  r  or  reset      \u2192 clear calibration")
    uart_println(uart, "")

    if not calibration["is_calibrated"]:
        uart_println(uart, "Not yet calibrated. Send 'c' to calibrate.")

    last_monitor_time = 0
    MONITOR_INTERVAL  = 2.0   # seconds between posture checks
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
                    r3 = get_reading(fsr3)
                    uart_println(uart, "--- Current Readings ---")
                    uart_println(uart, f"  FSR1 ({SENSOR_TYPE['fsr1']}): {r1}  "
                                       f"({pressure_label(r1, SENSOR_TYPE['fsr1'])})")
                    uart_println(uart, f"  FSR2 ({SENSOR_TYPE['fsr2']}): {r2}  "
                                       f"({pressure_label(r2, SENSOR_TYPE['fsr2'])})")
                    uart_println(uart, f"  FSR3 ({SENSOR_TYPE['fsr3']}): {r3}  "
                                       f"({pressure_label(r3, SENSOR_TYPE['fsr3'])})")
                    if calibration["is_calibrated"]:
                        uart_println(uart, f"  Baseline \u2192 FSR1: {calibration['fsr1_baseline']:.1f}  "
                                           f"FSR2: {calibration['fsr2_baseline']:.1f}  "
                                           f"FSR3: {calibration['fsr3_baseline']:.1f}")
                    else:
                        uart_println(uart, "  (not calibrated yet)")
                    uart_println(uart, "")

                elif cmd in ("r", "reset"):
                    calibration["fsr1_baseline"] = None
                    calibration["fsr2_baseline"] = None
                    calibration["fsr3_baseline"] = None
                    calibration["is_calibrated"] = False
                    posture_bad = False
                    led_uncalibrated()
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
            r3 = get_reading(fsr3)

            alerts = check_posture(r1, r2, r3)

            if alerts:
                if not posture_bad:
                    posture_bad  = True
                    _pulse_start = time.monotonic()
                uart_println(uart, "--- POSTURE ALERT ---")
                for a in alerts:
                    uart_println(uart, a)
                uart_println(uart, "")
            else:
                if posture_bad:
                    posture_bad = False
                    led_good()
                    uart_println(uart, "--- POSTURE OK ---")

        # ── LED tick — runs every loop iteration for smooth pulsing ───────────
        if posture_bad:
            led_alert_tick()

    led_off()   # BLE dropped — go dark
    print("BLE disconnected. Re-advertising...")
