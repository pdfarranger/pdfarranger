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

from setuptools import Command
from setuptools import setup
from setuptools import __version__ as setuptools_version

# support distros that ship old setuptools
setuptools_version = tuple(int(n) for n in setuptools_version.split('.')[:2])
if setuptools_version < (65, 2):
    from distutils.command.build import build
else:
    from setuptools.command.build import build

from os.path import join
import glob
import os
import subprocess

data_files = [
    ('share/applications', ['data/com.github.jeromerobert.pdfarranger.desktop']),
    ('share/pdfarranger', ['data/pdfarranger.ui', 'data/menu.ui']),
    ('share/man/man1', ['doc/pdfarranger.1']),
    ('share/metainfo', ['data/com.github.jeromerobert.pdfarranger.metainfo.xml']),
]


def _dir_to_data_files(src_dir, target_dir):
    data_files = []
    for root, _, files in os.walk(src_dir):
        tgt = join(target_dir, os.path.relpath(root, src_dir))
        if files:
            data_files.append((tgt, [join(root, f) for f in files]))
    return data_files


def _data_files(command):
    """Return the data_files of a command"""
    data_files = command.distribution.data_files
    if data_files is None:
        data_files = []
        command.distribution.data_files = data_files
    return data_files


class build_i18n(Command):
    description = "Build gettext .mo files"

    def initialize_options(self):
        self.build_base = None

    def finalize_options(self):
        self.set_undefined_options("build", ("build_base", "build_base"))

    def run(self):
        mo_dir = join(self.build_base, "mo")
        for filename in glob.glob(join("po", "*.po")):
            lang = os.path.basename(filename)[:-3]
            lang_dir = join(self.build_base, "mo", lang, "LC_MESSAGES")
            os.makedirs(lang_dir, exist_ok=True)
            subprocess.check_call(
                ["msgfmt", filename, "-o", join(lang_dir, "pdfarranger.mo")]
            )
        data_files = _data_files(self)
        data_files += _dir_to_data_files(mo_dir, join("share", "locale"))


class build_icons(Command):
    description = "Ensure icons get installed"

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        src_icons = join("data", "icons")
        tgt_icons = join("share", "icons")
        data_files = _data_files(self)
        data_files += _dir_to_data_files(src_icons, tgt_icons)


build.sub_commands += [(x, lambda _: True) for x in ["build_i18n", "build_icons"]]

setup(
    name='pdfarranger',
    version='1.10.0',
    author='Jerome Robert',
    author_email='jeromerobert@gmx.com',
    description='A simple application for PDF Merging, Rearranging, and Splitting',
    url='https://github.com/pdfarranger/pdfarranger',
    license='GNU GPL-3',
    packages=['pdfarranger'],
    data_files=data_files,
    zip_safe=False,
    cmdclass={
        "build": build,
        "build_i18n": build_i18n,
        "build_icons": build_icons,
    },
    entry_points={
        'console_scripts': ['pdfarranger=pdfarranger.pdfarranger:main']
    },
    install_requires=['pikepdf>=1.17.0','python-dateutil>=2.4.0', 'packaging'],
    extras_require={
        'image': ['img2pdf>=0.3.4'],
    },
)
