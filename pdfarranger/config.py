# Copyright (C) 2020 pdfarranger contributors
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

import platform
import configparser
import os
from gi.repository import Gdk

class Config(object):
    """ Wrap a ConfigParser object for PDFArranger """

    @staticmethod
    def _config_file(domain):
        """ Return the location of the configuration file """
        home = os.path.expanduser("~")
        if platform.system() == 'Darwin':
            p = os.path.join(home, 'Library', 'Preferences')
        elif 'APPDATA' in os.environ:
            p = os.getenv('APPDATA')
        elif 'XDG_CONFIG_HOME' in os.environ:
            p = os.getenv('XDG_CONFIG_HOME')
        else:
            p = os.path.join(home, '.config')
        p = os.path.join(p, domain)
        os.makedirs(p, exist_ok=True)
        return os.path.join(p, 'config.ini')

    def __init__(self, domain):
        self.domain = domain
        self.data = configparser.ConfigParser()
        self.data.add_section('window')
        self.data.read(Config._config_file(domain))

    def window_size(self):
        ds = Gdk.Screen.get_default()
        return self.data.getint('window', 'width', fallback=int(min(700, ds.get_width() / 2))), \
            self.data.getint('window', 'height', fallback=int(min(600, ds.get_height() - 50)))

    def set_window_size(self, size):
        self.data.set('window', 'width', str(size[0]))
        self.data.set('window', 'height', str(size[1]))

    def maximized(self):
        return self.data.getboolean('window', 'maximized', fallback=False)

    def set_maximized(self, maximized):
        self.data.set('window', 'maximized', str(maximized))

    def zoom_level(self):
        return self.data.getint('DEFAULT', 'zoom-level', fallback=0)

    def set_zoom_level(self, level):
        self.data.set('DEFAULT', 'zoom-level', str(level))

    def save(self):
        conffile = Config._config_file(self.domain)
        os.makedirs(os.path.dirname(conffile), exist_ok=True)
        with open(conffile, 'w') as f:
            self.data.write(f)
