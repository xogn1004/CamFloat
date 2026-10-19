"""Summarize local timing counters; no camera requests or settings changes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from camera_model import data_path


def summarize(document):
    events = document.get('events', [])
    dispatched = {r['seq']: r for r in events if r.get('event') == 'dispatch'}
    ends = {r['input']: r['ms'] for r in events if r.get('event') == 'input_end'}
    sent = [r for r in events if r.get('event') == 'sent']
    writes = [r for r in events if r.get('event') == 'write_started']
    groups = {}
    for row in sent:
        dispatch = dispatched.get(row.get('seq'))
        if dispatch:
            groups.setdefault(dispatch.get('input'), []).append(row['ms'])
    gaps = [b - a for values in groups.values() for a, b in zip(sorted(values), sorted(values)[1:])]
    durations = [r['duration_ms'] for r in events if r.get('event') == 'reply' and type(r.get('duration_ms')) in (int, float)]
    def after_end(row):
        dispatch = dispatched.get(row.get('seq'), {})
        end = ends.get(dispatch.get('input'))
        return end is not None and row['ms'] > end
    def hold_after_end(row):
        return dispatched.get(row.get('seq'), {}).get('repeat', True) and after_end(row)
    def stats(values):
        return (dict(min=round(min(values), 3), median=round(statistics.median(values), 3),
                     max=round(max(values), 3)) if values else None)
    return dict(sent=len(sent), click_ignored=sum(r.get('event') == 'click_ignored' for r in events),
                request_limit=sum(r.get('event') == 'request_limit' for r in events),
                send_interval_ms=stats(gaps), request_duration_ms=stats(durations),
                write_started_after_release=sum(hold_after_end(r) for r in writes),
                transmission_completed_after_release=sum(hold_after_end(r) for r in sent),
                queued_click_writes_after_release=sum(after_end(r) and not hold_after_end(r) for r in writes),
                failure_phases=dict(Counter(r['failure_phase'] for r in events
                    if r.get('event') == 'reply' and type(r.get('failure_phase')) is int)),
                cancelled=sum(bool(r.get('cancelled')) for r in events if r.get('event') == 'reply'),
                deadline_exceeded=sum(bool(r.get('deadline')) for r in events if r.get('event') == 'reply'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='카메라 방향 입력 전송 간격 확인')
    parser.add_argument('--path', type=Path)
    args = parser.parse_args(argv)
    path = args.path or data_path().parent / 'diagnostics/direction-timing.json'
    if not path.is_file():
        parser.error('기록이 없습니다. 새 개발본에서 방향 버튼을 시험한 뒤 다시 실행하세요.')
    if path.stat().st_size > 1024 * 1024:
        parser.error('기록 파일이 너무 큽니다.')
    print(json.dumps(summarize(json.loads(path.read_text(encoding='utf-8'))), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
