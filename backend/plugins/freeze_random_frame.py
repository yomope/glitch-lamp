import os
import random
import cv2
import numpy as np
from backend.plugins.base import VideoEffect


class FreezeRandomFrame(VideoEffect):
    """Remplace toute la vidéo par un seul frame tiré au hasard."""

    def __init__(self):
        self.force_silent = False

    @property
    def name(self) -> str:
        return "freeze-random-frame"

    @property
    def description(self) -> str:
        return "Figer le flux sur une frame choisie aléatoirement"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {"name": "force_silent", "type": "bool", "default": False, "label": "Supprimer l'audio"},
        ]

    def update_options(self, options: dict):
        self.force_silent = bool(options.get("force_silent", False))

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        if not input_path or not os.path.exists(input_path):
            return input_path

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return input_path

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        if frame_count <= 0 or width <= 0 or height <= 0:
            cap.release()
            return input_path

        target_idx = random.randint(0, max(0, frame_count - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            # fallback: restart and grab first
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                return input_path

        cap.release()

        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*'mp4v'),
            float(fps),
            (width, height)
        )

        total_frames = frame_count if frame_count > 0 else int(fps * 5)
        for _ in range(total_frames):
            writer.write(frame)
        writer.release()

        # Audio: option to drop; if not forced silent, we just keep the silent video (no audio track)
        # (Adding a silent audio track adds complexity; we keep video-only by default)

        if os.path.exists(output_path):
            return output_path
        return input_path
