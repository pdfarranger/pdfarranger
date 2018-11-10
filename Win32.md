# PDFShuffler on Windows

Tested on Windows 10.

## Installation

Install MSYS2: http://www.msys2.org/

### upgrade
```
pacman -Syu
```
You might need to run it again (it tells you to)
```
pacman -Su
```

### mingw (with msys2)
```
pacman -S mingw-w64-x86_64-gtk3 mingw-w64-x86_64-python3-gobject mingw-w64-x86_64-gettext mingw-w64-x86_64-python3-cairo mingw-w64-x86_64-poppler mingw-w64-x86_64-python3-pip
```

Then

```
pip3 install --user -r https://raw.githubusercontent.com/jeromerobert/pdfarranger/master/requirements.txt
```

### Run

Launch from a mingw64 shell:
```
~/.local/bin/pdfarranger
```

#### Example Bat file which lauches the app with windows integration (home folder etc.)
```
@echo off
set PYTHONPATH=C:\msys64\home\%USERNAME%\.local\lib\python3.7\site-packages;C:\msys64\mingw64\lib\python3.7
set PATH=%PATH%;C:\msys64\mingw64\bin
start C:\msys64\mingw64\bin\python3w C:\msys64\home\%USERNAME%\.local\bin\pdfarranger
```
Note: This might break if the username contains spaces!

## TODO

* fix translations
	* https://github.com/Cimbali/pympress/pull/21/files
* fix delete of temp files on exit (there is some code in the old win version)
* fix about dialog (argv0 is python3w in some cases)
* easier install

