# pdfarranger on Windows

Tested on Windows 10.

## Installation

Install [MSYS2](http://www.msys2.org) then upgrade it:

```
pacman -Syu
```

You might need to run it again (it tells you to):

```
pacman -Su
```

Install the required dependencies:

```
pacman -S python3-pip python3-distutils-extra mingw-w64-x86_64-gtk3 \
 mingw-w64-x86_64-python3-gobject mingw-w64-x86_64-gettext \
 mingw-w64-x86_64-python3-cairo mingw-w64-x86_64-poppler
```

Install pdfarranger:

```
pip3 install --user -r https://raw.githubusercontent.com/jeromerobert/pdfarranger/master/requirements.txt
```

## Running pdfarranger

From a MSYS2 shell:

```
/mingw64/bin/python3 ~/.local/bin/pdfarranger
```

## Example Bat file which lauches the app with windows integration (home folder etc.)

```
@echo off
set PYTHONPATH=C:\msys64\home\%USERNAME%\.local\lib\python3.7\site-packages;C:\msys64\mingw64\lib\python3.7
set PATH=%PATH%;C:\msys64\mingw64\bin
start C:\msys64\mingw64\bin\python3w C:\msys64\home\%USERNAME%\.local\bin\pdfarranger
```
Note: This might break if the username contains spaces!

## TODO

* fix about dialog (argv0 is python3w in some cases)
* easier install
