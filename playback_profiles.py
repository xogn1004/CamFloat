"""Explicit, independent playback paths for diagnosing camera compatibility."""
from pathlib import Path


PROFILES = {'auto': '기본', 'cpu': 'CPU 출력', 'clock': 'RTSP 시각 보정'}


def select_profile(arguments, executable):
    for argument in arguments:
        if argument.startswith('--playback-profile='):
            value = argument.split('=', 1)[1]
            if value not in PROFILES:
                raise ValueError('지원하지 않는 재생 모드입니다.')
            return value
    stem = Path(executable).stem.casefold()
    return {'camfloat-cpu': 'cpu', 'camfloat-clock': 'clock'}.get(stem, 'auto')


def instance_options(profile):
    if profile == 'cpu':
        return ('--vout=wingdi', '--avcodec-hw=none')
    if profile == 'clock':
        return ('--clock-jitter=0', '--clock-synchro=0')
    return ()


def media_options(profile, hardware):
    options = [':avcodec-hw=any' if hardware and profile != 'cpu' else ':avcodec-hw=none']
    if profile == 'cpu':
        options.append(':vout=wingdi')
    elif profile == 'clock':
        options.extend((':clock-jitter=0', ':clock-synchro=0'))
    return options
