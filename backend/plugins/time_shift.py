import os
import subprocess
import shutil
from backend.plugins.base import VideoEffect


class TimeShift(VideoEffect):
    """Décale la vidéo (+/- secondes) en bouclant pour conserver la durée."""

    def __init__(self):
        self.shift = 1.0

    @property
    def name(self) -> str:
        return "time-shift"

    @property
    def description(self) -> str:
        return "Décalage temporel circulaire (+/- s)"

    @property
    def type(self) -> str:
        return "file"

    @property
    def options(self):
        return [
            {"name": "shift_seconds", "type": "float", "default": 1.0, "min": -30.0, "max": 30.0, "step": 0.1, "label": "Décalage (s)"},
        ]

    def update_options(self, options: dict):
        try:
            self.shift = float(options.get("shift_seconds", self.shift))
        except Exception:
            self.shift = 1.0

    def _find_ffmpeg(self):
        ffmpeg_system = shutil.which("ffmpeg")
        if ffmpeg_system:
            return ffmpeg_system
        # fallback local
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_exe = os.path.join(backend_dir, "ffmpeg.exe")
        if os.path.exists(local_exe):
            return local_exe
        return None

    def _find_ffprobe(self):
        ffprobe_system = shutil.which("ffprobe")
        if ffprobe_system:
            return ffprobe_system
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_exe = os.path.join(backend_dir, "ffprobe.exe")
        if os.path.exists(local_exe):
            return local_exe
        return None

    def _probe_duration(self, path: str) -> float:
        ffprobe = self._find_ffprobe()
        if not ffprobe:
            return 0.0
        try:
            res = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", path],
                capture_output=True, text=True, timeout=10
            )
            dur = float(res.stdout.strip())
            return dur if dur > 0 else 0.0
        except Exception:
            return 0.0

    def _has_audio(self, path: str) -> bool:
        ffprobe = self._find_ffprobe()
        if not ffprobe:
            return True
        try:
            res = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=10
            )
            return bool(res.stdout.strip())
        except Exception:
            return True

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg or not os.path.exists(input_path):
            return input_path

        duration = self._probe_duration(input_path)
        if duration <= 0:
            return input_path

        shift = self.shift
        if shift == 0:
            shutil.copy(input_path, output_path)
            return output_path

        # circular shift
        shift = shift % duration
        if shift < 0:
            shift = duration + shift  # convert negative shift to equivalent positive wrap

        has_audio = self._has_audio(input_path)

        vf = (
            f"[0:v]split[v1][v2];"
            f"[v1]trim=start={shift},setpts=PTS-STARTPTS[vA];"
            f"[v2]trim=end={shift},setpts=PTS-STARTPTS[vB];"
            f"[vA][vB]concat=n=2:v=1:a=0[vout]"
        )

        if has_audio:
            af = (
                f"[0:a]asplit[a1][a2];"
                f"[a1]atrim=start={shift},asetpts=PTS-STARTPTS[aA];"
                f"[a2]atrim=end={shift},asetpts=PTS-STARTPTS[aB];"
                f"[aA][aB]concat=n=2:v=0:a=1[aout]"
            )
            filter_complex = vf + ";" + af
            map_args = ["-map", "[vout]", "-map", "[aout]"]
        else:
            filter_complex = vf
            map_args = ["-map", "[vout]"]

        cmd = [
            ffmpeg, "-y", "-i", input_path,
            "-filter_complex", filter_complex,
            *map_args,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
        ]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        else:
            cmd += ["-an"]
        cmd += [output_path]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
            if os.path.exists(output_path):
                return output_path
        except Exception:
            pass
        return input_path
