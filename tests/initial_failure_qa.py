"""A failed initial RTSP connection must stay stopped until the user retries."""
import json
import os
import socket
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
publisher = None
report = dict(version=VERSION, ok=False)
try:
    tile = window.tiles[0]
    assert wait_for(lambda: tile.initial_failed, 18), 'Initial failure was not recognized'
    assert wait_for(lambda: not tile.worker.busy, 5), 'Initial attempt did not stop'
    revision = tile.worker.revision
    QTest.qWait(4000)
    assert tile.worker.revision == revision and tile.retry_at is None
    report['initial_failure_no_auto_retry'] = True
    # Use the same loopback server as network QA. A playback-only VLC bundle
    # need not include VLC's RTSP publishing modules.
    executable = Path(os.environ['LOCALAPPDATA']) / 'CamFloatQA/mediamtx-1.21.2/mediamtx.exe'
    if not executable.is_file():
        raise RuntimeError('Install the documented MediaMTX QA fixture first')
    source = Path(os.environ.get('CAMFLOAT_QA_VIDEO') or ROOT / 'verification/rtsp-keyframes-test.mp4')
    fixture_config = ROOT / 'verification/current/mediamtx-initial-qa.yml'
    fixture_config.write_text('logLevel: warn\nrtspAddress: 127.0.0.1:18555\nrtspTransports: [tcp]\n'
        'rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\npaths:\n  stream:\n', encoding='utf-8')
    server = subprocess.Popen([str(executable), str(fixture_config)], creationflags=subprocess.CREATE_NO_WINDOW,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def fixture_ready():
        global publisher
        try:
            with socket.create_connection(('127.0.0.1', 18555), timeout=.3) as connection:
                if publisher is None:
                    publisher = subprocess.Popen(['ffmpeg', '-v', 'error', '-re', '-stream_loop', '-1',
                        '-i', str(source), '-c', 'copy', '-f', 'rtsp', '-rtsp_transport', 'tcp',
                        'rtsp://127.0.0.1:18555/stream'], creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                connection.sendall(b'DESCRIBE rtsp://127.0.0.1:18555/stream RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n\r\n')
                return connection.recv(4096).startswith(b'RTSP/1.0 200')
        except OSError:
            return False
    assert wait_for(fixture_ready, 15), 'Loopback fixture did not start publishing'
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
    for process in (publisher, server):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
    instance.release()
    output = ROOT / 'verification' / 'current'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'initial-failure-qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
