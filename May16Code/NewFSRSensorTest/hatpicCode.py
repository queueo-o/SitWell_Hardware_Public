import time
import board
import busio
import adafruit_drv2605

# Initialize I2C - STEMMA QT uses the default I2C pins
i2c = busio.I2C(board.SCL, board.SDA)
drv = adafruit_drv2605.DRV2605(i2c)

def test_effect(effect_id, label):
    print(f"Playing effect {effect_id}: {label}")
    drv.sequence[0] = adafruit_drv2605.Effect(effect_id)
    drv.play()
    time.sleep(0.5)
    drv.stop()
    time.sleep(0.5)

# Test a variety of built-in effects
print("Starting DRV2605L Haptic Motor Test...")
time.sleep(1)

# Single buzz
test_effect(1, "Strong Click")

# Double click
test_effect(10, "Double Click")

# Triple click  
test_effect(12, "Triple Click")

# Soft bump
test_effect(52, "Soft Bump")

# Alert
test_effect(18, "Alert 100%")

# Rumble
test_effect(47, "Long Buzz")

# Pulsing
test_effect(48, "Smooth Hum 1")

print("Test complete!")