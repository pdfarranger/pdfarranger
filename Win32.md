# PDF Arranger on Windows

## Prerequisites

Install [MSYS2](http://www.msys2.org). Once installed start `MSYS2 MSYS` shell.
Update all packages: 

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
 mingw-w64-x86_64-python-cairo mingw-w64-x86_64-poppler \
 mingw-w64-x86_64-python-lxml mingw-w64-x86_64-qpdf mingw-w64-x86_64-pybind11 \
 mingw-w64-x86_64-gettext mingw-w64-x86_64-gnutls mingw-w64-x86_64-python-pillow \
 mingw-w64-x86_64-python-dateutil mingw-w64-x86_64-python-pip mingw-w64-x86_64-libhandy \
 mingw-w64-x86_64-python-cx-freeze git python-pip \
 mingw-w64-x86_64-python-pikepdf mingw-w64-x86_64-img2pdf
```

```
/mingw64/bin/python3.exe -m pip install --user keyboard darkdetect
```

## Building PDF Arranger

Get the PDF Arranger sources:

```
git clone https://github.com/pdfarranger/pdfarranger.git
```

Then

```
cd pdfarranger
/mingw64/bin/python3.exe ./setup.py build
/mingw64/bin/python3.exe setup_win32.py bdist_msi
/mingw64/bin/python3.exe setup_win32.py bdist_zip
```

## Debug / hacking

After running `setup.py build` it's possible to run PDF Arranger without creating the installer:

```
cd pdfarranger
/mingw64/bin/python3.exe ./setup.py build
/mingw64/bin/python3.exe -m pdfarranger
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

## Docker / Podman

```bash
#! /bin/sh -ex

mydocker() {
  # You may switch to docker and adapt image name & tag if needed
  podman run -v local:/root/.wine/drive_c/users/root/.local \
    -v $PWD:/pdfarranger -w /pdfarranger -it docker.io/jeromerobert/wine-mingw64:1.8.1 "$@"
}

pythonwin32() {
  mydocker wine cmd /c z:/mingw64/bin/python "$@"
}

mydocker ./setup.py build
pythonwin32 setup_win32.py bdist_msi
pythonwin32 setup_win32.py bdist_zip
```
