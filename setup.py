#!/usr/bin/env python3

#
# pdfarranger - GTK+ based utility for splitting, rearrangement and
# modification of PDF documents.
# Copyright (C) 2008-2017 Konstantinos Poulios
#
# This program is free software; you can redistribute it and/or modify
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

from setuptools import setup


data_files = [
    ('share/applications', ['data/com.github.jeromerobert.pdfarranger.desktop']),
    ('share/pdfarranger', ['data/pdfarranger.ui', 'data/menu.ui']),
    ('share/man/man1', ['doc/pdfarranger.1']),
    ('share/metainfo', ['data/com.github.jeromerobert.pdfarranger.metainfo.xml']),
]

setup(
    data_files=data_files,
)
