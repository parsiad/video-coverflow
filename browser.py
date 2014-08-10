import ConfigParser
import fnmatch
import json
import math
import re
import os
import subprocess
import sys
import time
from threading import Thread

from trie import Trie
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
    _iniDefaults = { 'fullscreen': '1', 'extensions': '.3gp,.asf,.avi,.flv,.m4v,.mkv,.mov,.mpeg,.mpg,.mpe,.mp4,.ogg,.ogv,.ogm,.rmi,.wmv', 'paths': '' }

    _delimiters = ['.', '-', '_', ':', ',', ';']
    _pattern = re.compile('(\s*\[[^]]*\])*\s*(.*)')
    _halts = [ \
        re.compile('season[0-9]?(?i)') \
        , re.compile('S[0-9]{1,2}E[0-9]{1,2}(?i)') \
        , re.compile('DVDRip(?i)') \
        , re.compile('XviD(?i)') \
        , re.compile('B[DR]Rip(?i)') \
        , re.compile('DVDSCR(?i)') \
        , re.compile('WEBRip(?i)') \
        , re.compile('HDCAM(?i)') \
        , re.compile('HDRip(?i)') \
        , re.compile('[0-9]{3,4}p') \
        , re.compile('TS') \
        , re.compile('US') \
    ]
    _year = re.compile('\(?([0-9]{4})\)?')

    _sleep = 1

    _defaultCoverPath = os.path.join( os.path.abspath(os.path.dirname(__file__)), 'film.png' )

    class TileflowWidget(QtOpenGL.QGLWidget):

        _scale = 0.7
        _spread_image = 0.14
        _flank_spread = 0.4
        _visible_tiles = 10
        _direction = 1
        _dscale = 0.1

        def __init__(self, parent, browser):
            QtOpenGL.QGLWidget.__init__(self, parent)

            self._indexMapping = []

            self._browser = browser

            self._width = 0
            self._height = 0
            self._clearColor = QtCore.Qt.black
            self._lastPos = QtCore.QPoint()
            self._offset = 3
            self._mouseDown = False

            timer = QtCore.QTimer(self)
            timer.timeout.connect(self.focusTile)
            timer.start(20)

        def minimumSizeHint(self):
            return QtCore.QSize(640, 320)

        def sizeHint(self):
            return QtCore.QSize(640, 320)

        def setClearColor(self, color):
            self._clearColor = color
            self.updateGL()

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
            for mediaList in self._browser:
                for media in mediaList:
                    coverPath = media.getCover()
                    if coverPath is not None:
                        texture = self.bindTexture(QtGui.QPixmap(coverPath))
                        indexedTextures.append( (ind, texture) )
                    ind += 1

            # generate lists
            ind = self._missing_tile = GL.glGenLists( len(indexedTextures) + 1 )
            defaultTexture = self.bindTexture(QtGui.QPixmap( Browser._defaultCoverPath ))
            self.generateTile(ind, defaultTexture)
            ind += 1
            for k, texture in indexedTextures:
                self.generateTile(ind, texture)
                ind += 1

            # map tiles to gl lists
            ind = self._missing_tile + 1
            for mediaList in self._browser:
                for media in mediaList:
                    if media.getCover() is None:
                        self._indexMapping.append((media, self._missing_tile))
                    else:
                        self._indexMapping.append((media, ind))
                        ind += 1

            # spawn thread
            t = Thread(target=self.downloadCoverDaemon)
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
            ratio = float(self._width) / self._height
            GL.glMatrixMode(GL.GL_PROJECTION)
            GL.glLoadIdentity()
            GL.glOrtho(-ratio * Browser.TileflowWidget._scale, ratio * Browser.TileflowWidget._scale, -1 * Browser.TileflowWidget._scale, 1 * Browser.TileflowWidget._scale, 1, 3)

            GL.glMatrixMode(GL.GL_MODELVIEW)
            GL.glLoadIdentity()
            GLU.gluLookAt(0, 0, 2, 0, 0, 0, 0, 1, 0)
            GL.glDisable(GL.GL_DEPTH_TEST)

            self.qglClearColor(self._clearColor)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

            if len(self._browser) > 0:

                GL.glPushMatrix()
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glEnable(GL.GL_BLEND)
                GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

                offset, mid = self.offsetMid()
                start_pos = mid - Browser.TileflowWidget._visible_tiles
                if start_pos < 0:
                    start_pos = 0
                end_pos = mid + Browser.TileflowWidget._visible_tiles
                if end_pos > len(self._browser):
                    end_pos = len(self._browser)
                for i in range(start_pos, mid)[::Browser.TileflowWidget._direction]:
                    self.drawTile(i, i - offset)
                for i in range(mid, end_pos)[::-Browser.TileflowWidget._direction]:
                    self.drawTile(i, i - offset)

                GL.glPopMatrix()

        def focusTile(self):
            if not self._mouseDown:
                target = math.floor(self._offset + 0.5)
                if not abs(target - self._offset) <= 0.01:
                    self._offset += (target - self._offset) / 3
                    self.updateGL()

                if len(self._browser) > 0:
                    offset, mid = self.offsetMid()
                    filename = os.path.basename(self._indexMapping[mid][0].getSinglePath())
                    self._browser.setWindowTitle(self.tr( '%s - %s' % (Browser._title, filename) ))

        def resizeGL(self, width, height):
            self._width = width
            self._height = height
            GL.glViewport(0, 0, width, height)

        def mousePressEvent(self, event):
            self._lastPos = QtCore.QPoint(event.pos())
            self._mouseDown = True

        def mouseMoveEvent(self, event):
            dx = event.x() - self._lastPos.x()
            offset = self._offset - float(dx) * 6 / (self._width * 0.6)
            if offset < 0:
                self._offset = 0
            elif offset > len(self._browser) - 1:
                self._offset = len(self._browser) - 1
            else:
                self._offset = offset
            self.updateGL()

            self._lastPos = QtCore.QPoint(event.pos())

        def mouseReleaseEvent(self, event):
            #QtGui.QSound.play('')
            self._mouseDown = False

        def openCurrent(self):
            offset, mid = self.offsetMid()
            path = self._indexMapping[mid][0].getSinglePath()
            if sys.platform.startswith('darwin'):
                subprocess.call(('open', path))
            elif os.name == 'nt':
                os.startfile(path)
            elif os.name == 'posix':
                subprocess.call(('xdg-open', path))

        def mouseDoubleClickEvent(self, event): self.openCurrent()

        def wheelEvent(self, event):
            if event.delta() < 0:
                Browser.TileflowWidget._scale += Browser.TileflowWidget._dscale
                if Browser.TileflowWidget._scale > 2:
                    Browser.TileflowWidget._scale = 2
                else:
                    Browser.TileflowWidget._visible_tiles += 2
            else:
                Browser.TileflowWidget._scale -= 0.1
                if Browser.TileflowWidget._scale < 0.5:
                    Browser.TileflowWidget._scale = 0.5
                else:
                    Browser.TileflowWidget._visible_tiles -= 2
            self.resizeGL(self._width, self._height)
            self.updateGL()

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Left:
                self._offset = max(0, self._offset - 1)
                self.updateGL()
            elif event.key() == QtCore.Qt.Key_Right:
                self._offset = min(self._offset + 1, len(self._browser) - 1)
                self.updateGL()
            elif event.key() == QtCore.Qt.Key_Return:
                self.openCurrent()

        def drawTile(self, position, offset):
            matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
            trans = offset * Browser.TileflowWidget._spread_image
            f = offset * Browser.TileflowWidget._flank_spread
            if (f > Browser.TileflowWidget._flank_spread):
                f = Browser.TileflowWidget._flank_spread
            elif (f < -Browser.TileflowWidget._flank_spread):
                f = -Browser.TileflowWidget._flank_spread

            media, ind = self._indexMapping[position]
            if media.getCover() is not None and ind == self._missing_tile:
                newInd = GL.glGenLists(1)
                texture = self.bindTexture(QtGui.QPixmap( media.getCover() ))
                self.generateTile(newInd, texture)
                self._indexMapping[position] = (media, newInd)

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

        def downloadCoverDaemon(self):
            k = 0
            for media, ind in self._indexMapping:
                if media.getCover() is None:
                    sys.stderr.write( 'info: attempting to download cover for `%s`...' % (media.getName()) )
                    try:
                        media = self._indexMapping[k][0]

                        metadata = media.getMetadata()
                        cover = metadata.downloadCover()
                        with open(media.getCoverPath(), 'wb') as f:
                            f.write(cover)

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

        def __init__(self, name, path, filePaths, year):
            self._name = name
            self._path = path
            self._filePaths = filePaths
            self._year = year if year is not None else ''

        def getName(self): return self._name

        def getSinglePath(self):
            if len(self._filePaths) > 1:
                return self._path
            else:
                return self._filePaths[0]

        def getCoverPath(self):
            identifier = ''.join([self._name, '__', self._year])
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

        self.populate()

        QtGui.QMainWindow.__init__(self, parent)
        self._tileflow = Browser.TileflowWidget(self, self)
        self._tileflow.setFocus()
        self.setCentralWidget(self._tileflow)
        self.setWindowTitle(self.tr(Browser._title))

        QtGui.QShortcut(QtGui.QKeySequence(self.tr("Ctrl+F", "Fullscreen")), self, self.toggleFullScreen)

        self.updateFullScreen()

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

    def getFullScreen(self): return bool(int(self._config.get(Browser._iniSection, 'fullscreen')))
    def getPaths(self): return self._config.get(Browser._iniSection, 'paths').split(',')
    def getExtensions(self): return self._config.get(Browser._iniSection, 'extensions').split(',')

    def addMedia(self, name, path, filePaths):
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

        name = ' '.join(l).strip()

        # TODO: fix the empty name bug
        if name == '': return

        # add media to trie and dict if necessary
        #if path not in self._mediaDict:
        media = Browser.Media(name, path, filePaths, year)
        #self._mediaDict[path] = media

        # check to see if trie contains name
        in_trie = True
        n = self._mediaTrie.root
        for c in name:
            if c not in n.nodes:
                in_trie = False
                break
            n = n.nodes[c]

        if in_trie:
            self._mediaTrie[name].append(media)
        else:
            self._mediaTrie[name] = [media]

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
                        self.addMedia(name, fullPath, [fullPath])
                else:
                    # directory
                    for root, directories, filenames in os.walk(fullPath):
                        filePaths = []
                        for filename in filenames:
                            name, extension = os.path.splitext(filename)
                            if extension in extensions:
                                filePaths.append(os.path.join(root, filename))
                        if len(filePaths) == 0:
                            continue
                        self.addMedia(subpath, fullPath, filePaths)

