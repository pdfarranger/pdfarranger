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
if os.name == 'nt':
    import darkdetect
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import Gtk
from gi.repository import Handy

_ = gettext.gettext

# See https://gitlab.gnome.org/GNOME/gtk/-/blob/3.24.23/gdk/keynames.txt for list of keys
_DEFAULT_ACCELS = [
    ('delete', 'Delete'),
    ('page-format', 'c'),
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

    @staticmethod
    def _compare_function(a, b, user_data):
        """Comparison function for sorting ListStore"""
        element_a = a.get_value()
        element_b = b.get_value()

        if element_a < element_b:
            return -1
        elif element_a > element_b:
            return 1
        else:
            return 0

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

    def on_language_selected(self, widget, event, langs_store):
        selected_index = widget.get_selected_index()
        if selected_index > 0:
            selected_lang = langs_store[selected_index].get_string()
        else:
            selected_lang = ""
        self.set_language(selected_lang)

    def theme(self):
        return self.data.getint('preferences', 'theme', fallback=0)

    def set_theme(self, row, param):
        self.data.set('preferences', 'theme', str(row.get_selected_index()))

    def set_color_scheme(self):
        try:
            scheme = Handy.ColorScheme.PREFER_LIGHT
            if os.name == 'nt' and darkdetect.isDark():
                scheme = Handy.ColorScheme.PREFER_DARK
            theme = self.theme()
            if theme == 1:
                scheme = Handy.ColorScheme.FORCE_LIGHT
            elif theme == 2:
                scheme = Handy.ColorScheme.FORCE_DARK
            Handy.StyleManager.get_default().set_color_scheme(scheme)
        except AttributeError:
            # This libhandy is too old. 1.5.90 needed ?
            pass

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

    def preferences_window(self, parent, resource_path, localedir):
        """A window where language and theme can be selected."""
        langs_store = Gio.ListStore.new(Handy.ValueObject)

        if os.path.isdir(localedir):
            for lang in os.listdir(localedir):
                langs_store.insert_sorted(Handy.ValueObject.new(lang), self._compare_function, None)
        langs_store.insert_sorted(Handy.ValueObject.new("en"), self._compare_function, None)
        langs_store.insert(0, Handy.ValueObject.new(_("System setting")))

        theme_store = Gio.ListStore.new(Handy.ValueObject)

        theme_store.insert(0, Handy.ValueObject.new(_("System setting")))
        theme_store.insert(1, Handy.ValueObject.new(_("Light")))
        theme_store.insert(2, Handy.ValueObject.new(_("Dark")))

        builder = Gtk.Builder()
        builder.set_translation_domain(self.domain)
        builder.add_from_file(resource_path("preferences.ui"))

        prefs = builder.get_object("prefs_window")
        prefs.set_transient_for(parent)

        langs_combo_row = builder.get_object("langs_combo_row")
        langs_combo_row.bind_name_model(langs_store, Handy.ValueObject.dup_string)
        for i, lang in enumerate(langs_store):
            if lang.get_string() == self.language():
                langs_combo_row.set_selected_index(i)
                break
        langs_combo_row.connect('notify::selected-index', self.on_language_selected, langs_store)

        theme_combo_row = builder.get_object("theme_combo_row")
        theme_combo_row.bind_name_model(theme_store, Handy.ValueObject.dup_string)
        theme_combo_row.set_selected_index(self.theme())
        theme_combo_row.connect('notify::selected-index', self.set_theme)
        theme_combo_row.connect('notify::selected-index', lambda *args: self.set_color_scheme())

        prefs.show_all()
