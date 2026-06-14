import sys
import threading
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

#这里是避免出现pip install genie-tts后,genie-tts的src目录被添加到sys.path中，导致import genie_tts.Core.Resources报错
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from genie_tts.GUI.GUI import MainWindow
from genie_tts.Server import start_server

# 启动服务器线程,并设置为守护线程
# 这样当主程序退出时,服务器线程也会被强制停止
server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# 启动主窗口
app = QApplication(sys.argv)
font = QFont("Microsoft YaHei", 10)
app.setFont(font)
window = MainWindow()
window.show()
sys.exit(app.exec())
