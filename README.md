## About

[![Total alerts](https://img.shields.io/lgtm/alerts/g/pdfarranger/pdfarranger.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/pdfarranger/pdfarranger/alerts/)
[![Language grade: Python](https://img.shields.io/lgtm/grade/python/g/pdfarranger/pdfarranger.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/pdfarranger/pdfarranger/context:python)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/1be9c9a69f3a44b79612cc5b2887c0f7)](https://www.codacy.com/gh/pdfarranger/pdfarranger/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=pdfarranger/pdfarranger&amp;utm_campaign=Badge_Grade)
[![pdfarranger](https://github.com/pdfarranger/pdfarranger/workflows/pdfarranger/badge.svg)](https://github.com/pdfarranger/pdfarranger/actions?query=workflow%3Apdfarranger+branch%3Amaster)
[![codecov](https://codecov.io/gh/pdfarranger/pdfarranger/branch/master/graph/badge.svg)](https://codecov.io/gh/pdfarranger/pdfarranger)

*pdfarranger* is a small python-gtk application, which helps the user to merge
or split pdf documents and rotate, crop and rearrange their pages using an
interactive and intuitive graphical interface. It is a frontend for
[pikepdf](https://github.com/pikepdf/pikepdf).

*pdfarranger* is a fork of Konstantinos Poulios’s pdfshuffler
(see [Savannah](https://savannah.nongnu.org/projects/pdfshuffler) or
[Sourceforge](http://sourceforge.net/projects/pdfshuffler)).
It’s a humble attempt to make the project a bit more active.

![screenshot of pdfarranger](https://github.com/pdfarranger/pdfarranger/raw/master/data/screenshot.png)

## Downloads

| [Microsoft® Windows®](https://github.com/pdfarranger/pdfarranger/releases) | <a href='https://flathub.org/apps/details/com.github.jeromerobert.pdfarranger'><img width='120' alt='Download on Flathub' src='https://flathub.org/assets/badges/flathub-badge-en.svg'/></a> | [More…](https://github.com/pdfarranger/pdfarranger/wiki/Binary-packages) |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |

### Linux packages

[![Linux packages](https://repology.org/badge/vertical-allrepos/pdfarranger.svg?columns=4)](https://repology.org/project/pdfarranger/versions)

## Customization of keyboard shortcuts

In case you are not satisfied with the default keyboard shortcuts they can be
changed. To do so, set `enable_custom` to `true` in
`~/.config/pdfarranger/config.ini` or
`C:\Users\username\AppData\Roaming\pdfarranger\config.ini` and edit other
lines.

## Install from source

*pdfarranger* requires [pikepdf](https://github.com/pikepdf/pikepdf) >= 1.7.0. Older versions may work
but are not supported. [pikepdf](https://github.com/pikepdf/pikepdf) >= 1.15.1 is highly recommended.

**On Debian based distributions**

```
sudo apt-get install python3-pip python3-distutils-extra python3-wheel python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-poppler-0.18 python3-setuptools
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
pip3 install --user --upgrade https://github.com/pdfarranger/pdfarranger/zipball/master
```

In addition, *pdfarranger* supports image file import if [img2pdf](https://gitlab.mister-muffin.de/josch/img2pdf) is installed.

## For developers

```
git clone https://github.com/pdfarranger/pdfarranger.git
cd pdfarranger
pip install -e .
./setup.py build
python3 -m pdfarranger
```

For Windows see [Win32.md](Win32.md).

## For translators

-   Download the master branch (see [For developers](#for-developers))

-   Run `po/genpot.sh`. The `pot` is an automatically generated file and as such
    should not be in the repository. It is to make life of some translators
    easier, but it may be often not synchronized with the source code. If you can
    regenerate it before adding or updating a translation, then do it.

-   Translations are in the following files:
    -   [`po`](po)`/*.po`
    -   [data/com.github.jeromerobert.pdfarranger.metainfo.xml](data/com.github.jeromerobert.pdfarranger.metainfo.xml)
    -   [data/com.github.jeromerobert.pdfarranger.desktop](data/com.github.jeromerobert.pdfarranger.desktop)

-   For mnemonics accelerators (letters preceded by an underscore) try to follow
    those rules by priority order:
    -   be consistent with other GTK/GNOME software
    -   pick a unique letter **within that given menu** if possible
    -   pick the same letter as the original string if available
    -   pick a strong letter (e.g. in "Search and replace" rather pick `s`, `r` or `p` than `a`)

-   If possible test your translation to see it in context (see [For developers](#for-developers))

-   You may test different languages with `LANG=xx_YY python3 -m pdfarranger`

-   Do not include `pdfarranger.pot` (or any `*.po` file which was just
    automatically regenerated) in your pull request. Submit only the translations
    you actually updated or added.

-   If you don’t want or can’t use the developers tooling (`git`,
    `po/genpot.sh`, `python`, …) you can edit, download or upload the `*.po`
    files from the GitHub web pages.
