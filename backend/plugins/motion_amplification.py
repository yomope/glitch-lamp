import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class MotionAmplificationEffect(VideoEffect):
    def __init__(self):
        self.factor = 2.0
        self.previous_frame = None

    @property
    def name(self):
        return "motion_amplification"

    @property
    def description(self):
        return "Amplifies movement between frames"

    @property
    def options(self):
        return [
            {"name": "factor", "type": "float", "default": 2.0, "min": 1.0, "max": 10.0, "label": "Amplification Factor", "tooltip": "Strength of the motion amplification"}
        ]

    def update_options(self, options: dict):
        self.factor = options.get("factor", self.factor)

    def reset(self):
        self.previous_frame = None

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        if self.previous_frame is None:
            self.previous_frame = frame.copy()
            return frame

        # Calculate difference
        # Convert to float to avoid overflow/underflow during subtraction
        current_float = frame.astype(np.float32)
        prev_float = self.previous_frame.astype(np.float32)
        
        diff = current_float - prev_float
        
        # Amplify difference
        amplified_diff = diff * self.factor
        
        # Add back to current frame
        result = current_float + amplified_diff
        
        # Clip to valid range
        result = np.clip(result, 0, 255).astype(np.uint8)
        
        # Update previous frame
        self.previous_frame = frame.copy()
        
        return result
