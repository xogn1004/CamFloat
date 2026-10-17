"""Render release controls using an isolated, muted local-video profile."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from camera_model import default_config, find_vlc_directory, make_vlc_instance, new_camera
from main import PlayerWindow, VERSION

app = QApplication([])
instance = make_vlc_instance(find_vlc_directory())
config = default_config()
video = QUrl.fromLocalFile(str(ROOT / 'sample-test.mp4')).toString()
config['cameras'] = [new_camera(f'카메라 {i + 1}', video) for i in range(4)]
for camera in config['cameras']:
    camera['muted'] = True
config['layout'] = 4
config['slots'] = [camera['id'] for camera in config['cameras']]
config['geometry'] = [100, 100, 600, 360]
window = PlayerWindow(config, instance, persist=False)
output = ROOT / 'verification/current'
output.mkdir(parents=True, exist_ok=True)
report = {'version': VERSION, 'ok': False}
try:
    window.show()
    app.processEvents()
    window.chrome.reveal()
    window.chrome.panel.layout().activate()
    app.processEvents()
    window.chrome.grab().save(str(output / 'toolbar.png'))
    menu = window.build_app_menu()
    menu.ensurePolished()
    menu.resize(menu.sizeHint())
    menu.grab().save(str(output / 'app-menu.png'))
    menu.deleteLater()
    window.resize(300, 180)
    app.processEvents()
    overlay = window.tiles[0].overlay
    overlay.reveal_controls()
    overlay.volume_popup.show_for_speaker()
    app.processEvents()
    overlay.volume_popup.grab().save(str(output / 'compact-volume.png'))
    report.update(ok=True, toolbar_size=[window.chrome.width(), window.chrome.height()],
                  compact_popup_size=[overlay.volume_popup.width(), overlay.volume_popup.height()],
                  compact_popup_in_screen=overlay.rect().contains(overlay.volume_popup.geometry()))
finally:
    window.close()
    deadline = time.monotonic() + 15
    while not all(tile.worker.done.is_set() for tile in window.tiles) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    window.close()
    instance.release()
    (output / 'visual-qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
