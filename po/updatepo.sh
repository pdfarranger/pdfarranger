#!/bin/sh

#
# PdfShuffler 0.6.0 - GTK+ based utility for splitting, rearrangement and
# modification of PDF documents.
# Copyright (C) 2008-2012 Konstantinos Poulios
# <https://sourceforge.net/projects/pdfshuffler>
#
# This file is part of PdfShuffler.
#
# PdfShuffler is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

# Update translation files
find ./po -type f -iname "*.po" -exec msgmerge -U {} po/pdfshuffler.pot \;
