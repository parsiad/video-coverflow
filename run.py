import os
import sys
from browser import Browser
from PySide import QtGui

def run():
    app = QtGui.QApplication(sys.argv)
    browser = Browser()
    browser.show()
    sys.exit(app.exec_())

