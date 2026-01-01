import os
import random
import cv2
import numpy as np
from backend.plugins.base import VideoEffect


class NoiseSource(VideoEffect):
    """Génère une source vidéo de bruit synthétique (aucune entrée requise)."""

    def __init__(self):
        self.duration = 6
        self.width = 1280
        self.height = 720
        self.fps = 30
        self.noise_type = "white"
        self.seed = None

    @property
    def name(self) -> str:
        return "noise"

    @property
    def description(self) -> str:
        return "Source bruit (white/gauss/film grain)"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {"name": "duration", "type": "int", "default": 6, "min": 1, "max": 120, "label": "Durée (s)"},
            {"name": "width", "type": "int", "default": 1280, "min": 160, "max": 3840, "label": "Largeur"},
            {"name": "height", "type": "int", "default": 720, "min": 160, "max": 2160, "label": "Hauteur"},
            {"name": "fps", "type": "int", "default": 30, "min": 10, "max": 60, "label": "FPS"},
            {"name": "noise_type", "type": "select", "default": "white", "options": ["white", "gauss", "film"], "label": "Type"},
            {"name": "seed", "type": "int", "default": 0, "min": 0, "max": 2_147_483_647, "label": "Seed (0=random)"},
        ]

    def update_options(self, options: dict):
        self.duration = int(options.get("duration", self.duration) or self.duration)
        self.width = int(options.get("width", self.width) or self.width)
        self.height = int(options.get("height", self.height) or self.height)
        self.fps = int(options.get("fps", self.fps) or self.fps)
        self.noise_type = options.get("noise_type", self.noise_type) or self.noise_type
        seed_val = int(options.get("seed", 0) or 0)
        self.seed = None if seed_val == 0 else seed_val

    def _rng(self):
        if self.seed is None:
            return np.random.default_rng()
        return np.random.default_rng(self.seed)

    def _frame_white(self, rng):
        return rng.integers(0, 256, size=(self.height, self.width, 3), dtype=np.uint8)

    def _frame_gauss(self, rng):
        frame = rng.normal(127, 36, size=(self.height, self.width, 3))
        return np.clip(frame, 0, 255).astype(np.uint8)

    def _frame_film(self, rng, t):
        base = self._frame_gauss(rng)
        flicker = 1.0 + 0.05 * np.sin(t * 3.14 * 2)
        grain = self._frame_white(rng).astype(np.float32) * 0.15
        out = np.clip(base.astype(np.float32) * flicker + grain, 0, 255)
        return out.astype(np.uint8)

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        rng = self._rng()
        if self.width <= 0 or self.height <= 0 or self.fps <= 0 or self.duration <= 0:
            return input_path

        # Essayer plusieurs codecs en ordre de préférence
        codecs_to_try = [
            ('H264', cv2.VideoWriter_fourcc(*'H264')),
            ('XVID', cv2.VideoWriter_fourcc(*'XVID')),
            ('mp4v', cv2.VideoWriter_fourcc(*'mp4v')),
            ('MJPG', cv2.VideoWriter_fourcc(*'MJPG')),
        ]
        
        from backend.utils.logger import logger
        writer = None
        codec_used = None
        
        for codec_name, fourcc in codecs_to_try:
            try:
                writer = cv2.VideoWriter(
                    output_path,
                    fourcc,
                    float(self.fps),
                    (int(self.width), int(self.height))
                )
                
                if writer.isOpened():
                    codec_used = codec_name
                    logger.debug(f"NoiseSource: Using codec {codec_name}")
                    break
                else:
                    writer.release()
                    writer = None
            except Exception as e:
                logger.warning(f"NoiseSource: Failed to open with codec {codec_name}: {e}")
                if writer:
                    writer.release()
                    writer = None
                continue
        
        if not writer or not writer.isOpened():
            error_msg = f"Failed to open VideoWriter for noise source with any codec: {output_path}"
            logger.error(f"NoiseSource: {error_msg}")
            raise Exception(error_msg)
        
        total_frames = int(self.duration * self.fps)
        frames_written = 0
        
        try:
            for i in range(total_frames):
                if self.noise_type == "gauss":
                    frame = self._frame_gauss(rng)
                elif self.noise_type == "film":
                    frame = self._frame_film(rng, i / self.fps)
                else:
                    frame = self._frame_white(rng)
                
                # writer.write() peut retourner False même si l'écriture réussit
                # On écrit quand même et on vérifiera le fichier final
                writer.write(frame)
                frames_written += 1
        finally:
            writer.release()
        
        # Vérifier que le fichier a été créé et contient des données
        if not os.path.exists(output_path):
            error_msg = f"Noise source file was not created: {output_path}"
            logger.error(f"NoiseSource: {error_msg}")
            raise Exception(error_msg)
        
        file_size = os.path.getsize(output_path)
        if file_size == 0:
            error_msg = f"Noise source file is empty: {output_path}"
            logger.error(f"NoiseSource: {error_msg}")
            raise Exception(error_msg)
        
        # Vérifier que le fichier contient au moins quelques frames
        # Un fichier vidéo valide devrait avoir une taille minimale
        min_expected_size = total_frames * self.width * self.height * 3 // 100  # Au moins 1% de la taille brute
        if file_size < min_expected_size:
            error_msg = f"Noise source file is too small ({file_size} bytes, expected at least {min_expected_size}): {output_path}. Only {frames_written}/{total_frames} frames written."
            logger.error(f"NoiseSource: {error_msg}")
            raise Exception(error_msg)
        
        logger.debug(f"NoiseSource: Successfully created {output_path} with {frames_written} frames using codec {codec_used}")
        return output_path
