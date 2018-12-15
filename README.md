# About

*pdfarranger* is a small python-gtk application, which helps the user to merge
or split pdf documents and rotate, crop and rearrange their pages using an
interactive and intuitive graphical interface. It is a frontend for
python-pyPdf.

*pdfarranger* is a fork of Konstantinos Poulios's pdfshuffler
(see [Savannah](https://savannah.nongnu.org/projects/pdfshuffler) or
[Sourceforge](http://sourceforge.net/projects/pdfshuffler)).
It's an humble tentative to make the project a bit more active.


# Install

On Debian based distributions:

```
sudo apt-get install python3-distutils-extra python3-wheel python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-poppler-0.18 python3-setuptools
```

On Arch Linux:

```
sudo pacman -S poppler-glib python-distutils-extra python-pip python-gobject gtk3 python-cairo
```

On Fedora

```
sudo dnf install poppler-glib python3-distutils-extra python3-pip python3-gobject gtk3 python3-cairo intltool python3-wheel python3-PyPDF2
```

Then:

```
pip3 install --user -r https://raw.githubusercontent.com/jeromerobert/pdfarranger/master/requirements.txt
```

# For developers

From a git clone:

```
./setup.py build
python -m pdfarranger
```
