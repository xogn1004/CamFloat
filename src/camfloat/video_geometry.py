"""Video presentation geometry; decoded frames and snapshots stay unchanged."""
import math

from PySide6.QtCore import QRect, QSize


def cover_rect(width, height, ratio):
    if width <= 0 or height <= 0 or not ratio or not math.isfinite(ratio) or ratio <= 0:
        return QRect(0, 0, width, height)
    if width / height > ratio:
        video_width, video_height = width, math.ceil(width / ratio)
    else:
        video_width, video_height = math.ceil(height * ratio), height
    if max(video_width, video_height) > 32767:
        return QRect(0, 0, width, height)
    return QRect((width - video_width) // 2, (height - video_height) // 2, video_width, video_height)


def smaller_size(width, height, ratio, minimum):
    if not ratio or not math.isfinite(ratio) or ratio <= 0 or width <= 0 or height <= 0:
        return None
    if width / height > ratio:
        width = max(1, math.floor(height * ratio))
    else:
        height = max(1, math.floor(width / ratio))
    if width < minimum.width() or height < minimum.height():
        return None
    return QSize(width, height)


def display_ratio(player, width, height):
    """Read sample aspect and rotation without leaking libVLC track allocations."""
    if width <= 0 or height <= 0:
        return None
    ratio = width / height
    import ctypes
    import vlc
    media = player.get_media()
    if media is None:
        return ratio
    tracks = ctypes.POINTER(vlc.MediaTrack)()
    count = 0
    try:
        count = vlc.libvlc_media_tracks_get(media, ctypes.byref(tracks))
        if count and tracks:
            entries = ctypes.cast(tracks, ctypes.POINTER(ctypes.POINTER(vlc.MediaTrack)))
            selected = player.video_get_track()
            for index in range(min(count, 256)):
                track = entries[index].contents
                if track.type != vlc.TrackType.video or not track.video or track.id != selected:
                    continue
                video = track.video.contents
                if video.width and video.height:
                    ratio = video.width / video.height
                if video.sar_num and video.sar_den:
                    ratio *= video.sar_num / video.sar_den
                if video.orientation.value in (4, 5, 6, 7):
                    ratio = 1 / ratio
                break
    except (AttributeError, ValueError, TypeError, ZeroDivisionError):
        ratio = width / height
    finally:
        if count and tracks:
            vlc.libvlc_media_tracks_release(
                ctypes.cast(tracks, ctypes.POINTER(ctypes.POINTER(vlc.MediaTrack))), count)
        media.release()
    return ratio if math.isfinite(ratio) and ratio > 0 else width / height
