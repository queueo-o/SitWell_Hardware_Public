import time
import board
import busio
import neopixel
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService

'''
find these libraries from circuitpython bundle:
adafruit_ble
adafruit_ble_adafruit
adafruit_bluefruit_connect
'''

DEVICE_NAME = "ESP32-UART Tyler"
SEND_INTERVAL = 5.0

# Neopixel setup
PIXEL_PIN = board.NEOPIXEL
Num_Pin = 1
BRIGHTNESS = 0.3

pixel = neopixel.NeoPixel(PIXEL_PIN, Num_Pin,
brightness=BRIGHTNESS,
auto_write=True)

OFF = (0,0,0)
BLUE = (0,0,255)
RED = (255,0,0)

def set_status(color):
    pixel.fill(color)

# You will initialize your sensors or ANY hardware here
def setup_sensors ():
    sensor = None
    return sensor


def collect_data(sensor):
    example_value1 = 10
    example_value2 = 5.1
    string_1 = "val1"
    string_2 = "val2"

    message = f"{example_value1}:{example_value2},{string_1},{string_2}\n"
    return message

def main():
    print(f"[BLE UART] Starting '{DEVICE_NAME}' ")
    ble = BLERadio()
    ble.name = DEVICE_NAME

    uart = UARTService()
    advertisement = ProvideServicesAdvertisement(uart)

    sensor = setup_sensors()

    while True:
        print("[BLE UART] Advertising - waiting for conection...")
        ble.start_advertising(advertisement)
        set_status(RED)

        while not ble.connected:
            time.sleep(0.1)

        ble.stop_advertising()
        print("Connection successful!")
        set_status(BLUE)
        time.sleep(5)
        set_status(OFF)

        while ble.connected:
            try:
                data = collect_data(sensor)
                uart.write(data.encode("utf-8"))
                print(f"[TX] {data.strip()}")

                if uart.in_waiting:
                    raw_input = uart.read(uart.in_waiting)
                    try:
                        incoming = raw_input.decode("utf-8")
                    except UnicodeDecodeError:
                        incoming = str(raw_input)
                    print(f"[RX] {incoming.strip()}")

            except Exception as e:
                print(f"[ERROR] {e}")

            time.sleep(SEND_INTERVAL)

        print("Bluetooth Disconnected")
        set_status(RED)
        time.sleep(1)

main()
