import os
import shutil
import subprocess
import cv2
from backend.plugins.base import VideoEffect


class SlowMoInterpolation(VideoEffect):
    """Ralentit la séquence en interpolant des frames pour conserver la fluidité."""

    def __init__(self):
        self.factor = 2.0

    @property
    def name(self) -> str:
        return "slowmo"

    @property
    def description(self) -> str:
        return "Ralenti fluide via interpolation de mouvement (FFmpeg minterpolate)"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {
                "name": "factor",
                "type": "float",
                "default": 2.0,
                "min": 1.0,
                "max": 8.0,
                "step": 0.1,
                "label": "Facteur de ralenti (>=1)"
            },
        ]

    def update_options(self, options: dict):
        try:
            val = float(options.get("factor", self.factor))
        except Exception:
            val = self.factor
        self.factor = max(1.0, min(8.0, val))

    def _find_ffmpeg(self) -> str:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ffmpeg_local_exe = os.path.join(backend_dir, "ffmpeg.exe")
        ffmpeg_system = shutil.which("ffmpeg")
        if ffmpeg_system:
            return ffmpeg_system
        if os.path.exists(ffmpeg_local_exe):
            return ffmpeg_local_exe
        return None

    def _find_ffprobe(self) -> str:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ffprobe_local = os.path.join(backend_dir, "ffprobe.exe")
        ffprobe_system = shutil.which("ffprobe")
        if ffprobe_system:
            return ffprobe_system
        if os.path.exists(ffprobe_local):
            return ffprobe_local
        return None

    def _probe_fps(self, input_path: str) -> float:
        fps = 30.0
        try:
            cap = cv2.VideoCapture(input_path)
            if cap.isOpened():
                read_fps = cap.get(cv2.CAP_PROP_FPS)
                if read_fps and read_fps > 0.1:
                    fps = read_fps
            cap.release()
        except Exception:
            pass
        return fps

    def _has_audio(self, input_path: str) -> bool:
        ffprobe = self._find_ffprobe()
        if not ffprobe:
            return True  # on suppose de l'audio pour ne pas perdre la piste
        try:
            res = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "csv=p=0",
                    input_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(res.stdout.strip())
        except Exception:
            return True

    def _atempo_chain(self, rate: float) -> str:
        # atempo supporte 0.5 à 2. On chaîne si nécessaire.
        if rate <= 0:
            rate = 1.0
        parts = []
        remaining = rate
        while remaining < 0.5:
            parts.append(0.5)
            remaining /= 0.5
        parts.append(remaining)
        return ",".join(f"atempo={p:.3f}" for p in parts)

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        ffmpeg_exe = self._find_ffmpeg()
        if not ffmpeg_exe:
            print("FFmpeg introuvable pour slowmo, bypass.")
            return input_path

        factor = self.factor
        fps_in = self._probe_fps(input_path)
        has_audio = self._has_audio(input_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        vf_filter = (
            f"minterpolate=mi_mode=mci:mc_mode=aobmc:vsbmc=1:fps={fps_in * factor:.3f},"
            f"setpts={factor}*PTS"
        )

        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            input_path,
            "-map",
            "0:v:0?",
        ]

        if has_audio:
            cmd += ["-map", "0:a:0?"]

        cmd += [
            "-vf",
            vf_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
        ]

        if has_audio:
            atempo_chain = self._atempo_chain(1.0 / factor)
            cmd += [
                "-af",
                atempo_chain,
                "-c:a",
                "aac",
                "-b:a",
                "160k",
            ]
        else:
            cmd += ["-an"]

        cmd += [
            "-movflags",
            "+faststart",
            output_path,
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            if os.path.exists(output_path):
                return output_path
        except subprocess.TimeoutExpired:
            print("Slowmo FFmpeg timeout")
        except Exception as e:
            print(f"Slowmo FFmpeg error: {e}")
        return input_path
