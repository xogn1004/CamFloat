"""Shared names and shortcut hints for toolbar, SCREEN controls and menus."""
CAMERAS = '카메라 관리…'
TOPMOST = '항상 위에'
LAYOUT = '화면 구성'
OPACITY = '전체 투명도'


def menu_text(name, shortcut=None):
    return f'{name}\t{shortcut}' if shortcut else name


def tooltip(name, shortcut=None):
    return f'{name} ({shortcut})' if shortcut else name


def fullscreen_name(fullscreen):
    return '전체화면 해제' if fullscreen else '전체화면'


def topmost_name(enabled):
    return '항상 위에 해제' if enabled else TOPMOST


def master_mute_name(enabled):
    return '전체 음소거 해제' if enabled else '전체 음소거'


def hardware_name(enabled):
    return '하드웨어 가속 해제' if enabled else '하드웨어 가속'
