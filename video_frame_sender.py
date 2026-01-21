import cv2
import socket
import numpy as np
import time
import os

# --- Configuration ---
VIDEO_FILE = "testvideo26-11-2025.mp4"
NUM_FRAMES = 50
REMOTE_HOST = '10.43.234.253'  # Change this to the IP address of the remote PC
REMOTE_PORT = 65432      # Must match the port the server on the remote PC is listening on

def send_frame_to_remote(frame_data: bytes, frame_index: int):
    """
    Connects to the remote host and sends the size of the frame data,
    followed by the frame data itself.
    """
    print(f"[Sender] Attempting to send Frame {frame_index} data...")

    try:
        # Create a socket object
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Connect to the remote server
            s.connect((REMOTE_HOST, REMOTE_PORT))
            print(f"[Sender] Connected to {REMOTE_HOST}:{REMOTE_PORT}")

            # 1. Send the size of the data (4 bytes)
            data_size = len(frame_data)
            s.sendall(data_size.to_bytes(4, byteorder='big'))

            # 2. Send the frame index (4 bytes)
            s.sendall(frame_index.to_bytes(4, byteorder='big'))

            # 3. Send the actual frame data
            s.sendall(frame_data)

            print(f"[Sender] Successfully sent Frame {frame_index} ({data_size} bytes)")

    except ConnectionRefusedError:
        print(f"[ERROR] Connection to {REMOTE_HOST}:{REMOTE_PORT} refused.")
        print("    --> Ensure a server program is running on the remote PC and listening on this IP/Port.")
        print("    --> Ensure the firewall allows the connection.")
    except socket.gaierror:
        print(f"[ERROR] Address lookup failed for {REMOTE_HOST}. Check the IP address.")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during transmission: {e}")

def extract_and_send_frames():
    """
    Main function to extract, process, and send video frames.
    """
    if not os.path.exists(VIDEO_FILE):
        print(f"[FATAL] Video file '{VIDEO_FILE}' not found.")
        print("Please ensure the file exists in the same directory as this script.")
        return

    # Open the video file
    cap = cv2.VideoCapture(VIDEO_FILE)

    if not cap.isOpened():
        print(f"[FATAL] Could not open video file '{VIDEO_FILE}'.")
        return

    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video opened. Total frames: {total_frames}")

    if total_frames < NUM_FRAMES:
        print(f"[WARNING] Video has less than {NUM_FRAMES} frames. Using all available frames.")
        frames_to_extract = total_frames
    else:
        frames_to_extract = NUM_FRAMES

    # Calculate the interval for evenly spaced frames
    frame_interval = total_frames / frames_to_extract

    extracted_count = 0

    print("-" * 40)
    print(f"Extracting {frames_to_extract} evenly spaced frames...")
    print("-" * 40)

    for i in range(frames_to_extract):
        # Calculate the exact frame index to sample
        target_frame_index = round(i * frame_interval)

        # Skip the last frame if it's beyond the count (due to rounding)
        if target_frame_index >= total_frames:
             break

        # Set the position of the next frame to be read
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_index)

        # Read the frame
        ret, frame = cap.read()

        if not ret:
            print(f"[WARNING] Failed to read frame at index {target_frame_index}. Skipping.")
            continue

        # 1. Convert to grayscale
        grayscale_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 2. Encode the frame into a memory buffer (JPEG format)
        # We use JPEG because it's compressed, suitable for network transfer.
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90] # JPEG quality 90
        success, buffer = cv2.imencode('.jpg', grayscale_frame, encode_param)

        if not success:
            print(f"[ERROR] Failed to encode frame {i} to JPEG buffer.")
            continue

        # Convert the NumPy array buffer to bytes
        frame_bytes = buffer.tobytes()

        # 3. Send the encoded frame remotely
        send_frame_to_remote(frame_bytes, i)

        extracted_count += 1
        time.sleep(0.1) # Brief pause between sending frames

    # Release the video capture object
    cap.release()
    print("-" * 40)
    print(f"Extraction and sending complete. Sent {extracted_count} frames.")

if __name__ == "__main__":
    # Ensure you have the OpenCV library installed:
    # pip install opencv-python
    
    # IMPORTANT: You must rename your video file to "testvideo.mp4" 
    # and place it in the same directory as this script.
    
    extract_and_send_frames()