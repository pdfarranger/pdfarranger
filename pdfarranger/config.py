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

# See https://gitlab.gnome.org/GNOME/gtk/-/blob/3.24.23/gdk/keynames.txt for list of keys
_DEFAULT_ACCELS=[
    ('delete', 'Delete'),
    ('page-format', 'c'),
    ('rotate(90)', '<Ctrl>Right'),
    ('rotate(-90)', '<Ctrl>Left'),
    ('save', '<Ctrl>s'),
    ('save-as', '<Ctrl><Shift>s'),
    ('export-selection(2)', '<Ctrl>e'),
    ('export-all', '<Ctrl><Shift>e'),
    ('quit', '<Ctrl>q'),
    ('import', '<Ctrl>o'),
    ('zoom(5)', 'plus KP_Add <Ctrl>plus <Ctrl>KP_Add'),
    ('zoom(-5)', 'minus KP_Subtract <Ctrl>minus <Ctrl>KP_Subtract'),
    ('undo', '<Ctrl>z'),
    ('redo', '<Ctrl>y'),
    ('cut', '<Ctrl>x'),
    ('copy', '<Ctrl>c'),
    ('paste(0)', '<Ctrl>v'),
    ('paste(1)', '<Ctrl><Shift>v'),
    ('select(0)', '<Ctrl>a'),
    ('select(1)', '<Ctrl><Shift>a'),
    ('main-menu', 'F10'),
]

class Config(object):
    """ Wrap a ConfigParser object for PDFArranger """

    @staticmethod
    def __get_action_list(m, r):
        for i in range(m.get_n_items()):
             it = m.iterate_item_attributes(i)
             target, action = None, None
             while it.next():
                 if it.get_name() == 'target':
                     target = it.get_value()
                 elif it.get_name() == 'action':
                     action = it.get_value()
             if action is not None:
                 action = action.get_string()[4:]
                 if target is not None:
                     action += "({})".format(target)
                 r.append(action)
             it = m.iterate_item_links(i)
             while it.next():
                 Config.__get_action_list(it.get_value(), r)
        return r

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
        if 'accelerators' not in self.data:
            self.data.add_section('accelerators')
        a = self.data['accelerators']
        if 'enable_custom' not in a:
            a['enable_custom'] = 'false'
        enable_custom = a.getboolean('enable_custom')
        for k, v in _DEFAULT_ACCELS:
            if not enable_custom or k not in a:
                a[k] = v

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
        return self.data.getint('window', 'zoom-level', fallback=0)

    def set_zoom_level(self, level):
        self.data.set('window', 'zoom-level', str(level))

    def save(self):
        conffile = Config._config_file(self.domain)
        os.makedirs(os.path.dirname(conffile), exist_ok=True)
        with open(conffile, 'w') as f:
            self.data.write(f)

    def set_actions(self, builder):
        """
        Set the list of actions to which shortcuts may be associated.

        :param builder: A Gtk.Builder from which to get actions
        """
        actions = []
        for m in builder.get_objects():
            self.__get_action_list(m, actions)
        actions = set(actions)
        accels_section = self.data['accelerators']
        for a in actions:
            if a not in accels_section:
                accels_section[a] = ""
        # Have accelerators sorted in the .ini file (cosmetic)
        sortedaccels = [(k, v) for k, v in accels_section.items() if k != 'enable_custom']
        sortedaccels = sorted(sortedaccels)
        enable_custom = accels_section['enable_custom']
        accels_section.clear()
        accels_section['enable_custom'] = enable_custom
        accels_section.update(sortedaccels)

    def get_accels(self):
        """Return the accelerators for each actions."""
        return [
            (k, v.split())
            for k, v in self.data["accelerators"].items()
            if k != "enable_custom"
        ]
