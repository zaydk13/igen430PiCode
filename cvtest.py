import numpy
from picamera2 import Picamera2, Preview
from libcamera import Transform
import time
import cv2 as cv
from matplotlib import pyplot as plt
 
imgL = cv.imread('sampleL.png', cv.IMREAD_GRAYSCALE)
imgR = cv.imread('sampleR.png', cv.IMREAD_GRAYSCALE)
 
stereo = cv.StereoBM.create(numDisparities=16, blockSize=15)
stereo.setUniquenessRatio(5)
stereo.setTextureThreshold(200)
disparity = stereo.compute(imgL,imgR)
plt.imshow(disparity,'gray')
plt.show()

'''


'''
