import cv2
import numpy as np
import time
import os
import http.server
import socketserver
from datetime import datetime
# Removed socket import as network functionality is no longer needed.

# --- Configuration ---
# If VIDEO_FILE is left None, the script will automatically pick the most
# recent video file in the current directory based on modification time.
VIDEO_FILE = None
VIDEO_EXTS = ('.mp4', '.mov', '.avi', '.mkv', '.MP4', '.MOV', '.AVI', '.MKV')
NUM_FRAMES = 50
# If None, we'll create a directory named after the selected video + timestamp
OUTPUT_DIR = None  # populated at runtime in the main block


def find_most_recent_video(directory: str = '.', exts: tuple = VIDEO_EXTS) -> str | None:
    """Return the path to the most recently modified file in `directory`
    whose extension is in `exts`. Returns None if no matching file is found.
    """
    try:
        entries = [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f)) and os.path.splitext(f)[1] in exts
        ]
    except FileNotFoundError:
        return None

    if not entries:
        return None

    # Sort by modification time, newest last
    entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return entries[0]

def save_compressed_frame(frame_data: bytes, frame_index: int):
    """
    Creates the output directory if it doesn't exist and saves the 
    compressed JPEG frame data to a local file.
    """
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    filename = os.path.join(OUTPUT_DIR, f"frame_{frame_index:02d}.jpg")
    
    try:
        # Write the raw JPEG bytes (the compressed data) directly to the file
        with open(filename, 'wb') as f:
            f.write(frame_data)
        
        print(f"[Processor] Saved Frame {frame_index} ({len(frame_data)} bytes) to {filename}")

    except Exception as e:
        print(f"[ERROR] An unexpected error occurred while saving frame {frame_index}: {e}")

def extract_and_process_frames():
    """
    Main function to extract evenly spaced frames, keep them in color,
    compress them using JPEG encoding, and save them.
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
    print(f"Extracting and compressing {frames_to_extract} evenly spaced frames...")
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

        # 1. Keep color frame (BGR). We do NOT convert to grayscale so
        # saved JPEGs retain full color information.
        color_frame = frame

        # 2. Encode the frame into a memory buffer (JPEG format for compression)
        # JPEG encoding is a form of compression. Quality 90 is a good balance.
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        success, buffer = cv2.imencode('.jpg', color_frame, encode_param)

        if not success:
            print(f"[ERROR] Failed to encode frame {i} to JPEG buffer.")
            continue

        # Convert the NumPy array buffer to bytes (this is the compressed data)
        frame_bytes = buffer.tobytes()

        # 3. Save the compressed frame locally
        save_compressed_frame(frame_bytes, i)

        extracted_count += 1
        time.sleep(0.01) # Small pause

    # Release the video capture object
    cap.release()
    print("-" * 40)
    print(f"Processing complete. Saved {extracted_count} compressed frames to '{OUTPUT_DIR}'.")

if __name__ == "__main__":
    # Ensure you have the OpenCV library installed:
    # pip install opencv-python
    # Choose the video file to process. If VIDEO_FILE is None, automatically
    # pick the most recent video in the current directory.
    if VIDEO_FILE is None:
        selected = find_most_recent_video('.')
        if selected is None:
            print("[FATAL] No video files found in the current directory.")
            print(f"Looking for extensions: {VIDEO_EXTS}")
            raise SystemExit(1)
        VIDEO_FILE = selected
        print(f"[INFO] Selected most recent video: {VIDEO_FILE}")

    # If OUTPUT_DIR was left None, create a timestamped directory based on the
    # selected video's basename so results are separated and easy to find.
    if OUTPUT_DIR is None:
        base = os.path.splitext(os.path.basename(VIDEO_FILE))[0]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        OUTPUT_DIR = f"compressed_{base}"
        print(f"[INFO] Using output directory: {OUTPUT_DIR}")

    extract_and_process_frames()

    # After extracting and saving frames, start a simple HTTP server
    # to serve the output directory so the Raspberry Pi acts as a server.
    def start_http_server(directory: str, port: int = 8000, bind: str = "0.0.0.0"):
        """
        Serve the given directory over HTTP on the specified port and bind address.
        Uses a ThreadingHTTPServer when available for simple concurrent serving.
        """
        if not os.path.isdir(directory):
            print(f"[ERROR] Output directory '{directory}' does not exist. Nothing to serve.")
            return

        # Change working directory so SimpleHTTPRequestHandler serves from `directory`.
        os.chdir(directory)

        handler = http.server.SimpleHTTPRequestHandler

        server_address = (bind, port)

        try:
            # ThreadingHTTPServer provides simple concurrency for clients
            with http.server.ThreadingHTTPServer(server_address, handler) as httpd:
                sa = httpd.socket.getsockname()
                print("-" * 40)
                print(f"Serving '{directory}' at http://{sa[0]}:{sa[1]}/")
                print("Press Ctrl+C to stop the server")
                print("-" * 40)
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    print("\n[INFO] Server stopped by user")
        except AttributeError:
            # Fallback for very old Python versions without ThreadingHTTPServer
            with socketserver.TCPServer(server_address, handler) as httpd:
                sa = httpd.socket.getsockname()
                print("-" * 40)
                print(f"Serving '{directory}' at http://{sa[0]}:{sa[1]}/")
                print("Press Ctrl+C to stop the server")
                print("-" * 40)
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    print("\n[INFO] Server stopped by user")

    # Start server on port 8000 binding to all interfaces so other devices
    # (e.g., your local machine) can access the Pi's served frames.
    try:
        start_http_server(OUTPUT_DIR, port=8000, bind="0.0.0.0")
    except Exception as e:
        print(f"[ERROR] Failed to start HTTP server: {e}")