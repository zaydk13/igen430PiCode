import time
from time import sleep
import datetime
from picamera2 import Picamera2
from libcamera import controls
import RPi.GPIO as gpio
import threading
import cv2
import os
import shutil

def empty_folder(folder_path):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            # If it's a file or a symbolic link, use os.unlink (or os.remove)
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            # If it's a directory, use shutil.rmtree to wipe its contents too
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f'Failed to delete {file_path}. Reason: {e}')

# GPIO setup
gpio.setmode(gpio.BCM)

# Define GPIO pins for stepper motor control
INA = 17  # Coil A positive
INB = 27  # Coil A negative
INC = 22  # Coil B positive
IND = 23  # Coil B negative

control_pins = [INA, INB, INC, IND]

# Define trigger pin
trigger_pin = 24

# Set up all pins as outputs
for pin in control_pins:
    gpio.setup(pin, gpio.OUT)
    gpio.output(pin, 0)

# Set up trigger pin as input
gpio.setup(trigger_pin, gpio.IN, pull_up_down=gpio.PUD_DOWN)

def turn_stepper_motor(steps=2048*4, delay=0.005):
    
    # Half-step sequence for smoother operation on Osepp STEPD-01 bipolar stepper motor
    step_sequence = [
        [1, 0, 0, 0],  # Step 0: Coil A
        [1, 0, 1, 0],  # Step 1: Coil A and B
        [0, 0, 1, 0],  # Step 2: Coil B
        [0, 1, 1, 0],  # Step 3: Coil B and -A
        [0, 1, 0, 0],  # Step 4: Coil -A
        [0, 1, 0, 1],  # Step 5: Coil -A and -B
        [0, 0, 0, 1],  # Step 6: Coil -B
        [1, 0, 0, 1],  # Step 7: Coil -B and A
    ]
    
    step_count = len(step_sequence)
    
    print(f"Starting stepper motor rotation with half-stepping ({steps} steps)...")
    
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
camera.resolution = (4608, 2592)

camera.start(show_preview=True)
camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
success = camera.autofocus_cycle()
job = camera.autofocus_cycle(wait=False)

if not os.path.exists('image_send'):
    os.makedirs('image_send')

while True:
    now = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm")

    empty_folder('image_send')

    # Wait for GPIO trigger
    print(f"Waiting for GPIO trigger on pin {trigger_pin}...")
    gpio.wait_for_edge(trigger_pin, gpio.RISING)
    print("Trigger detected, starting video capture pipeline...")

    # Start motor rotation in a separate thread
    motor_thread = threading.Thread(target=turn_stepper_motor)
    motor_thread.start()

    # Start video recording
    success = camera.wait(job)
    camera.start_and_record_video(f"testvideo{now}.mp4", duration=30)

    # Wait for motor to finish
    motor_thread.join()

    sleep(2)

    # Extract frames from the video
    video_path = f"testvideo{now}.mp4"
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    for i in range(50):
        frame_num = int(i * total_frames / 50)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(f'image_send/frame_{i:02d}.jpg', frame)

    cap.release()
    print("Frame extraction complete!")

# Clean up GPIO pins (unreachable in continuous mode)
gpio.cleanup()