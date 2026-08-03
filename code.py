# Posture Checker - CircuitPython
# Hardware: Adafruit ESP32-S3 Feather (8MB Flash, No PSRAM)
# Sensors:  FSR on A0-A5 (circle, square, and velostat compatible)
# BLE:      Adafruit Bluefruit Connect app (UART mode)
#
# Wiring:
#   FSR1-4: one leg → 3.3V, other leg → A0-A3; 10K pulldown from pin → GND
#   FSR5-6: velostat — one leg → 3.3V, other leg → A4-A5; 10K pulldown from pin → GND
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

PULLDOWN_OHMS  = 10_000
REFERENCE_OHMS = 10_000
SCALE = REFERENCE_OHMS / PULLDOWN_OHMS

CALIBRATION_SAMPLES = 20
CALIBRATION_DELAY   = 0.15

SENSOR_TYPE = {
    "fsr1": "circle",
    "fsr2": "circle",
    "fsr3": "square",
    "fsr4": "square",
    "fsr5": "velostat_seat",
    "fsr6": "velostat_back",
}

MIN_BASELINE = 10

DEVIATION = {
    "circle":        0.5,
    "square":        0.6,
    "velostat_seat": 0.10,
    "velostat_back": 0.20,
}

CIRCLE_THRESHOLDS = [
    (15,  "No contact"),
    (50,  "Very light"),
    (150, "Light"),
    (250, "Moderate"),
    (350, "Firm"),
    (float("inf"), "Heavy"),
]

SQUARE_THRESHOLDS = [
    (350,  "No/minimal contact"),
    (450,  "Light"),
    (700,  "Moderate"),
    (800,  "Firm"),
    (900,  "High"),
    (float("inf"), "Max load"),
]

VELOSTAT_THRESHOLDS = [
    (650,  "No pressure"),
    (750,  "Below normal"),
    (850,  "Normal posture"),
    (float("inf"), "Excess pressure"),
]

_THRESHOLDS = {
    "circle":        CIRCLE_THRESHOLDS,
    "square":        SQUARE_THRESHOLDS,
    "velostat_seat": VELOSTAT_THRESHOLDS,
    "velostat_back": VELOSTAT_THRESHOLDS,
}

# ════════════════════════════════════════════════════════════════════════════
#  END OF SENSOR CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

fsr1 = analogio.AnalogIn(board.A0)
fsr2 = analogio.AnalogIn(board.A1)
fsr3 = analogio.AnalogIn(board.A2)
fsr4 = analogio.AnalogIn(board.A3)
fsr5 = analogio.AnalogIn(board.A4)
fsr6 = analogio.AnalogIn(board.A5)

calibration = {
    "fsr1_baseline": None,
    "fsr2_baseline": None,
    "fsr3_baseline": None,
    "fsr4_baseline": None,
    "fsr5_baseline": None,
    "fsr6_baseline": None,
    "is_calibrated": False,
}

ble  = adafruit_ble.BLERadio()
ble.name = "Posture Check BT"
uart = UARTService()
advertisement = ProvideServicesAdvertisement(uart)

pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=1.0, auto_write=True)

COLOR_OFF         = (0,   0,   0)
COLOR_GOOD        = (0,   20,  0)
COLOR_ALERT       = (255, 0,   0)
COLOR_UNCALIB     = (0,   0,   20)
COLOR_CALIBRATING = (255, 165, 0)

PULSE_PERIOD = 1.5
_pulse_start = 0.0


def led_good():
    pixel.brightness = 1.0
    pixel[0] = COLOR_GOOD


def led_alert_tick():
    phase = (time.monotonic() - _pulse_start) / PULSE_PERIOD
    pixel.brightness = (math.sin(phase * 2 * math.pi - math.pi / 2) + 1) / 2
    pixel[0] = COLOR_ALERT


def led_uncalibrated():
    pixel.brightness = 1.0
    pixel[0] = COLOR_UNCALIB


def led_calibrating():
    pixel.brightness = 1.0
    pixel[0] = COLOR_CALIBRATING


def led_off():
    pixel.brightness = 1.0
    pixel[0] = COLOR_OFF


def get_reading(pin):
    return min(1023, int((pin.value >> 6) * SCALE))


def pressure_label(reading, sensor_type):
    thresholds = _THRESHOLDS.get(sensor_type, CIRCLE_THRESHOLDS)
    for limit, label in thresholds:
        if reading < limit:
            return label
    return thresholds[-1][1]


def uart_println(uart_svc, text):
    uart_svc.write((text + "\r\n").encode())


def run_calibration(uart_svc):
    uart_println(uart_svc, "")
    uart_println(uart_svc, "=== CALIBRATION STARTED ===")
    uart_println(uart_svc, "Sit in your comfortable rest/good-posture position.")
    uart_println(uart_svc, f"Taking {CALIBRATION_SAMPLES} samples over "
                           f"~{int(CALIBRATION_SAMPLES * CALIBRATION_DELAY)} seconds...")
    uart_println(uart_svc, "")

    led_calibrating()

    sum1 = sum2 = sum3 = sum4 = sum5 = sum6 = 0

    for i in range(1, CALIBRATION_SAMPLES + 1):
        sum1 += get_reading(fsr1)
        sum2 += get_reading(fsr2)
        sum3 += get_reading(fsr3)
        sum4 += get_reading(fsr4)
        sum5 += get_reading(fsr5)
        sum6 += get_reading(fsr6)

        if i % 5 == 0:
            pct = int((i / CALIBRATION_SAMPLES) * 100)
            bar = "#" * (pct // 10) + "." * (10 - pct // 10)
            uart_println(uart_svc, f"  [{bar}] {pct}%")

        time.sleep(CALIBRATION_DELAY)

    baseline1 = sum1 / CALIBRATION_SAMPLES
    baseline2 = sum2 / CALIBRATION_SAMPLES
    baseline3 = sum3 / CALIBRATION_SAMPLES
    baseline4 = sum4 / CALIBRATION_SAMPLES
    baseline5 = sum5 / CALIBRATION_SAMPLES
    baseline6 = sum6 / CALIBRATION_SAMPLES

    calibration["fsr1_baseline"] = baseline1
    calibration["fsr2_baseline"] = baseline2
    calibration["fsr3_baseline"] = baseline3
    calibration["fsr4_baseline"] = baseline4
    calibration["fsr5_baseline"] = baseline5
    calibration["fsr6_baseline"] = baseline6
    calibration["is_calibrated"] = True

    uart_println(uart_svc, "")
    uart_println(uart_svc, "=== CALIBRATION COMPLETE ===")
    uart_println(uart_svc, f"  FSR1 ({SENSOR_TYPE['fsr1']}) baseline : {baseline1:.1f}  "
                           f"({pressure_label(int(baseline1), SENSOR_TYPE['fsr1'])})")
    uart_println(uart_svc, f"  FSR2 ({SENSOR_TYPE['fsr2']}) baseline : {baseline2:.1f}  "
                           f"({pressure_label(int(baseline2), SENSOR_TYPE['fsr2'])})")
    uart_println(uart_svc, f"  FSR3 ({SENSOR_TYPE['fsr3']}) baseline : {baseline3:.1f}  "
                           f"({pressure_label(int(baseline3), SENSOR_TYPE['fsr3'])})")
    uart_println(uart_svc, f"  FSR4 ({SENSOR_TYPE['fsr4']}) baseline : {baseline4:.1f}  "
                           f"({pressure_label(int(baseline4), SENSOR_TYPE['fsr4'])})")
    uart_println(uart_svc, f"  FSR5 ({SENSOR_TYPE['fsr5']}) baseline : {baseline5:.1f}  "
                           f"({pressure_label(int(baseline5), SENSOR_TYPE['fsr5'])})")
    uart_println(uart_svc, f"  FSR6 ({SENSOR_TYPE['fsr6']}) baseline : {baseline6:.1f}  "
                           f"({pressure_label(int(baseline6), SENSOR_TYPE['fsr6'])})")
    uart_println(uart_svc, f"  Thresholds → circle ±{int(DEVIATION['circle']*100)}%  "
                           f"square ±{int(DEVIATION['square']*100)}%  "
                           f"velostat_seat ±{int(DEVIATION['velostat_seat']*100)}%  "
                           f"velostat_back ±{int(DEVIATION['velostat_back']*100)}%")
    uart_println(uart_svc, "Monitoring will now begin.")
    uart_println(uart_svc, "")

    led_good()


def check_posture(r1, r2, r3, r4, r5, r6):
    alerts = []

    sensors = [
        ("FSR1", r1, calibration["fsr1_baseline"], SENSOR_TYPE["fsr1"]),
        ("FSR2", r2, calibration["fsr2_baseline"], SENSOR_TYPE["fsr2"]),
        ("FSR3", r3, calibration["fsr3_baseline"], SENSOR_TYPE["fsr3"]),
        ("FSR4", r4, calibration["fsr4_baseline"], SENSOR_TYPE["fsr4"]),
        ("FSR5", r5, calibration["fsr5_baseline"], SENSOR_TYPE["fsr5"]),
        ("FSR6", r6, calibration["fsr6_baseline"], SENSOR_TYPE["fsr6"]),
    ]

    for name, reading, baseline, stype in sensors:
        if baseline is None or baseline < MIN_BASELINE:
            continue

        threshold = DEVIATION[stype]
        ratio     = reading / baseline

        if ratio > (1 + threshold) or ratio < (1 - threshold):
            direction = "increased" if reading > baseline else "decreased"
            pct_off   = int(abs(ratio - 1) * 100)
            alerts.append(
                f"  ⚠ {name} ({stype}) pressure {direction} by {pct_off}%  "
                f"(now {reading}, baseline {baseline:.1f}, "
                f"limit ±{int(threshold * 100)}%)"
            )

    return alerts


# ── Main loop ────────────────────────────────────────────────────────────────

print("Posture Checker booting — advertising BLE...")
led_off()

while True:
    ble.start_advertising(advertisement)
    print("Waiting for BLE connection...")

    while not ble.connected:
        pass

    ble.stop_advertising()
    print("BLE connected.")

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
    MONITOR_INTERVAL  = 2.0
    ALERT_SUSTAIN     = 5.0
    posture_bad       = False
    _deviation_start  = None

    while ble.connected:

        if uart.in_waiting:
            raw = uart.readline()
            if raw:
                cmd = raw.decode("utf-8").strip().lower()

                if cmd in ("c", "calibrate"):
                    run_calibration(uart)
                    posture_bad      = False
                    _deviation_start = None

                elif cmd in ("s", "status"):
                    r1 = get_reading(fsr1)
                    r2 = get_reading(fsr2)
                    r3 = get_reading(fsr3)
                    r4 = get_reading(fsr4)
                    r5 = get_reading(fsr5)
                    r6 = get_reading(fsr6)
                    uart_println(uart, "--- Current Readings ---")
                    uart_println(uart, f"  FSR1 ({SENSOR_TYPE['fsr1']}): {r1}  "
                                       f"({pressure_label(r1, SENSOR_TYPE['fsr1'])})")
                    uart_println(uart, f"  FSR2 ({SENSOR_TYPE['fsr2']}): {r2}  "
                                       f"({pressure_label(r2, SENSOR_TYPE['fsr2'])})")
                    uart_println(uart, f"  FSR3 ({SENSOR_TYPE['fsr3']}): {r3}  "
                                       f"({pressure_label(r3, SENSOR_TYPE['fsr3'])})")
                    uart_println(uart, f"  FSR4 ({SENSOR_TYPE['fsr4']}): {r4}  "
                                       f"({pressure_label(r4, SENSOR_TYPE['fsr4'])})")
                    uart_println(uart, f"  FSR5 ({SENSOR_TYPE['fsr5']}): {r5}  "
                                       f"({pressure_label(r5, SENSOR_TYPE['fsr5'])})")
                    uart_println(uart, f"  FSR6 ({SENSOR_TYPE['fsr6']}): {r6}  "
                                       f"({pressure_label(r6, SENSOR_TYPE['fsr6'])})")
                    if calibration["is_calibrated"]:
                        uart_println(uart, f"  Baseline → "
                                           f"FSR1: {calibration['fsr1_baseline']:.1f}  "
                                           f"FSR2: {calibration['fsr2_baseline']:.1f}  "
                                           f"FSR3: {calibration['fsr3_baseline']:.1f}  "
                                           f"FSR4: {calibration['fsr4_baseline']:.1f}  "
                                           f"FSR5: {calibration['fsr5_baseline']:.1f}  "
                                           f"FSR6: {calibration['fsr6_baseline']:.1f}")
                    else:
                        uart_println(uart, "  (not calibrated yet)")
                    uart_println(uart, "")

                elif cmd in ("r", "reset"):
                    calibration["fsr1_baseline"] = None
                    calibration["fsr2_baseline"] = None
                    calibration["fsr3_baseline"] = None
                    calibration["fsr4_baseline"] = None
                    calibration["fsr5_baseline"] = None
                    calibration["fsr6_baseline"] = None
                    calibration["is_calibrated"] = False
                    posture_bad      = False
                    _deviation_start = None
                    led_uncalibrated()
                    uart_println(uart, "Calibration reset. Send 'c' to recalibrate.")

                else:
                    uart_println(uart, f"Unknown command: '{cmd}'")
                    uart_println(uart, "Valid commands: c/calibrate  s/status  r/reset")

        now = time.monotonic()
        if calibration["is_calibrated"] and (now - last_monitor_time >= MONITOR_INTERVAL):
            last_monitor_time = now

            r1 = get_reading(fsr1)
            r2 = get_reading(fsr2)
            r3 = get_reading(fsr3)
            r4 = get_reading(fsr4)
            r5 = get_reading(fsr5)
            r6 = get_reading(fsr6)

            alerts = check_posture(r1, r2, r3, r4, r5, r6)

            if alerts:
                if _deviation_start is None:
                    _deviation_start = time.monotonic()  # start sustain timer
                elif time.monotonic() - _deviation_start >= ALERT_SUSTAIN:
                    if not posture_bad:
                        posture_bad  = True
                        _pulse_start = time.monotonic()
                    uart_println(uart, "--- POSTURE ALERT ---")
                    for a in alerts:
                        uart_println(uart, a)
                    uart_println(uart, "")
            else:
                _deviation_start = None  # reset timer — posture recovered
                if posture_bad:
                    posture_bad = False
                    uart_println(uart, "--- POSTURE OK ---")
                    led_good()

        if posture_bad:
            led_alert_tick()

    led_off()
    print("BLE disconnected. Re-advertising...")
