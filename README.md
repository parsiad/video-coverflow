video-coverflow
===============

Downloads covers for movies and TV-shows using filenames and displays them in an OS X-like coverflow.

![video-coverflow screenshot](https://raw.githubusercontent.com/parsiad/video-coverflow/gh-pages/screenshot.png "Screenshot")

Instructions
------------

You will need:

* Python 2.7
* PySide
* PyOpenGL

First, clone the repository by

```git clone git@github.com:parsiad/video-coverflow.git```

Then, simply run

```python video-coverflow/```

Usage
-----

One or more directories can be chosen using the open button in the top-left of the application window.

Dragging the mouse left and right or using the arrow keys moves the coverflow. Double-clicking or pressing the return key launches the video centered in the coverflow.

The text-box in the top-right of the application window can be used to search for titles.

Fine-grain control is available to those willing to edit ~/.video-coverflow/config.ini (this file is generated after running and closing the application once).
