import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class ColorAdjustEffect(VideoEffect):
    def __init__(self):
        self.hue_shift = 0
        self.saturation_scale = 1.0
        self.luminosity_scale = 1.0
        self.contrast = 1.0
        self.brightness = 0

    @property
    def name(self):
        return "color_adjust"

    @property
    def description(self):
        return "Adjust Hue, Saturation, Luminosity, and Contrast"

    @property
    def options(self):
        return [
            {"name": "hue_shift", "type": "int", "default": 0, "min": -180, "max": 180, "label": "Hue Shift", "tooltip": "Shift colors around the color wheel"},
            {"name": "saturation_scale", "type": "float", "default": 1.0, "min": 0.0, "max": 3.0, "label": "Saturation", "tooltip": "Color intensity"},
            {"name": "luminosity_scale", "type": "float", "default": 1.0, "min": 0.0, "max": 3.0, "label": "Luminosity", "tooltip": "Brightness multiplier"},
            {"name": "contrast", "type": "float", "default": 1.0, "min": 0.0, "max": 3.0, "label": "Contrast", "tooltip": "Difference between light and dark"},
            {"name": "brightness", "type": "int", "default": 0, "min": -100, "max": 100, "label": "Brightness", "tooltip": "Brightness offset"}
        ]

    def update_options(self, options: dict):
        self.hue_shift = options.get("hue_shift", self.hue_shift)
        self.saturation_scale = options.get("saturation_scale", self.saturation_scale)
        self.luminosity_scale = options.get("luminosity_scale", self.luminosity_scale)
        self.contrast = options.get("contrast", self.contrast)
        self.brightness = options.get("brightness", self.brightness)

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        # Apply Contrast and Brightness first (linear transform)
        # new_img = alpha * old_img + beta
        if self.contrast != 1.0 or self.brightness != 0:
            frame = cv2.convertScaleAbs(frame, alpha=self.contrast, beta=self.brightness)

        # Convert to HSV for Hue/Sat/Lum
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        
        # Hue shift
        if self.hue_shift != 0:
            hsv[:, :, 0] = (hsv[:, :, 0] + self.hue_shift) % 180
            
        # Saturation scale
        if self.saturation_scale != 1.0:
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * self.saturation_scale, 0, 255)
            
        # Luminosity (Value) scale
        if self.luminosity_scale != 1.0:
            hsv[:, :, 2] = np.clip(hsv[:, :, 2] * self.luminosity_scale, 0, 255)
            
        # Convert back to BGR
        hsv = hsv.astype(np.uint8)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        
        return frame
