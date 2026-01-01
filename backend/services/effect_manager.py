import cv2
import os
import shutil
import subprocess
import random
import copy
from typing import Dict, List, Any, Optional
from backend.plugins.base import VideoEffect

class EffectManager:
    def __init__(self):
        self.effects = {}
        self.active_effects = []

    def register_effect(self, effect: VideoEffect):
        self.effects[effect.name] = effect
        print(f"Registered effect: {effect.name}")

    # Removed set_active_effects to make it stateless/thread-safe
    
    def get_available_effects(self):
        return [{"name": e.name, "description": e.description, "type": e.type, "options": e.options} for e in self.effects.values()]

    def get_default_options_for_effect(self, effect_name: str) -> Dict[str, Any]:
        """Return a dict of default option values for a given effect."""
        if effect_name not in self.effects:
            return {}
        defaults: Dict[str, Any] = {}
        for opt in self.effects[effect_name].options:
            defaults[opt["name"]] = opt.get("default")
        return defaults

    def get_random_options_for_effect(self, effect_name):
        if effect_name not in self.effects:
            return {}
        
        effect = self.effects[effect_name]
        options_def = effect.options
        random_options = {}
        
        for opt in options_def:
            name = opt["name"]
            opt_type = opt["type"]
            
            if opt_type == "int":
                min_val = opt.get("min", 0)
                max_val = opt.get("max", 100)
                random_options[name] = random.randint(min_val, max_val)
            elif opt_type == "float":
                min_val = opt.get("min", 0.0)
                max_val = opt.get("max", 1.0)
                random_options[name] = random.uniform(min_val, max_val)
            elif opt_type == "bool":
                random_options[name] = random.choice([True, False])
            elif opt_type == "select":
                choices = opt.get("options", [])
                if choices:
                    random_options[name] = random.choice(choices)
            elif opt_type == "text":
                 if "color" in name.lower():
                     random_options[name] = "#{:06x}".format(random.randint(0, 0xFFFFFF))
                 else:
                     random_options[name] = opt.get("default", "")
                     
        return random_options

    def generate_random_chain(self, min_length=1, max_length=5) -> List[Dict[str, Any]]:
        """Generate a random chain of effects."""
        chain = []
        available_names = list(self.effects.keys())
        if not available_names:
            return []
        
        length = random.randint(min_length, max_length)
        for _ in range(length):
            name = random.choice(available_names)
            options = self.get_random_options_for_effect(name)
            chain.append({"name": name, "options": options})
        return chain

    def process_video(
        self,
        input_path: str,
        output_path: str,
        effect_chain: Optional[List[Dict[str, Any]]] = None,
        effect_options: Optional[Dict[str, Dict[str, Any]]] = None,
        active_effects_names: Optional[List[str]] = None,
    ):
        """
        Apply a chain of effects in order. effect_chain is a list of {"name": str, "options": dict}.
        If effect_chain is None, it falls back to active_effects_names + effect_options (legacy).
        File-level effects are applied immediately in order. Frame-level effects are applied in order afterwards.
        """

        if effect_chain is None:
            effect_chain = []
        if effect_options is None:
            effect_options = {}

        if not effect_chain and active_effects_names:
            for name in active_effects_names:
                effect_chain.append({"name": name, "options": effect_options.get(name, {})})

        # Reset and prime options per effect instance
        instantiated_frame_effects: List[VideoEffect] = []
        current_path = input_path

        for idx, entry in enumerate(effect_chain):
            name = entry.get("name")
            opts = entry.get("options", {}) or {}
            effect_template = self.effects.get(name)
            if not effect_template:
                print(f"Effect {name} not registered; skipping")
                continue

            # Create a fresh instance for this step in the chain
            effect = copy.deepcopy(effect_template)

            # Reset before applying per instance
            effect.reset()
            effect.update_options(opts)

            if effect.type == "file":
                print(f"Applying file effect: {effect.name}")
                if not os.path.exists(current_path):
                    raise Exception(f"Input file does not exist for effect {effect.name}: {current_path}")
                temp_out = current_path.replace(".mp4", f"_{effect.name}_{idx}.mp4")
                processed_path = effect.apply_file(current_path, temp_out)
                if processed_path and os.path.exists(processed_path):
                    current_path = processed_path
                else:
                    raise Exception(f"Effect {effect.name} failed: output file does not exist: {processed_path}")
            else:
                # Frame effects are queued and applied in listed order later
                instantiated_frame_effects.append(effect)

        # If no frame effects, finalize copy
        if not instantiated_frame_effects:
            if current_path != output_path:
                if not os.path.exists(current_path):
                    raise Exception(f"Input file does not exist: {current_path}")
                shutil.copy(current_path, output_path)
            if not os.path.exists(output_path):
                raise Exception(f"Output file was not created: {output_path}")
            return output_path

        print(f"Applying frame effects: {[e.name for e in instantiated_frame_effects]}")

        cap = cv2.VideoCapture(current_path)
        if not cap.isOpened():
            print("Error opening video stream or file")
            return current_path

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        temp_output = output_path.replace(".mp4", "_temp.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))

        frame_index = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            for effect in instantiated_frame_effects:
                try:
                    frame = effect.apply_frame(frame, fps=fps, frame_index=frame_index)
                except Exception as e:
                    print(f"Error in effect {effect.name}: {e}")

            out.write(frame)
            frame_index += 1

        cap.release()
        out.release()

        # Find ffmpeg (local Windows exe or system PATH)
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ffmpeg_local_exe = os.path.join(backend_dir, "ffmpeg.exe")
        ffmpeg_exe = None
        
        # Detect OS: on Windows use .exe, on Linux/Mac prefer system ffmpeg
        import sys
        is_windows = os.name == 'nt' or sys.platform.startswith('win')
        
        if is_windows:
            # On Windows, check for local ffmpeg.exe first
            if os.path.exists(ffmpeg_local_exe):
                ffmpeg_exe = ffmpeg_local_exe
            else:
                # Fallback to system ffmpeg on Windows
                ffmpeg_system = shutil.which("ffmpeg")
                if ffmpeg_system:
                    ffmpeg_exe = ffmpeg_system
        else:
            # On Linux/Mac, always prefer system ffmpeg
            ffmpeg_system = shutil.which("ffmpeg")
            if ffmpeg_system:
                ffmpeg_exe = ffmpeg_system
            elif os.path.exists(ffmpeg_local_exe):
                # Fallback to .exe only if system ffmpeg not found (unlikely to work)
                print("WARNING: System ffmpeg not found, trying Windows exe (may not work)")
                ffmpeg_exe = ffmpeg_local_exe

        if ffmpeg_exe:
            print(f"Re-encoding to H.264 using FFmpeg at {ffmpeg_exe}...")
            try:
                # Compression améliorée : CRF 28 pour fichiers plus petits, preset medium pour meilleur équilibre
                subprocess.run([
                    ffmpeg_exe, '-y', '-i', temp_output,
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '28',  # CRF plus élevé = plus de compression
                    '-c:a', 'aac', '-b:a', '96k',  # Bitrate audio réduit
                    '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart',  # Optimisation pour streaming web
                    output_path
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)

                if os.path.exists(temp_output):
                    os.remove(temp_output)

                return output_path
            except subprocess.TimeoutExpired:
                print("FFmpeg encoding timed out")
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_output, output_path)
                return output_path
            except Exception as e:
                print(f"FFmpeg encoding failed: {e}, returning mp4v file")
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_output, output_path)
                return output_path
        else:
            print("FFmpeg not found, returning mp4v file (might not play in all browsers)")
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(temp_output, output_path)
            return output_path
