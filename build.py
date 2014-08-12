import sys
from cx_Freeze import setup, Executable

base = None
if sys.platform == 'darwin':
    # ok
    pass
#elif sys.platform == 'win32':
#    base = 'Win32GUI'
else:
    sys.stderr.write('error: not implemented yet')
    sys.exit(1)

includes = ['OpenGL', 'PySide']

setup(
        name = 'Video Coverflow',
        description = 'Browse your movies and TV-shows in a coverflow',
        options = {'build_exe' : {'includes' : includes }},
        executables = [Executable(''.join(['VideoCoverflow_', sys.platform, '.py']), base = base)])

