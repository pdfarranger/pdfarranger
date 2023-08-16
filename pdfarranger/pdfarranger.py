# Copyright (C) 2008-2017 Konstantinos Poulios, 2018-2019 Jerome Robert
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

import os
import ctypes

if os.name == 'nt':
    try:
        ctypes.windll.kernel32.SetDefaultDllDirectories(0x1000)
    except AttributeError:
        # Windows too old KB2533623
        pass

import shutil  # for file operations like whole directory deletion
import sys  # for processing of command line args
import tempfile
import signal
import mimetypes
import multiprocessing
import traceback
import locale  # for multilanguage support
import gettext
import gc
import subprocess
import pikepdf
import hashlib
from urllib.request import url2pathname
from functools import lru_cache
from math import log

multiprocessing.freeze_support()  # Does nothing in Linux

sharedir = os.path.join(sys.prefix, 'share')
basedir = '.'
if getattr(sys, 'frozen', False):
    basedir = os.path.dirname(sys.executable)
    sharedir = os.path.join(basedir, 'share')
elif sys.argv[0]:
    execdir = os.path.dirname(os.path.realpath(sys.argv[0]))
    basedir = os.path.dirname(execdir)
    sharedir = os.path.join(basedir, 'share')
    if not os.path.exists(sharedir):
        sharedir = basedir
localedir = os.path.join(sharedir, 'locale')
if not os.path.exists(localedir):
    # Assume we are in development mode
    localedir = os.path.join(basedir, 'build', 'mo')

try:
    locale.setlocale(locale.LC_ALL, '')
except locale.Error:
    pass  # Gtk already prints a warning

DOMAIN = 'pdfarranger'
ICON_ID = 'com.github.jeromerobert.' + DOMAIN
if hasattr(locale, 'bindtextdomain'):
    # glibc
    locale.bindtextdomain(DOMAIN, localedir)
    # https://docs.gtk.org/glib/i18n.html
    locale.bind_textdomain_codeset(DOMAIN, 'UTF-8')
else:
    # Windows or musl
    libintl = ctypes.cdll['libintl-8' if os.name == 'nt' else 'libintl.so.8']
    libintl.bindtextdomain(DOMAIN.encode(), localedir.encode(sys.getfilesystemencoding()))
    libintl.bind_textdomain_codeset(DOMAIN.encode(), 'UTF-8'.encode())
    del libintl

APPNAME = 'PDF Arranger'
VERSION = '1.10.0'
WEBSITE = 'https://github.com/pdfarranger/pdfarranger'

if os.name == 'nt':
    import darkdetect
    import keyboard  # to get control key state when drag to other instance
    # Add support for dnd to other instance and insert file at drop location in Windows
    os.environ['GDK_WIN32_USE_EXPERIMENTAL_OLE2_DND'] = 'true'
    # Use client side decorations. Will also enable window moving with Win + left/right
    os.environ['GTK_CSD'] = '1'

import gi

# check that we don't need GObject.threads_init()
gi.check_version('3.10.2')
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
try:
    gi.require_version('Handy', '1')
    from gi.repository import Handy
except ValueError:
    Handy = None

if Gtk.check_version(3, 20, 0):
    raise Exception('You do not have the required version of GTK+ installed. ' +
                    'Installed GTK+ version is ' +
                    '.'.join([str(Gtk.get_major_version()),
                              str(Gtk.get_minor_version()),
                              str(Gtk.get_micro_version())]) +
                    '. Required GTK+ version is 3.20 or higher.')

from gi.repository import Gdk
from gi.repository import GObject  # for using custom signals
from gi.repository import Gio  # for inquiring mime types information
from gi.repository import GLib
from gi.repository import Pango

from .config import Config
from .core import Sides


def _set_language_locale():
    lang = Config(DOMAIN).language()
    if os.name == 'nt':
        if not lang:
            winlang = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            lang = locale.windows_locale[winlang]
        os.environ['LANG'] = lang
    elif lang:
        if locale.getlocale(locale.LC_MESSAGES)[0] is None and lang != 'en':
            print('LC_MESSAGES = "C" or not valid. Translations may not work properly.')
        os.environ['LANGUAGE'] = lang


_set_language_locale()

gettext.bindtextdomain(DOMAIN, localedir)
gettext.textdomain(DOMAIN)
_ = gettext.gettext

from . import undo
from . import exporter
from . import metadata
from . import pageutils
from . import splitter
from .iconview import CellRendererImage, IconviewCursor, IconviewDragSelect, IconviewPanView
from .core import img2pdf_supported_img, PageAdder, PDFDocError, PDFRenderer
GObject.type_register(CellRendererImage)

layer_support = exporter.layer_support()

def _install_workaround_bug29():
    """ Install a workaround for https://gitlab.gnome.org/GNOME/pygobject/issues/29 """
    try:
        gi.check_version('3.29.2')
    except ValueError:
        def func(self, entries):
            # simplified version of https://gitlab.gnome.org/GNOME/pygobject/commit/d0b219c
            for d in entries:
                param_type = None if len(d) < 3 else GLib.VariantType.new(d[2])
                action = Gio.SimpleAction(name=d[0], parameter_type=param_type)
                action.connect("activate", d[1], None)
                self.add_action(action)

        Gtk.ApplicationWindow.add_action_entries = func


_install_workaround_bug29()


def malloc_trim():
    """Release free memory from the heap."""
    if os.name == 'nt':
        return
    mtrim = malloc_trim_available()
    if mtrim:
        mtrim()


@lru_cache()
def malloc_trim_available():
    try:
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    except (FileNotFoundError, AttributeError, OSError):
        print('malloc_trim not available. Application may not release memory properly.')
        return None
    def mtrim():
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    return mtrim


def get_file_path_from_uri(uri):
    """Extracts the path from an uri"""
    uri = uri[5:]  # remove 'file:'
    path = url2pathname(uri)  # escape special chars
    path = path.strip('\r\n\x00\x2F')  # remove \r\n and NULL and \
    if os.name == 'posix':
        path = '/' + path
    return path


class PdfArranger(Gtk.Application):
    # Drag and drop ID for pages coming from the same pdfarranger instance
    MODEL_ROW_INTERN = 1001
    # Drag and drop ID for pages coming from an other pdfarranger instance
    MODEL_ROW_EXTERN = 1002
    # Drag and drop ID for pages coming from a non-pdfarranger application
    TEXT_URI_LIST = 1003
    TARGETS_IV = [Gtk.TargetEntry.new('MODEL_ROW_INTERN', Gtk.TargetFlags.SAME_WIDGET,
                                      MODEL_ROW_INTERN),
                  Gtk.TargetEntry.new('MODEL_ROW_EXTERN', Gtk.TargetFlags.OTHER_APP,
                                      MODEL_ROW_EXTERN)]
    TARGETS_SW = [Gtk.TargetEntry.new('text/uri-list', 0, TEXT_URI_LIST),
                  Gtk.TargetEntry.new('MODEL_ROW_EXTERN', Gtk.TargetFlags.OTHER_APP,
                                      MODEL_ROW_EXTERN)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id="com.github.jeromerobert.pdfarranger",
                         flags=Gio.ApplicationFlags.NON_UNIQUE |
                            Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
                         **kwargs)

        # Create the temporary directory
        self.tmp_dir = tempfile.mkdtemp(DOMAIN)
        os.chmod(self.tmp_dir, 0o700)

        # Defining instance attributes

        # The None values will be set later in do_activate
        self.config = Config(DOMAIN)
        self.uiXML = None
        self.window = None
        self.sw = None
        self.model = None
        self.undomanager = None
        self.iconview = None
        self.cellthmb = None
        self.status_bar = None
        self.popup = None
        self.is_unsaved = False
        self.zoom_level = None
        self.zoom_level_old = 0
        self.zoom_level_limits = [-10, 80]
        self.zoom_scale = None
        self.zoom_fit_page = False
        self.render_id = None
        self.id_scroll_to_sel = None
        self.target_is_intern = True

        self.export_directory = os.path.expanduser('~')
        self.import_directory = None
        self.nfile = 0
        self.iv_auto_scroll_timer = None
        self.pdfqueue = []
        self.metadata = {}
        self.pressed_button = None
        self.click_path = None
        self.scroll_path = None
        self.rendering_thread = None
        self.export_process = None
        self.post_action = None
        self.save_file = None
        self.export_file = None
        self.drag_path = None
        self.drag_pos = Gtk.IconViewDropPosition.DROP_RIGHT
        self.window_width_old = 0
        self.set_iv_visible_id = None
        self.vadj_percent = None
        self.end_rubberbanding = False
        self.disable_quit = False
        multiprocessing.set_start_method('spawn')
        self.quit_flag = multiprocessing.Event()
        self.layer_pos = 0.5, 0.5

        # Clipboard for cut copy paste
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        self.add_arguments()

    def add_arguments(self):
        self.set_option_context_summary(_(
           "PDF Arranger is a small python-gtk application, which helps the "
           "user to merge or split pdf documents and rotate, crop and rearrange "
           "their pages using an interactive and intuitive graphical interface. "
           "It is a frontend for pikepdf."
        ))

        self.add_main_option(
            "version",
            ord("v"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            _("Print the version of PDF Arranger and exit"),
            None,
        )
        self.add_main_option(
            GLib.OPTION_REMAINING,
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING_ARRAY,
            _("File(s) to open"),
            "[FILES]",
        )

    @staticmethod
    def __resource_path(path):
        """ Return the path of a resource file """
        # TODO: May be we could use Application.set_resource_base_path and
        # get_menu_by_id in place of that
        # Trying different possible locations
        f = os.path.join(basedir, 'share', DOMAIN, path)
        if not os.path.exists(f):
            f = os.path.join(basedir, 'data', path)
        if not os.path.exists(f):
            f = '/usr/share/{}/{}'.format(DOMAIN, path)
        if not os.path.exists(f):
            f = '/usr/local/share/{}/{}'.format(DOMAIN, path)
        return f

    def set_color_scheme(self):
        if Handy:
            try:
                scheme = Handy.ColorScheme.PREFER_LIGHT
                if os.name == 'nt' and darkdetect.isDark():
                    scheme = Handy.ColorScheme.PREFER_DARK
                theme = self.config.theme()
                if theme == 'dark':
                    scheme = Handy.ColorScheme.FORCE_DARK
                elif theme == 'light':
                    scheme = Handy.ColorScheme.FORCE_LIGHT
                Handy.StyleManager.get_default().set_color_scheme(scheme)
            except AttributeError:
                # This libhandy is too old. 1.5.90 needed ?
                pass

    def __create_main_window(self):
        """Create the Gtk.ApplicationWindow or Handy.ApplicationWindow"""
        b = Gtk.Builder()
        b.set_translation_domain(DOMAIN)
        with open(self.__resource_path(DOMAIN + ".ui")) as ff:
            s = ff.read()
            if Handy:
                Handy.init()
                s = s.replace("GtkHeaderBar", "HdyHeaderBar")
            b.add_from_string(s)
        b.connect_signals(self)
        self.uiXML = b
        self.window = self.uiXML.get_object("main_window")
        if Handy:
            self.set_color_scheme()
            # Add an intermediate vertical box
            box = Gtk.Box()
            box.props.orientation = Gtk.Orientation.VERTICAL
            hd = self.uiXML.get_object("header_bar")
            mb = self.uiXML.get_object("main_box")
            self.window.remove(hd)
            self.window.remove(mb)
            # Replace the Gtk.ApplicationWindow by the Handy one
            self.window = Handy.ApplicationWindow()
            box.add(hd)
            mb.props.expand = True
            box.add(mb)
            self.window.add(box)
        self.window.set_default_icon_name(ICON_ID)
        return b

    def __create_menus(self):
        b = Gtk.Builder()
        b.set_translation_domain(DOMAIN)
        b.add_from_file(self.__resource_path("menu.ui"))
        b.connect_signals(self)
        self.config.set_actions(b)
        self.popup = Gtk.Menu.new_from_model(b.get_object("popup_menu"))
        self.popup.attach_to_widget(self.window, None)
        main_menu = self.uiXML.get_object("main_menu_button")
        main_menu.set_menu_model(b.get_object("main_menu"))

    def __create_actions(self):
        # Both Handy.ApplicationWindow and Gtk.Application are Gio.ActionMap. Some action are window
        # related some other are application related. As pdfarrager is a single window app does not
        # matter that much.
        self.actions = [
            ('rotate', self.rotate_page_action, 'i'),
            ('delete', self.on_action_delete),
            ('duplicate', self.duplicate),
            ('page-size', self.page_size_dialog),
            ('crop', self.crop_dialog),
            ('crop-white-borders', self.crop_white_borders),
            ('export-selection', self.choose_export_selection_pdf_name, 'i'),
            ('export-all', self.on_action_export_all),
            ('reverse-order', self.reverse_order),
            ('save', self.on_action_save),
            ('save-as', self.on_action_save_as),
            ('new', self.on_action_new),
            ('open', self.on_action_open),
            ('import', self.on_action_import),
            ('zoom-in', self.on_action_zoom_in),
            ('zoom-out', self.on_action_zoom_out),
            ('zoom-fit', self.on_action_zoom_fit),
            ('fullscreen', self.on_action_fullscreen),
            ('close', self.on_action_close),
            ('quit', self.on_quit),
            ('undo', self.undomanager.undo),
            ('redo', self.undomanager.redo),
            ('split', self.split_pages),
            ('merge', self.merge_pages),
            ('metadata', self.edit_metadata),
            ('cut', self.on_action_cut),
            ('copy', self.on_action_copy),
            ('paste', self.on_action_paste, 'i'),
            ('select', self.on_action_select, 'i'),
            ('select-same-file', self.on_action_select, 'i'),
            ('select-same-format', self.on_action_select, 'i'),
            ('about', self.about_dialog),
            ("insert-blank-page", self.insert_blank_page),
            ("generate-booklet", self.generate_booklet),
            ("preferences", self.on_action_preferences),
            ("print", self.on_action_print),
        ]
        self.window.add_action_entries(self.actions)

        self.main_menu = self.uiXML.get_object("main_menu_button")
        self.window.add_action(Gio.PropertyAction.new("main-menu", self.main_menu, "active"))
        for a, k in self.config.get_accels():
            self.set_accels_for_action("win." + a, [k] if isinstance(k, str) else k)
        # Disable actions
        self.iv_selection_changed_event()
        self.window_focus_in_out_event()
        self.undomanager.set_actions(self.window.lookup_action('undo'),
                                     self.window.lookup_action('redo'))

    def insert_blank_page(self, _action, _option, _unknown):
        size = (21 / 2.54 * 72, 29.7 / 2.54 * 72) # A4 by default
        selection = self.iconview.get_selected_items()
        selection.sort()
        model = self.iconview.get_model()
        if len(selection) > 0:
            size = model[selection[-1]][0].size_in_points()
        page_size = pageutils.BlankPageDialog(size, self.window).run_get()
        if page_size is not None:
            adder = PageAdder(self)
            if len(selection) > 0:
                adder.move(Gtk.TreeRowReference.new(model, selection[-1]), False)
            adder.addpages(exporter.create_blank_page(self.tmp_dir, page_size))
            adder.commit(select_added=False, add_to_undomanager=True)

    def generate_booklet(self, _action, _option, _unknown):
        self.undomanager.commit("generate booklet")
        model = self.iconview.get_model()

        selection = self.iconview.get_selected_items()
        selection.sort(key=lambda x: x.get_indices()[0])
        ref_list = [Gtk.TreeRowReference.new(model, path)
                    for path in selection]
        pages = [model.get_value(model.get_iter(ref.get_path()), 0)
                 for ref in ref_list]

        # Need uniform page size.
        p1w, p1h = pages[0].size_in_points()
        for page in pages[1:]:
            pw, ph = page.size_in_points()
            if abs(p1w-pw) > 1e-2 or abs(p1h-ph) > 1e-2:
                msg = _('All pages must have the same size.')
                self.error_message_dialog(msg)
                return

        # We need a multiple of 4
        blank_page_count = 0 if len(pages) % 4 == 0 else 4 - len(pages) % 4
        if blank_page_count > 0:
            file = exporter.create_blank_page(self.tmp_dir, pages[0].size_in_points())
            adder = PageAdder(self)
            for __ in range(blank_page_count):
                adder.addpages(file)
            pages += adder.pages

        adder = PageAdder(self)
        booklet = exporter.generate_booklet(self.pdfqueue, self.tmp_dir, pages)
        adder.move(Gtk.TreeRowReference.new(self.model, selection[0]), True)
        adder.addpages(booklet)
        adder.commit(select_added=False, add_to_undomanager=False)
        self.clear_selected(add_to_undomanager=False)
        self.silent_render()

    def on_action_preferences(self, _action, _option, _unknown):
        handy_available = True if Handy else False
        self.config.preferences_dialog(self.window, localedir, handy_available)
        self.set_color_scheme()

    def on_action_print(self, _action, _option, _unknown):
        exporter.PrintOperation(self).run()

    @staticmethod
    def __create_filters(file_type_list):
        filter_list = []
        f_supported = Gtk.FileFilter()
        f_supported.set_name(_('All supported files'))
        filter_list.append(f_supported)
        if 'pdf' in file_type_list:
            f_pdf = Gtk.FileFilter()
            f_pdf.set_name(_('PDF files'))
            for f in [f_pdf, f_supported]:
                f.add_pattern('*.pdf')
                if os.name != 'nt':
                    f.add_mime_type('application/pdf')
            filter_list.append(f_pdf)
        if 'all' in file_type_list:
            f = Gtk.FileFilter()
            f.set_name(_('All files'))
            f.add_pattern('*')
            filter_list.append(f)
        if 'img2pdf' in file_type_list:
            f_img = Gtk.FileFilter()
            f_img.set_name(_('Supported image files'))
            for f in [f_img, f_supported]:
                for mime in img2pdf_supported_img:
                    if os.name != 'nt':
                        f.add_mime_type(mime)
                    for extension in mimetypes.guess_all_extensions(mime):
                        f.add_pattern('*' + extension)
            filter_list.append(f_img)
        return filter_list

    def set_title(self, title):
        if Handy:
            self.uiXML.get_object('header_bar').set_title(title)
        else:
            self.window.set_title(title)

    def do_activate(self):
        """ https://lazka.github.io/pgi-docs/Gio-2.0/classes/Application.html#Gio.Application.do_activate """
        # TODO: huge method that should be split

        iconsdir = os.path.join(sharedir, 'icons')
        if not os.path.exists(iconsdir):
            iconsdir = os.path.join(sharedir, 'data', 'icons')
        Gtk.IconTheme.get_default().append_search_path(iconsdir)
        self.__create_main_window()
        self.set_title(APPNAME)
        self.window.set_border_width(0)
        self.window.set_application(self)
        if self.config.maximized():
            self.window.maximize()
        self.window.set_default_size(*self.config.window_size())
        self.window.move(*self.config.position())
        self.window.connect('delete_event', self.on_quit)
        self.window.connect('focus_in_event', self.window_focus_in_out_event)
        self.window.connect('focus_out_event', self.window_focus_in_out_event)
        self.window.connect('configure_event', self.window_configure_event)

        if hasattr(GLib, "unix_signal_add"):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.close_application)

        # Create a scrolled window to hold the thumbnails-container
        self.sw = self.uiXML.get_object('scrolledwindow')
        self.sw.drag_dest_set(Gtk.DestDefaults.HIGHLIGHT |
                              Gtk.DestDefaults.DROP,
                              self.TARGETS_SW,
                              Gdk.DragAction.COPY)
        self.sw.connect('drag_data_received', self.sw_dnd_received_data)
        self.sw.connect('button_press_event', self.sw_button_press_event)
        self.sw.connect('scroll_event', self.sw_scroll_event)

        # Create ListStore model and IconView
        self.model = Gtk.ListStore(GObject.TYPE_PYOBJECT, str)
        self.undomanager = undo.Manager(self)
        self.zoom_set(self.config.zoom_level())

        self.iconview = Gtk.IconView(self.model)
        self.iconview.clear()
        self.iconview.set_item_width(-1)

        self.cellthmb = CellRendererImage()
        self.cellthmb.set_padding(3, 3)
        self.cellthmb.set_alignment(0.5, 0.5)
        self.iconview.pack_start(self.cellthmb, False)
        self.iconview.set_cell_data_func(self.cellthmb, self.set_cellrenderer_data, None)
        self.iconview.set_text_column(1)
        cell_text_renderer = self.iconview.get_cells()[1]
        cell_text_renderer.props.ellipsize = Pango.EllipsizeMode.MIDDLE

        self.iconview.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.iconview.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                               self.TARGETS_IV,
                                               Gdk.DragAction.COPY |
                                               Gdk.DragAction.MOVE)
        self.iconview.enable_model_drag_dest(self.TARGETS_IV,
                                             Gdk.DragAction.COPY |
                                             Gdk.DragAction.MOVE)
        self.iconview.connect('drag_begin', self.iv_drag_begin)
        self.iconview.connect('drag_data_get', self.iv_dnd_get_data)
        self.iconview.connect('drag_data_received', self.iv_dnd_received_data)
        self.iconview.connect('drag_data_delete', self.iv_dnd_data_delete)
        self.iconview.connect('drag_motion', self.iv_dnd_motion)
        self.iconview.connect('drag_leave', self.iv_dnd_leave_end)
        self.iconview.connect('drag_end', self.iv_dnd_leave_end)
        self.iconview.connect('button_press_event', self.iv_button_press_event)
        self.iconview.connect('motion_notify_event', self.iv_motion)
        self.iconview.connect('button_release_event', self.iv_button_release_event)
        self.iconview.connect('style_updated', self.set_text_renderer_cell_height)
        self.id_selection_changed_event = self.iconview.connect('selection_changed',
                                                          self.iv_selection_changed_event)
        self.iconview.connect('key_press_event', self.iv_key_press_event)
        self.iconview.connect('size_allocate', self.iv_size_allocate)

        self.sw.add(self.iconview)

        # Status bar to the left
        self.status_bar = self.uiXML.get_object('statusbar')

        # Status bar to the right
        self.status_bar2 = self.uiXML.get_object('statusbar2')

        # Vertical scrollbar
        vscrollbar = self.sw.get_vscrollbar()
        vscrollbar.connect('value_changed', self.vscrollbar_value_changed)
        vscrollbar.props.adjustment.step_increment = 75

        self.window.show_all()

        # Change iconview color background
        style_context_sw = self.sw.get_style_context()
        color_selected = self.iconview.get_style_context() \
            .get_background_color(Gtk.StateFlags.SELECTED)
        color_prelight = color_selected.copy()
        color_prelight.alpha = 0.3
        for state in (Gtk.StateFlags.NORMAL, Gtk.StateFlags.ACTIVE):
            self.iconview.override_background_color(
                state, style_context_sw.get_background_color(state))
        self.iconview.override_background_color(Gtk.StateFlags.SELECTED,
                                                color_selected)
        self.iconview.override_background_color(Gtk.StateFlags.PRELIGHT,
                                                color_prelight)

        # Set cursor look and hide overshoot gradient
        style_provider = Gtk.CssProvider()
        css_data = """
        iconview {
            outline-color: alpha(currentColor, 0.8);
            outline-style: dashed;
            outline-offset: -2px;
            outline-width: 2px;
            -gtk-outline-radius: 2px;
        }
        scrolledwindow overshoot {
            background: none;
        }
        """
        style_provider.load_from_data(bytes(css_data.encode()))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        GObject.type_register(PDFRenderer)
        GObject.signal_new('update_thumbnail', PDFRenderer, GObject.SignalFlags.RUN_FIRST, None,
                           [GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT,
                            GObject.TYPE_PYOBJECT, GObject.TYPE_BOOLEAN])
        self.set_unsaved(False)
        self.__create_actions()
        self.__create_menus()

        self.iv_cursor = IconviewCursor(self)
        self.iv_drag_select = IconviewDragSelect(self)
        self.iv_pan_view = IconviewPanView(self)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()

        # Print PDF Arranger version and exit
        if options.contains("version"):
            print(APPNAME + "-" + VERSION)
            print("pikepdf-" + pikepdf.__version__)
            print("libqpdf-" + pikepdf.__libqpdf_version__)
            return 0

        self.activate()

        if options.lookup_value(GLib.OPTION_REMAINING):
            files = [Gio.File.new_for_commandline_arg(i)
                    for i in options.lookup_value(GLib.OPTION_REMAINING)]

            GObject.idle_add(self.add_files, files)

        return 0

    def add_files(self, files):
        """Add files passed as command line arguments."""
        a = PageAdder(self)
        for f in files:
            try:
                a.addpages(f.get_path())
            except FileNotFoundError as e:
                print(e, file=sys.stderr)
                self.error_message_dialog(e)

        a.commit(select_added=False, add_to_undomanager=True)

    @staticmethod
    def set_text_renderer_cell_height(iconview):
        """Update text renderer cell height on style update.

        Having a fixed height will improve speed.
        Cell height is: "number of rows" * "text height" + 2 * padding
        At start cell will have the height of 1 row + paddings.
        """
        cell_text_renderer = iconview.get_cells()[1]
        cell_text_renderer.set_fixed_size(-1, -1)
        paddy = cell_text_renderer.get_padding()[1]
        natural_height = cell_text_renderer.get_preferred_height(iconview)[1]
        text = cell_text_renderer.props.text
        height = 2 * (natural_height - paddy) if text is None else natural_height
        cell_text_renderer.set_fixed_size(-1, height)

    @staticmethod
    def set_cellrenderer_data(_column, cell, model, it, _data=None):
        cell.set_page(model.get_value(it, 0))

    def render(self):
        self.render_id = None
        if not self.sw.is_sensitive():
            return
        alive = self.quit_rendering()
        if alive:
            self.silent_render()
            return
        self.visible_range = self.get_visible_range2()
        columns_nr = self.iconview.get_columns()
        self.rendering_thread = PDFRenderer(self.model, self.pdfqueue,
                                            self.visible_range , columns_nr)
        self.rendering_thread.connect('update_thumbnail', self.update_thumbnail)
        self.rendering_thread.start()
        ctxt_id = self.status_bar2.get_context_id("rendering")
        self.status_bar2.push(ctxt_id, _('Rendering…'))

    def quit_rendering(self):
        """Quit rendering."""
        if self.rendering_thread is None:
            return False
        self.rendering_thread.quit = True
        # If thread is busy with page.render(cr) it might take some time for thread to quit.
        # Therefore set a timeout here so app continues to stay responsive.
        self.rendering_thread.join(timeout=0.15)
        return self.rendering_thread.is_alive()

    def silent_render(self):
        """Render when silent i.e. when no call for last 149ms.

        Improves app responsiveness by not calling render too frequently.
        """
        if self.render_id:
            GObject.source_remove(self.render_id)
        self.render_id = GObject.timeout_add(149, self.render)

    def render_lock(self):
        """Acquire/release a lock (before any add/delete/reorder)."""
        class __RenderLock:
            def __init__(self, app):
                self.app = app

            def _th(self):
                return self.app.rendering_thread

            def __enter__(self):
                if self._th():
                    self._th().model_lock.acquire()

            def __exit__(self, _exc_type, _exc_value, _traceback):
                if self._th() and self._th().model_lock.locked():
                    self._th().model_lock.release()
        return __RenderLock(self)

    def vscrollbar_value_changed(self, _vscrollbar):
        """Render when vertical scrollbar value has changed."""
        self.silent_render()

    def window_configure_event(self, _window, event):
        """Handle window size and position changes."""
        if self.window_width_old not in [0, event.width] and len(self.model) > 0:
            if self.set_iv_visible_id:
                GObject.source_remove(self.set_iv_visible_id)
            self.set_iv_visible_id = GObject.timeout_add(500, self.set_iconview_visible)
            self.iconview.set_visible(False)
        self.window_width_old = event.width
        if len(self.model) > 1: # Don't trigger extra render after first page is inserted
            self.silent_render()

    def set_iconview_visible(self):
        self.set_iv_visible_id = None
        if len(self.iconview.get_selected_items()) == 0:
            self.vadj_percent_handler(store=True)
        self.update_iconview_geometry()
        self.scroll_to_selection()
        self.sw.set_visible(False)
        self.sw.set_visible(True)
        GObject.idle_add(self.iconview.set_visible, True)
        self.iconview.grab_focus()
        self.silent_render()

    def set_save_file(self, file):
        if file != self.save_file:
            self.save_file = file
            self.set_unsaved(True)

    def set_unsaved(self, flag):
        self.is_unsaved = flag
        GObject.idle_add(self.retitle)

    def retitle(self):
        if self.save_file:
            title = self.save_file
        else:
            title = _('untitled')
        if self.is_unsaved:
            title += '*'

        all_files = set(os.path.splitext(doc.basename)[0] for doc in self.pdfqueue)
        all_files.discard('')
        if len(all_files) > 0:
            title += ' [' + ', '.join(sorted(all_files)) + ']'

        title += ' – ' + APPNAME
        self.set_title(title)
        return False

    def update_thumbnail(self, _obj, ref, thumbnail, zoom, scale, is_preview):
        """Update thumbnail emitted from rendering thread."""
        if ref is None:
            # Rendering ended
            ctxt_id = self.status_bar2.get_context_id("rendering")
            self.status_bar2.remove_all(ctxt_id)
            malloc_trim()
            return
        path = ref.get_path()
        if path is None:
            # Page no longer exist
            return
        if (self.visible_range[0] <= path.get_indices()[0] <= self.visible_range[1] and
                zoom != self.zoom_scale):
            # Thumbnail is in the visible range but is not rendered for current zoom level
            self.silent_render()
            return
        page = self.model[path][0]
        if page.scale != scale:
            # Page scale was changed while page was rendered -> trash & rerender
            self.silent_render()
            return
        page.thumbnail = thumbnail
        page.resample = 1 / zoom
        if is_preview:
            page.preview = thumbnail
        # Let iconview refresh the thumbnail (only) by selecting it
        with GObject.signal_handler_block(self.iconview, self.id_selection_changed_event):
            if self.iconview.path_is_selected(path):
                self.iconview.unselect_path(path)
                self.iconview.select_path(path)
            else:
                self.iconview.select_path(path)
                self.iconview.unselect_path(path)
        ac = self.iconview.get_accessible().ref_accessible_child(path.get_indices()[0])
        ac.set_description(page.description())

    def get_visible_range2(self):
        """Get range of items visible in window.

        A item is considered visible if more than 50% of item is visible.
        """
        vr = self.iconview.get_visible_range()
        if vr is None:
            return -1, -1
        first_ind = vr[0].get_indices()[0]
        last_ind = vr[1].get_indices()[0]
        first_cell = self.iconview.get_cell_rect(vr[0])[1]
        last_cell = self.iconview.get_cell_rect(vr[1])[1]
        sw_height = self.sw.get_allocated_height()
        if first_cell.y + first_cell.height * 0.5 < 0:
            columns_nr = self.iconview.get_columns()
            first_ind = min(first_ind + columns_nr, len(self.model) - 1)
        if last_cell.y + last_cell.height * 0.5 > sw_height:
            last_item_col = self.iconview.get_item_column(vr[1])
            last_ind = max(last_ind - last_item_col - 1, 0)
        return min(first_ind, last_ind), max(first_ind, last_ind)

    def hide_horizontal_scrollbar(self):
        """Hide horizontal scrollbar when not needed."""
        sw_hadj = self.sw.get_hadjustment()
        hscrollbar = self.sw.get_hscrollbar()
        if sw_hadj.get_upper() <= self.sw.get_allocated_width():
            hscrollbar.hide()
        else:
            hscrollbar.show()

    def update_iconview_geometry(self):
        """Set iconview cell size, margins, number of columns and spacing."""
        if len(self.model) > 0:
            item_width = max(row[0].width_in_pixel() for row in self.model)
            item_padding = self.iconview.get_item_padding()
            cellthmb_xpad, cellthmb_ypad = self.cellthmb.get_padding()
            border_and_shadow = 7  # 2*th1+th2 set in iconview.py
            # cell width min limit 50 is set in gtkiconview.c
            cell_width = max(item_width + 2 * cellthmb_xpad + border_and_shadow, 50)
            cell_height = -1
            if self.zoom_fit_page:
                item_height = max(row[0].height_in_pixel() for row in self.model)
                cell_height = item_height + 2 * cellthmb_ypad + border_and_shadow
            self.cellthmb.set_fixed_size(cell_width, cell_height)
            padded_cell_width = cell_width + 2 * item_padding
            min_col_spacing = 5
            min_margin = 11
            iw_width = self.sw.get_allocation().width
            # 2 * min_margin + col_num * padded_cell_width
            #  + min_col_spacing * (col_num+1) = iw_width
            col_num = (iw_width - 2 * min_margin - min_col_spacing) //\
                      (padded_cell_width + min_col_spacing)
            spacing = (iw_width - col_num * padded_cell_width - 2 * min_margin) // (col_num + 1)
            margin = (iw_width - col_num * (padded_cell_width + spacing) + spacing) // 2
            if col_num == 0:
                col_num = 1
                margin = 6
            self.iconview.set_columns(col_num)
            self.iconview.set_column_spacing(spacing)
            self.iconview.set_margin(margin)

    def vadj_percent_handler(self, store=False, restore=False):
        """Store and restore adjustment percentual value."""
        sw_vadj = self.sw.get_vadjustment()
        lower_limit = sw_vadj.get_lower()
        upper_limit = sw_vadj.get_upper()
        page_size = sw_vadj.get_page_size()
        sw_vpos = sw_vadj.get_value()
        vadj_range = upper_limit - lower_limit - page_size
        if store and self.vadj_percent is None and vadj_range > 0:
            self.vadj_percent = (sw_vpos - lower_limit) / vadj_range
        if restore and self.vadj_percent is not None:
            sw_vadj.set_value(self.vadj_percent * vadj_range + lower_limit)
            self.vadj_percent = None

    def iv_size_allocate(self, _iconview, _allocation):
        self.hide_horizontal_scrollbar()
        self.set_adjustment_limits()
        if self.vadj_percent is not None:
            self.vadj_percent_handler(restore=True)
        if self.scroll_path:
            GObject.idle_add(self.scroll_to_path2, self.scroll_path)
            self.scroll_path = None

    def set_adjustment_limits(self):
        hscrollbar = self.sw.get_hscrollbar()
        vscrollbar = self.sw.get_vscrollbar()
        if len(self.model) == 0:
            # Hide scrollbars https://gitlab.gnome.org/GNOME/gtk/-/issues/4370 ?
            hscrollbar.set_range(0, 0)
            vscrollbar.set_range(0, 0)
        else:
            # Remove margins at top and bottom of iconview
            lower_limit = self.iconview.get_margin() - 6
            upper_limit = vscrollbar.props.adjustment.get_upper() - lower_limit
            vscrollbar.set_range(lower_limit, upper_limit)

    def confirm_dialog(self, msg, action):
        """A dialog for confirmation of an action."""
        d = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.NONE, msg)
        d.add_buttons(action, 1, _('_Cancel'), 2)
        response = d.run()
        d.destroy()
        return response == 1

    def save_changes_dialog(self, msg):
        """A dialog which ask if changes should be saved."""
        d = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.NONE, msg)
        d.format_secondary_markup(_("Your changes will be lost if you don’t save them."))
        d.add_buttons(_('Do_n’t Save'), 1, _('_Cancel'), 2, _('_Save'), 3)
        response = d.run()
        d.destroy()
        return response

    def on_action_close(self, _action, _param, _unknown):
        """Close all files and restore initial state."""
        if self.is_unsaved:
            if len(self.model) == 0:
                msg = _('Discard changes and close?')
                confirm = self.confirm_dialog(msg, action=_('_Close'))
                if not confirm:
                    return
            else:
                if self.save_file:
                    msg = _('Save changes to “{}” before closing?')
                    msg = msg.format(os.path.basename(self.save_file))
                else:
                    msg = _('Save changes before closing?')
                response = self.save_changes_dialog(msg)
                if response == 3:
                    self.post_action = 'CLEAR_DATA'
                    self.save_or_choose()
                    return
                elif response != 1:
                    return
        self.clear_data()

    def clear_data(self):
        self.iconview.unselect_all()
        with self.render_lock():
            self.model.clear()
        self.pdfqueue = []
        self.metadata = {}
        self.undomanager.clear()
        self.set_save_file(None)
        self.export_file = None
        self.set_unsaved(False)
        self.update_statusbar()
        malloc_trim()

    def on_quit(self, _action, _param=None, _unknown=None):
        if self.disable_quit:
            return Gdk.EVENT_STOP
        elif self.is_unsaved:
            if len(self.model) == 0:
                msg = _('Discard changes and quit?')
                confirm = self.confirm_dialog(msg, action=_('_Quit'))
                if not confirm:
                    return Gdk.EVENT_STOP
            else:
                if self.save_file:
                    msg = _('Save changes to “{}” before quitting?')
                    msg = msg.format(os.path.basename(self.save_file))
                else:
                    msg = _('Save changes before quitting?')
                response = self.save_changes_dialog(msg)
                if response == 3:
                    self.post_action = 'CLOSE_APPLICATION'
                    self.save_or_choose()
                    return Gdk.EVENT_STOP
                elif response != 1:
                    return Gdk.EVENT_STOP
        self.close_application()
        return Gdk.EVENT_STOP

    def close_application(self, _widget=None, _event=None, _data=None):
        """Termination"""
        self.quit_flag.set()
        if self.rendering_thread:
            self.rendering_thread.quit = True
            self.rendering_thread.join()
            self.rendering_thread.pdfqueue = []

        if self.export_process:
            self.export_process.join(timeout=2)
            if self.export_process.is_alive():
                self.export_process.terminate()
                self.export_process.join()

        # Prevent gtk errors when closing with everything selected
        self.iconview.unselect_all()
        self.iconview.get_model().clear()

        # Release Poppler.Document instances to unlock all temporary files
        self.pdfqueue = []
        gc.collect()
        self.config.set_window_size(self.window.get_size())
        self.config.set_maximized(self.window.is_maximized())
        self.config.set_zoom_level(self.zoom_level)
        self.config.set_position(self.window.get_position())
        self.config.save()
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)
        self.quit()

    @staticmethod
    def get_cnt_filename(f, need_cnt=False):
        """Get a filename where the value at end is incremented by 1."""
        shortname, ext = os.path.splitext(f)
        if ext.lower() != ".pdf":
            ext = ".pdf"
        cnt = ""
        for char in reversed(shortname):
            if char.isdigit():
                cnt = char + cnt
            else:
                break
        if cnt != "":
            name_part = shortname[:-len(cnt)]
            cnt_part = str(int(cnt) + 1).zfill(len(cnt))
            f = name_part + cnt_part + ext
        elif need_cnt:
            f = shortname + "-002" + ext
        return f

    def choose_export_pdf_name(self, exportmode):
        """Handles choosing a name for exporting """
        title = _('Save As…') if exportmode == 'ALL_TO_SINGLE' else _('Export…')

        chooser = Gtk.FileChooserNative.new(title=title,
                                        parent=self.window,
                                        action=Gtk.FileChooserAction.SAVE,
                                        accept_label=_("_Save"),
                                        cancel_label=_("_Cancel"))
        chooser.set_do_overwrite_confirmation(True)
        if len(self.pdfqueue) > 0:
            f = self.save_file or self.pdfqueue[0].filename
            f_dir, basename = os.path.split(f)
            tempdir = f_dir.startswith(tempfile.gettempdir()) and f_dir.endswith(DOMAIN)
            if exportmode == 'ALL_TO_SINGLE':
                if f.endswith(".pdf") and not tempdir:
                    chooser.set_filename(f)  # Set name to existing file
            else:
                shortname, ext = os.path.splitext(basename)
                if self.export_file is None and tempdir:
                    shortname = ""
                f = self.export_file or shortname + "-000" + ext
                f = self.get_cnt_filename(f)
                chooser.set_current_name(f)  # Set name to new file
                chooser.set_current_folder(self.export_directory)
        filter_list = self.__create_filters(['pdf', 'all'])
        for f in filter_list[1:]:
            chooser.add_filter(f)

        response = chooser.run()
        file_out = chooser.get_filename()
        chooser.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            root, ext = os.path.splitext(file_out)
            if ext.lower() != '.pdf':
                ext = '.pdf'
                file_out = file_out + ext
            files_out = [file_out]
            if exportmode in ['ALL_TO_MULTIPLE', 'SELECTED_TO_MULTIPLE']:
                s = self.iconview.get_selected_items()
                len_files = len(self.model) if exportmode == 'ALL_TO_MULTIPLE' else len(s)
                for i in range(1, len_files):
                    files_out.append(self.get_cnt_filename(files_out[-1], need_cnt=True))
                    if os.path.exists(files_out[i]):
                        msg = (_('A file named "%s" already exists. Do you want to replace it?')
                               % os.path.split(files_out[i])[1])
                        replace = self.confirm_dialog(msg, _("Replace"))
                        if not replace:
                            return
            self.save(exportmode, files_out)
        else:
            self.post_action = None

    def open_dialog(self, title):
        chooser = Gtk.FileChooserNative.new(title=title,
                                        parent=self.window,
                                        action=Gtk.FileChooserAction.OPEN,
                                        accept_label=_("_Open"),
                                        cancel_label=_("_Cancel"))
        if self.import_directory is not None:
            chooser.set_current_folder(self.import_directory)
        chooser.set_select_multiple(True)
        file_type_list = ['all', 'pdf']
        if len(img2pdf_supported_img) > 0:
            file_type_list = ['all', 'img2pdf', 'pdf']
        filter_list = self.__create_filters(file_type_list)
        for f in filter_list:
            chooser.add_filter(f)

        return chooser.run(), chooser

    def on_action_new(self, _action=None, _param=None, _unknown=None, filenames=None):
        """Start a new instance."""
        filenames = filenames or []
        if os.name == 'nt':
            args = [str(sys.executable)]
            for filename in filenames:
                args.append(filename)
            if sys.executable.find('python3.exe') != -1:
                args.insert(1, '-mpdfarranger')
            subprocess.Popen(args)
        else:
            display = Gdk.Display.get_default()
            launch_context = display.get_app_launch_context()
            desktop_file = "%s.desktop"%(self.get_application_id())
            try:
                app_info = Gio.DesktopAppInfo.new(desktop_file)
                launch_files = []
                for filename in filenames:
                    launch_file = Gio.File.new_for_path(filename)
                    launch_files.append(launch_file)
                app_info.launch(launch_files, launch_context)
            except TypeError:
                args = [str(sys.executable), '-mpdfarranger']
                for filename in filenames:
                    args.append(filename)
                subprocess.Popen(args)

    def on_action_open(self, _action, _param, _unknown):
        """Open new file(s)."""
        response, chooser = self.open_dialog(_('Open…'))

        if response == Gtk.ResponseType.ACCEPT:
            if len(self.pdfqueue) > 0 or len(self.metadata) > 0:
                self.on_action_new(filenames=chooser.get_filenames())
            else:
                adder = PageAdder(self)
                filenames = chooser.get_filenames()
                filenames = reversed(filenames) if os.name == 'nt' else filenames
                for filename in filenames:
                    adder.addpages(filename)
                adder.commit(select_added=False, add_to_undomanager=True)
        chooser.destroy()

    def on_action_save(self, _action, _param, _unknown):
        self.save_or_choose()

    def save_or_choose(self):
        """Saves to the previously exported file or shows the export dialog if
        there was none."""
        savemode = 'ALL_TO_SINGLE'
        if self.save_file:
            self.save(savemode, [self.save_file])
        else:
            self.choose_export_pdf_name(savemode)

    def on_action_save_as(self, _action, _param, _unknown):
        self.choose_export_pdf_name('ALL_TO_SINGLE')

    def save(self, exportmode, files_out):
        """Saves to the specified file."""
        if exportmode in ['SELECTED_TO_SINGLE', 'SELECTED_TO_MULTIPLE']:
            selection = reversed(self.iconview.get_selected_items())
            pages = [self.model[row][0].duplicate(incl_thumbnail=False) for row in selection]
        else:
            pages = [row[0].duplicate(incl_thumbnail=False) for row in self.model]
        if exportmode == 'ALL_TO_SINGLE':
            self.set_save_file(files_out[0])
        else:
            self.export_file = os.path.split(files_out[-1])[1]
        self.export_directory = os.path.split(files_out[0])[0]

        if self.config.content_loss_warning():
            try:
                res, enabled = exporter.check_content(self.window, self.pdfqueue)
            except Exception as e:
                traceback.print_exc()
                self.error_message_dialog(e)
                return
            self.config.set_content_loss_warning(enabled)
            if res == Gtk.ResponseType.CANCEL:
                return # Abort

        files = [(pdf.copyname, pdf.password) for pdf in self.pdfqueue]
        export_msg = multiprocessing.Queue()
        a = files, pages, self.metadata, files_out, self.quit_flag, export_msg
        self.export_process = multiprocessing.Process(target=exporter.export_process, args=a)
        self.export_process.start()
        GObject.timeout_add(300, self.export_finished, exportmode, export_msg)
        self.set_export_state(True)

    def save_warning_dialog(self, msg):
        d = Gtk.MessageDialog(
            type=Gtk.MessageType.WARNING,
            parent=self.window,
            text=_("Saving produced some warnings"),
            secondary_text=_("Despite the warnings the document(s) should have no visible issues."),
            buttons=Gtk.ButtonsType.OK
            )
        sw = Gtk.ScrolledWindow(margin=6)
        label = Gtk.Label(msg, wrap=True, margin=6, xalign=0.0, selectable=True)
        sw.add(label)
        d.vbox.pack_start(sw, False, False, 0)
        cb = Gtk.CheckButton(_("Don't show warnings when saving again."), margin=6, can_focus=False)
        d.vbox.pack_start(cb, False, False, 0)
        d.show_all()
        sw.set_min_content_height(min(150, label.get_allocated_height()))
        cb.set_can_focus(True)
        d.run()
        self.config.set_show_save_warnings(not cb.get_active())
        d.destroy()

    def export_finished(self, exportmode, export_msg):
        """Check if export finished. Show any messages. Run any post action."""
        if self.export_process.is_alive():
            return True  # continue polling
        self.set_export_state(False)
        msg_type = None
        if not export_msg.empty():
            msg, msg_type = export_msg.get()
        if exportmode == 'ALL_TO_SINGLE' and msg_type != Gtk.MessageType.ERROR:
            self.set_unsaved(False)
        if msg_type == Gtk.MessageType.ERROR:
            self.error_message_dialog(msg)
        elif msg_type == Gtk.MessageType.WARNING and self.config.show_save_warnings():
            self.save_warning_dialog(msg)
        if not self.is_unsaved:
            if self.post_action == 'CLEAR_DATA':
                self.clear_data()
            elif self.post_action == 'CLOSE_APPLICATION':
                self.close_application()
        self.post_action = None
        return False  # cancel timer

    def set_export_state(self, enable, message=_("Saving…")):
        """Enable/disable app export state.

        When enabled app is moveable, resizable and closeable but does not respond to other input.
        """
        if self.quit_flag.is_set():
            return
        self.sw.set_sensitive(not enable)
        self.main_menu.set_sensitive(not enable)
        self.disable_quit = enable
        for a in self.actions:
            self.window.lookup_action(a[0]).set_enabled(not enable)
        ctxt_id = self.status_bar2.get_context_id("saving")
        if enable:
            self.status_bar2.push(ctxt_id, message)
            cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'wait')
            self.quit_rendering()
        else:
            self.status_bar2.remove_all(ctxt_id)
            cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'default')
            self.window_focus_in_out_event()
            self.iv_selection_changed_event()
            self.silent_render()
            self.iconview.grab_focus()
        self.iconview.get_window().set_cursor(cursor)

    def choose_export_selection_pdf_name(self, _action, mode, _unknown):
        exportmodes = {0: 'ALL_TO_SINGLE',
                       1: 'ALL_TO_MULTIPLE',
                       2: 'SELECTED_TO_SINGLE',
                       3: 'SELECTED_TO_MULTIPLE'}
        exportmode = exportmodes[mode.get_int32()]
        self.choose_export_pdf_name(exportmode)

    def on_action_export_all(self, _action, _param, _unknown):
        self.choose_export_pdf_name('ALL_TO_MULTIPLE')

    def on_action_import(self, _action, _param, _unknown):
        """Import doc"""
        response, chooser = self.open_dialog(_('Import…'))

        if response == Gtk.ResponseType.ACCEPT:
            adder = PageAdder(self)
            filenames = chooser.get_filenames()
            filenames = reversed(filenames) if os.name == 'nt' else filenames
            for filename in filenames:
                adder.addpages(filename)
            adder.commit(select_added=False, add_to_undomanager=True)
        chooser.destroy()

    def clear_selected(self, add_to_undomanager=True):
        """Removes the selected elements in the IconView"""
        if add_to_undomanager:
            self.undomanager.commit("Delete")
        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()
        selection.sort(reverse=True)
        self.set_unsaved(True)
        with GObject.signal_handler_block(self.iconview, self.id_selection_changed_event):
            with self.render_lock():
                for path in selection:
                    model.remove(model.get_iter(path))
            path = selection[-1]
            self.iconview.select_path(path)
            if not self.iconview.path_is_selected(path):
                if len(model) > 0:  # select the last row
                    row = model[-1]
                    path = row.path
                    self.iconview.select_path(path)
        self.scroll_path = path
        self.update_iconview_geometry()
        self.iv_selection_changed_event()
        self.iconview.grab_focus()
        self.silent_render()
        self.update_max_zoom_level()
        malloc_trim()

    def scroll_to_path2(self, path):
        """scroll_to_path() with modifications.

        * Don't scroll to a oversized page that already is filling window
        * Scroll only vertically
        """
        cell = self.iconview.get_cell_rect(path)[1]
        if cell.y <= 0 and cell.y + cell.height >= self.sw.get_allocated_height():
            return
        sw_hadj = self.sw.get_hadjustment()
        sw_hpos = sw_hadj.get_value()
        self.iconview.scroll_to_path(path, False, 0, 0)
        sw_hadj.set_value(sw_hpos)

    def copy_pages(self, add_hash=True):
        """Collect data from selected pages"""

        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()
        selection.sort(key=lambda x: x.get_indices()[0])

        data = []
        for path in selection:
            it = model.get_iter(path)
            data.append(model.get_value(it, 0).serialize())

        if data:
            data = '\n;\n'.join(data)
            if add_hash:
                h = hashlib.sha256(data.encode('utf-8')).hexdigest()
                data = h + '\n' + data
        return data

    def paste_pages(self, data, before, ref_to, select_added):
        """Paste pages to iconview"""

        pageadder = PageAdder(self)
        if ref_to:
            pageadder.move(ref_to, before)
        if not before and ref_to:
            data.reverse()

        for d in data:
            pageadder.addpages(*d)
        return pageadder.commit(select_added, add_to_undomanager=True)

    def paste_files(self, filepaths, before, ref_to):
        """Paste files to iconview."""
        pageadder = PageAdder(self)

        for filepath in filepaths:
            pageadder.move(ref_to, before)
            pageadder.addpages(filepath)
        pageadder.commit(select_added=False, add_to_undomanager=True)

    def paste_pages_interleave(self, data, before, ref_to):
        """Paste pages or files interleved to iconview."""
        pageadder = PageAdder(self)
        model = self.iconview.get_model()
        scroll = len(model) > 0
        iter_to = None
        iref = ref_to.get_path().get_indices()[0] if ref_to else 0

        self.undomanager.commit("Paste")
        self.set_unsaved(True)

        for d in data:
            pageadder.addpages(*d)

            pageadder.move(ref_to, before)
            pageadder.commit(select_added=False, add_to_undomanager=False)

            if ref_to:
                path = ref_to.get_path()
                iter_to = model.get_iter(path)
                iter_to = model.iter_next(iter_to)
                if not before:
                    iter_to = model.iter_next(iter_to)
            if iter_to:
                path = model.get_path(iter_to)
                ref_to = Gtk.TreeRowReference.new(model, path)
            else:
                ref_to = None

        if scroll:
            iscroll = iref if before else iref + 1
            scroll_path = Gtk.TreePath.new_from_indices([iscroll])
            self.iconview.scroll_to_path(scroll_path, False, 0, 0)

    def on_action_delete(self, _action, _parameter, _unknown):
        """Removes the selected elements in the IconView"""

        self.clear_selected()

    def on_action_cut(self, _action, _param, _unknown):
        """Cut selected pages to clipboard."""
        data = self.copy_pages()
        self.clipboard.set_text('pdfarranger-clipboard\n' + data, -1)
        self.clear_selected()
        self.window.lookup_action("paste").set_enabled(True)

    def on_action_copy(self, _action, _param, _unknown):
        """Copy selected pages to clipboard."""
        data = self.copy_pages()
        self.clipboard.set_text('pdfarranger-clipboard\n' + data, -1)
        self.window.lookup_action("paste").set_enabled(True)

    def on_action_paste(self, _action, mode, _unknown):
        """Paste pages, file paths or an image from clipboard."""
        data, data_is_filepaths = self.read_from_clipboard()
        if not data:
            return

        pastemodes = {0: 'AFTER', 1: 'BEFORE', 2: 'ODD', 3: 'EVEN', 4: 'OVERLAY', 5: 'UNDERLAY'}
        pastemode = pastemodes[mode.get_int32()]

        ref_to, before = self.set_paste_location(pastemode, data_is_filepaths)

        if pastemode in ['AFTER', 'BEFORE']:
            if data_is_filepaths:
                self.paste_files(data, before, ref_to)
            else:
                self.paste_pages(data, before, ref_to, select_added=False)
        elif pastemode in ['ODD', 'EVEN']:
            if data_is_filepaths:
                # Generate data to send to paste_pages_interleave
                filepaths = []
                try:
                    for filepath in data:
                        filemime = mimetypes.guess_type(filepath)[0]
                        if not filemime:
                            raise PDFDocError(filepath + ':\n' + _('Unknown file format'))
                        if filemime == 'application/pdf':
                            num_pages = exporter.num_pages(filepath)
                            if num_pages is None:
                                raise PDFDocError(filepath + ':\n' + _('PDF document is damaged'))
                            for page in range(1, num_pages + 1):
                                filepaths.append((filepath, page))
                        elif filemime.split('/')[0] == 'image':
                            filepaths.append((filepath, 1))
                        else:
                            raise PDFDocError(filepath + ':\n' + _('File is neither pdf nor image'))
                except PDFDocError as e:
                    print(e.message, file=sys.stderr)
                    self.error_message_dialog(e.message)
                    return
                data = filepaths
            self.paste_pages_interleave(data, before, ref_to)
            self.update_iconview_geometry()
            GObject.idle_add(self.retitle)
            self.iv_selection_changed_event()
            self.update_max_zoom_level()
            self.silent_render()
        elif pastemode in ['OVERLAY', 'UNDERLAY'] and not data_is_filepaths:
            selection = self.iconview.get_selected_items()
            self.paste_as_layer(data, selection, laypos=pastemode)

    def paste_as_layer(self, data, destination, laypos, offset_xy=None):
        page_stack = []
        pageadder = PageAdder(self)
        for filename, npage, _basename, angle, scale, crop, layerdata in data:
            d = [[filename, npage, angle, scale, laypos, crop, Sides()]] + layerdata
            page_stack.append(pageadder.get_layerpages(d))
            if page_stack[-1] is None:
                return
        if not self.is_paste_layer_available(destination):
            return
        dpage = self.model[destination[-1]][0]
        lpage_stack = page_stack[0]
        if offset_xy is None:
            a = self.window, dpage, lpage_stack, self.model, self.pdfqueue, laypos, self.layer_pos
            offset_xy = pageutils.PastePageLayerDialog(*a).get_offset()
            if offset_xy is None:
                return
            self.layer_pos = offset_xy
            self.undomanager.commit("Add Layer")
            self.set_unsaved(True)

        off_x, off_y = offset_xy  # Fraction of the page size differance at left & top
        for num, row in enumerate(reversed(destination)):
            dpage = self.model[row][0]
            layerpage_stack = page_stack[num % len(page_stack)]

            # Add the "main" pasted page
            lp0 = layerpage_stack[0].duplicate()
            dwidth, dheight = dpage.size[0] * dpage.scale, dpage.size[1] * dpage.scale
            scalex = (dpage.width_in_points() - lp0.width_in_points()) / dwidth
            scaley = (dpage.height_in_points() - lp0.height_in_points()) / dheight
            left = dpage.crop.left + off_x * scalex
            top = dpage.crop.top + off_y * scaley
            lp0.offset = Sides(left=left,
                               right=1 - left - lp0.width_in_points() / dwidth,
                               top=top,
                               bottom=1 - top - lp0.height_in_points() / dheight)
            dpage.layerpages.append(lp0)

            # Add layers from the pasted page
            nfirst = len(dpage.layerpages) - 1
            scalex = (lp0.size[0] * lp0.scale) / (dpage.size[0] * dpage.scale)
            scaley = (lp0.size[1] * lp0.scale) / (dpage.size[1] * dpage.scale)
            sm1 = Sides(scalex, scalex, scaley, scaley)
            for lp in layerpage_stack[1:]:
                lp = lp.duplicate()
                scalex = (lp0.size[0] * lp0.scale) / (lp.size[0] * lp.scale)
                scaley = (lp0.size[1] * lp0.scale) / (lp.size[1] * lp.scale)
                sm2 = Sides(scalex, scalex, scaley, scaley)
                # Crop layer area outside of the old parent mediabox
                outside = Sides(*(max(0, lp0.crop[i] - lp.offset[i]) for i in range(4)))
                lp.crop += outside * sm2
                lp.offset += outside

                # Recalculate the offset relative to the new destination page
                lp.offset = lp0.offset + (lp.offset - lp0.crop) * sm1
                if lp.crop.left + lp.crop.right > 1 or lp.crop.top + lp.crop.bottom > 1:
                    # The layer is outside of the visible area
                    continue
                # Mark as OVERLAY or UNDERLAY and add the layer at right place in stack
                if lp.laypos != laypos:
                    lp.laypos = laypos
                    dpage.layerpages.insert(nfirst, lp)
                else:
                    dpage.layerpages.append(lp)

            dpage.resample = -1
        self.silent_render()

    def is_paste_layer_available(self, selection):
        if len(selection) == 0:
            return False
        if not layer_support:
            msg = _("Pikepdf >= 3 is needed for overlay/underlay/merge support.")
            self.error_message_dialog(msg)
        return layer_support

    def read_from_clipboard(self):
        """Read and pre-process data from clipboard.

        If an image is found it is stored as a temporary png file.
        If id "pdfarranger-clipboard" is found pages is expected to be in clipboard, else file paths.
        """
        if len(img2pdf_supported_img) > 0 and self.clipboard.wait_is_image_available():
            data_is_filepaths = True
            image = self.clipboard.wait_for_image()
            if image is None:
                data = ''
            else:
                fd, filename = tempfile.mkstemp(suffix=".png", dir=self.tmp_dir)
                os.close(fd)
                image.savev(filename, "png", [], [])
                data = [filename]
        else:
            data = self.clipboard.wait_for_text()
            if not data:
                data = ''

            data_is_filepaths = False
            if data.startswith('pdfarranger-clipboard\n'):
                data = data.replace('pdfarranger-clipboard\n', '', 1)
                try:
                    copy_hash = data[:data.index('\n')]
                except ValueError:
                    copy_hash = None
                else:
                    data = data.replace(copy_hash + '\n', '', 1)
                    paste_hash = hashlib.sha256(data.encode('utf-8')).hexdigest()
                if copy_hash is not None and copy_hash == paste_hash:
                    data = self.deserialize(data.split('\n;\n'))
                else:
                    message = _("Pasted data not valid. Aborting paste.")
                    self.error_message_dialog(message)
                    data = []
            else:
                data_is_filepaths = True
                if os.name == 'posix' and data.startswith('x-special/nautilus-clipboard\ncopy'):
                    data = data.replace('x-special/nautilus-clipboard\ncopy', '', 1)
                rows = data.split('\n')
                rows = filter(None, rows)
                data = []
                for row in rows:
                    if os.name == 'posix' and row.startswith('file:///'):  # Dolphin, Nautilus
                        row = get_file_path_from_uri(row)
                    elif os.name == 'nt' and row.startswith('"') and row.endswith('"'):
                        row = row[1:-1]
                    if os.path.isfile(row):
                        data.append(row)
                    else:
                        data = []
                        break

        return data, data_is_filepaths

    @staticmethod
    def deserialize(data):
        """Deserialize data from copy & paste or drag & drop operation."""
        d = []
        while data:
            tmp = data.pop(0).split('\n')
            filename = tmp[0]
            npage = int(tmp[1])
            if len(tmp) < 3:  # Only when paste files interleaved
                d.append((filename, npage))
            else:
                basename = tmp[2]
                angle = int(tmp[3])
                scale = float(tmp[4])
                crop = [float(side) for side in tmp[5:9]]
                layerdata = []
                i = 9
                while i < len(tmp):  # If page has overlay/underlay
                    lfilename = tmp[i]
                    lnpage = int(tmp[i + 1])
                    langle = int(tmp[i + 2])
                    lscale = float(tmp[i + 3])
                    laypos = tmp[i + 4]
                    lcrop = [float(side) for side in tmp[i + 5:i + 9]]
                    loffset = [float(offs) for offs in tmp[i + 9:i + 13]]
                    layerdata.append([lfilename, lnpage, langle, lscale, laypos, lcrop, loffset])
                    i += 13
                d.append((filename, npage, basename, angle, scale, crop, layerdata))
        return d

    def set_paste_location(self, pastemode, data_is_filepaths):
        """Sets reference where pages should be pasted and if before or after that."""
        model = self.iconview.get_model()

        selection = self.iconview.get_selected_items()
        selection.sort(key=lambda x: x.get_indices()[0])
        if len(model) == 0:
            before = True
            ref_to = None
        elif pastemode == 'AFTER':
            last_row = model[-1]
            if len(selection) == 0 or selection[-1] == last_row.path:
                before = False
                ref_to = None
            elif data_is_filepaths:
                before = True
                path = selection[-1]
                iter_next = model.iter_next(model.get_iter(path))
                path_next = model.get_path(iter_next)
                ref_to = Gtk.TreeRowReference.new(model, path_next)
            else:
                before = False
                ref_to = Gtk.TreeRowReference.new(model, selection[-1])
        else:
            if pastemode == 'EVEN':
                before = False
            else:  # BEFORE or ODD
                before = True
            if len(selection) == 0:
                ref_to = Gtk.TreeRowReference.new(model, Gtk.TreePath(0))
            else:
                ref_to = Gtk.TreeRowReference.new(model, selection[0])
        return ref_to, before

    def on_action_select(self, _action, option, _unknown):
        """Selects items according to selected option."""
        selectoptions = {0: 'ALL', 1: 'DESELECT', 2: 'ODD', 3: 'EVEN',
                         4: 'SAME_FILE', 5: 'SAME_FORMAT', 6:'INVERT'}
        selectoption = selectoptions[option.get_int32()]
        model = self.iconview.get_model()
        with GObject.signal_handler_block(self.iconview, self.id_selection_changed_event):
            if selectoption == 'ALL':
                self.iconview.select_all()
            elif selectoption == 'DESELECT':
                self.iconview.unselect_all()
            elif selectoption == 'ODD':
                for page_number, row in enumerate(model, start=1):
                    if page_number % 2:
                        self.iconview.select_path(row.path)
                    else:
                        self.iconview.unselect_path(row.path)
            elif selectoption == 'EVEN':
                for page_number, row in enumerate(model, start=1):
                    if page_number % 2:
                        self.iconview.unselect_path(row.path)
                    else:
                        self.iconview.select_path(row.path)
            elif selectoption == 'SAME_FILE':
                selection = self.iconview.get_selected_items()
                copynames = set(model[row][0].copyname for row in selection)
                for page_number, row in enumerate(model):
                    if model[page_number][0].copyname in copynames:
                        self.iconview.select_path(row.path)
            elif selectoption == 'SAME_FORMAT':
                selection = self.iconview.get_selected_items()
                formats = set(model[row][0].size_in_points() for row in selection)
                # Chop digits to detect same page format on rotated cropped pages
                formats = [(round(w, 8), round(h, 8)) for (w, h) in formats]
                for row in model:
                    page = model[row.path][0]
                    w, h = page.size_in_points()
                    if (round(w, 8), round(h, 8)) in formats:
                        self.iconview.select_path(row.path)
            elif selectoption == 'INVERT':
                for row in model:
                    if self.iconview.path_is_selected(row.path):
                        self.iconview.unselect_path(row.path)
                    else:
                        self.iconview.select_path(row.path)
        self.iv_selection_changed_event()

    @staticmethod
    def iv_drag_begin(iconview, context):
        """Sets custom drag icon."""
        selected_count = len(iconview.get_selected_items())
        stock_icon = "gtk-dnd-multiple" if selected_count > 1 else "gtk-dnd"
        iconview.stop_emission('drag_begin')
        Gtk.drag_set_icon_name(context, stock_icon, 16, 16)

    def iv_dnd_get_data(self, _iconview, _context,
                        selection_data, _target_id, _etime):
        """Handles requests for data by drag and drop in iconview"""

        target = str(selection_data.get_target())
        if target == 'MODEL_ROW_INTERN':
            self.target_is_intern = True
            selection = self.iconview.get_selected_items()
            selection.sort(key=lambda x: x.get_indices()[0])
            data = []
            for path in selection:
                data.append(str(path[0]))
            if data:
                data = '\n;\n'.join(data)
        elif target == 'MODEL_ROW_EXTERN':
            self.target_is_intern = False
            data = self.copy_pages(add_hash=False)
        else:
            return
        selection_data.set(selection_data.get_target(), 8, data.encode())

    def iv_dnd_received_data(self, iconview, context, _x, _y,
                             selection_data, _target_id, etime):
        """Handles received data by drag and drop in iconview"""

        model = iconview.get_model()
        data = selection_data.get_data()
        if not data:
            return
        data = data.decode().split('\n;\n')
        if self.drag_path and len(model) > 0:
            ref_to = Gtk.TreeRowReference.new(model, self.drag_path)
        else:
            ref_to = None
        before = self.drag_pos == Gtk.IconViewDropPosition.DROP_LEFT
        target = selection_data.get_target().name()
        if target == 'MODEL_ROW_INTERN':
            move = context.get_selected_action() & Gdk.DragAction.MOVE
            self.undomanager.commit("Move" if move else "Copy")
            self.set_unsaved(True)
            data.sort(key=int, reverse=not before)
            ref_from_list = [Gtk.TreeRowReference.new(model, Gtk.TreePath(p))
                             for p in data]
            iter_to = self.model.get_iter(ref_to.get_path())
            with self.render_lock():
                for ref_from in ref_from_list:
                    iterator = model.get_iter(ref_from.get_path())
                    page = model.get_value(iterator, 0).duplicate()
                    if before:
                        it = model.insert_before(iter_to, [page, page.description()])
                    else:
                        it = model.insert_after(iter_to, [page, page.description()])
                    path = model.get_path(it)
                    iconview.select_path(path)
                if move:
                    for ref_from in ref_from_list:
                        model.remove(model.get_iter(ref_from.get_path()))
            GObject.idle_add(self.render)

        elif target == 'MODEL_ROW_EXTERN':
            data = self.deserialize(data)
            changed = self.paste_pages(data, before, ref_to, select_added=True)
            if changed and context.get_selected_action() & Gdk.DragAction.MOVE:
                context.finish(True, True, etime)

    def iv_dnd_data_delete(self, _widget, _context):
        """Delete pages from a pdfarranger instance after they have
        been moved to another instance."""
        if self.target_is_intern and os.name == 'nt':
            # Workaround for windows
            # On Windows this method is in some situations triggered even for drag & drop
            # within the same pdfarranger instance
            return
        selection = self.iconview.get_selected_items()
        self.undomanager.commit("Move")
        self.set_unsaved(True)
        model = self.iconview.get_model()
        ref_del_list = [Gtk.TreeRowReference.new(model, path) for path in selection]
        with self.render_lock():
            for ref_del in ref_del_list:
                path = ref_del.get_path()
                model.remove(model.get_iter(path))
        self.update_iconview_geometry()
        GObject.idle_add(self.render)
        malloc_trim()

    def iv_dnd_motion(self, iconview, context, x, y, etime):
        """Handles drag motion: autoscroll, select move or copy, select drag cursor location."""
        # Block dnd when a modal dialog is open
        for w in self.window.list_toplevels():
            if w.get_modal():
                iconview.stop_emission('drag_motion')
                return Gdk.EVENT_PROPAGATE

        x, y = iconview.convert_widget_to_bin_window_coords(x, y)

        # Auto-scroll when drag up/down
        self.iv_autoscroll(x, y, autoscroll_area=40)

        # Select move or copy dragAction
        drag_move_posix = os.name == 'posix' and context.get_actions() & Gdk.DragAction.MOVE
        drag_move_nt = os.name == 'nt' and not keyboard.is_pressed('control')
        if drag_move_posix or drag_move_nt:
            Gdk.drag_status(context, Gdk.DragAction.MOVE, etime)
        else:
            Gdk.drag_status(context, Gdk.DragAction.COPY, etime)

        # By default 5 drag & drop positions are possible: into, left, right, above and below.
        # We override default behaviour and only allow drag & drop to left or right.
        # When drag location is a valid drop location True is returned.
        model = iconview.get_model()
        if len(model) == 0:
            return Gdk.EVENT_STOP
        cell_width, _cell_height = self.cellthmb.get_fixed_size()
        row_distance = iconview.get_row_spacing() + 2 * iconview.get_item_padding()
        column_distance = iconview.get_column_spacing() + 2 * iconview.get_item_padding()
        search_positions = [('XY', x, y),
                            ('Right', x + column_distance / 2, y),
                            ('Left', x - column_distance / 2, y),
                            ('Below', x, y + row_distance / 2),
                            ('Above', x, y - row_distance / 2),
                            ('Left-Above', x - column_distance, y - row_distance),
                            ('Right-Far', x + cell_width, y),
                            ('Left-Far', x - cell_width, y),
                            ('Right-Below-Far', x + cell_width, y + row_distance),
                            ('Left-Below-Far', x - cell_width, y + row_distance),
                            ('Below-Far', x, y + row_distance)]
        for search_pos, x_s, y_s in search_positions:
            path = iconview.get_path_at_pos(x_s, y_s)
            if path:
                break
        if search_pos in ['XY', 'Right', 'Left', 'Below', 'Above']:
            self.drag_path = path
            if path == iconview.get_path_at_pos(x_s + cell_width * 0.6, y_s):
                self.drag_pos = Gtk.IconViewDropPosition.DROP_LEFT
            elif path == iconview.get_path_at_pos(x_s - cell_width * 0.6, y_s):
                self.drag_pos = Gtk.IconViewDropPosition.DROP_RIGHT
        elif search_pos == 'Left-Above' and iconview.get_drag_dest_item()[0]:
            return Gdk.EVENT_STOP
        elif not path or (path == model[-1].path and x_s < x):
            self.drag_path = model[-1].path
            self.drag_pos = Gtk.IconViewDropPosition.DROP_RIGHT
        else:
            iconview.stop_emission('drag_motion')
            return Gdk.EVENT_PROPAGATE
        iconview.set_drag_dest_item(self.drag_path, self.drag_pos)
        return Gdk.EVENT_STOP

    def iv_autoscroll(self, x, y, autoscroll_area):
        """Iconview auto-scrolling."""
        sw_vadj = self.sw.get_vadjustment()
        if y < sw_vadj.get_value() + autoscroll_area:
            if not self.iv_auto_scroll_timer:
                self.iv_auto_scroll_timer = GObject.timeout_add(150, self.iv_auto_scroll, 'UP')
        elif y > sw_vadj.get_page_size() + sw_vadj.get_value() - autoscroll_area:
            if not self.iv_auto_scroll_timer:
                self.iv_auto_scroll_timer = GObject.timeout_add(150, self.iv_auto_scroll, 'DOWN')
        elif self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_dnd_leave_end(self, _widget, _context, _ignored=None):
        """Ends the auto-scroll during DND"""

        if self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_auto_scroll(self, direction):
        """Timeout routine for auto-scroll"""
        sw_vadj = self.sw.get_vadjustment()
        step = sw_vadj.get_step_increment()
        step = -step if direction == "UP" else step
        with GObject.signal_handler_block(self.iconview, self.id_selection_changed_event):
            sw_vadj.set_value(sw_vadj.get_value() + step)
            if not self.click_path:
                changed = self.iv_drag_select.motion(step=step)
                if changed:
                    self.iv_selection_changed_event()
        return True  # call me again

    def iv_motion(self, iconview, event):
        """Manages mouse movement on the iconview."""
        # Pan the view when pressing mouse wheel and moving mouse
        if event.state & Gdk.ModifierType.BUTTON2_MASK:
            self.iv_pan_view.motion(event)

        # Detect drag and drop events
        if self.pressed_button:
            if iconview.drag_check_threshold(self.pressed_button.x,
                                             self.pressed_button.y,
                                             event.x, event.y):
                iconview.drag_begin_with_coordinates(Gtk.TargetList.new(self.TARGETS_IV),
                                                     Gdk.DragAction.COPY | Gdk.DragAction.MOVE,
                                                     self.pressed_button.button, event, -1, -1)
                self.pressed_button = None

        # Drag-select when clicking between items and dragging mouse
        if event.state & Gdk.ModifierType.BUTTON1_MASK and self.iv_drag_select.click_location:
            self.iv_autoscroll(event.x, event.y, autoscroll_area=4)
            if not self.click_path:
                with GObject.signal_handler_block(iconview, self.id_selection_changed_event):
                    changed = self.iv_drag_select.motion(event)
                if changed:
                    self.iv_selection_changed_event()

    def iv_button_release_event(self, iconview, event):
        """Manages mouse releases on the iconview"""
        if self.end_rubberbanding:
            self.end_rubberbanding = False
            return
        self.iv_drag_select.end()
        self.iv_pan_view.end()

        if self.pressed_button:
            # Button was pressed and released on a previously selected item
            # without causing a drag and drop.
            path = iconview.get_path_at_pos(event.x, event.y)
            if not path:
                return
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                # Deselect the clicked item.
                iconview.unselect_path(path)
            else:
                # Deselect everything except the clicked item.
                iconview.unselect_all()
                iconview.select_path(path)
        self.pressed_button = None

        # Stop drag-select autoscrolling when button is released
        if self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_button_press_event(self, iconview, event):
        """Manages mouse clicks on the iconview"""
        # Switch between zoom_fit and zoom_set on double-click
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS and self.click_path:
            self.pressed_button = None
            self.on_action_zoom_fit()
            return Gdk.EVENT_STOP

        # Change to 'move' cursor when pressing mouse wheel
        if event.button == 2:
            self.iv_pan_view.click(event)

        click_path_old = self.click_path
        self.click_path = iconview.get_path_at_pos(event.x, event.y)

        # On shift-click, select all items from cursor up to the shift-clicked item.
        # On shift-ctrl-click, toggle selection for single items.
        # IconView's built-in multiple-selection mode performs rubber-band
        # (rectangular) selection, which is not what we want. We override
        # it by handling the shift-click here.
        if event.button == 1 and self.click_path and event.state & Gdk.ModifierType.SHIFT_MASK:
            cursor_path = iconview.get_cursor()[1]
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if iconview.path_is_selected(self.click_path):
                    iconview.unselect_path(self.click_path)
                else:
                    iconview.select_path(self.click_path)
            elif cursor_path:
                i_cursor = cursor_path[0]
                i_click = self.click_path[0]
                i_click_old = click_path_old[0] if click_path_old else i_click
                range_start = min(i_cursor, i_click, i_click_old)
                range_end = max(i_cursor, i_click, i_click_old)
                with GObject.signal_handler_block(iconview, self.id_selection_changed_event):
                    for i in range(range_start, range_end + 1):
                        path = Gtk.TreePath.new_from_indices([i])
                        if min(i_cursor, i_click) <= i <= max(i_cursor, i_click):
                            iconview.select_path(path)
                        else:
                            iconview.unselect_path(path)
                self.iv_selection_changed_event()
            return Gdk.EVENT_STOP

        # Forget where cursor was when shift was pressed
        if event.button == 1 and not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.iv_cursor.sel_start_page = None

        # Do not deselect when clicking an already selected item for drag and drop
        if event.button == 1:
            selection = iconview.get_selected_items()
            if self.click_path and self.click_path in selection:
                self.pressed_button = event
                if iconview.get_cursor()[1] != self.click_path:
                    self.iconview.set_cursor(self.click_path, None, False)
                return Gdk.EVENT_STOP  # prevent propagation i.e. (de-)selection

        # Display right click menu
        if event.button == 3 and not self.iv_auto_scroll_timer:
            self.iv_drag_select.end()
            self.iv_pan_view.end()
            if self.click_path:
                selection = iconview.get_selected_items()
                if self.click_path not in selection:
                    iconview.unselect_all()
                    iconview.select_path(self.click_path)
            else:
                iconview.unselect_all()
            iconview.grab_focus()
            self.popup.popup(None, None, None, None, event.button, event.time)
            return Gdk.EVENT_STOP

        # Go into drag-select mode if clicked between items
        if not self.click_path:
            if event.button == 1:
                self.iv_drag_select.click(event)
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                return Gdk.EVENT_STOP  # Don't deselect all

            # Let iconview hide cursor. Then stop rubberbanding with the release event
            self.end_rubberbanding = True
            release_event = event.copy()
            release_event.type = Gdk.EventType.BUTTON_RELEASE
            release_event.put()
        return Gdk.EVENT_PROPAGATE

    def iv_key_press_event(self, iconview, event):
        """Manages keyboard press events on the iconview."""
        if event.state & Gdk.ModifierType.BUTTON1_MASK:
            return Gdk.EVENT_STOP
        if event.keyval in [Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right,
                              Gdk.KEY_Home, Gdk.KEY_End, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down,
                              Gdk.KEY_KP_Page_Up, Gdk.KEY_KP_Page_Down]:
            # Move cursor, select pages and scroll with navigation keys
            with GObject.signal_handler_block(iconview, self.id_selection_changed_event):
                self.iv_cursor.handler(iconview, event)
            self.iv_selection_changed_event(None, move_cursor_event=True)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def iv_selection_changed_event(self, _iconview=None, move_cursor_event=False):
        selection = self.iconview.get_selected_items()
        ne = len(selection) > 0
        for a, e in [
            ("reverse-order", self.reverse_order_available(selection)),
            ("delete", ne),
            ("duplicate", ne),
            ("page-size", ne),
            ("crop", ne),
            ("rotate", ne),
            ("export-selection", ne),
            ("cut", ne),
            ("copy", ne),
            ("split", ne),
            ("merge", ne),
            ("select-same-file", ne),
            ("select-same-format", ne),
            ("crop-white-borders", ne),
            ("generate-booklet", ne),
        ]:
            self.window.lookup_action(a).set_enabled(e)
        self.update_statusbar()
        if selection and not move_cursor_event:
            self.iv_cursor.cursor_is_visible = False

    def window_focus_in_out_event(self, _widget=None, _event=None):
        """Keyboard focus enter or leave window."""
        # Enable or disable paste actions based on clipboard content
        text = self.clipboard.wait_is_text_available()
        image = len(img2pdf_supported_img) > 0 and self.clipboard.wait_is_image_available()
        if self.window.lookup_action("paste"):  # Prevent error when closing with Alt+F4
            if self.sw.is_sensitive():
                self.window.lookup_action("paste").set_enabled(text or image)

    def sw_dnd_received_data(self, _scrolledwindow, _context, _x, _y,
                             selection_data, target_id, _etime):
        """Handles received data by drag and drop in scrolledwindow"""
        if target_id == self.TEXT_URI_LIST:
            pageadder = PageAdder(self)
            model = self.iconview.get_model()
            ref_to = None
            before = True
            if len(model) > 0:
                last_row = model[-1]
                if self.drag_pos == Gtk.IconViewDropPosition.DROP_LEFT:
                    ref_to = Gtk.TreeRowReference.new(model, self.drag_path)
                elif self.drag_path != last_row.path:
                    iter_next = model.iter_next(model.get_iter(self.drag_path))
                    path_next = model.get_path(iter_next)
                    ref_to = Gtk.TreeRowReference.new(model, path_next)
            pageadder.move(ref_to, before)
            for uri in selection_data.get_uris():
                filename = get_file_path_from_uri(uri)
                pageadder.addpages(filename)
            pageadder.commit(select_added=False, add_to_undomanager=True)
            self.iv_selection_changed_event()

    def sw_button_press_event(self, _scrolledwindow, event):
        """Unselects all items in iconview on mouse click in scrolledwindow"""
        # TODO most likely unreachable code

        if event.button == 1:
            self.iconview.unselect_all()

    def sw_scroll_event(self, _scrolledwindow, event):
        """Manages mouse scroll events in scrolledwindow"""
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            # Scroll horizontally
            return Gdk.EVENT_PROPAGATE
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            dy = event.get_scroll_deltas()[2]
            if dy < 0:
                direction = 'UP'
            elif dy > 0:
                direction = 'DOWN'
            else:
                return Gdk.EVENT_PROPAGATE
        elif event.direction == Gdk.ScrollDirection.UP:
            direction = 'UP'
        elif event.direction == Gdk.ScrollDirection.DOWN:
            direction = 'DOWN'
        else:
            return Gdk.EVENT_PROPAGATE
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            # Zoom
            zoom_delta = 1 if direction == 'UP' else -1
            self.zoom_set(self.zoom_level + zoom_delta)
        else:
            #Scroll. Also drag-select if mouse button is pressed
            sw_vadj = self.sw.get_vadjustment()
            step = sw_vadj.get_step_increment()
            step = -step if direction == 'UP' else step
            with GObject.signal_handler_block(self.iconview, self.id_selection_changed_event):
                sw_vadj.set_value(sw_vadj.get_value() + step)
                if event.state & Gdk.ModifierType.BUTTON1_MASK:
                    changed = self.iv_drag_select.motion(event, step=step)
                    if changed:
                        self.iv_selection_changed_event()
        return Gdk.EVENT_STOP

    def enable_zoom_buttons(self, out_enable, in_enable):
        if self.window.lookup_action("zoom-out"):
            self.window.lookup_action("zoom-out").set_enabled(out_enable)
            self.window.lookup_action("zoom-in").set_enabled(in_enable)

    def update_max_zoom_level(self):
        """Update upper zoom level limit so thumbnails are max 6000000 pixels."""
        if len(self.model) == 0:
            return
        max_pixels = 6000000  # 6000000 pixels * 4 byte/pixel -> 23Mb
        max_page_size = max(p.width_in_points() * p.height_in_points() for p, _ in self.model)
        max_zoom_scale = (max_pixels / max_page_size) ** .5
        self.zoom_level_limits[1] = min(int(log(max_zoom_scale / .2) / log(1.1)), 80)
        self.zoom_set(self.zoom_level)

    def zoom_set(self, level):
        """Sets the zoom level"""
        lower, upper = self.zoom_level_limits
        level = min(max(level, lower), upper)
        self.enable_zoom_buttons(level != lower, level != upper)
        if self.zoom_level == level:
            return
        self.vadj_percent_handler(store=True)
        self.zoom_level = level
        self.zoom_scale = 0.2 * (1.1 ** level)
        if self.id_scroll_to_sel:
            GObject.source_remove(self.id_scroll_to_sel)
        self.zoom_fit_page = False
        self.quit_rendering()  # For performance reasons
        for row in self.model:
            row[0].zoom = self.zoom_scale
        if len(self.model) > 0:
            self.update_iconview_geometry()
            self.model[0][0] = self.model[0][0]  # Let iconview refresh itself
            self.id_scroll_to_sel = GObject.timeout_add(400, self.scroll_to_selection)
            self.silent_render()

    def zoom_fit(self, path):
        """Zoom and scroll to path."""
        item_padding = self.iconview.get_item_padding()
        cell_image_renderer, cell_text_renderer = self.iconview.get_cells()
        image_padding = cell_image_renderer.get_padding()
        text_rect = self.iconview.get_cell_rect(path, cell_text_renderer)[1]
        text_rect_height = text_rect.height  # cell_text_renderer padding is included here
        border_and_shadow = 7  # 2*th1+th2 set in iconview.py
        cell_extraX = 2 * (item_padding + image_padding[0]) + border_and_shadow
        cell_extraY = 2 * (item_padding + image_padding[1]) + text_rect_height + border_and_shadow
        sw_width = self.sw.get_allocated_width()
        sw_height = self.sw.get_allocated_height()
        page_width = max(p.width_in_points() for p, _ in self.model)
        page_height = max(p.height_in_points() for p, _ in self.model)
        margins = 12  # leave 6 pixel at left and 6 pixel at right
        zoom_scaleX_new = max(1, (sw_width - cell_extraX - margins)) / page_width
        zoom_scaleY_new = max(1, (sw_height - cell_extraY)) / page_height
        zoom_scale = min(zoom_scaleY_new, zoom_scaleX_new)

        lower, upper = self.zoom_level_limits
        self.zoom_level = min(max(int(log(zoom_scale / .2) / log(1.1)), lower), upper)
        if self.zoom_level in [lower, upper]:
            zoom_scale = 0.2 * (1.1 ** self.zoom_level)
        self.zoom_scale = zoom_scale
        self.enable_zoom_buttons(self.zoom_level != lower, self.zoom_level != upper)
        for page, _ in self.model:
            page.zoom = self.zoom_scale
        self.model[0][0] = self.model[0][0]
        self.update_iconview_geometry()
        self.iconview.scroll_to_path(path, True, 0.5, 0.5)

    def on_action_zoom_in(self, _action, _param, _unknown):
        self.zoom_set(self.zoom_level + 5)

    def on_action_zoom_out(self, _action, _param, _unknown):
        self.zoom_set(self.zoom_level - 5)

    def on_action_zoom_fit(self, _action=None, _param=None, _unknown=None):
        """Switch between zoom_fit and zoom_set."""
        if len(self.model) == 0:
            return
        if self.zoom_fit_page:
            self.zoom_set(self.zoom_level_old)
        else:
            selection = self.iconview.get_selected_items()
            if len(selection) > 0:
                path = selection[-1]
            else:
                path = Gtk.TreePath.new_from_indices([self.get_visible_range2()[0]])
                self.iconview.select_path(path)
            self.iconview.set_cursor(path, None, False)
            self.zoom_level_old = self.zoom_level
            self.zoom_fit_page = True
            self.zoom_fit(path)

    def on_action_fullscreen(self, _action, _param, _unknown):
        """Toggle fullscreen mode."""
        header_bar = self.uiXML.get_object('header_bar')
        if header_bar.get_visible():
            self.window.fullscreen()
            header_bar.hide()
        else:
            self.window.unfullscreen()
            header_bar.show()

    def scroll_to_selection(self):
        """Scroll iconview so that selection is in center of window."""
        self.id_scroll_to_sel = None
        selection = self.iconview.get_selected_items()
        if len(selection) > 0:
            path = selection[len(selection) // 2]
            self.iconview.scroll_to_path(path, True, 0.5, 0.5)

    def rotate_page_action(self, _action, angle, _unknown):
        """Rotates the selected page in the IconView"""
        self.undomanager.commit("Rotate")
        angle = angle.get_int32()
        selection = self.iconview.get_selected_items()
        if self.rotate_page(selection, angle):
            self.set_unsaved(True)
            self.update_statusbar()

    def rotate_page(self, selection, angle):
        model = self.iconview.get_model()
        rotated = False
        page_width_old = max(p.width_in_points() for p, _ in self.model)
        page_height_old = max(p.height_in_points() for p, _ in self.model)
        for path in selection:
            treeiter = model.get_iter(path)
            p = model.get_value(treeiter, 0)
            if p.rotate(angle):
                rotated = True
                model.set_value(treeiter, 0, p)
        self.update_iconview_geometry()
        page_width_new = max(p.width_in_points() for p, _ in self.model)
        page_height_new = max(p.height_in_points() for p, _ in self.model)
        if page_width_old != page_width_new or page_height_old != page_height_new:
            self.scroll_to_selection()
        return rotated

    def split_pages(self, _action, _parameter, _unknown):
        """ Split selected pages """
        diag = splitter.Dialog(self.window)
        leftcrops, topcrops = diag.run_get()
        if leftcrops is None or topcrops is None:
            return
        model = self.iconview.get_model()
        self.set_unsaved(True)
        self.undomanager.commit("Split")
        # selection is a list of 1-tuples, not in order
        selection = self.iconview.get_selected_items()
        selection.sort(key=lambda x: x.get_indices()[0])
        ref_list = [Gtk.TreeRowReference.new(model, path)
                    for path in selection]
        with self.render_lock():
            for ref in ref_list:
                iterator = model.get_iter(ref.get_path())
                page = model.get_value(iterator, 0)
                page.resample = -1
                newpages = page.split(leftcrops, topcrops)
                for p in newpages:
                    p.resample = -1
                    model.insert_after(iterator, [p, p.description()])
                model.set_value(iterator, 0, page)
        self.update_iconview_geometry()
        self.iv_selection_changed_event()
        self.update_max_zoom_level()
        GObject.idle_add(self.render)

    def get_size_info(self, selection):
        sizes = [self.model[row][0].size_in_points() for row in reversed(selection)]
        max_width = max(s[0] for s in sizes)
        min_width = min(s[0] for s in sizes)
        max_height = max(s[1] for s in sizes)
        min_height = min(s[1] for s in sizes)
        equal = max_width == min_width and max_height == min_height
        return sizes, (max_width, max_height), equal

    def merge_pages(self, _action, _parameter, _unknown):
        """Merge selected pages."""
        selection = self.iconview.get_selected_items()
        if not self.is_paste_layer_available(selection):
            return
        data = self.copy_pages(add_hash=False)
        data = self.deserialize(data.split('\n;\n'))
        sizes, max_size, equal = self.get_size_info(selection)
        r = pageutils.MergePagesDialog(self.window, max_size, equal).run_get()
        if r is None:
            return
        cols, rows, add_order, size = r
        self.undomanager.commit("Merge")
        self.set_unsaved(True)
        self.clear_selected()
        self.iconview.unselect_all()

        ndpage = selection[-1].get_indices()[0]
        before = ndpage < len(self.model)
        ref = Gtk.TreeRowReference.new(self.model, selection[-1]) if before else None
        wdpage, hdpage = size[0] * cols, size[1] * rows
        ndpages = -(len(data) // -(cols * rows))
        file = exporter.create_blank_page(self.tmp_dir, (wdpage, hdpage), ndpages)
        adder = PageAdder(self)
        adder.move(ref, before)
        adder.addpages(file)
        with GObject.signal_handler_block(self.iconview, self.id_selection_changed_event):
            adder.commit(select_added=True, add_to_undomanager=False)

        nlpage = 0
        while ndpage < len(self.model) and nlpage < len(data):
            for row, col in add_order:
                wlpage, hlpage = sizes[nlpage]
                wdiff, hdiff = wdpage - wlpage, hdpage - hlpage
                off_x = off_y = 0.5
                if wdiff != 0:
                    off_x = (col * wdpage / cols + 0.5 * wdpage / cols - wlpage / 2) / wdiff
                if hdiff != 0:
                    off_y = (row * hdpage / rows + 0.5 * hdpage / rows - hlpage / 2) / hdiff
                dest = self.model[ndpage].path
                self.paste_as_layer([data[nlpage]], dest, 'OVERLAY', (off_x, off_y))
                nlpage += 1
                if nlpage > len(data) - 1:
                    break
            ndpage += 1
        self.update_iconview_geometry()
        self.iv_selection_changed_event()
        self.update_max_zoom_level()

    def edit_metadata(self, _action, _parameter, _unknown):
        files = [(pdf.copyname, pdf.password) for pdf in self.pdfqueue]
        if metadata.edit(self.metadata, files, self.window):
            self.set_unsaved(True)

    def page_size_dialog(self, _action, _parameter, _unknown):
        """Opens a dialog box to define page size."""
        selection = self.iconview.get_selected_items()
        diag = pageutils.ScaleDialog(self.iconview.get_model(), selection, self.window)
        newscale = diag.run_get()
        if newscale is None:
            return
        if not pageutils.scale(self.model, selection, newscale):
            return
        self.undomanager.commit("Size")
        self.set_unsaved(True)
        self.update_statusbar()
        self.update_iconview_geometry()
        self.update_max_zoom_level()
        GObject.idle_add(self.render)

    def crop_dialog(self, _action, _parameter, _unknown):
        """Opens a dialog box to define margins for page cropping."""
        s = self.iconview.get_selected_items()
        a = self.window, s, self.model, self.pdfqueue, self.is_unsaved, self.update_crop
        pageutils.CropDialog(*a)

    def update_crop(self, crops, selection, is_unsaved):
        self.undomanager.commit("Crop")
        self.crop(selection, crops)
        self.set_unsaved(is_unsaved)
        self.update_statusbar()
        self.update_iconview_geometry()
        self.update_max_zoom_level()
        GObject.idle_add(self.render)

    def crop_white_borders(self, _action, _parameter, _unknown):
        selection = self.iconview.get_selected_items()
        crop = pageutils.white_borders(self.iconview.get_model(), selection, self.pdfqueue)
        self.undomanager.commit("Crop white Borders")
        if self.crop(selection, crop):
            self.set_unsaved(True)
            self.update_statusbar()
        self.update_max_zoom_level()
        GObject.idle_add(self.render)

    def crop(self, selection, newcrop):
        changed = False
        model = self.iconview.get_model()
        for id_sel, path in enumerate(selection):
            pos = model.get_iter(path)
            page = model.get_value(pos, 0)
            if page.crop != Sides(*newcrop[id_sel]):
                page.crop = Sides(*newcrop[id_sel])
                page.resample = -1
                changed = True
            model.set_value(pos, 0, page)
        self.update_iconview_geometry()
        return changed

    def duplicate(self, _action, _parameter, _unknown):
        """Duplicates the selected elements"""

        self.set_unsaved(True)
        self.undomanager.commit("Duplicate")

        model = self.iconview.get_model()
        # selection is a list of 1-tuples, not in order
        selection = self.iconview.get_selected_items()
        selection.sort(key=lambda x: x.get_indices()[0])
        ref_list = [Gtk.TreeRowReference.new(model, path)
                    for path in selection]
        with self.render_lock():
            for ref in ref_list:
                iterator = model.get_iter(ref.get_path())
                page = model.get_value(iterator, 0).duplicate()
                model.insert_after(iterator, [page, page.description()])
        self.iv_selection_changed_event()
        GObject.idle_add(self.render)


    @staticmethod
    def reverse_order_available(selection):
        """Determine whether the selection is suitable for the
           reverse-order command: the selection must be a multiple and
           contiguous range of pages.
        """
        if len(selection) < 2:
            return False

        # selection is a list of 1-tuples, not in order
        indices = sorted([i[0] for i in selection])
        first = indices[0]
        last = indices[-1]
        contiguous = (len(indices) == last - first + 1)

        return contiguous

    def reverse_order(self, _action, _parameter, _unknown):
        """Reverses the selected elements in the IconView"""

        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()

        # selection is a list of 1-tuples, not in order
        indices = sorted([i[0] for i in selection])
        first = indices[0]
        last = indices[-1]

        self.set_unsaved(True)
        indices.reverse()
        new_order = list(range(first)) + indices + list(range(last + 1, len(model)))
        self.undomanager.commit("Reorder")
        with self.render_lock():
            model.reorder(new_order)
        GObject.idle_add(self.render)

    def about_dialog(self, _action, _parameter, _unknown):
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_transient_for(self.window)
        about_dialog.set_modal(True)
        about_dialog.set_name(APPNAME)
        about_dialog.set_program_name(APPNAME)
        about_dialog.set_version(VERSION)
        pike = pikepdf.__version__
        qpdf = pikepdf.__libqpdf_version__
        gtkv = "{}.{}.{}".format(
            Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()
        )
        pyv = "{}.{}.{}".format(
            sys.version_info.major, sys.version_info.minor, sys.version_info.micro
        )
        about_dialog.set_comments(
            "".join(
                (
                    _("%s is a tool for rearranging and modifying PDF files.")
                    % APPNAME,
                    "\n \n",
                    _("It uses libqpdf %s, pikepdf %s, GTK %s and Python %s.")
                    % (qpdf, pike, gtkv, pyv),
                )
            )
        )
        about_dialog.set_authors(['Konstantinos Poulios'])
        about_dialog.add_credit_section(_('Maintainers and contributors'), [
            'https://github.com/pdfarranger/pdfarranger/graphs/contributors'])
        about_dialog.set_website(WEBSITE)
        about_dialog.set_website_label(WEBSITE)
        about_dialog.set_logo_icon_name(ICON_ID)
        about_dialog.set_license(_('GNU General Public License (GPL) Version 3.'))
        about_dialog.connect('response', lambda w, *args: w.destroy())
        about_dialog.connect('delete_event', lambda w, *args: w.destroy())
        about_dialog.show_all()

    def update_statusbar(self):
        selection = self.iconview.get_selected_items()
        selected_pages = sorted([p.get_indices()[0] + 1 for p in selection])
        # Compact the representation of the selected page range
        jumps = [[l, r] for l, r in zip(selected_pages, selected_pages[1:])
                    if l + 1 < r]
        ranges = list(selected_pages[0:1] + sum(jumps, []) + selected_pages[-1:])
        display = []
        for lo, hi in zip(ranges[::2], ranges[1::2]):
            range_str = '{}-{}'.format(lo,hi) if lo < hi else '{}'.format(lo)
            display.append(range_str)
        ctxt_id = self.status_bar.get_context_id("selected_pages")
        num_pages = len(self.model)
        msg = _("Selected pages: ") + ", ".join(display) + " / " + str(num_pages)
        if len(selection) == 1:
            model = self.iconview.get_model()
            pagesize = model[selection[0]][0].size_in_points()
            pagesize = [x * 25.4 / 72 for x in pagesize]
            msg += " | "+_("Page Size:")+ " {:.1f}mm \u00D7 {:.1f}mm".format(*pagesize)
        self.status_bar.push(ctxt_id, msg)

        for a in ["save", "save-as", "select", "export-all", "zoom-fit", "print"]:
            self.window.lookup_action(a).set_enabled(num_pages > 0)

    def error_message_dialog(self, msg):
        error_msg_dlg = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
                                          type=Gtk.MessageType.ERROR, parent=self.window,
                                          message_format=str(msg),
                                          buttons=Gtk.ButtonsType.OK)
        response = error_msg_dlg.run()
        if response == Gtk.ResponseType.OK:
            error_msg_dlg.destroy()


def main():
    PdfArranger().run(sys.argv)
