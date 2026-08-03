# pressure_sensor_test.py
# Wiring: 3.3V --> Sensor --> A0 --> Resistor --> GND
# As pressure increases, sensor resistance drops, A0 voltage rises.
#
# ============================================================
#  SENSOR SWAP GUIDE — comment/uncomment the marked lines
#  below to switch between Velostat and FSR sensors.
#
#  VELOSTAT: use 10kΩ resistor, r_fixed=10000, r_max=50000,  v_floor=0.01
#  FSR:      use 47kΩ resistor, r_fixed=47000, r_max=200000, v_floor=0.005
# ============================================================

import time
import board
import analogio
import displayio
import terminalio
from adafruit_display_text import label

# --- Analog input setup ---
analog_in = analogio.AnalogIn(board.A0)

def read_voltage(pin):
    """Convert raw 16-bit ADC reading to voltage (0–3.3V)."""
    return (pin.value * 3.3) / 65535

def voltage_to_resistance(v_out, v_in=3.3,
    r_fixed=10000,   # VELOSTAT: 10kΩ  — match your physical resistor
    # r_fixed=47000, # FSR:      47kΩ  — swap resistor on breadboard too!
    ):
    """
    Voltage divider: V_out = V_in * R_fixed / (R_sensor + R_fixed)
    Solving for R_sensor: R = R_fixed * (V_in - V_out) / V_out
    """
    if v_out >= v_in:
        return 0
    if v_out <= 0.01:   # VELOSTAT: 0.01  — filters noise at rest
    # if v_out <= 0.005: # FSR:      0.005 — FSR rests near 0V, lower floor needed
        return float('inf')
    return r_fixed * (v_in - v_out) / v_out

def pressure_level(resistance,
    r_max=50000,    # VELOSTAT: ~50kΩ  — typical unloaded resistance
    # r_max=200000, # FSR:      ~200kΩ — FSR rests much higher; tune via serial
    ):
    """Map resistance to 0–100% pressure (lower R = more pressure)."""
    if resistance == float('inf'):
        return 0
    pct = (1 - min(resistance, r_max) / r_max) * 100
    return max(0, min(100, pct))

def make_bar_tile(width, color, x=12, y=150, height=20):
    """Create a filled TileGrid rectangle of given width and color."""
    bmp = displayio.Bitmap(max(1, width), height, 1)
    pal = displayio.Palette(1)
    pal[0] = color
    return displayio.TileGrid(bmp, pixel_shader=pal, x=x, y=y)

# --- Display setup ---
display = board.DISPLAY
display.rotation = 0

BAR_MAX_WIDTH = display.width - 24
BAR_X = 12
BAR_Y = 150
BAR_H = 20

main_group = displayio.Group()
display.root_group = main_group

# Background
bg_bitmap = displayio.Bitmap(display.width, display.height, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = 0x1A1A2E
main_group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

# Labels
title_lbl = label.Label(terminalio.FONT, text="Velostat Test", color=0x00D4FF, scale=2)  # VELOSTAT
# title_lbl = label.Label(terminalio.FONT, text="FSR Test",      color=0x00D4FF, scale=2)  # FSR
title_lbl.anchor_point = (0.5, 0.0)
title_lbl.anchored_position = (display.width // 2, 10)
main_group.append(title_lbl)

voltage_lbl = label.Label(terminalio.FONT, text="Voltage:  0.000 V", color=0xFFFFFF, scale=2)
voltage_lbl.anchor_point = (0.5, 0.0)
voltage_lbl.anchored_position = (display.width // 2, 55)
main_group.append(voltage_lbl)

resist_lbl = label.Label(terminalio.FONT, text="Resist:  ---- ohm", color=0xFFFFFF, scale=2)
resist_lbl.anchor_point = (0.5, 0.0)
resist_lbl.anchored_position = (display.width // 2, 85)
main_group.append(resist_lbl)

pressure_lbl = label.Label(terminalio.FONT, text="Press:      0 %", color=0x00FF88, scale=2)
pressure_lbl.anchor_point = (0.5, 0.0)
pressure_lbl.anchored_position = (display.width // 2, 115)
main_group.append(pressure_lbl)

# Bar background (static)
bar_bg_bmp = displayio.Bitmap(BAR_MAX_WIDTH, BAR_H + 4, 1)
bar_bg_pal = displayio.Palette(1)
bar_bg_pal[0] = 0x333355
main_group.append(displayio.TileGrid(bar_bg_bmp, pixel_shader=bar_bg_pal, x=BAR_X - 2, y=BAR_Y - 2))

# Bar fill — kept at a fixed index so we can swap it out each frame
BAR_FILL_INDEX = len(main_group)
main_group.append(make_bar_tile(1, 0x00FF88, BAR_X, BAR_Y, BAR_H))

print("Velostat sensor test running. Press the sensor!")  # VELOSTAT
# print("FSR sensor test running. Press the sensor!")      # FSR

# --- Main loop ---
while True:
    voltage = read_voltage(analog_in)
    resistance = voltage_to_resistance(voltage)
    pressure = pressure_level(resistance)

    # Update labels
    voltage_lbl.text = f"Voltage: {voltage:6.3f} V"
    if resistance == float('inf'):
        resist_lbl.text = "Resist:  open"
    elif resistance > 99999:
        resist_lbl.text = "Resist: >99k ohm"
    else:
        resist_lbl.text = f"Resist: {int(resistance):5d} ohm"
    pressure_lbl.text = f"Press:  {int(pressure):3d} %"

    # Color: green -> yellow -> red
    p = pressure / 100
    if p < 0.5:
        r = int(p * 2 * 255)
        g = 255
    else:
        r = 255
        g = int((1 - p) * 2 * 255)
    color = (r << 16) | (g << 8)

    # Swap bar tile (only way to resize — recreate it)
    bar_width = max(1, int(BAR_MAX_WIDTH * pressure / 100))
    main_group[BAR_FILL_INDEX] = make_bar_tile(bar_width, color, BAR_X, BAR_Y, BAR_H)

    # Serial output
    r_str = "inf" if resistance == float('inf') else f"{int(resistance)}"
    print(f"V={voltage:.3f}V  R={r_str:>8} ohm  P={pressure:.1f}%")

    time.sleep(0.1)
