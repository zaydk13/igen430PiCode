import RPi.GPIO as gpio
import time

gpio.setmode(gpio.BCM)

control_pins = [17, 27, 22, 23]  # Example GPIO pins for controlling the turntable

for pin in control_pins:
    gpio.setup(pin, gpio.OUT)
    gpio.output(pin, 0)

def turntable_step(steps, delay=0.01):
    """
    Rotate the turntable by a specified number of steps.
    Positive steps for clockwise, negative for counter-clockwise.
    """
    step_sequence = [
        [1, 0, 0, 1],
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1],
    ]

    turntable_step(200)

    step_count = len(step_sequence)
    step_dir = 1 if steps > 0 else -1
    steps = abs(steps)

    for _ in range(steps):
        for step in range(step_count)[::step_dir]:
            for pin in range(4):
                gpio.output(control_pins[pin], step_sequence[step][pin])
            time.sleep(delay)

    # Turn off all pins after movement
    for pin in control_pins:
        gpio.output(pin, 0)

