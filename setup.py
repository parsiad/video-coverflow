from cx_Freeze import setup,Executable

includefiles = []
includes = []
excludes = []
packages = []

setup(
    name = 'video-coverflow',
    version = '0.1',
    description = 'Downloads covers for movies and TV-shows using filenames and displays them in an OS X-like coverflow',
    author = 'parsiad',
    author_email = 'parsiad.azimzadeh@gmail.com',
    options = {'build_exe': {'excludes':excludes,'packages':packages,'include_files':includefiles}},
    executables = [Executable('__main__.py')]
)
