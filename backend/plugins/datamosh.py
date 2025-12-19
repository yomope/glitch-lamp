import ffmpeg
import os
from backend.plugins.base import VideoEffect

class DatamoshEffect(VideoEffect):
    def __init__(self):
        self.gop_size = 300
        self.qscale = 3

    @property
    def name(self):
        return "datamosh"

    @property
    def description(self):
        return "Tomato style datamoshing"

    @property
    def type(self):
        return "file"

    @property
    def options(self):
        return [
            {"name": "gop_size", "type": "int", "default": 300, "min": 1, "max": 1000, "label": "GOP Size", "tooltip": "Keyframe interval; larger values give longer smears."},
            {"name": "qscale", "type": "int", "default": 3, "min": 1, "max": 31, "label": "Q-Scale", "tooltip": "Lower is cleaner; raise for more compression artifacts."}
        ]

    def update_options(self, options: dict):
        self.gop_size = options.get("gop_size", self.gop_size)
        self.qscale = options.get("qscale", self.qscale)

    def apply_file(self, input_path: str, output_path: str, **kwargs) -> str:
        temp_avi = output_path + ".avi"
        try:
            # 1. Convert to AVI with specific mpeg4 settings for datamoshing
            (
                ffmpeg
                .input(input_path)
                .output(
                    temp_avi,
                    vcodec='mpeg4',
                    b='2000k',
                    g=self.gop_size,
                    bf=2,
                    flags='+mv4+aic',
                    data_partitioning=1,
                    ps=1000,
                    qscale=self.qscale,
                    f='avi'
                )
                .overwrite_output()
                .run(quiet=True)
            )

            # 2. Read the AVI file binary and modify it
            with open(temp_avi, 'rb') as f:
                content = f.read()

            # Split by the video frame marker '00dc' (Stream 00, Video)
            frames = content.split(b'00dc')
            
            # Start reconstructing the file with the header
            new_content = frames[0]
            
            first_iframe_found = False
            
            for i in range(1, len(frames)):
                frame_data = frames[i]
                
                # Check for MPEG-4 VOP Start Code: 00 00 01 B6
                idx = frame_data.find(b'\x00\x00\x01\xb6', 0, 200)
                
                is_iframe = False
                if idx != -1 and idx + 4 < len(frame_data):
                    # The 2 bits after the start code define the frame type:
                    # 00 = I-VOP (Intra-coded / Keyframe)
                    vop_type = (frame_data[idx+4] & 0xC0) >> 6
                    if vop_type == 0:
                        is_iframe = True

                if is_iframe:
                    if not first_iframe_found:
                        # Always keep the very first I-frame
                        first_iframe_found = True
                        new_content += b'00dc' + frame_data
                    else:
                        # Remove subsequent I-frames to create bloom effect
                        pass 
                else:
                    # Always keep P-frames
                    new_content += b'00dc' + frame_data

            # Write modified content back to temp avi
            with open(temp_avi, 'wb') as f:
                f.write(new_content)

            # 3. Convert back to output format
            (
                ffmpeg
                .input(temp_avi)
                .output(output_path)
                .overwrite_output()
                .run(quiet=True)
            )
            
            return output_path
        except Exception as e:
            print(f"Datamosh error: {e}")
            return input_path
        finally:
            if os.path.exists(temp_avi):
                try:
                    os.remove(temp_avi)
                except:
                    pass
