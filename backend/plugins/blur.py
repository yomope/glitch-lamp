import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class BlurEffect(VideoEffect):
    def __init__(self):
        self.kernel_size = 5

    @property
    def name(self):
        return "blur"

    @property
    def description(self):
        return "Applies Gaussian blur to the video"

    @property
    def options(self):
        return [
            {"name": "kernel_size", "type": "int", "default": 5, "min": 1, "max": 50, "label": "Kernel Size", "tooltip": "Size of the blur kernel (must be odd)"}
        ]

    def update_options(self, options: dict):
        k = options.get("kernel_size", self.kernel_size)
        if k % 2 == 0:
            k += 1
        self.kernel_size = k

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        return cv2.GaussianBlur(frame, (self.kernel_size, self.kernel_size), 0)
