"""Real RTSP transport, service outage/recovery, UI heartbeat and soak check."""
import json
import os
import socket
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'verification' / 'rtsp-keyframes-test.mp4'
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from camera_model import default_config, find_vlc_directory, make_vlc_instance, new_camera
from main import PlayerWindow, VERSION


class RTSPFixture:
    def __init__(self):
        self.publisher = None
        folder = Path(os.environ['LOCALAPPDATA']) / 'CamFloatQA/mediamtx-1.21.2'
        executable = folder / 'mediamtx.exe'
        if not executable.exists():
            raise RuntimeError('Install the official MediaMTX 1.21.2 Windows amd64 QA fixture first')
        config = ROOT / 'verification' / 'mediamtx-qa.yml'
        config.write_text('logLevel: warn\nrtspAddress: 127.0.0.1:18554\nrtspTransports: [tcp]\n'
            'rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\n'
            'paths:\n  stream:\n', encoding='utf-8')
        self.server = subprocess.Popen([str(executable), str(config)], creationflags=subprocess.CREATE_NO_WINDOW,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def poll(self):
        return self.server.poll()

    def terminate(self):
        if self.publisher and self.publisher.poll() is None:
            self.publisher.terminate()
            self.publisher.wait(5)
        if self.server.poll() is None:
            self.server.terminate()

    def wait(self, seconds):
        return self.server.wait(seconds)


def start_server():
    fixture = RTSPFixture()
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', 18554), timeout=.3) as connection:
                    if fixture.publisher is None:
                        fixture.publisher = subprocess.Popen(['ffmpeg', '-v', 'error', '-re', '-stream_loop', '-1',
                            '-i', str(SOURCE), '-c', 'copy', '-f', 'rtsp', '-rtsp_transport', 'tcp',
                            'rtsp://127.0.0.1:18554/stream'], creationflags=subprocess.CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    connection.sendall(b'DESCRIBE rtsp://127.0.0.1:18554/stream RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n\r\n')
                    if connection.recv(4096).startswith(b'RTSP/1.0 200'):
                        return fixture
            except OSError:
                pass
            time.sleep(.1)
        raise RuntimeError('Local RTSP source did not become ready')
    except Exception:
        fixture.terminate()
        fixture.wait(5)
        raise


def wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(100)
    return False


def working_set():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'paged_peak', 'paged',
                                                'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = wintypes.HANDLE
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not query(current(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return round(counters.working / 1024 ** 2, 2)


app = QApplication([])
instance = make_vlc_instance(find_vlc_directory())
report = {'version': VERSION, 'ok': False}
server = None
window = None
ticks = []
try:
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        subprocess.run(['ffmpeg', '-v', 'error', '-stream_loop', '-1', '-i', str(ROOT / 'sample-test.mp4'),
                        '-t', '240', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                        '-r', '15', '-g', '15', '-keyint_min', '15', '-sc_threshold', '0',
                        '-x264-params', 'repeat-headers=1', '-c:a', 'aac', str(SOURCE)],
                        check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    server = start_server()
    config = default_config()
    config['cameras'] = [new_camera(f'RTSP QA {i + 1}', 'rtsp://127.0.0.1:18554/stream') for i in range(4)]
    for camera in config['cameras']:
        camera['muted'] = True
    config['slots'] = [c['id'] for c in config['cameras']]
    config['layout'] = 4
    window = PlayerWindow(config, instance, persist=False)
    window.show()
    timer = QTimer(window)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(50)
    playing = lambda: all(t.player.is_playing() and t.player.has_vout() > 0 and t.player.get_time() > 0 for t in window.tiles)
    assert wait_for(playing, 20), 'Four RTSP streams did not start'
    # Late RTSP subscribers must wait for the next video keyframe, not just audio.
    recorded = wait_for(lambda: all(t.ever_played for t in window.tiles), 15)
    report['playback_history_debug'] = dict(timer_active=window.status_timer.isActive(),
        states=[str(t.player.get_state()) for t in window.tiles],
        vouts=[t.player.has_vout() for t in window.tiles], busy=[t.worker.busy for t in window.tiles],
        ever=[t.ever_played for t in window.tiles], failed=[t.initial_failed for t in window.tiles])
    assert recorded, 'Successful playback was not recorded'
    report['initial_four_streams'] = True
    revisions = [t.worker.revision for t in window.tiles]
    native_handles = [int(t.winId()) for t in window.tiles]
    for index in (0, 1, 2, 3, 0):
        window.single_view(index)
        QTest.qWait(100)
        assert playing(), 'Enlarging a screen interrupted playback'
        assert [t.worker.revision for t in window.tiles] == revisions, 'Enlargement started a new session'
    window.restore_focus()
    assert revisions == [t.worker.revision for t in window.tiles]
    assert native_handles == [int(t.winId()) for t in window.tiles]
    report['enlargement_no_reconnect'] = True
    handles = [int(t.winId()) for t in window.tiles]
    server.terminate()
    server.wait(5)
    server = None
    assert wait_for(lambda: any(t.retry_count for t in window.tiles), 30), 'Outage did not trigger automatic recovery'
    report['outage_detected'] = True
    window.set_always_on_top(False)
    window.set_always_on_top(True)
    window.set_opacity(30)
    window.set_opacity(100)
    server = start_server()
    assert wait_for(playing, 45), 'RTSP automatic recovery failed'
    report['automatic_recovery_four_streams'] = True
    report['stable_native_handles'] = handles == [int(t.winId()) for t in window.tiles]
    for count in (1, 2, 4):
        window.set_layout(count)
        QTest.qWait(300)
    assert wait_for(playing, 15), 'Layout changes lost playback'
    # At least one minute of continuous real transport after recovery.
    start = time.monotonic()
    cpu_start = time.process_time()
    report['working_set_start_mb'] = working_set()
    first = [t.player.get_time() for t in window.tiles]
    report['timeline'] = []
    next_sample = start
    duration = max(65, int(os.environ.get('CAMFLOAT_QA_SOAK_SECONDS', '65')))
    while time.monotonic() - start < duration:
        QTest.qWait(200)
        if time.monotonic() >= next_sample:
            entry = dict(seconds=round(time.monotonic() - start, 1),
                states=[str(t.player.get_state()) for t in window.tiles],
                times=[t.player.get_time() for t in window.tiles],
                retries=[t.retry_count for t in window.tiles], busy=[t.worker.busy for t in window.tiles],
                working_set_mb=working_set())
            report['timeline'].append(entry)
            print(json.dumps(entry), flush=True)
            next_sample += 2
    report['final_states'] = [str(t.player.get_state()) for t in window.tiles]
    report['final_video_outputs'] = [t.player.has_vout() for t in window.tiles]
    report['server_exit_code'] = server.poll()
    assert playing(), 'Streams stopped during soak'
    report['soak_seconds'] = round(time.monotonic() - start, 2)
    report['working_set_end_mb'] = working_set()
    report['cpu_one_core_percent'] = round((time.process_time() - cpu_start) / (time.monotonic() - start) * 100, 2)
    report['stream_times_ms'] = [t.player.get_time() for t in window.tiles]
    report['ui_heartbeat_max_gap_ms'] = round(max(b - a for a, b in zip(ticks, ticks[1:])) * 1000, 2)
    assert report['ui_heartbeat_max_gap_ms'] < 1200, 'UI blocked for more than 1.2 seconds'
    report['ok'] = True
finally:
    if window:
        window.close()
        wait_for(lambda: all(t.worker.done.is_set() for t in window.tiles), 15)
        window.close()
    if server:
        server.terminate()
        server.wait(5)
    instance.release()
    output = ROOT / 'verification' / VERSION
    output.mkdir(parents=True, exist_ok=True)
    (output / 'network-qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
