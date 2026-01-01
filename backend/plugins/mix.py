import cv2
import numpy as np
import os
from typing import Optional
from backend.plugins.base import VideoEffect


def _mode_screen(a, b):
    return 255 - ((255 - a) * (255 - b) // 255)


def _mode_overlay(a, b):
    mask = a > 127
    res = np.empty_like(a)
    res[~mask] = (2 * a[~mask] * b[~mask]) // 255
    res[mask] = 255 - (2 * (255 - a[mask]) * (255 - b[mask]) // 255)
    return res


class MixEffect(VideoEffect):
    def __init__(self):
        self.mode = "normal"
        self.opacity = 0.5

    @property
    def name(self) -> str:
        return "mix"

    @property
    def description(self) -> str:
        return "Mixe deux vidéos avec modes de fusion"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {
                "name": "mode",
                "type": "select",
                "default": "normal",
                "options": ["normal", "add", "screen", "multiply", "overlay", "lighten", "darken", "difference", "subtract"],
                "label": "Mode de fusion",
            },
            {
                "name": "opacity",
                "type": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "label": "Opacité",
            },
        ]

    def update_options(self, options: dict):
        self.mode = options.get("mode", self.mode)
        self.opacity = float(options.get("opacity", self.opacity))
        self.opacity = min(1.0, max(0.0, self.opacity))

    def reset(self):
        pass

    def apply_file(self, input_path: str, output_path: str, second_input: Optional[str] = None, **kwargs) -> str:
        if not second_input or not os.path.exists(second_input):
            # Rien à mixer, passer au travers
            return input_path

        cap_a = cv2.VideoCapture(input_path)
        cap_b = cv2.VideoCapture(second_input)

        if not cap_a.isOpened() or not cap_b.isOpened():
            if cap_a: cap_a.release()
            if cap_b: cap_b.release()
            return input_path

        fps_a = cap_a.get(cv2.CAP_PROP_FPS) or 30
        fps_b = cap_b.get(cv2.CAP_PROP_FPS) or 30
        fps = max(1.0, min(fps_a, fps_b))

        w_a, h_a = int(cap_a.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap_a.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w_b, h_b = int(cap_b.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap_b.get(cv2.CAP_PROP_FRAME_HEIGHT))
        tgt_w, tgt_h = min(w_a, w_b), min(h_a, h_b)
        if tgt_w <= 0 or tgt_h <= 0:
            cap_a.release(); cap_b.release()
            return input_path

        frames_a = int(cap_a.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frames_b = int(cap_b.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        max_frames = max(frames_a, frames_b)
        if max_frames <= 0:
            max_frames = max(1, frames_a + frames_b)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, fps, (tgt_w, tgt_h))

        def _read_loop(cap, total_frames):
            nonlocal fps
            idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    if total_frames <= 0:
                        break
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if not ret:
                        break
                yield idx, frame
                idx += 1

        iter_a = _read_loop(cap_a, frames_a)
        iter_b = _read_loop(cap_b, frames_b)

        count = 0
        for _, frame_a in iter_a:
            try:
                _, frame_b = next(iter_b)
            except StopIteration:
                break

            if frame_a.shape[1] != tgt_w or frame_a.shape[0] != tgt_h:
                frame_a = cv2.resize(frame_a, (tgt_w, tgt_h), interpolation=cv2.INTER_AREA)
            if frame_b.shape[1] != tgt_w or frame_b.shape[0] != tgt_h:
                frame_b = cv2.resize(frame_b, (tgt_w, tgt_h), interpolation=cv2.INTER_AREA)

            a = frame_a.astype(np.uint16)
            b = frame_b.astype(np.uint16)

            if self.mode == "add":
                mixed = np.clip(a + b * self.opacity, 0, 255)
            elif self.mode == "screen":
                mixed = _mode_screen(a, (b * self.opacity).astype(np.uint16))
            elif self.mode == "multiply":
                mixed = (a * (b * self.opacity) // 255)
            elif self.mode == "overlay":
                mixed = _mode_overlay(a, (b * self.opacity).astype(np.uint16))
            elif self.mode == "lighten":
                mixed = np.maximum(a, (b * self.opacity))
            elif self.mode == "darken":
                mixed = np.minimum(a, (b * self.opacity))
            elif self.mode == "difference":
                mixed = np.abs(a.astype(np.int16) - (b * self.opacity).astype(np.int16))
            elif self.mode == "subtract":
                mixed = np.clip(a - (b * self.opacity), 0, 255)
            else:  # normal
                mixed = a * (1.0 - self.opacity) + b * self.opacity

            mixed = np.clip(mixed, 0, 255).astype(np.uint8)
            writer.write(mixed)
            count += 1
            if count >= max_frames:
                break

        cap_a.release()
        cap_b.release()
        writer.release()

        if os.path.exists(output_path):
            return output_path
        return input_path
