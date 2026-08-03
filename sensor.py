# FSR simple testing - CircuitPython
#
# Connect one end of FSR to 3.3V, the other end to A0.
# Then connect one end of your pulldown resistor from A0 to ground.

import time
import board
import analogio

# ── Adjust this to match your pulldown resistor in ohms ──
PULLDOWN_OHMS = 120_000  # 120K
# ─────────────────────────────────────────────────────────

# Thresholds are tuned for a 10K reference resistor.
# Scaling factor adjusts them automatically for other resistor values.
REFERENCE_OHMS = 10_000
SCALE = REFERENCE_OHMS / PULLDOWN_OHMS  # < 1.0 for larger resistors

fsr = analogio.AnalogIn(board.A0)

def get_reading():
    # Scale 16-bit (0-65535) down to 10-bit (0-1023)
    return fsr.value >> 6

while True:
    fsr_reading = get_reading()

    # Apply resistor scaling to thresholds
    if fsr_reading < int(10 * SCALE):
        pressure = "No pressure"
    elif fsr_reading < int(200 * SCALE):
        pressure = "Light touch"
    elif fsr_reading < int(500 * SCALE):
        pressure = "Light squeeze"
    elif fsr_reading < int(800 * SCALE):
        pressure = "Medium squeeze"
    else:
        pressure = "Big squeeze"

    print(f"Analog reading = {fsr_reading} - {pressure}")

    time.sleep(1)