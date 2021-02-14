# PDF Arranger on Windows

## Prerequisites

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
pacman -S mingw-w64-x86_64-gtk3 mingw-w64-x86_64-python-gobject \
 mingw-w64-x86_64-python-cairo mingw-w64-x86_64-poppler mingw-w64-x86_64-gcc \
 mingw-w64-x86_64-python-lxml mingw-w64-x86_64-qpdf mingw-w64-x86_64-pybind11 \
 mingw-w64-x86_64-gettext mingw-w64-x86_64-gnutls mingw-w64-x86_64-python-pillow \
 mingw-w64-x86_64-python-dateutil mingw-w64-x86_64-python-pip git python-pip intltool
```

and

```
pip install --user https://launchpad.net/python-distutils-extra/trunk/2.39/+download/python-distutils-extra-2.39.tar.gz
/mingw64/bin/python3 -m pip install --user keyboard img2pdf pikepdf https://github.com/jeromerobert/cx_Freeze/zipball/pdfarranger
```

Get the PDF Arranger sources from a MSYS2 shell:

```
git clone https://github.com/pdfarranger/pdfarranger.git
```

## Building distributions

```
cd pdfarranger
./setup.py build
/mingw64/bin/python3 setup_win32.py bdist_msi
/mingw64/bin/python3 setup_win32.py bdist_zip
```

## Wine

MSYS2 no longer work in Wine (see <https://github.com/msys2/MSYS2-packages/issues/682>). To
create a pdfarranger installer in Wine you must first install the required mingw-w64 packages
on a real Windows box. Then copy the MSYS2 `/mingw64` to Linux and run installation process with
`wine /path/to/mingw64/bin/python3` instead of `/mingw64/bin/python3`.

To run the PDF Arranger in Wine you may have to:

```
unset $(env |grep ^XDG_ | cut -d= -f1)
```

## Docker

```
alias pythonwin32="docker run -v local:/root/.wine/drive_c/users/root/.local -v $PWD:/pdfarranger -w /pdfarranger -it jeromerobert/wine-mingw64 wine cmd /c z:/mingw64/bin/python"
cd pdfarranger
./setup.py build
pythonwin32 -m pip install --user pikepdf==1.19.3 img2pdf python-dateutil https://github.com/jeromerobert/cx_Freeze/zipball/pdfarranger
pythonwin32 setup_win32.py bdist_msi
pythonwin32 setup_win32.py bdist_zip
```
