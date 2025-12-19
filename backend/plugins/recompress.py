import ffmpeg
from backend.plugins.base import VideoEffect

class RecompressEffect(VideoEffect):
    def __init__(self):
        self.bitrate = '100k'
        self.gop_size = 1000

    @property
    def name(self):
        return "recompress"

    @property
    def description(self):
        return "Simulated compression artifacts (Recompress)"

    @property
    def type(self):
        return "file"

    @property
    def options(self):
        return [
            {"name": "bitrate", "type": "string", "default": "100k", "label": "Bitrate (e.g. 100k)", "tooltip": "Target video bitrate; lower values create harsher artifacts."},
            {"name": "gop_size", "type": "int", "default": 1000, "min": 10, "max": 5000, "label": "GOP Size", "tooltip": "Distance between keyframes; higher smears motion more."}
        ]

    def update_options(self, options: dict):
        self.bitrate = options.get("bitrate", self.bitrate)
        self.gop_size = options.get("gop_size", self.gop_size)

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        # Simulate datamosh by converting to very low bitrate and wrong GOP
        try:
            (
                ffmpeg
                .input(input_path)
                .output(output_path, video_bitrate=self.bitrate, g=self.gop_size, keyint_min=self.gop_size) # Low bitrate, few keyframes
                .overwrite_output()
                .run(quiet=True)
            )
            return output_path
        except Exception as e:
            print(f"Recompress error: {e}")
            return input_path
