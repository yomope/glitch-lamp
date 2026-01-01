import cv2
import numpy as np
import random
import os
import subprocess
from backend.plugins.base import VideoEffect
from backend.utils.logger import logger

class PlaybackJitterEffect(VideoEffect):
    def __init__(self):
        self.speed = 1.0
        self.jitter_probability = 0.1
        self.jitter_intensity = 5

    @property
    def name(self):
        return "playback_jitter"

    @property
    def description(self):
        return "Modifies playback speed and adds timeline jumps"

    @property
    def type(self):
        return "file"

    @property
    def options(self):
        return [
            {"name": "speed", "type": "float", "default": 1.0, "min": 0.1, "max": 5.0, "step": 0.1, "label": "Playback Speed", "tooltip": "Overall speed multiplier for the clip."},
            {"name": "jitter_probability", "type": "float", "default": 0.1, "min": 0.0, "max": 1.0, "step": 0.05, "label": "Jitter Probability", "tooltip": "Chance that the timeline will jump on a frame."},
            {"name": "jitter_intensity", "type": "int", "default": 5, "min": 0, "max": 30, "label": "Jitter Intensity (Frames)", "tooltip": "Maximum number of frames to jump forward or backward."}
        ]

    def update_options(self, options: dict):
        self.speed = options.get("speed", self.speed)
        self.jitter_probability = options.get("jitter_probability", self.jitter_probability)
        self.jitter_intensity = options.get("jitter_intensity", self.jitter_intensity)

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            error_msg = f"Failed to open video file: {input_path}"
            logger.error(f"PlaybackJitter: {error_msg}")
            raise Exception(error_msg)

        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames <= 0:
            # Fallback if frame count is unknown
            total_frames = 999999

        # Setup writer - Use mp4v for intermediate
        temp_output = output_path.replace(".mp4", "_jitter_temp.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))
        
        if not out.isOpened():
            cap.release()
            error_msg = f"Failed to open VideoWriter for {temp_output}"
            logger.error(f"PlaybackJitter: {error_msg}")
            raise Exception(error_msg)

        current_pos = 0.0
        last_read_frame_idx = -1
        last_frame = None
        frames_written = 0

        # We will generate roughly the same duration of video as the input * (1/speed)
        
        while current_pos < total_frames:
            # Determine which frame to read
            read_idx = int(current_pos)
            
            # Apply Jitter
            if self.jitter_probability > 0 and random.random() < self.jitter_probability:
                offset = random.randint(-self.jitter_intensity, self.jitter_intensity)
                read_idx += offset
            
            # Clamp
            read_idx = max(0, min(read_idx, total_frames - 1))

            # Read frame
            if read_idx != last_read_frame_idx:
                # Optimization: if we are just 1 frame ahead of last read, we can just read()
                if read_idx == last_read_frame_idx + 1:
                    ret, frame = cap.read()
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, read_idx)
                    ret, frame = cap.read()
                
                if ret:
                    last_frame = frame
                    last_read_frame_idx = read_idx
                else:
                    # If read fails (e.g. end of stream), break or use last frame
                    if last_frame is not None:
                        frame = last_frame
                    else:
                        break
            else:
                # Re-use last frame (e.g. slow motion or jitter to same frame)
                frame = last_frame

            if frame is not None:
                if out.write(frame):
                    frames_written += 1

            # Advance virtual head
            current_pos += self.speed

        cap.release()
        out.release()
        
        # Verify temp file was created and frames were written
        if frames_written == 0:
            error_msg = f"No frames were written to temp file: {temp_output}"
            logger.error(f"PlaybackJitter: {error_msg}")
            raise Exception(error_msg)
        
        if not os.path.exists(temp_output):
            error_msg = f"Temp file {temp_output} was not created after VideoWriter release"
            logger.error(f"PlaybackJitter: {error_msg}")
            raise Exception(error_msg)
        
        # Vérifier que le fichier n'est pas vide
        file_size = os.path.getsize(temp_output)
        if file_size == 0:
            error_msg = f"Temp file {temp_output} is empty after writing {frames_written} frames"
            logger.error(f"PlaybackJitter: {error_msg}")
            raise Exception(error_msg)
        
        # Re-encode to H.264 using FFmpeg
        # This ensures the output is playable in browser if this is the last effect
        try:
            # Find ffmpeg (local Windows exe or system PATH)
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ffmpeg_local_exe = os.path.join(backend_dir, "ffmpeg.exe")
            ffmpeg_exe = None
            
            # Detect OS: on Windows use .exe, on Linux/Mac prefer system ffmpeg
            import sys
            import shutil
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
                        ffmpeg_exe = "ffmpeg"  # Fallback: hope it's in PATH
            else:
                # On Linux/Mac, always prefer system ffmpeg
                ffmpeg_system = shutil.which("ffmpeg")
                if ffmpeg_system:
                    ffmpeg_exe = ffmpeg_system
                elif os.path.exists(ffmpeg_local_exe):
                    # Fallback to .exe only if system ffmpeg not found (unlikely to work)
                    print("WARNING: System ffmpeg not found, trying Windows exe (may not work)")
                    ffmpeg_exe = ffmpeg_local_exe
                else:
                    ffmpeg_exe = "ffmpeg"  # Final fallback: hope it's in PATH
            
            if not ffmpeg_exe:
                error_msg = "FFmpeg not found"
                logger.error(f"PlaybackJitter: {error_msg}")
                raise Exception(error_msg)
            
            # Check if temp file exists and is valid
            if not os.path.exists(temp_output):
                error_msg = f"Temp file {temp_output} does not exist"
                logger.error(f"PlaybackJitter: {error_msg}")
                raise Exception(error_msg)
            
            # Get file size to verify it's not empty
            file_size = os.path.getsize(temp_output)
            if file_size == 0:
                error_msg = f"Temp file {temp_output} is empty"
                logger.error(f"PlaybackJitter: {error_msg}")
                raise Exception(error_msg)
            
            result = subprocess.run([
                ffmpeg_exe, '-y', '-i', temp_output,
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '28',
                '-c:a', 'aac', '-b:a', '96k',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ], check=True, capture_output=True, text=True, timeout=120)
            
            if os.path.exists(temp_output):
                os.remove(temp_output)
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
            logger.error(f"PlaybackJitter: FFmpeg re-encoding failed for {temp_output}: {error_msg}")
            # Nettoyer le fichier temporaire s'il existe
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception as cleanup_error:
                    logger.warning(f"PlaybackJitter: Failed to cleanup temp file {temp_output}: {cleanup_error}")
            raise Exception(f"FFmpeg re-encoding failed: {error_msg}")
        except Exception as e:
            logger.error(f"PlaybackJitter: Re-encoding failed for {temp_output}: {e}")
            # Nettoyer le fichier temporaire s'il existe
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception as cleanup_error:
                    logger.warning(f"PlaybackJitter: Failed to cleanup temp file {temp_output}: {cleanup_error}")
            raise
        
        return output_path
