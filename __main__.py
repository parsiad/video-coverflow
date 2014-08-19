import sys
from video_coverflow import VideoCoverflow
from PySide import QtGui

if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    vc = VideoCoverflow()
    vc.show()
    sys.exit(app.exec_())

