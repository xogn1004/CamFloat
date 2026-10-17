"""Isolated visual QA window; never reads or writes the user's settings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from camera_model import default_config, new_camera, make_vlc_instance, find_vlc_directory
from main import PlayerWindow, VERSION

app = QApplication([])
instance = make_vlc_instance(find_vlc_directory())
config = default_config()
video = QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'sample-test.mp4')).toString()
config['cameras'] = [new_camera(f'카메라 {i + 1}', video) for i in range(6)]
for camera in config['cameras']:
    camera['muted'] = True
config['slots'] = [c['id'] for c in config['cameras'][:4]]
config['layout'] = 4
config['geometry'] = [100, 100, 900, 540]
window = PlayerWindow(config, instance, persist=False)
window.setWindowTitle(f'CamFloat UI {VERSION}')
window.show()
app.exec()
for tile in window.tiles:
    tile.worker.done.wait(5)
instance.release()
