import os
import random
import cv2
import numpy as np
from typing import List
from backend.plugins.base import VideoEffect


class Chopper(VideoEffect):
    """Assemble des portions aléatoires (1 à 4 flux) dans un seul clip."""

    def __init__(self):
        self.num_cuts = 6
        self.final_duration = 8.0
        self.equal_segments = True
        self.min_seg = 0.4
        self.max_seg = 2.5

    @property
    def name(self) -> str:
        return "chopper"

    @property
    def description(self) -> str:
        return "Découpe/concat aléatoire (1-4 entrées)"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {"name": "num_cuts", "type": "int", "default": 6, "min": 1, "max": 50, "label": "Nb de cuts"},
            {"name": "final_duration", "type": "float", "default": 8.0, "min": 1.0, "max": 120.0, "step": 0.1, "label": "Durée finale (s)"},
            {"name": "equal_segments", "type": "bool", "default": True, "label": "Durées égales"},
            {"name": "min_seg", "type": "float", "default": 0.4, "min": 0.1, "max": 10.0, "step": 0.1, "label": "Durée min (aléa)"},
            {"name": "max_seg", "type": "float", "default": 2.5, "min": 0.2, "max": 20.0, "step": 0.1, "label": "Durée max (aléa)"},
        ]

    def update_options(self, options: dict):
        self.num_cuts = max(1, int(options.get("num_cuts", self.num_cuts) or self.num_cuts))
        self.final_duration = float(options.get("final_duration", self.final_duration) or self.final_duration)
        self.equal_segments = bool(options.get("equal_segments", self.equal_segments))
        self.min_seg = float(options.get("min_seg", self.min_seg) or self.min_seg)
        self.max_seg = float(options.get("max_seg", self.max_seg) or self.max_seg)
        if self.max_seg < self.min_seg:
            self.max_seg = self.min_seg

    def _read_frames(self, path: str):
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
        # inputs: list de chemins (jusqu'à 4)
        inputs: List[str] = []
        if input_path:
            inputs.append(input_path)
        extra = kwargs.get("inputs") or []
        for p in extra:
            if p and p not in inputs:
                inputs.append(p)
        inputs = [p for p in inputs if p and os.path.exists(p)]
        if not inputs:
            return input_path

        videos = []
        fps_list = []
        for p in inputs[:4]:
            fr, fps = self._read_frames(p)
            if fr:
                videos.append(fr)
                fps_list.append(fps if fps > 1e-2 else 30.0)

        if not videos:
            return input_path

        # Ajuster résolution à la plus petite
        min_h = min(f.shape[0] for vid in videos for f in vid)
        min_w = min(f.shape[1] for vid in videos for f in vid)
        videos = [[cv2.resize(f, (min_w, min_h), interpolation=cv2.INTER_AREA) for f in vid] for vid in videos]

        fps_out = fps_list[0] if fps_list else 30.0

        # Plan de coupes
        if self.equal_segments or self.num_cuts <= 1:
            seg_len = max(0.1, self.final_duration / self.num_cuts)
            seg_lengths = [seg_len] * self.num_cuts
        else:
            seg_lengths = []
            remaining = self.final_duration
            for i in range(self.num_cuts):
                max_allow = max(self.min_seg, min(self.max_seg, remaining - self.min_seg * (self.num_cuts - i - 1)))
                min_allow = max(self.min_seg, min(self.max_seg, max(0.1, remaining - self.max_seg * (self.num_cuts - i - 1))))
                if max_allow < min_allow:
                    max_allow = min_allow
                length = random.uniform(min_allow, max_allow)
                seg_lengths.append(length)
                remaining -= length
                if remaining <= 0:
                    break

        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*'mp4v'),
            float(fps_out),
            (min_w, min_h)
        )

        for seg_len in seg_lengths:
            src_idx = random.randint(0, len(videos) - 1)
            vid = videos[src_idx]
            total_frames = len(vid)
            if total_frames == 0:
                continue
            seg_frames = max(1, int(seg_len * fps_out))
            if seg_frames >= total_frames:
                # boucle si nécessaire
                for i in range(seg_frames):
                    writer.write(vid[i % total_frames])
                continue
            start = random.randint(0, total_frames - seg_frames)
            for i in range(seg_frames):
                writer.write(vid[start + i])

        writer.release()
        return output_path if os.path.exists(output_path) else input_path
