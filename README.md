## About

[![Total alerts](https://img.shields.io/lgtm/alerts/g/jeromerobert/pdfarranger.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/jeromerobert/pdfarranger/alerts/)
[![Language grade: Python](https://img.shields.io/lgtm/grade/python/g/jeromerobert/pdfarranger.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/jeromerobert/pdfarranger/context:python)
[![Codacy Badge](https://api.codacy.com/project/badge/Grade/f30fcd52c2fe4d438542275876221ecd)](https://app.codacy.com/app/jeromerobert/pdfarranger?utm_source=github.com&utm_medium=referral&utm_content=jeromerobert/pdfarranger&utm_campaign=Badge_Grade_Settings)
[![pdfarranger](https://github.com/jeromerobert/pdfarranger/workflows/pdfarranger/badge.svg)](https://github.com/jeromerobert/pdfarranger/actions?query=workflow%3Apdfarranger+branch%3Amaster)

*pdfarranger* is a small python-gtk application, which helps the user to merge
or split pdf documents and rotate, crop and rearrange their pages using an
interactive and intuitive graphical interface. It is a frontend for
[pikepdf](https://github.com/pikepdf/pikepdf).

*pdfarranger* is a fork of Konstantinos Poulios’s pdfshuffler
(see [Savannah](https://savannah.nongnu.org/projects/pdfshuffler) or
[Sourceforge](http://sourceforge.net/projects/pdfshuffler)).
It’s a humble attempt to make the project a bit more active.

![screenshot of pdfarranger](https://github.com/jeromerobert/pdfarranger/raw/master/data/screenshot.png)
## Binary distribution

See this [wiki page](https://github.com/jeromerobert/pdfarranger/wiki/Binary-packages).

## Install from source

*pdfarranger* requires [pikepdf](https://github.com/pikepdf/pikepdf) >= 1.7.0. Older versions may work
but are not supported. [pikepdf](https://github.com/pikepdf/pikepdf) >= 1.15.1 is highly recommended.

**On Debian based distributions**

```
sudo apt-get install python3-distutils-extra python3-wheel python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-poppler-0.18 python3-setuptools
```

**On Arch Linux**

```
sudo pacman -S poppler-glib python-distutils-extra python-pip python-gobject gtk3 python-cairo
```

**On Fedora**

```
sudo dnf install poppler-glib python3-distutils-extra python3-pip python3-gobject gtk3 python3-cairo python3-wheel
```
or `sudo dnf builddep pdfarranger`

**Then**

```
pip3 install --user --upgrade https://github.com/jeromerobert/pdfarranger/zipball/master
```

In addition, *pdfarranger* support image file import if [img2pdf](https://gitlab.mister-muffin.de/josch/img2pdf) is installed.

## For developers

From a git clone:

```
./setup.py build
python3 -m pdfarranger
```

For Windows see [Win32.md](Win32.md).
