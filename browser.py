import ConfigParser
import ctypes
import fnmatch
import json
import math
import re
import multiprocessing
import os
import subprocess
import sys
import time
from threading import Thread

from trie import Node, Trie
from urllib2 import urlopen
from xml.etree import ElementTree

from PySide import QtCore, QtGui, QtOpenGL
from OpenGL import GLU, GL

class Browser(QtGui.QMainWindow):

    _title = 'Media Browser'

    _configDirectory = '.video-coverflow'
    _configPath = os.path.join(os.path.expanduser('~'), _configDirectory)

    _iniFilename = 'config.ini'
    _iniPath = os.path.join(_configPath, _iniFilename)
    _iniSection = 'CUSTOM'
    _iniDefaults = { 'width': '640', 'height': '320', 'fullscreen': '1', 'scale': '0.7', 'extensions': '.3gp,.asf,.avi,.flv,.m4v,.mkv,.mov,.mpeg,.mpg,.mpe,.mp4,.ogg,.ogv,.ogm,.rmi,.wmv', 'paths': '' }

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

    _defaultCoverPath = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'film.png' )

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
            self._lists = []
            self._hasCleared = False
            self.clear()

        def clear(self):
            for (ind, size) in self._lists:
                GL.glDeleteLists(ind, size)
            self._lists = []

            self._indexMapping = []

            self._clearColor = QtCore.Qt.black
            self._lastPos = QtCore.QPoint()
            self._offset = 0
            self._mouseDown = False

            timer = QtCore.QTimer(self)
            timer.timeout.connect(self.focusTile)
            timer.start(10)

            if self._hasCleared:
                self.initializeGL()
                self.updateGL()
            self._hasCleared = True

        def minimumSizeHint(self):
            return QtCore.QSize(Browser.TileflowWidget._minWidth, Browser.TileflowWidget._minHeight)

        def sizeHint(self):
            return QtCore.QSize(self._browser.getWidth(), self._browser.getHeight())

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
            # load images outside of glNewList/glEndList block
            indexedTextures = []
            ind = 0
            for media in self._browser:
                coverPath = media.getCover()
                if coverPath is not None:
                    texture = self.bindTexture(QtGui.QPixmap(coverPath))
                    indexedTextures.append( (ind, texture) )
                ind += 1

            # generate lists
            size = len(indexedTextures) + 1
            ind = self._missing_tile = GL.glGenLists(size)
            self._lists.append( (ind, size) )
            defaultTexture = self.bindTexture(QtGui.QPixmap( Browser._defaultCoverPath ))
            self.generateTile(ind, defaultTexture)
            ind += 1
            for k, texture in indexedTextures:
                self.generateTile(ind, texture)
                ind += 1

            # map tiles to gl lists
            ind = self._missing_tile + 1
            for media in self._browser:
                if media.getCover() is None:
                    self._indexMapping.append((media, self._missing_tile))
                else:
                    self._indexMapping.append((media, ind))
                    ind += 1

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
            scale = self._browser.getScale()
            ratio = float(self._browser.getWidth()) / self._browser.getHeight()

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
                start_pos = mid - Browser.TileflowWidget._visibleTiles
                if start_pos < 0:
                    start_pos = 0
                end_pos = mid + Browser.TileflowWidget._visibleTiles
                if end_pos > len(self._browser):
                    end_pos = len(self._browser)
                for i in range(start_pos, mid)[::Browser.TileflowWidget._direction]:
                    self.drawTile(i, i - offset)
                for i in range(mid, end_pos)[::-Browser.TileflowWidget._direction]:
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
                        self._lists.append( (newInd, 1) )
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

            #if len(self._browser) > 0:
            #    offset, mid = self.offsetMid()
            #    media = self._indexMapping[mid][0]
            #    display = os.path.basename( ''.join([media.getName(), ' (', media.getYear(), ')']) )
            #    self._browser.setWindowTitle(self.tr( '%s - %s' % (Browser._title, display) ))

        def resizeGL(self, width, height):
            self._browser.setWidth(width)
            self._browser.setHeight(height)
            GL.glViewport(0, 0, width, height)

        def mousePressEvent(self, event):
            self._lastPos = QtCore.QPoint(event.pos())
            self._mouseDown = True

        def mouseMoveEvent(self, event):
            dx = event.x() - self._lastPos.x()
            offset = self._offset - float(dx) * 6 / (self._browser.getWidth() * 0.6)
            if offset < 0:
                self._offset = 0
            elif offset > len(self._browser) - 1:
                self._offset = len(self._browser) - 1
            else:
                self._offset = offset
            self.updateGL()

            self._lastPos = QtCore.QPoint(event.pos())

        def mouseReleaseEvent(self, event): self._mouseDown = False

        def openCurrent(self):
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

        def mouseDoubleClickEvent(self, event): self.openCurrent()

        def wheelEvent(self, event):
            if event.orientation() == QtCore.Qt.Horizontal:
                self._xvel = float(event.delta()) / 256
                self.updateGL()
            else:
                # TODO: make this fluid
                if event.delta() < 0:
                    scale = self._browser.getScale()
                    scale = min(2, scale + Browser.TileflowWidget._dscale)
                    self._browser.setScale(scale)
                    self.updateGL()
                elif event.delta() > 0:
                    scale = self._browser.getScale()
                    scale = max(0.5, scale - Browser.TileflowWidget._dscale)
                    self._browser.setScale(scale)
                    self.updateGL()

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Left:
                self._offset = int( (self._offset - 1) % len(self._browser) )
                self.updateGL()
            elif event.key() == QtCore.Qt.Key_Right:
                self._offset = int( (self._offset + 1) % len(self._browser) )
                self.updateGL()
            elif event.key() == QtCore.Qt.Key_Return:
                self.openCurrent()

        def drawTile(self, position, offset):
            matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
            trans = offset * Browser.TileflowWidget._spreadImage
            f = offset * Browser.TileflowWidget._flankSpread
            if (f > Browser.TileflowWidget._flankSpread):
                f = Browser.TileflowWidget._flankSpread
            elif (f < -Browser.TileflowWidget._flankSpread):
                f = -Browser.TileflowWidget._flankSpread

            matrix[3] = -1 * Browser.TileflowWidget._direction * f
            matrix[0] = 1 - abs(f)
            scale = 0.45 * matrix[0]
            trans += f * 1
            GL.glPushMatrix()
            GL.glTranslatef(trans, 0, 0)
            GL.glScalef(scale, scale, 1.0)
            GL.glMultMatrixf(matrix)
            GL.glCallList(self._indexMapping[position][1])
            GL.glPopMatrix()

        def downloadCoverDaemon(self, indexMapping):
            k = 0
            for media, ind in indexMapping:
                if media.getCover() is None:
                    sys.stderr.write( 'info: attempting to download cover for `%s`...' % (media.getName()) )
                    try:
                        media = indexMapping[k][0]

                        metadata = media.getMetadata()
                        cover = metadata.downloadCover()
                        with open(media.getCoverPath(), 'wb') as f:
                            f.write(cover)

                        self._queue.put(k)

                        sys.stderr.write(' done\r\n')
                        time.sleep(Browser._sleep)
                    except:
                        sys.stderr.write(' fail\r\n')
                k += 1

    class Metadata:

        _pattern = re.compile('<div\s*class="image">\s*<a[^>]*>\s*<img[^>]*\ssrc="([^"]+)"[^>]*>')

        _imdb = 'http://www.imdb.com/title/%s'
        _omdbapi = 'http://omdbapi.com/?tomatoes=true&s=%s&y=%s'

        def __init__(self, search, year=''):
            url = Browser.Metadata._omdbapi % (search.replace(' ', '%20'), year)
            self._meta = json.load( urlopen( url ) )['Search'][0]

        def downloadCover(self):
            url = Browser.Metadata._imdb % (self._meta['imdbID'])
            return urlopen( Browser.Metadata._pattern.search( urlopen( url ).read() ).group(1) ).read()

    class Media:

        def __init__(self, name, year, filePaths):
            self._name = name
            self._year = year if year is not None else ''
            self._filePaths = filePaths

        def addFilePaths(self, filePaths): self._filePaths.extend(filePaths)

        def getFilePaths(self): return self._filePaths[:]
        def getName(self): return self._name
        def getYear(self): return self._year

        def getCoverPath(self):
            identifier = ''.join([self._name, '_', self._year])
            path = os.path.join( Browser._configPath,  identifier)
            return path

        def getCover(self):
            coverPath = self.getCoverPath()
            if os.path.isfile(coverPath):
                return coverPath
            return None

        def getMetadata(self): return Browser.Metadata(self._name, self._year)

    def __init__(self, parent=None):
        # make config directory
        if not os.path.isdir(Browser._configPath):
            os.mkdir(Browser._configPath)

        # load ini file
        self._config = ConfigParser.SafeConfigParser(Browser._iniDefaults)
        self._config.read(Browser._iniPath)
        if not self._config.has_section(Browser._iniSection):
            self._config.add_section(Browser._iniSection)

        QtGui.QMainWindow.__init__(self, parent)

        self._tileflowCreated = False

        if len(self.getPaths()) == 0:
            msgBox = QtGui.QMessageBox(self)
            msgBox.setText('It looks like you\'re running Video Coverflow for the first time!\n\nPress Ok to browse for one or more directories containing videos.')
            msgBox.setStandardButtons(QtGui.QMessageBox.Ok)
            msgBox.setIcon(QtGui.QMessageBox.Information)
            ret = msgBox.exec_()
            self.openDirectories(True)
        else:
            self.populate()

        self._tileflow = Browser.TileflowWidget(self, self)
        self._tileflow.setFocus()
        self._tileflowCreated = True
        self.setCentralWidget(self._tileflow)

        QtGui.QShortcut(QtGui.QKeySequence(self.tr('Ctrl+F', 'Fullscreen')), self, self.toggleFullScreen)
        QtGui.QShortcut(QtGui.QKeySequence(self.tr('Ctrl+O', 'Open')), self, self.openDirectories)

        self.updateFullScreen()

    def openDirectories(self, killOnNoDirectories=False):

        #dialog = QtGui.QFileDialog()
        #dialog.setOption(QtGui.QFileDialog.ShowDirsOnly, True)
        #if dialog.exec_():
        #    self.setPaths( dialog.selectedFiles() )

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
                self.setPaths( w.selectedFiles() )
            elif killOnNoDirectories:
                sys.exit(1)

            self.populate()

            if len(self) == 0:
                msgBox = QtGui.QMessageBox(self)
                msgBox.setText('No videos were found in the selected location(s). Would you like to select another location(s)?')
                msgBox.setStandardButtons(QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
                msgBox.setIcon(QtGui.QMessageBox.Question)
                ret = msgBox.exec_()
                if ret == QtGui.QMessageBox.No:
                    if killOnNoDirectories:
                        sys.exit(1)
                    break
            else:
                break

        if self._tileflowCreated: self._tileflow.clear()

    def updateFullScreen(self):
        if self.getFullScreen(): self.showFullScreen()
        else: self.showNormal()

    def toggleFullScreen(self):
        self._config.set( Browser._iniSection, 'fullscreen', str(int( not self.getFullScreen() )) )
        self.updateFullScreen()

    def closeEvent(self, event):
        # write ini file
        with open(self._iniPath, 'wb') as f:
            self._config.write(f)

    def __iter__(self): return self._mediaTrie.itervalues()
    def __len__(self): return self._count

    def setScale(self, scale): self._config.set(Browser._iniSection, 'scale', str(scale))

    def getScale(self):
        try: return float(self._config.get(Browser._iniSection, 'scale'))
        except: return float(Browser._iniDefaults['scale'])

    def getWidth(self):
        try: return int(self._config.get(Browser._iniSection, 'width'))
        except: return int(Browser._iniDefaults['width'])
    def getHeight(self):
        try: return int(self._config.get(Browser._iniSection, 'height'))
        except: return int(Browser._iniDefaults['height'])

    def setWidth(self, width): self._config.set(Browser._iniSection, 'width', str(width))
    def setHeight(self, height): self._config.set(Browser._iniSection, 'height', str(height))

    def getFullScreen(self):
        try: return bool(int(self._config.get(Browser._iniSection, 'fullscreen')))
        except: return bool(Browser._iniDefaults['fullscreen'])

    def setPaths(self, paths): self._config.set(Browser._iniSection, 'paths', ','.join(paths))

    def getPaths(self):
        try: return [ path for path in self._config.get(Browser._iniSection, 'paths').split(',') if path.strip() != '' ]
        except: return []

    def getExtensions(self):
        try: return self._config.get(Browser._iniSection, 'extensions').split(',')
        except: return Browser._iniDefaults['extensions'].split(',')

    def addMedia(self, name, filePaths):
        # gets rid of delimiters and tags (as best as possible)
        l = []
        for c in name:
            if c in Browser._delimiters:
                l.append(' ')
            else:
                l.append(c)
        tokens = Browser._pattern.match( ''.join(l) ).group(2).split(' ')
        l = []
        stop = False
        year = None
        for token in tokens:
            m = Browser._year.search(token)
            if m:
                stop = True
                year = m.group(1)
                break
            for halt in Browser._halts:
                if halt.search(token):
                    stop = True
                    break
            if stop: break
            l.append(token)
        newName = ' '.join(l).strip()
        if newName != '': name = newName

        # key is of the form MOVIE[_YEAR]
        key = ''.join([name, '_', year]) if year is not None else name
        try:
            self._mediaTrie[key].addFilePaths(filePaths)
        except:
            self._mediaTrie[key] = Browser.Media(name, year, filePaths)
            self._count += 1

    def populate(self):
        self._count = 0
        self._mediaTrie = Trie()

        extensions = self.getExtensions()

        for path in self.getPaths():
            # check to make sure this is really a directory
            if not os.path.isdir(path):
                sys.stderr.write('warning: media directory `%s` was not found or is not a directory; skipping\r\n' % (path))
                continue

            for subpath in os.listdir(path):
                # full path to directory or file
                fullPath = os.path.join(path, subpath)

                if os.path.isfile(fullPath):
                    # file
                    name, extension = os.path.splitext(subpath)
                    if extension in extensions:
                        self.addMedia(name, [fullPath])
                else:
                    # directory
                    filePaths = []
                    for root, directories, filenames in os.walk(fullPath):
                        for filename in filenames:
                            name, extension = os.path.splitext(filename)
                            if extension in extensions:
                                filePaths.append(os.path.join(root, filename))
                    if len(filePaths) == 0: continue
                    self.addMedia(subpath, filePaths)

