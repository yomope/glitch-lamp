import os
import cv2
import numpy as np
from backend.plugins.base import VideoEffect


class Posterize(VideoEffect):
    """Posterise la vidéo (réduction de palette)."""

    def __init__(self):
        self.levels = 4

    @property
    def name(self) -> str:
        return "posterize"

    @property
    def description(self) -> str:
        return "Réduction du nombre de niveaux (posterize)"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {"name": "levels", "type": "int", "default": 4, "min": 2, "max": 32, "label": "Niveaux"},
        ]

    def update_options(self, options: dict):
        try:
            self.levels = int(options.get("levels", self.levels))
        except Exception:
            self.levels = 4
        self.levels = max(2, min(32, self.levels))

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        if not input_path or not os.path.exists(input_path):
            return input_path
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return input_path

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*'mp4v'),
            float(fps),
            (width, height)
        )

        levels = float(self.levels)
        scale = 255.0 / (levels - 1)

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            f = frame.astype(np.float32)
            f = np.round(f / scale) * scale
            f = np.clip(f, 0, 255).astype(np.uint8)
            writer.write(f)

        cap.release()
        writer.release()
        return output_path if os.path.exists(output_path) else input_path
