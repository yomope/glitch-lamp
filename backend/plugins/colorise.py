import cv2
import numpy as np
from backend.plugins.base import VideoEffect

class ColoriseEffect(VideoEffect):
    def __init__(self):
        self.colormap_name = "HOT"
        self.colormaps = {
            "AUTUMN": cv2.COLORMAP_AUTUMN,
            "BONE": cv2.COLORMAP_BONE,
            "JET": cv2.COLORMAP_JET,
            "WINTER": cv2.COLORMAP_WINTER,
            "RAINBOW": cv2.COLORMAP_RAINBOW,
            "OCEAN": cv2.COLORMAP_OCEAN,
            "SUMMER": cv2.COLORMAP_SUMMER,
            "SPRING": cv2.COLORMAP_SPRING,
            "COOL": cv2.COLORMAP_COOL,
            "HSV": cv2.COLORMAP_HSV,
            "PINK": cv2.COLORMAP_PINK,
            "HOT": cv2.COLORMAP_HOT,
            "PARULA": cv2.COLORMAP_PARULA,
            "MAGMA": cv2.COLORMAP_MAGMA,
            "INFERNO": cv2.COLORMAP_INFERNO,
            "PLASMA": cv2.COLORMAP_PLASMA,
            "VIRIDIS": cv2.COLORMAP_VIRIDIS,
            "CIVIDIS": cv2.COLORMAP_CIVIDIS,
            "TWILIGHT": cv2.COLORMAP_TWILIGHT,
            "TWILIGHT_SHIFTED": cv2.COLORMAP_TWILIGHT_SHIFTED,
            "TURBO": cv2.COLORMAP_TURBO,
            "DEEPGREEN": cv2.COLORMAP_DEEPGREEN
        }

    @property
    def name(self):
        return "colorise"

    @property
    def description(self):
        return "Applies a color map to the video"

    @property
    def options(self):
        return [
            {"name": "colormap", "type": "select", "default": "HOT", "options": list(self.colormaps.keys()), "label": "Color Map", "tooltip": "The color scheme to apply"}
        ]

    def update_options(self, options: dict):
        self.colormap_name = options.get("colormap", self.colormap_name)
        print(f"ColoriseEffect updated: colormap={self.colormap_name}")

    def apply_frame(self, frame: np.ndarray, **kwargs) -> np.ndarray:
        colormap_id = self.colormaps.get(self.colormap_name, cv2.COLORMAP_HOT)
        # print(f"Applying colormap: {self.colormap_name} -> {colormap_id}")
        return cv2.applyColorMap(frame, colormap_id)
