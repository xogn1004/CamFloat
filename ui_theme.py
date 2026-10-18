"""Shared dialog styling; no top-level tool windows are needed for forms."""
STYLE = '''
QDialog {background:#171c25; color:#e7edf6; font-family:"Malgun Gothic"; font-size:12px;}
QLabel,QCheckBox {color:#d8e2f0;}
QLineEdit,QComboBox,QSpinBox {background:#242d3b;color:#f4f7fc;border:1px solid #435066;
    border-radius:5px; padding:7px; min-height:19px;}
QLineEdit:focus,QComboBox:focus {border-color:#75afff;}
QPushButton {background:#303f55;color:#f4f7fc;border:0;border-radius:5px;padding:9px 15px;}
QPushButton:hover {background:#405575;} QPushButton:disabled {color:#647083;background:#232a35;}
QPushButton#primary {background:#386aa9;} QPushButton#primary:hover{background:#457dbf;}
QToolButton{background:transparent;color:#c7d9f1;border:0;border-radius:5px;padding:3px;}
QToolButton:hover{background:#304158;}
QTableView {background:#202734;color:#e9eff8;gridline-color:#303b4b;border:1px solid #39475c;
    selection-background-color:#324e74;selection-color:#ffffff;border-radius:7px;}
QHeaderView::section {background:#293547;color:#c5d5e9;padding:9px;border:0;}
QTabWidget::pane{border:0;}
QTabBar::tab{background:transparent;color:#9eafc6;padding:10px 18px;border-bottom:2px solid transparent;}
QTabBar::tab:selected{color:#d9eaff;border-bottom:2px solid #78b0fa;}
QFrame#detail,QFrame#screenCard{background:#202734;border:1px solid #354155;border-radius:9px;}
QScrollArea{background:transparent;border:0;} QScrollArea>QWidget>QWidget{background:transparent;}
QMenu{background:#1c2533;color:#dae5f5;border:1px solid #405069;padding:6px;}
QMenu::item{padding:7px 18px;} QMenu::item:selected{background:#324e74;}
QMenu::item:disabled{color:#6c7b90;}
QToolTip{background:#1b2432;color:#e4ecf8;border:1px solid #364358;padding:6px;}
'''
