#!/usr/bin/python

#
# PDF-Shuffler 0.5.1 - pyGTK PDF Merging, Rearranging, and Splitting
# Copyright (C) 2008-2010 Konstantinos Poulios
# <https://sourceforge.net/projects/pdfshuffler>
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

import os
import re
from distutils.core import setup

data_files=[('share/applications/', ['data/pdfshuffler.desktop']),
            ('share/man/man1', ['doc/pdfshuffler.1']),
            ('share/pixmaps/', ['data/pdfshuffler.svg']),
            ('share/pixmaps/', ['data/pdfshuffler.png']) ]


# Freshly generate .mo from .po, add to data_files:
if os.path.isdir('mo/'):
    os.system ('rm -r mo/')
for name in os.listdir('po'):
    m = re.match(r'(.+)\.po$', name)
    if m != None:
        lang = m.group(1)
        out_dir = 'mo/%s/LC_MESSAGES' % lang
        out_name = os.path.join(out_dir, 'pdfshuffler.mo')
        install_dir = 'share/locale/%s/LC_MESSAGES/' % lang
        os.makedirs(out_dir)
        os.system('msgfmt -o %s po/%s' % (out_name, name))
        data_files.append((install_dir, [out_name]))

setup(name='pdfshuffler',
      version='0.5',
      author='Konstantinos Poulios',
      author_email='poulios.konstantinos at gmail dot com',
      description='A simple application for PDF Merging, Rearranging, and Splitting',
      url = 'https://sourceforge.net/projects/pdfshuffler',
      license='GNU GPL-2',
      scripts=['pdfshuffler'],
      data_files=data_files
     )

# Clean up temporary files
if os.path.isdir('mo/'):
    os.system ('rm -r mo/')
if os.path.isdir('build/'):
    os.system ('rm -r build/')

