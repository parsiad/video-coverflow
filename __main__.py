import sys
from browser import Browser
from PySide import QtGui

if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    browser = Browser()
    browser.show()
    sys.exit(app.exec_())

