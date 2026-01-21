from time import sleep
import datetime
from picamera2 import Picamera2
from libcamera import controls

camera = Picamera2()
camera.resolution = (1024, 768)

camera.start(show_preview=True)
camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})

now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
camera.start_and_record_video(f"testvideo{now}.mp4", duration = 30)

sleep(2)
camera.close()