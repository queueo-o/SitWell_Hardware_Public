# FSR simple testing - CircuitPython
#
# Connect one end of FSR to 3.3V, the other end to A0.
# Then connect one end of your pulldown resistor from A0 to ground.

import time
import board
import analogio

# ── Adjust this to match your pulldown resistor in ohms ──
PULLDOWN_OHMS = 10_000  # 120K
# ─────────────────────────────────────────────────────────

# Thresholds are tuned for a 10K reference resistor.
# Scaling factor adjusts them automatically for other resistor values.
REFERENCE_OHMS = 10_000
SCALE = REFERENCE_OHMS / PULLDOWN_OHMS  # < 1.0 for larger resistors

fsr1 = analogio.AnalogIn(board.A0)
fsr2 = analogio.AnalogIn(board.A1)

def get_reading1():
    # Scale 16-bit (0-65535) down to 10-bit (0-1023)
    return fsr1.value >> 6
def get_reading2():
    # Scale 16-bit (0-65535) down to 10-bit (0-1023)
    return fsr2.value >> 6

while True:
    fsr1_reading = get_reading1()
    fsr2_reading = get_reading2()


    # Apply resistor scaling to thresholds
    if fsr1_reading < int(10 * SCALE):
        pressure1 = "No pressure"
    elif fsr1_reading < int(250 * SCALE):
        pressure1 = "Light touch"
    elif fsr1_reading < int(400 * SCALE):
        pressure1 = "Light squeeze"
    elif fsr1_reading == int(523):
        pressure1 = "Big squeeze"
    elif fsr1_reading < int(900 * SCALE):
        pressure1 = "Medium squeeze"
    else:
        pressure1 = "Big squeeze"

    if fsr2_reading < int(5 * SCALE):
        pressure2 = "No pressure"
    elif fsr2_reading < int(100 * SCALE):
        pressure2 = "Light touch"
    elif fsr2_reading < int(250 * SCALE):
        pressure2 = "Light squeeze"
    elif fsr2_reading == int(523):
        pressure2 = "Big squeeze"
    elif fsr2_reading < int(450 * SCALE):
        pressure2 = "Medium squeeze"
    else:
        pressure2 = "Big squeeze"

    print(f"Analog reading 1 = {fsr1_reading} - {pressure1}")
    print(f"Analog reading 2 = {fsr2_reading} - {pressure2}")


    time.sleep(1)
