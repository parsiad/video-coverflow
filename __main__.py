import sys

from sys import platform as _platform
if _platform == "linux" or _platform == "linux2":
    # linux
    import OpenGL.platform.glx
elif _platform == "darwin":
    # OS X
    import OpenGL.platform.darwin
elif _platform == "win32":
    # Windows
    import OpenGL.platform.win32

import OpenGL.arrays.ctypesarrays
import OpenGL.arrays.numpymodule
import OpenGL.arrays.lists
import OpenGL.arrays.numbers
import OpenGL.arrays.strings

from video_coverflow import VideoCoverflow
from PySide import QtGui

if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    vc = VideoCoverflow()
    vc.show()
    sys.exit(app.exec_())

