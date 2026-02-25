import time
from time import sleep
import datetime
from picamera2 import Picamera2
from libcamera import controls
import RPi.GPIO as gpio
import threading

# GPIO setup
gpio.setmode(gpio.BCM)

# Define GPIO pins for stepper motor control
INA = 17  # Coil A positive
INB = 27  # Coil A negative
INC = 22  # Coil B positive
IND = 23  # Coil B negative

control_pins = [INA, INB, INC, IND]

# Set up all pins as outputs
for pin in control_pins:
    gpio.setup(pin, gpio.OUT)
    gpio.output(pin, 0)

def turn_stepper_motor(steps=2048*3, delay=0.005):
    
    # Full-step sequence for bipolar stepper motor
    step_sequence = [
        [1, 0, 1, 0],  # Step 0
        [0, 1, 1, 0],  # Step 1
        [0, 1, 0, 1],  # Step 2
        [1, 0, 0, 1],  # Step 3
    ]
    
    step_count = len(step_sequence)
    
    print(f"Starting one full turn of stepper motor ({steps} steps)...")
    
    # Execute the step sequence
    for step_num in range(steps):
        current_step = step_sequence[step_num % step_count]
        
        # Apply the step pattern to the pins
        gpio.output(INA, current_step[0])
        gpio.output(INB, current_step[1])
        gpio.output(INC, current_step[2])
        gpio.output(IND, current_step[3])
        
        time.sleep(delay)
    
    # Turn off all coils
    for pin in control_pins:
        gpio.output(pin, 0)
    
    print("Motor rotation complete!")

camera = Picamera2()
camera.resolution = (1024, 768)

camera.start(show_preview=True)
camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})

now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# Start video recording
camera.start_and_record_video(f"testvideo{now}.mp4", duration=30)

# Start motor rotation in a separate thread
motor_thread = threading.Thread(target=turn_stepper_motor)
motor_thread.start()

# Wait for motor to finish
motor_thread.join()

sleep(2)
camera.close()

# Clean up GPIO pins
gpio.cleanup()