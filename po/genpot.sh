#!/bin/sh

#
# pdfarranger - GTK+ based utility for splitting, rearrangement and
# modification of PDF documents.
# Copyright (C) 2008-2017 Konstantinos Poulios
#
# pdfarranger is free software; you can redistribute it and/or modify
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

# Make translation files
intltool-extract --type=gettext/glade data/pdfarranger.ui
intltool-extract --type=gettext/glade data/menu.ui
intltool-extract --type=gettext/glade data/querysavedialog.ui
xgettext --language=Python --keyword=_ --keyword=N_ --output=po/pdfarranger.pot \
  pdfarranger/*.py data/pdfarranger.ui.h data/menu.ui.h data/querysavedialog.ui.h
