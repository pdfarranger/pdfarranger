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
import sys
import gettext
from gi.repository import Gdk
from gi.repository import Gtk

_ = gettext.gettext

# See https://gitlab.gnome.org/GNOME/gtk/-/blob/3.24.23/gdk/keynames.txt for list of keys
_DEFAULT_ACCELS = [
    ('delete', 'Delete'),
    ('page-size', 's'),
    ('crop', 'c'),
    ('rotate(90)', '<Primary>Right'),
    ('rotate(-90)', '<Primary>Left'),
    ('save', '<Primary>s'),
    ('save-as', '<Primary><Shift>s'),
    ('export-selection(2)', '<Primary>e'),
    ('export-all', '<Primary><Shift>e'),
    ('print', '<Primary>p'),
    ('close', '<Primary>w'),
    ('quit', '<Primary>q'),
    ('new', '<Primary>n'),
    ('open', '<Primary>o'),
    ('import', '<Primary>i'),
    ('zoom-in', 'plus KP_Add <Primary>plus <Primary>KP_Add'),
    ('zoom-out', 'minus KP_Subtract <Primary>minus <Primary>KP_Subtract'),
    ('zoom-fit', 'f'),
    ('fullscreen', 'F11'),
    ('undo', '<Primary>z'),
    ('redo', '<Primary>y'),
    ('cut', '<Primary>x'),
    ('copy', '<Primary>c'),
    ('paste(0)', '<Primary>v'),
    ('paste(1)', '<Primary><Shift>v'),
    ('paste(4)', '<Primary><Shift>o'),
    ('paste(5)', '<Primary><Shift>u'),
    ('select(0)', '<Primary>a'),
    ('select(1)', '<Primary><Shift>a'),
    ('main-menu', 'F10'),
    ('metadata', '<Alt>Return'),
]


class Config(object):
    """Wrap a ConfigParser object for PDFArranger"""

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
        """Return the location of the configuration file"""
        if os.name == 'nt' and getattr(sys, 'frozen', False):
            p = os.path.dirname(sys.executable)
            config_ini = os.path.join(p, 'config.ini')
            if os.path.isfile(config_ini):
                return config_ini
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
        if 'preferences' not in self.data:
            self.data.add_section('preferences')
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

    def set_position(self, position):
        self.data.set('window', 'root_x', str(position[0]))
        self.data.set('window', 'root_y', str(position[1]))

    def position(self):
        return self.data.getint('window', 'root_x', fallback=10), self.data.getint('window', 'root_y', fallback=10)

    def maximized(self):
        return self.data.getboolean('window', 'maximized', fallback=False)

    def set_maximized(self, maximized):
        self.data.set('window', 'maximized', str(maximized))

    def zoom_level(self):
        return self.data.getint('preferences', 'zoom-level', fallback=0)

    def set_zoom_level(self, level):
        self.data.set('preferences', 'zoom-level', str(level))

    def content_loss_warning(self):
        return self.data.getboolean('preferences', 'content-loss-warning', fallback=True)

    def set_content_loss_warning(self, enabled):
        self.data.set('preferences', 'content-loss-warning', str(enabled))

    def show_save_warnings(self):
        return self.data.getboolean('preferences', 'show-save-warnings', fallback=True)

    def set_show_save_warnings(self, enabled):
        self.data.set('preferences', 'show-save-warnings', str(enabled))

    def language(self):
        return self.data.get('preferences', 'language', fallback="")

    def set_language(self, language):
        self.data.set('preferences', 'language', language)

    def theme(self):
        return self.data.get('preferences', 'theme', fallback="")

    def set_theme(self, theme):
        self.data.set('preferences', 'theme', theme)

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

    def preferences_dialog(self, parent, localedir, handy_available):
        """A dialog where language and theme can be selected."""
        d = Gtk.Dialog(title=_("Preferences"),
                       parent=parent,
                       flags=Gtk.DialogFlags.MODAL,
                       buttons=(
                           _("_Cancel"), Gtk.ResponseType.CANCEL,
                           _("_OK"), Gtk.ResponseType.OK,
                        ),
                       )
        d.set_resizable(False)
        hbox = Gtk.Box(spacing=6, margin=8)
        frame = Gtk.Frame(label=_("Language"), margin=8)
        combo = Gtk.ComboBoxText(margin=8)
        label = Gtk.Label(_("(Requires restart)"))
        hbox.pack_start(combo, False, False, 8)
        hbox.pack_start(label, False, False, 8)
        frame.add(hbox)
        d.vbox.pack_start(frame, False, False, 8)
        hbox2 = Gtk.Box(spacing=6, margin=8)
        frame2 = Gtk.Frame(label=_("Theme"), margin=8)
        combo2 = Gtk.ComboBoxText(margin=8)
        label2 = Gtk.Label("" if handy_available else _("(Libhandy missing)"))
        hbox2.pack_start(combo2, False, False, 8)
        hbox2.pack_start(label2, False, False, 8)
        frame2.add(hbox2)
        d.vbox.pack_start(frame2, False, False, 8)
        t = _("For more options see:")
        frame3 = Gtk.Frame(label=t, shadow_type=Gtk.ShadowType.NONE, margin=8)
        label3 = Gtk.Label(self._config_file(self.domain), selectable=True, margin=8)
        frame3.add(label3)
        d.vbox.pack_start(frame3, False, False, 8)

        langs = []
        if os.path.isdir(localedir):
            langs = os.listdir(localedir)
        langs.append("en")
        langs.sort()
        langs.insert(0, _("System setting"))
        for lan in langs:
            combo.append(None, lan)
        lang = self.language()
        if lang in langs:
            combo.set_active(langs.index(lang))
        else:
            combo.set_active(0)
        themes = [_("System setting"), "light", "dark"]
        for the in themes:
            combo2.append(None, the)
        theme = self.theme()
        if theme in themes:
            combo2.set_active(themes.index(theme))
        else:
            combo2.set_active(0)
        combo2.set_sensitive(handy_available)

        d.show_all()
        result = d.run()
        if result == Gtk.ResponseType.OK:
            num = combo.get_active()
            language = langs[num] if num != 0 else ""
            self.set_language(language)
            num2 = combo2.get_active()
            theme = themes[num2] if num2 != 0 else ""
            self.set_theme(theme)
        d.destroy()
