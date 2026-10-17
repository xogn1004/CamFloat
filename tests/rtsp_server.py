"""Synthetic loopback RTSP source, using the already-installed VLC runtime."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_model import find_vlc_directory, make_vlc_instance

# VLC's RTSP output expires idle control sessions after 60 seconds by default.
# Disable that fixture-only timeout so a 65-second soak measures the player.
instance = make_vlc_instance(find_vlc_directory(), '--rtsp-timeout=0')
source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'sample-test.mp4'
media = instance.media_new(str(source))
port = int(sys.argv[2]) if len(sys.argv) > 2 else 18554
media.add_option(f':sout=#rtp{{sdp=rtsp://127.0.0.1:{port}/stream}}')
media.add_option(':sout-keep')
media.add_option(':input-repeat=65535')
player = instance.media_player_new()
player.set_media(media)
player.play()
try:
    while True:
        time.sleep(1)
finally:
    player.stop()
    player.release()
    media.release()
    instance.release()
