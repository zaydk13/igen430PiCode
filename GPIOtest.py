import RPi.GPIO as gpio
import time

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

def turn_stepper_motor(steps=200, delay=0.01):
    """
    Turn a stepper motor one full rotation.
    
    Args:
        steps: Number of steps (default 200 for one full turn with half-step sequence)
        delay: Time delay between steps in seconds (default 0.01)
    """
    # Half-step sequence for bipolar stepper motor
    step_sequence = [
        [1, 0, 0, 1],  # Step 0
        [1, 0, 0, 0],  # Step 1
        [1, 1, 0, 0],  # Step 2
        [0, 1, 0, 0],  # Step 3
        [0, 1, 1, 0],  # Step 4
        [0, 0, 1, 0],  # Step 5
        [0, 0, 1, 1],  # Step 6
        [0, 0, 0, 1],  # Step 7
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

try:
    # Execute one full turn
    turn_stepper_motor(steps=200, delay=0.01)
    
finally:
    # Clean up GPIO pins
    gpio.cleanup()