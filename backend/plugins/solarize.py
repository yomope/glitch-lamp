import numpy as np
from backend.plugins.base import VideoEffect

class SolarizeEffect(VideoEffect):
    def __init__(self):
        self.threshold = 128

    @property
    def name(self):
        return "solarize"

    @property
    def description(self):
        return "Inverts colors above a threshold"

    @property
    def options(self):
        return [
            {"name": "threshold", "type": "int", "default": 128, "min": 0, "max": 255, "label": "Threshold", "tooltip": "Pixels brighter than this value get inverted."}
        ]

    def update_options(self, options: dict):
        self.threshold = options.get("threshold", self.threshold)

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        # Apply solarization
        # Where pixel > threshold, invert it
        # We use numpy boolean indexing for efficiency
        mask = frame >= self.threshold
        frame[mask] = 255 - frame[mask]
        return frame
