# About

This repo is an unofficial mirror (possibly not synchronized) of
<https://savannah.nongnu.org/projects/pdfshuffler/> and
<http://sourceforge.net/projects/pdfshuffler/>.

I set it up because I feel frustrated to work with subversion and without PR.
The developer of pdfshuffler do not read this repo so don't expect any PR or
issues posted here to reach him.

I just use this repo to keep my own patches and, as a source for `pip install`.

See <https://github.com/jeromerobert/pdfshuffler/issues/9> for details.

# Install

In order to install run:

On Debian based distributions:

```
sudo apt-get install gettext python3-wheel python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-poppler-0.18
```

On Arch Linux:

```
sudo pacman -S poppler-glib gettext python-pip python-gobject gtk3 python-cairo
```

Then:

```
pip install --user -r https://raw.githubusercontent.com/jeromerobert/pdfshuffler/master/requirements.txt
```
