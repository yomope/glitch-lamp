import os
import cv2
import numpy as np
from backend.plugins.base import VideoEffect


class TransferMotion(VideoEffect):
    """Transfère les vecteurs de mouvement d'une 2e vidéo vers la 1ère (warp)."""

    def __init__(self):
        self.strength = 1.0

    @property
    def name(self) -> str:
        return "transfer-motion"

    @property
    def description(self) -> str:
        return "Transfert de mouvement (2 entrées)"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {"name": "strength", "type": "float", "default": 1.0, "min": 0.1, "max": 2.0, "step": 0.05, "label": "Intensité du warp"},
        ]

    def update_options(self, options: dict):
        try:
            self.strength = float(options.get("strength", self.strength))
        except Exception:
            self.strength = 1.0
        self.strength = max(0.1, min(2.0, self.strength))

    def _read_frames(self, path):
        cap = cv2.VideoCapture(path)
        frames = []
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        cap.release()
        return frames, fps

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        second_input = kwargs.get("second_input")
        if not input_path or not second_input or not os.path.exists(input_path) or not os.path.exists(second_input):
            return input_path

        frames_a, fps_a = self._read_frames(input_path)
        frames_b, fps_b = self._read_frames(second_input)
        if not frames_a or not frames_b or len(frames_b) < 2:
            return input_path

        # Ajuster dimensions : prendre le plus petit cadre des deux
        hA, wA = frames_a[0].shape[:2]
        hB, wB = frames_b[0].shape[:2]
        w = min(wA, wB)
        h = min(hA, hB)
        frames_a = [cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA) for f in frames_a]
        frames_b = [cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA) for f in frames_b]

        # Durée : couper au plus court
        max_len = min(len(frames_a), len(frames_b) - 1)
        frames_a = frames_a[:max_len]
        frames_b = frames_b[:max_len + 1]

        fps_out = fps_a if fps_a > 1e-2 else fps_b if fps_b > 1e-2 else 30.0
        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*'mp4v'),
            float(fps_out),
            (w, h)
        )

        grid_x, grid_y = np.meshgrid(np.arange(w), np.arange(h))

        for idx in range(max_len):
            frame_a = frames_a[idx]
            frame_b0 = frames_b[idx]
            frame_b1 = frames_b[idx + 1] if idx + 1 < len(frames_b) else frames_b[idx]
            gray0 = cv2.cvtColor(frame_b0, cv2.COLOR_BGR2GRAY)
            gray1 = cv2.cvtColor(frame_b1, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(
                gray0, gray1, None,
                pyr_scale=0.5, levels=3, winsize=21, iterations=3, poly_n=5, poly_sigma=1.2, flags=0
            )
            flow_x = flow[..., 0] * self.strength
            flow_y = flow[..., 1] * self.strength
            map_x = (grid_x + flow_x).astype(np.float32)
            map_y = (grid_y + flow_y).astype(np.float32)
            warped = cv2.remap(frame_a, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)
            writer.write(warped)

        writer.release()
        return output_path if os.path.exists(output_path) else input_path
