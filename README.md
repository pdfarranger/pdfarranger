PDF-Shuffler, is a simple pyGTK utility to merge,
split and rearrange PDF documents. PDF-Shuffler lets also rotate and crop
individual pages of a pdf document.

PDF-Shuffler is written in Python using PyGTK. It is released under the GNU GPL-3.

Install
-------

In order to install run:

On Debian based distributions:

    sudo apt-get install python-gi python-gi-cairo gir1.2-gtk-3.0 gir1.2-poppler-0.18

On Arch Linux:

    sudo pacman -S poppler-glib gettext python-pip python-gobject gtk3 python-cairo

Then:

    pip install --user -r https://raw.githubusercontent.com/jeromerobert/pdfshuffler/master/requirements.txt

What's new in version 0.7
---------------------------

* Port to Gtk+3 (new dependency on gir1.2-poppler-0.18).
* Port to Python 3 (new alternative dependency on python3-pypdf2).

Known issues
------------

* High memory consumption.
* No autoscrolling during navigation with the keyboard arrows.
