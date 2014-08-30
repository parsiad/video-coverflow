import ctypes
import errno
import fnmatch
import imghdr
import json
import math
import re
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from threading import Thread

from xml.etree import ElementTree

from PySide import QtCore, QtGui, QtOpenGL # TODO: Why not imported?
from OpenGL import GLU, GL

from trie import Node, Trie

if sys.version_info.major >= 3:
    from configparser import SafeConfigParser
    from urllib.request import urlopen
else:
    from ConfigParser import SafeConfigParser
    from urllib2 import urlopen

# modified from http://stackoverflow.com/questions/12462562/how-to-do-inside-in-qlineedit-insert-the-button-pyqt4
class ButtonLineEdit(QtGui.QLineEdit):
    def __init__(self, icon_file, parent=None):
        super(ButtonLineEdit, self).__init__(parent)

        self.button = QtGui.QToolButton(self)
        self.button.setIcon(QtGui.QIcon(icon_file))
        self.button.setStyleSheet('border: 0px; padding: 0px;')
        self.button.setCursor(QtCore.Qt.ArrowCursor)

        frameWidth = self.style().pixelMetric(QtGui.QStyle.PM_DefaultFrameWidth)
        buttonSize = self.button.sizeHint()

        self.setStyleSheet('QLineEdit {padding-right: %dpx; }' % (buttonSize.width() + frameWidth + 1))
        self.setMinimumSize(max(self.minimumSizeHint().width(), buttonSize.width() + frameWidth*2 + 2),
                            max(self.minimumSizeHint().height(), buttonSize.height() + frameWidth*2 + 2))

    def resizeEvent(self, event):
        buttonSize = self.button.sizeHint()
        frameWidth = self.style().pixelMetric(QtGui.QStyle.PM_DefaultFrameWidth)
        self.button.move(self.rect().right() - frameWidth - buttonSize.width(),
                         (self.rect().bottom() - buttonSize.height() + 1)/2)
        super(ButtonLineEdit, self).resizeEvent(event)

# mkdir_p from http://stackoverflow.com/questions/600268/mkdir-p-functionality-in-python
def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

class VideoCoverflow(QtGui.QMainWindow):

    _title = 'Video Coverflow'

    _configDirectory = '.video-coverflow'
    _configPath = os.path.join(os.path.expanduser('~'), _configDirectory)

    _iniFilename = 'config.ini'
    _iniPath = os.path.join(_configPath, _iniFilename)
    _iniSection = 'CUSTOM'
    _iniDefaults = { 'width': '1024', 'height': '576', 'fullscreen': '0', 'scale': '0.5', 'extensions': '.3gp,.asf,.avi,.flv,.m4v,.mkv,.mov,.mpeg,.mpg,.mpe,.mp4,.ogg,.ogv,.ogm,.rmi,.wmv', 'css': 'QToolBar QLabel, QToolBar QLineEdit { font-size: 28px; } QToolBar { padding: 15px; background-color: black; border: 1px solid black; } QToolBar QLabel { color: white; } QToolBar QLineEdit { padding: 5px; background-color: white; color: black; border-radius: 5px; }' }

    _delimiters = ['.', '-', '_', ':', ',', ';']
    _pattern = re.compile('(\s*\[[^]]*\])*\s*(.*)')
    _halts = [ \
          re.compile('^season[0-9]?$(?i)') \
        , re.compile('^S[0-9]{1,2}E[0-9]{1,2}$(?i)') \
        , re.compile('DVD(?i)') \
        , re.compile('DVDR(?i)') \
        , re.compile('DVDRip(?i)') \
        , re.compile('DVDSCR(?i)') \
        , re.compile('XviD(?i)') \
        , re.compile('B[DR]Rip(?i)') \
        , re.compile('^B[DR]$(?i)') \
        , re.compile('WEBRip(?i)') \
        , re.compile('HDCAM(?i)') \
        , re.compile('HDRip(?i)') \
        , re.compile('^DD([0-9]\.[0-9])?$') \
        , re.compile('^[0-9]{3,4}p$') \
        , re.compile('^TS$') \
        , re.compile('^US$') \
        , re.compile('^HC$') \
        , re.compile('^NL$') \
        , re.compile('^Subs$(?i)') \
        , re.compile('^\[[^]].*\]$') \
    ]
    _year = re.compile('\(?([0-9]{4})\)?')

    _sleep = 1

    _defaultCoverPath = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/film.png' )
    _openIcon = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/open.png' )
    _fullScreenIcon = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/fullscreen.png' )
    _clearIcon = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/clear.png' )
    _indexIcon = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/index.png' )
    _imageIcon = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/image.png' )
    _playIcon = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'img/play.png' )

    class TileflowWidget(QtOpenGL.QGLWidget):

        _spreadImage = 0.14
        _flankSpread = 0.4
        _visibleTiles = 10
        _direction = 1
        _dscale = 0.1

        _minWidth = 640
        _minHeight = 320

        def __init__(self, parent, browser):
            QtOpenGL.QGLWidget.__init__(self, parent)

            self._browser = browser

            self._xvel = 0

            self._queue = multiprocessing.Queue()
            self._lists = set()
            self._hasCleared = False
            self.clear()

        def clear(self):
            for ind in self._lists:
                GL.glDeleteLists(ind, 1)
            self._lists.clear()

            self._indexMapping = []

            self._clearColor = QtCore.Qt.black
            self._lastPos = QtCore.QPoint()
            self._offset = 0
            self._mouseDown = False

            timer = QtCore.QTimer(self)
            timer.timeout.connect(self.focusTile)
            timer.start(20)

            if self._hasCleared:
                self.initializeGL()
                self.updateGL()
            self._hasCleared = True

        def minimumSizeHint(self):
            return QtCore.QSize(VideoCoverflow.TileflowWidget._minWidth, VideoCoverflow.TileflowWidget._minHeight)

        def sizeHint(self):
            return QtCore.QSize( int(self._browser.get('width')), int(self._browser.get('height')) )

        def generateTile(self, ind, texture):
            GL.glNewList(ind, GL.GL_COMPILE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)

            GL.glBegin(GL.GL_QUADS)
            GL.glTexCoord2d(1, 0)
            GL.glVertex3d(1, -1, 0)
            GL.glTexCoord2d(0, 0)
            GL.glVertex3d(-1, -1, 0)
            GL.glTexCoord2d(0, 1)
            GL.glVertex3d(-1, 1, 0)
            GL.glTexCoord2d(1, 1)
            GL.glVertex3d(1, 1, 0)
            GL.glEnd()

            GL.glTranslatef(0, -2.0, 0)
            GL.glScalef(1, -1, 1)
            GL.glColor4f(1, 1, 1, 0.5)

            GL.glBegin(GL.GL_QUADS)
            GL.glTexCoord2d(1, 0)
            GL.glVertex3d(1, -1, 0)
            GL.glTexCoord2d(0, 0)
            GL.glVertex3d(-1, -1, 0)
            GL.glTexCoord2d(0, 1)
            GL.glVertex3d(-1, 1, 0)
            GL.glTexCoord2d(1, 1)
            GL.glVertex3d(1, 1, 0)
            GL.glEnd()

            GL.glColor4f(1, 1, 1, 1)

            GL.glEndList()

        def initializeGL(self):
            # generate lists
            self._missing_tile = GL.glGenLists(1)
            self._lists.add(self._missing_tile)
            defaultTexture = self.bindTexture(QtGui.QPixmap( VideoCoverflow._defaultCoverPath ))
            self.generateTile(self._missing_tile, defaultTexture)

            for media in self._browser:
                coverPath = media.getCover()
                if coverPath is not None:
                    texture = self.bindTexture(QtGui.QPixmap(coverPath))
                    ind = GL.glGenLists(1)
                    self.generateTile(ind, texture)
                    self._lists.add(ind)
                    self._indexMapping.append((media, ind))
                else:
                    self._indexMapping.append((media, self._missing_tile))

        def spawnDownloadCoverDaemon(self):
            timer = QtCore.QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.spawn)
            timer.start(250)

        def spawn(self):
            # spawn thread
            l = self._indexMapping[:]
            t = Thread( target=self.downloadCoverDaemon, args=(l,) )
            t.daemon = True
            t.start()

        def offsetMid(self):
            offset = self._offset
            if offset <= 0:
                offset = 0
            if offset > len(self._browser) - 1:
                offset = len(self._browser) - 1
            mid = int(math.floor(offset + 0.5))
            return (offset, mid)

        def paintGL(self):
            scale = float(self._browser.get('scale'))
            ratio = float(self._browser.get('width')) / float(self._browser.get('height'))

            self.qglClearColor(self._clearColor)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

            GL.glDisable(GL.GL_DEPTH_TEST)

            GL.glMatrixMode(GL.GL_PROJECTION)
            GL.glLoadIdentity()
            GL.glOrtho(-ratio * scale, ratio * scale, -1 * scale, 1 * scale, 1, 3)

            GL.glMatrixMode(GL.GL_MODELVIEW)
            GL.glLoadIdentity()
            GLU.gluLookAt(0, 0, 2, 0, 0, 0, 0, 1, 0)

            if len(self._browser) > 0:

                GL.glPushMatrix()
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glEnable(GL.GL_BLEND)
                GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

                offset, mid = self.offsetMid()
                start_pos = mid - VideoCoverflow.TileflowWidget._visibleTiles
                if start_pos < 0:
                    start_pos = 0
                end_pos = mid + VideoCoverflow.TileflowWidget._visibleTiles
                if end_pos > len(self._browser):
                    end_pos = len(self._browser)
                for i in range(start_pos, mid)[::VideoCoverflow.TileflowWidget._direction]:
                    self.drawTile(i, i - offset)
                for i in range(mid, end_pos)[::-VideoCoverflow.TileflowWidget._direction]:
                    self.drawTile(i, i - offset)

                GL.glPopMatrix()

        def moving(self): return self._mouseDown

        def focusTile(self):
            while not self._queue.empty():
                position = self._queue.get()
                try:
                    media, ind = self._indexMapping[position]
                    if media.getCover() is not None and ind == self._missing_tile:
                        newInd = GL.glGenLists(1)
                        self._lists.add(newInd)
                        texture = self.bindTexture(QtGui.QPixmap( media.getCover() ))
                        self.generateTile(newInd, texture)
                        self._indexMapping[position] = (media, newInd)
                        self.updateGL()
                except:
                    pass

            if abs(self._xvel) > 1e-2:
                self._xvel *= 0.75
                self._offset += self._xvel
                self.updateGL()
            elif not self.moving():
                target = math.floor(self._offset + 0.5)
                if not abs(target - self._offset) <= 0.01:
                    self._offset += (target - self._offset) / 3
                    self.updateGL()

            if len(self._browser) > 0:
                offset, mid = self.offsetMid()
                media = self._indexMapping[mid][0]
                name = media.getName()
                year = media.getYear()
                display = ''.join([media.getName(), ' (', media.getYear(), ')']) if year != '' else name
                self._browser.setMessage(display)

        def resizeGL(self, width, height):
            self._browser.set('width', width)
            self._browser.set('height', height)
            GL.glViewport(0, 0, width, height)

        def mousePressEvent(self, event):
            self.setFocus()
            self._lastPos = QtCore.QPoint(event.pos())
            self._mouseDown = True

        def mouseMoveEvent(self, event):
            dx = event.x() - self._lastPos.x()
            offset = self._offset - float(dx) * 6. / (float(self._browser.get('width')) * 0.6)
            if offset < 0:
                self._offset = 0
            elif offset > len(self._browser) - 1:
                self._offset = len(self._browser) - 1
            else:
                self._offset = offset
            self.updateGL()

            self._lastPos = QtCore.QPoint(event.pos())

        def mouseReleaseEvent(self, event): self._mouseDown = False

        def play(self):
            if len(self._browser) == 0: return

            offset, mid = self.offsetMid()
            filePaths = self._indexMapping[mid][0].getFilePaths()
            path = None
            if len(filePaths) == 1:
                path = filePaths[0]
            else:
                path, accept = QtGui.QInputDialog.getItem(self, 'Make selection', 'This title is associated with multiple video files. Please choose one to view:', filePaths, 0, False)
                if not accept: return
            if sys.platform.startswith('darwin'):
                subprocess.call(('open', path))
            elif os.name == 'nt':
                os.startfile(path)
            elif os.name == 'posix':
                subprocess.call(('xdg-open', path))

        def changeCover(self):
            dialog = QtGui.QFileDialog()
            if dialog.exec_():
                coverPath = dialog.selectedFiles()[0]

                offset, mid = self.offsetMid()

                media, oldInd = self._indexMapping[mid]

                # copy image
                shutil.copyfile(coverPath, media.getCoverPath())

                # remove old image
                if oldInd != self._missing_tile:
                    self._lists.remove(oldInd)
                    GL.glDeleteLists(oldInd, 1)

                # load new image
                texture = self.bindTexture(QtGui.QPixmap( media.getCoverPath() ))
                ind = GL.glGenLists(1)
                self.generateTile(ind, texture)
                self._lists.add(ind)
                self._indexMapping[mid] = (media, ind)

                self.updateGL()

        def mouseDoubleClickEvent(self, event): self.play()

        def wheelEvent(self, event):
            if event.orientation() == QtCore.Qt.Horizontal:
                self._xvel = float(event.delta()) / 256
                self.updateGL()
            else:
                # TODO: make this fluid
                if event.delta() < 0:
                    scale = float(self._browser.get('scale'))
                    scale = min(2, scale + VideoCoverflow.TileflowWidget._dscale)
                    self._browser.set('scale', scale)
                    self.updateGL()
                elif event.delta() > 0:
                    scale = float(self._browser.get('scale'))
                    scale = max(0.5, scale - VideoCoverflow.TileflowWidget._dscale)
                    self._browser.set('scale', scale)
                    self.updateGL()

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Left:
                self._offset = int( (self._offset - 1) % len(self._browser) )
                self.updateGL()
            elif event.key() == QtCore.Qt.Key_Right:
                self._offset = int( (self._offset + 1) % len(self._browser) )
                self.updateGL()
            elif event.key() == QtCore.Qt.Key_Return:
                self.play()

        def drawTile(self, position, offset):
            matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
            trans = offset * VideoCoverflow.TileflowWidget._spreadImage
            f = offset * VideoCoverflow.TileflowWidget._flankSpread
            if (f > VideoCoverflow.TileflowWidget._flankSpread):
                f = VideoCoverflow.TileflowWidget._flankSpread
            elif (f < -VideoCoverflow.TileflowWidget._flankSpread):
                f = -VideoCoverflow.TileflowWidget._flankSpread

            matrix[3] = -1 * VideoCoverflow.TileflowWidget._direction * f
            matrix[0] = 1 - abs(f)
            scale = 0.45 * matrix[0]
            trans += f * 1
            GL.glPushMatrix()
            GL.glTranslatef(trans, 0, 0)
            GL.glScalef(scale, scale, 1.0)
            GL.glMultMatrixf(matrix)
            GL.glCallList(self._indexMapping[position][1])
            GL.glPopMatrix()

        def goToCharacter(self, c):
            k = 0
            i = ord(c)
            for media in self._browser:
                if ord(media.getName()[0].upper()) >= i:
                    break
                k += 1
            self._offset = k
            self.updateGL()

        def downloadCoverDaemon(self, indexMapping):
            # TODO: kill this thread explicitly
            k = 0

            for media, ind in indexMapping:
                if media.getCover() is None:
                    sys.stderr.write( 'info: attempting to download cover for `%s`...' % (media.getName()) )
                    try:
                        media = indexMapping[k][0]

                        metadata = media.getMetadata()
                        cover = metadata.downloadCover()
                        mkdir_p(os.path.dirname(media.getCoverPath()))
                        with open(media.getCoverPath(), 'wb') as f:
                            f.write(cover)

                        self._queue.put(k)

                        sys.stderr.write(' done\r\n')
                        time.sleep(VideoCoverflow._sleep)
                    except:
                        sys.stderr.write(' fail\r\n')
                k += 1

    class Metadata:

        _pattern = re.compile('<div\s*class="image">\s*<a[^>]*>\s*<img[^>]*\ssrc="([^"]+)"[^>]*>')

        _imdb = 'http://www.imdb.com/title/%s'
        _omdbapi = 'http://omdbapi.com/?tomatoes=true&s=%s&y=%s'

        def __init__(self, search, year=''):
            url = VideoCoverflow.Metadata._omdbapi % (search.replace(' ', '%20'), year)
            self._meta = json.load( urlopen( url ) )['Search'][0]

        def downloadCover(self):
            url = VideoCoverflow.Metadata._imdb % (self._meta['imdbID'])
            return urlopen( VideoCoverflow.Metadata._pattern.search( urlopen( url ).read() ).group(1) ).read()

    class Media:

        _pattern = re.compile('^\\\\*([^\\\\]*)$')

        def __init__(self, key, name, year, filePaths, collectionPath):
            self._key = key
            self._name = name
            self._year = year if year is not None else ''
            self._filePaths = filePaths

            absPath = os.path.abspath(collectionPath)
            if os.name == 'nt':
                tmp = absPath.split(':')

                m = VideoCoverflow.Media._pattern.match(tmp[1])
                self._collectionPath = os.path.join(tmp[0], m.group(1))
            else:
                self._collectionPath = absPath[1:]

        def addFilePaths(self, filePaths): self._filePaths.extend(filePaths)

        def getKey(self): return self._key
        def getName(self): return self._name
        def getYear(self): return self._year
        def getFilePaths(self): return self._filePaths[:]

        def getCoverPath(self):
            identifier = ''.join([self._name, '_', self._year])
            path = os.path.join(VideoCoverflow._configPath, self._collectionPath, identifier)
            return path

        def getCover(self):
            coverPath = self.getCoverPath()
            if os.path.isfile(coverPath):
                return coverPath
            return None

        def getMetadata(self): return VideoCoverflow.Metadata(self._name, self._year)

    class IndexAction(QtGui.QAction):

        def __init__(self, c, tileflow, parent):
            QtGui.QAction.__init__(self, c, parent)

            self._tileflow = tileflow
            self._c = c

            self.triggered.connect(self.go)

        def go(self):
            self._tileflow.goToCharacter(self._c)

    def __init__(self, parent=None):
        sys.stderr.write('initialing... ')

        # make config directory
        if not os.path.isdir(VideoCoverflow._configPath):
            os.mkdir(VideoCoverflow._configPath)

        # load ini file
        self._config = ConfigParser.SafeConfigParser(VideoCoverflow._iniDefaults)
        try: self._config.read(VideoCoverflow._iniPath)
        except: pass
        if not self._config.has_section(VideoCoverflow._iniSection):
            self._config.add_section(VideoCoverflow._iniSection)

        QtGui.QMainWindow.__init__(self, parent)

        # window title
        self.setWindowTitle('Video Coverflow')

        # style
        self.setStyleSheet(self.get('css'));

        # status bar
        self._progress = QtGui.QProgressBar()
        self.statusBar().addPermanentWidget(self._progress)

        # widget to display title
        self._label = QtGui.QLabel()
        self.statusBar().showMessage('Indexing directories...')
        self._label.setAlignment(QtCore.Qt.AlignCenter)
        statusBar = QtGui.QStatusBar()
        statusBar.addWidget(self._label, 1)
        statusBar.setSizeGripEnabled(False)

        self._searchBox = ButtonLineEdit(VideoCoverflow._clearIcon)
        self._searchBox.button.clicked.connect(self.clearQuery)

        openAction = QtGui.QAction(QtGui.QIcon(VideoCoverflow._openIcon), 'Open...', self)
        openAction.setShortcut('Ctrl+O')
        openAction.triggered.connect(self.openDirectories)

        fullScreenAction = QtGui.QAction(QtGui.QIcon(VideoCoverflow._fullScreenIcon), 'Toggle Fullscreen', self)
        fullScreenAction.setShortcut('Ctrl+F')
        fullScreenAction.triggered.connect(self.toggleFullScreen)

        indexMenu = QtGui.QMenu('Browse Alphabetically', self)
        index = QtGui.QToolButton()
        index.setIcon(QtGui.QIcon(VideoCoverflow._indexIcon))
        index.setMenu(indexMenu)
        index.setPopupMode(QtGui.QToolButton.InstantPopup)

        self._coverAction = QtGui.QAction(QtGui.QIcon(VideoCoverflow._imageIcon), 'Change Cover', self)
        self._coverAction.setEnabled(False)

        self._playAction = QtGui.QAction(QtGui.QIcon(VideoCoverflow._playIcon), 'Play', self)
        self._playAction.setEnabled(False)

        toolBar = self.addToolBar('Toolbar')
        self.setContextMenuPolicy(QtCore.Qt.NoContextMenu) # toolbar unhideable
        toolBar.setMovable(False)
        toolBar.setFloatable(False)
        toolBar.addAction(openAction)
        toolBar.addWidget(index)
        toolBar.addAction(fullScreenAction)
        toolBar.addAction(self._coverAction)
        toolBar.addAction(self._playAction)
        toolBar.addWidget(statusBar)
        toolBar.addWidget(self._searchBox)

        self._previousSearch = None
        self._searchBox.editingFinished.connect(self.search)

        palette = toolBar.palette()
        palette.setColor(QtGui.QPalette.Background, QtCore.Qt.black);
        palette.setColor(QtGui.QPalette.Foreground, QtCore.Qt.white);
        toolBar.setPalette(palette);
        toolBar.setAutoFillBackground(True);

        #self._tileflowCreated = False

        sys.stderr.write('done!\r\n')

        # initialize the library as empty
        self._count = 0
        self._collectionIsTrie = False
        self._collection = []

        # fire an event later to populate the library
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self.populate)
        timer.start(100)

        self._tileflow = VideoCoverflow.TileflowWidget(self, self)
        self._tileflow.setFocus()
        #self._tileflowCreated = True
        self.setCentralWidget(self._tileflow)

        self._playAction.triggered.connect(self._tileflow.play)
        self._coverAction.triggered.connect(self._tileflow.changeCover)

        for c in ['0', 'A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z']:
            indexC = VideoCoverflow.IndexAction(c, self._tileflow, self);
            indexMenu.addAction(indexC);

        # daemon
        self._tileflow.spawnDownloadCoverDaemon()

        QtGui.QShortcut(QtGui.QKeySequence(self.tr('Esc', 'Exit Fullscreen')), self, self.escape)

        self.updateFullScreen()

    def setMessage(self, message): self._label.setText(message)

    def openDirectories(self):

        while True:
            w = QtGui.QFileDialog(self)
            w.setFileMode(QtGui.QFileDialog.DirectoryOnly)
            w.setOption(QtGui.QFileDialog.DontUseNativeDialog, True)
            l = w.findChild(QtGui.QListView, 'listView')
            if l:
                l.setSelectionMode(QtGui.QAbstractItemView.MultiSelection)
            t = w.findChild(QtGui.QTreeView, 'treeView')
            if t:
                t.setSelectionMode(QtGui.QAbstractItemView.MultiSelection)
            if w.exec_():
                self.set( 'paths', ''.join(w.selectedFiles()) )
            else:
                break

            self._previousSearch = None
            self.populate()

            #if self._tileflowCreated:
            self._tileflow.clear()

            if len(self) == 0:
                msgBox = QtGui.QMessageBox(self)
                msgBox.setText('No videos were found in the selected location(s). Would you like to select another?')
                msgBox.setStandardButtons(QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
                msgBox.setIcon(QtGui.QMessageBox.Question)
                ret = msgBox.exec_()
                if ret == QtGui.QMessageBox.No:
                    break
            else:
                # daemon
                self._tileflow.spawnDownloadCoverDaemon()
                break

    def updateFullScreen(self):
        if int(self.get('fullscreen')): self.showFullScreen()
        else: self.showNormal()

    def escape(self):
        self._tileflow.setFocus()
        self.set('fullscreen', 0)
        self.showNormal()

    def toggleFullScreen(self):
        self.set( 'fullscreen', int(not int( self.get('fullscreen') )) )
        self.updateFullScreen()

    def closeEvent(self, event):
        # write ini file
        with open(self._iniPath, 'wb') as f:
            self._config.write(f)

    def __iter__(self):
        if self._collectionIsTrie:
            return self._collection.itervalues()
        else:
            return self._collection.__iter__()

    def __len__(self): return self._count

    def get(self, key):
        try: return self._config.get(VideoCoverflow._iniSection, key)
        except: return VideoCoverflow._iniDefaults[key]

    def set(self, key, value):
        self._config.set(VideoCoverflow._iniSection, key, str(value))

    def getPaths(self):
        try: return [ path for path in self.get('paths').split(',') if path.strip() != '' ]
        except: return []

    def getExtensions(self):
        try: return self.get('extensions').split(',')
        except: return VideoCoverflow._iniDefaults['extensions'].split(',')

    def addMedia(self, name, filePaths, collectionPath):
        # gets rid of delimiters and tags (as best as possible)
        l = []
        for c in name:
            if c in VideoCoverflow._delimiters:
                l.append(' ')
            else:
                l.append(c)
        tokens = VideoCoverflow._pattern.match( ''.join(l) ).group(2).split(' ')
        l = []
        stop = False
        year = None
        for token in tokens:
            m = VideoCoverflow._year.search(token)
            if m:
                stop = True
                year = m.group(1)
                break
            for halt in VideoCoverflow._halts:
                if halt.search(token):
                    stop = True
                    break
            if stop: break
            l.append(token)
        name = ' '.join(l).strip()
        if name == '': return

        # key is of the form MOVIE[_YEAR]
        key = (''.join([name, '_', year]) if year is not None else name).lower()
        node = None
        try:
            node = self._mediaTrie[key]
            node.addFilePaths(filePaths)
        except:
            node = VideoCoverflow.Media(key, name, year, filePaths, collectionPath)
            self._mediaTrie[key] = node
            self._totalCount += 1

    def clearQuery(self):
        self._searchBox.setText('')
        self.search()

    def search(self):
        if self.buildTrie(): self._tileflow.clear()

    def buildTrie(self):
        currentSearch = self._searchBox.text()
        if self._previousSearch == currentSearch: return False
        self._previousSearch = currentSearch

        self._collectionIsTrie = True

        self.setMessage('')

        tokens = [ token for token in currentSearch.split(' ') if token != '' ]
        if len(tokens) == 0:
            self._count = self._totalCount
            self._collection = self._mediaTrie
        else:
            self._collectionIsTrie = False

            tmp = []
            for media in self._mediaTrie.itervalues():
                matches = 0
                for token in tokens:
                    p = re.compile(''.join([token, '(?i)']))
                    if p.search(media.getName()):
                        matches += 1
                if matches > 0:
                    tmp.append( (-matches, media) )
            tmp.sort()
            self._collection = []
            for matches, media in tmp:
                self._collection.append(media)
            self._count = len(self._collection)

        enabled = self._count > 0
        self._playAction.setEnabled(enabled)
        self._coverAction.setEnabled(enabled)

        return True

    def populate(self):
        sys.stderr.write('populating... ')

        self._searchBox.setText('')

        self._totalCount = 0
        self._mediaTrie = Trie()

        extensions = self.getExtensions()

        self.statusBar().show()

        for path in self.getPaths():
            # check to make sure this is really a directory
            if not os.path.isdir(path):
                sys.stderr.write('warning: media directory `%s` was not found or is not a directory; skipping\r\n' % (path))
                continue

            subpaths = os.listdir(path)
            self._progress.setMaximum(len(subpaths))
            self._progress.setValue(0)
            for subpath in subpaths:
                self._progress.setValue(self._progress.value() + 1)

                # full path to directory or file
                fullPath = os.path.join(path, subpath)

                if os.path.isfile(fullPath):
                    # file
                    name, extension = os.path.splitext(subpath)
                    if extension.lower() in extensions:
                        self.addMedia(name, [fullPath], path)
                else:
                    # directory
                    filePaths = []
                    for root, directories, filenames in os.walk(fullPath):
                        for filename in filenames:
                            name, extension = os.path.splitext(filename)
                            if extension.lower() in extensions:
                                filePaths.append(os.path.join(root, filename))
                    if len(filePaths) == 0: continue
                    self.addMedia(subpath, filePaths, path)

        self.buildTrie()
        self._tileflow.clear()

        self.statusBar().hide()

        if len(self) == 0:
            self._searchBox.setPlaceholderText('')
            self._searchBox.setEnabled(False)
            self._searchBox.hide()
        else:
            self._searchBox.setPlaceholderText('Filter by keywords')
            self._searchBox.setEnabled(True)
            self._searchBox.show()

        sys.stderr.write('done!\r\n')

