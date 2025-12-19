import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class BloomEffect(VideoEffect):
    def __init__(self):
        self.threshold = 200
        self.blur_amount = 21
        self.intensity = 1.0

    @property
    def name(self):
        return "bloom"

    @property
    def description(self):
        return "Adds a glow effect to bright areas"

    @property
    def options(self):
        return [
            {"name": "threshold", "type": "int", "default": 200, "min": 0, "max": 255, "label": "Threshold", "tooltip": "Brightness threshold for glow"},
            {"name": "blur_amount", "type": "int", "default": 21, "min": 1, "max": 100, "label": "Blur Amount", "tooltip": "Spread of the glow"},
            {"name": "intensity", "type": "float", "default": 1.0, "min": 0.0, "max": 5.0, "label": "Intensity", "tooltip": "Strength of the glow"}
        ]

    def update_options(self, options: dict):
        self.threshold = options.get("threshold", self.threshold)
        k = options.get("blur_amount", self.blur_amount)
        if k % 2 == 0:
            k += 1
        self.blur_amount = k
        self.intensity = options.get("intensity", self.intensity)

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        # Convert to grayscale for thresholding
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Create a mask of bright areas
        _, mask = cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY)
        
        # Create an image containing only the bright parts
        bright_parts = cv2.bitwise_and(frame, frame, mask=mask)
        
        # Blur the bright parts
        blurred_bright = cv2.GaussianBlur(bright_parts, (self.blur_amount, self.blur_amount), 0)
        
        # Add the blurred bright parts to the original image
        # Use addWeighted to control intensity
        bloomed = cv2.addWeighted(frame, 1.0, blurred_bright, self.intensity, 0)
        
        return bloomed
