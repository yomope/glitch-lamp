import numpy as np
import cv2
import random
from backend.plugins.base import VideoEffect

class GlitchEffect(VideoEffect):
    def __init__(self):
        self.probability = 0.1
        self.intensity = 20
        self.scanline_jitter = True

    @property
    def name(self):
        return "glitch"

    @property
    def description(self):
        return "Digital noise and color channel shifting"

    @property
    def options(self):
        return [
            {"name": "probability", "type": "float", "default": 0.1, "min": 0.0, "max": 1.0, "step": 0.05, "label": "Glitch Probability", "tooltip": "Chance that a frame will be glitched."},
            {"name": "intensity", "type": "int", "default": 20, "min": 1, "max": 100, "label": "Intensity", "tooltip": "How far channels shift and lines jump."},
            {"name": "scanline_jitter", "type": "bool", "default": True, "label": "Scanline Jitter", "tooltip": "Adds horizontal jitter to random scanlines."}
        ]

    def update_options(self, options: dict):
        self.probability = options.get("probability", self.probability)
        self.intensity = options.get("intensity", self.intensity)
        self.scanline_jitter = options.get("scanline_jitter", self.scanline_jitter)

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        if random.random() > self.probability: # Only glitch sometimes
            return frame
            
        h, w, c = frame.shape
        
        # 1. Color Channel Shift
        shift = random.randint(-self.intensity, self.intensity)
        if shift != 0:
            # Split channels
            b, g, r = cv2.split(frame)
            # Shift one channel
            if random.choice([True, False]):
                b = np.roll(b, shift, axis=1)
            else:
                r = np.roll(r, shift, axis=0)
            frame = cv2.merge([b, g, r])

        # 2. Scanline Jitter
        if self.scanline_jitter and random.random() > 0.5:
            num_lines = random.randint(1, 10)
            for _ in range(num_lines):
                y = random.randint(0, h-1)
                x_shift = random.randint(-50, 50)
                frame[y, :] = np.roll(frame[y, :], x_shift, axis=0)

        return frame
