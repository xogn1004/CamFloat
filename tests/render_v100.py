"""Render dialogs with synthetic data, without accessing saved settings/cameras."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QToolButton
from camera_model import new_camera
from camera_manager import CameraManager
from camera_editor import CameraEditor

app = QApplication([])
output = ROOT / 'verification' / 'current' / 'v100'
output.mkdir(parents=True, exist_ok=True)
camera = new_camera('거실 카메라', 'rtsp://viewer:synthetic@127.0.0.1:8554/onvif1')
camera['number'] = 1
manager = CameraManager([camera])
manager.show()
QTest.qWait(50)
manager.grab().save(str(output / 'manager.png'))
manager.resize(manager.minimumSize())
app.processEvents()
manager.grab().save(str(output / 'manager-minimum.png'))
manager.resize(760, 500)
manager.tabs.setCurrentIndex(1)
app.processEvents()
manager.grab().save(str(output / 'assignments.png'))
info = next(b for b in manager.findChildren(QToolButton) if b.accessibleName() == '화면별 카메라 도움말')
info.click()
app.processEvents()
manager.tips.bubble.grab().save(str(output / 'info.png'))
manager.tips.clear()
manager.tabs.setCurrentIndex(0)
def capture_delete():
    box = app.activeModalWidget()
    box.grab().save(str(output / 'delete-confirmation.png'))
    box.reject()
QTimer.singleShot(30, capture_delete)
manager.delete_all()
editor = CameraEditor(parent=manager)
editor.show()
QTest.qWait(30)
editor.grab().save(str(output / 'editor.png'))
editor.done(QDialog.DialogCode.Rejected)
manager.done(QDialog.DialogCode.Rejected)
print('Rendered v100 dialogs with synthetic data only.')
