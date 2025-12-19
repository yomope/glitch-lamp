import cv2
import numpy as np
from collections import deque
from backend.plugins.base import VideoEffect

class DoubleExposureEffect(VideoEffect):
    def __init__(self):
        self.delay_frames = 30
        self.opacity = 0.5
        self.buffer = deque()

    @property
    def name(self):
        return "double_exposure"

    @property
    def description(self):
        return "Blends current frame with a delayed previous frame"

    @property
    def options(self):
        return [
            {"name": "delay_frames", "type": "int", "default": 30, "min": 1, "max": 120, "label": "Delay (Frames)", "tooltip": "How many frames back to sample from"},
            {"name": "opacity", "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "label": "Opacity", "tooltip": "Opacity of the delayed frame"}
        ]

    def update_options(self, options: dict):
        self.delay_frames = options.get("delay_frames", self.delay_frames)
        self.opacity = options.get("opacity", self.opacity)

    def reset(self):
        self.buffer.clear()

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        self.buffer.append(frame.copy())
        
        if len(self.buffer) > self.delay_frames:
            delayed_frame = self.buffer.popleft()
            # Blend
            return cv2.addWeighted(frame, 1.0, delayed_frame, self.opacity, 0)
        
        return frame
