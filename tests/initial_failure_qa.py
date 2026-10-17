"""A failed initial RTSP connection must stay stopped until the user retries."""
import json
import subprocess
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from camera_model import default_config, find_vlc_directory, make_vlc_instance, new_camera
from main import PlayerWindow, VERSION


def wait_for(predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(100)
    return False


app = QApplication([])
instance = make_vlc_instance(find_vlc_directory())
config = default_config()
config['cameras'] = [new_camera('initial-failure', 'rtsp://127.0.0.1:18555/stream')]
config['cameras'][0]['muted'] = True
config['slots'][0] = config['cameras'][0]['id']
window = PlayerWindow(config, instance, persist=False)
window.show()
server = None
report = dict(version=VERSION, ok=False)
try:
    tile = window.tiles[0]
    assert wait_for(lambda: tile.initial_failed, 18), 'Initial failure was not recognized'
    assert wait_for(lambda: not tile.worker.busy, 5), 'Initial attempt did not stop'
    revision = tile.worker.revision
    QTest.qWait(4000)
    assert tile.worker.revision == revision and tile.retry_at is None
    report['initial_failure_no_auto_retry'] = True
    server = subprocess.Popen([sys.executable, str(ROOT / 'tests/rtsp_server.py'),
        str(ROOT / 'sample-test.mp4'), '18555'], creationflags=subprocess.CREATE_NO_WINDOW)
    QTest.qWait(3000)
    assert tile.worker.revision == revision and not tile.player.is_playing()
    report['server_recovery_does_not_auto_start'] = True
    window.reconnect(0)
    assert wait_for(lambda: tile.ever_played, 18), 'Manual retry did not open the video'
    report.update(manual_retry_plays=True, ok=True)
finally:
    window.close()
    wait_for(lambda: all(t.worker.done.is_set() for t in window.tiles), 15)
    window.close()
    if server:
        server.terminate()
        server.wait(5)
    instance.release()
    output = ROOT / 'verification' / 'current'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'initial-failure-qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
