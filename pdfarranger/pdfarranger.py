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
import shutil  # for file operations like whole directory deletion
import sys  # for processing of command line args
import tempfile
import signal
import mimetypes
import warnings
import traceback
import locale  # for multilanguage support
import gettext
import gc
import subprocess
import ctypes
import pikepdf
from urllib.request import url2pathname
from functools import lru_cache


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
    try:
        locale.bind_textdomain_codeset(DOMAIN, 'UTF-8')
    except AttributeError:
        pass
else:
    # Windows or musl
    libintl = ctypes.cdll['libintl-8' if os.name == 'nt' else 'libintl.so.8']
    libintl.bindtextdomain(DOMAIN.encode(), localedir.encode(sys.getfilesystemencoding()))
    libintl.bind_textdomain_codeset(DOMAIN.encode(), 'UTF-8'.encode())
    del libintl

APPNAME = 'PDF Arranger'
VERSION = '1.7.1'
WEBSITE = 'https://github.com/pdfarranger/pdfarranger'

# Add support for dnd to other instance and insert file at drop location in Windows
if os.name == 'nt':
    import keyboard  # to get control key state when drag to other instance
    os.environ['GDK_WIN32_USE_EXPERIMENTAL_OLE2_DND'] = 'true'

import gi

# check that we don't need GObject.threads_init()
gi.check_version('3.10.2')
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

if Gtk.check_version(3, 12, 0):
    raise Exception('You do not have the required version of GTK+ installed. ' +
                    'Installed GTK+ version is ' +
                    '.'.join([str(Gtk.get_major_version()),
                              str(Gtk.get_minor_version()),
                              str(Gtk.get_micro_version())]) +
                    '. Required GTK+ version is 3.12 or higher.')

from gi.repository import Gdk
from gi.repository import GObject  # for using custom signals
from gi.repository import Gio  # for inquiring mime types information
from gi.repository import GLib
from gi.repository import Pango

if os.name == 'nt' and GLib.get_language_names():
    os.environ['LANG'] = GLib.get_language_names()[0]
gettext.bindtextdomain(DOMAIN, localedir)
gettext.textdomain(DOMAIN)
_ = gettext.gettext

from . import undo
from . import exporter
from . import metadata
from . import croputils
from . import splitter
from .iconview import CellRendererImage
from .iconview import IconviewCursor
from .iconview import IconviewDragSelect
from .config import Config
from .core import img2pdf_supported_img, PageAdder, PDFDocError, PDFRenderer
GObject.type_register(CellRendererImage)


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


def warn_dialog(func):
    """ Decorator which redirect warnings module messages to a gkt MessageDialog """

    class ShowWarning:
        def __init__(self):
            self.buffer = ""

        def __call__(self, message, category, filename, lineno, f=None, line=None):
            s = warnings.formatwarning(message, category, filename, lineno, line)
            if sys.stderr is not None:
                sys.stderr.write(s + '\n')
            self.buffer += str(message) + '\n'

    def wrapper(*args, **kwargs):
        self = args[0]
        backup_showwarning = warnings.showwarning
        warnings.showwarning = ShowWarning()
        try:
            func(*args, **kwargs)
            if len(warnings.showwarning.buffer) > 0:
                self.error_message_dialog(warnings.showwarning.buffer, Gtk.MessageType.WARNING)
        finally:
            warnings.showwarning = backup_showwarning

    return wrapper


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
        return
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
                         flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE,
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
        self.zoom_scale = None
        self.zoom_full_page = False
        self.render_id = None
        self.id_scroll_to_sel = None
        self.target_is_intern = True

        self.export_directory = os.path.expanduser('~')
        self.import_directory = self.export_directory
        self.nfile = 0
        self.iv_auto_scroll_direction = 0
        self.iv_auto_scroll_timer = None
        self.vp_css_margin = 0
        self.pdfqueue = []
        self.metadata = {}
        self.pressed_button = None
        self.click_path = None
        self.rendering_thread = None
        self.export_file = None
        self.drag_path = None
        self.drag_pos = Gtk.IconViewDropPosition.DROP_RIGHT
        self.sb_timeout_id = None
        self.window_width_old = 0
        self.set_iv_visible_id = None

        # Clipboard for cut copy paste
        self.clipboard_default = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if os.name == 'posix':
            # "private" clipboard does not work in Windows so we can't use it here
            self.clipboard_pdfarranger = Gtk.Clipboard.get(Gdk.Atom.intern('_SELECTION_PDFARRANGER',
                                                                           False))

    def do_open(self, files, _n, _hints):
        """ https://lazka.github.io/pgi-docs/Gio-2.0/classes/Application.html#Gio.Application.do_open """
        self.activate()
        # Importing documents passed as command line arguments
        a = PageAdder(self)
        for f in files:
            a.addpages(f.get_path())
        a.commit(select_added=False, add_to_undomanager=True)

    def __build_from_file(self, path):
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
        b = Gtk.Builder()
        b.set_translation_domain(DOMAIN)
        b.add_from_file(f)
        b.connect_signals(self)
        return b

    def __create_menus(self):
        b = self.__build_from_file("menu.ui")
        self.config.set_actions(b)
        self.popup = Gtk.Menu.new_from_model(b.get_object("popup_menu"))
        self.popup.attach_to_widget(self.window, None)
        main_menu = self.uiXML.get_object("main_menu_button")
        main_menu.set_menu_model(b.get_object("main_menu"))

    def __create_actions(self):
        # Both Gtk.ApplicationWindow and Gtk.Application are Gio.ActionMap. Some action are window
        # related some other are application related. As pdfarrager is a single window app does not
        # matter that much.
        self.window.add_action_entries([
            ('rotate', self.rotate_page_action, 'i'),
            ('delete', self.on_action_delete),
            ('duplicate', self.duplicate),
            ('page-format', self.page_format_dialog),
            ('crop-white-borders', self.crop_white_borders),
            ('export-selection', self.choose_export_selection_pdf_name, 'i'),
            ('export-all', self.on_action_export_all),
            ('reverse-order', self.reverse_order),
            ('save', self.on_action_save),
            ('save-as', self.on_action_save_as),
            ('new', self.on_action_new),
            ('import', self.on_action_add_doc_activate),
            ('zoom', self.zoom_change, 'i'),
            ('quit', self.on_quit),
            ('undo', self.undomanager.undo),
            ('redo', self.undomanager.redo),
            ('split', self.split_pages),
            ('metadata', self.edit_metadata),
            ('cut', self.on_action_cut),
            ('copy', self.on_action_copy),
            ('paste', self.on_action_paste, 'i'),
            ('select', self.on_action_select, 'i'),
            ('select-same-file', self.on_action_select, 'i'),
            ('select-same-format', self.on_action_select, 'i'),
            ('about', self.about_dialog),
            ("insert-blank-page", self.insert_blank_page),
        ])

        main_menu = self.uiXML.get_object("main_menu_button")
        self.window.add_action(Gio.PropertyAction.new("main-menu", main_menu, "active"))
        for a, k in self.config.get_accels():
            self.set_accels_for_action("win." + a, [k] if isinstance(k, str) else k)
        # Disable actions
        self.iv_selection_changed_event()
        self.window_focus_in_out_event()
        self.__update_num_pages(self.iconview.get_model())
        self.undomanager.set_actions(self.window.lookup_action('undo'),
                                     self.window.lookup_action('redo'))

    def insert_blank_page(self, _action, _option, _unknown):
        size = (21 / 2.54 * 72, 29.7 / 2.54 * 72) # A4 by default
        selection = self.iconview.get_selected_items()
        selection.sort()
        model = self.iconview.get_model()
        if len(selection) > 0:
            size = model[selection[-1]][0].size_in_points()
        page_size = croputils.BlankPageDialog(size, self.window).run_get()
        if page_size is not None:
            adder = PageAdder(self)
            if len(selection) > 0:
                adder.move(Gtk.TreeRowReference.new(model, selection[-1]), False)
            adder.addpages(exporter.create_blank_page(self.tmp_dir, page_size))
            adder.commit(select_added=False, add_to_undomanager=True)

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
                    f.add_mime_type(mime)
                    for extension in mimetypes.guess_all_extensions(mime):
                        f.add_pattern('*' + extension)
            filter_list.append(f_img)
        return filter_list

    def do_activate(self):
        """ https://lazka.github.io/pgi-docs/Gio-2.0/classes/Application.html#Gio.Application.do_activate """
        # TODO: huge method that should be splitted

        iconsdir = os.path.join(sharedir, 'icons')
        if not os.path.exists(iconsdir):
            iconsdir = os.path.join(sharedir, 'data', 'icons')
        Gtk.IconTheme.get_default().append_search_path(iconsdir)
        Gtk.Window.set_default_icon_name(ICON_ID)
        self.uiXML = self.__build_from_file(DOMAIN + '.ui')
        # Create the main window, and attach delete_event signal to terminating
        # the application
        self.window = self.uiXML.get_object('main_window')
        self.window.set_title(APPNAME)
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
        self.window.connect('button_release_event', self.window_button_release_event)
        self.window.connect('enter_notify_event', self.window_enter_notify_event)
        self.window.connect('window_state_event', self.window_state_event)

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
        self.id_selection_changed_event = self.iconview.connect('selection_changed',
                                                          self.iv_selection_changed_event)
        self.iconview.connect('key_press_event', self.iv_key_press_event)

        self.sw.add_with_viewport(self.iconview)

        self.model.connect('row-inserted', self.__update_num_pages)
        self.model.connect('row-deleted', self.__update_num_pages)
        self.model.connect('row-deleted', self.reset_export_file)

        # Progress bar
        self.progress_bar = self.uiXML.get_object('progressbar')

        # Status bar.
        self.status_bar = self.uiXML.get_object('statusbar')

        # Vertical scrollbar
        vscrollbar = self.sw.get_vscrollbar()
        vscrollbar.connect('value_changed', self.vscrollbar_value_changed)

        # Define window callback function and show window
        self.window.connect('check_resize', self.on_window_size_request)
        self.window.show_all()
        self.progress_bar.hide()

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

        # Set outline properties for iconview items i.e. cursor look
        style_provider = Gtk.CssProvider()
        css_data = """
        iconview {
            outline-color: alpha(currentColor, 0.8);
            outline-style: dashed;
            outline-offset: -2px;
            outline-width: 2px;
            -gtk-outline-radius: 2px;
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

    @staticmethod
    def set_cellrenderer_data(_column, cell, model, it, _data=None):
        cell.set_page(model.get_value(it, 0))

    def render(self):
        self.render_id = None
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

    def quit_rendering(self):
        """Quit rendering."""
        if self.rendering_thread:
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

    def model_lock(self):
        """Acquire model lock (before any add/delete/reorder)."""
        if self.rendering_thread:
            self.rendering_thread.model_lock.acquire()

    def model_unlock(self):
        """Release model lock."""
        if self.rendering_thread and self.rendering_thread.model_lock.locked():
            self.rendering_thread.model_lock.release()

    def vscrollbar_value_changed(self, _vscrollbar):
        """Render when vertical scrollbar value has changed."""
        self.silent_render()

    def window_configure_event(self, _window, event):
        """Handle window size and position changes."""
        if self.window_width_old not in [0, event.width] and len(self.model) > 0:
            if self.set_iv_visible_id:
                GObject.source_remove(self.set_iv_visible_id)
            self.set_iv_visible_id = GObject.timeout_add(1500, self.set_iconview_visible)
            self.iconview.set_visible(False)
        self.window_width_old = event.width
        if len(self.model) > 1: # Don't trigger extra render after first page is inserted
            self.silent_render()

    def window_button_release_event(self, _window, event):
        """Mouse button release on window."""
        if event.button == 1:
            self.set_iconview_visible(timeout=False)

    def window_enter_notify_event(self, _window, _event):
        """Mouse pointer enter window."""
        if os.name == 'nt':
            # In Windows this is triggered when dragging window edge. Instead the release event
            # is usually triggered when releasing button.
            return
        self.set_iconview_visible(timeout=False)

    def window_state_event(self, _window, _event):
        """Window state change."""
        GObject.timeout_add(100, self.set_iconview_visible)

    def set_iconview_visible(self, timeout=True):
        if timeout:
            self.set_iv_visible_id = None
        if not self.iconview.get_visible():
            self.update_iconview_geometry()
            self.scroll_to_selection()
            GObject.idle_add(self.iconview.set_visible, True)
            self.iconview.grab_focus()

    def set_export_file(self, file):
        if file != self.export_file:
            self.export_file = file
            self.set_unsaved(True)

    def set_unsaved(self, flag):
        self.is_unsaved = flag
        GObject.idle_add(self.retitle)

    def retitle(self):
        if self.export_file:
            title = self.export_file
            if self.is_unsaved:
                title += '*'
        else:
            title = _('untitled')

        all_files = self.active_file_names()
        if len(all_files) > 0:
            title += ' [' + ', '.join(sorted(all_files)) + ']'

        title += ' – ' + APPNAME
        self.window.set_title(title)
        return False

    def update_thumbnail(self, _obj, ref, thumbnail, resample, scale, is_preview):
        """Update thumbnail emitted from rendering thread."""
        if ref is None:
            # Rendering ended
            self.__update_statusbar(-1)
            malloc_trim()
            return
        path = ref.get_path()
        if path is None:
            # Page no longer exist
            return
        if (self.visible_range[0] <= path.get_indices()[0] <= self.visible_range[1] and
            resample != 1 / self.zoom_scale):
            # Thumbnail is in the visible range but is not rendered for current zoom level
            self.silent_render()
            return
        page = self.model[path][0]
        if page.scale != scale:
            # Page scale was changed while page was rendered -> trash & rerender
            self.silent_render()
            return
        page.thumbnail = thumbnail
        page.resample = resample
        page.zoom = self.zoom_scale
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
        self.__update_statusbar(path.get_indices()[0] + 1)

    def get_visible_range2(self):
        """Get range of items visible in window.

        A item is considered visible if more than 50% of item is visible.
        """
        sw_vadj = self.sw.get_vadjustment()
        sw_vpos = sw_vadj.get_value()
        columns_nr = max(self.iconview.get_columns(), 1)
        sw_height = self.sw.get_allocated_height()
        range_start = range_end = -1
        item_nr = 0
        while item_nr < len(self.model):
            path = Gtk.TreePath.new_from_indices([item_nr])
            cell_rect = self.iconview.get_cell_rect(path)[1]
            item_center = cell_rect.y + cell_rect.height / 2
            if range_start < 0 and item_center > sw_vpos - self.vp_css_margin:
                range_start = item_nr
            if item_center < sw_vpos + sw_height - self.vp_css_margin:
                range_end = item_nr + columns_nr - 1
            else:
                break
            item_nr += columns_nr
        if range_start < 0 and len(self.model) > 0:
            range_start = len(self.model) - 1
        return range_start, min(max(range_end, range_start), len(self.model) - 1)

    def on_window_size_request(self, _window):
        """Main Window resize."""
        if self.iconview.get_visible():
            self.update_iconview_geometry()

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
            if self.zoom_full_page:
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
            if self.vp_css_margin != 6 - margin:
                # remove margin on top and bottom
                self.vp_css_margin = 6 - margin
                css_data = 'window viewport {\
                margin-top:' + str(self.vp_css_margin) + 'px;\
                margin-bottom:' + str(self.vp_css_margin) + 'px;}'
                style_provider = Gtk.CssProvider()
                style_provider.load_from_data(bytes(css_data.encode()))
                Gtk.StyleContext.add_provider_for_screen(
                    Gdk.Screen.get_default(),
                    style_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def update_geometry(self, treeiter):
        """Recomputes the width and height of the rotated page and saves
           the result in the ListStore"""

        if not self.model.iter_is_valid(treeiter):
            return

        p = self.model.get(treeiter, 0)[0]
        page = self.pdfqueue[p.nfile - 1].document.get_page(p.npage - 1)
        p.set_size(page.get_size())
        self.model.set(treeiter, 0, p)

    def on_quit(self, _action, _param=None, _unknown=None):
        if self.is_unsaved:
            if self.export_file:
                msg = _('Save changes to “{}” before closing?').format(os.path.basename(self.export_file))
            else:
                msg = _('Save changes before closing?')
            d = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.NONE, msg)
            d.format_secondary_markup(_("Your changes will be lost if you don’t save them."))
            d.add_buttons(_('Do_n’t Save'), 1, _('_Cancel'), 2, _('_Save'), 3)
            response = d.run()
            d.destroy()

            if response == 2:
                # Returning True to stop self.window delete_event propagation.
                return True
            elif response == 3:
                # Save.
                self.save_or_choose()
                # Quit only if it has been really saved.
                if self.is_unsaved:
                    return True

        self.close_application()

    def close_application(self, _widget=None, _event=None, _data=None):
        """Termination"""
        if self.rendering_thread:
            self.rendering_thread.quit = True
            self.rendering_thread.join()
            self.rendering_thread.pdfqueue = []

        # Prevent gtk errors when closing with everything selected
        self.iconview.unselect_all()
        self.iconview.get_model().clear()

        # Release Poppler.Document instances to unlock all temporay files
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

    def choose_export_pdf_name(self, mode):
        """Handles choosing a name for exporting """

        chooser = Gtk.FileChooserNative.new(title=_('Export…'),
                                            parent=self.window,
                                            action=Gtk.FileChooserAction.SAVE
                                            )
        chooser.set_do_overwrite_confirmation(True)
        if len(self.pdfqueue) > 0:
            f = self.pdfqueue[0].filename
            # could be an image thanks to img2pdf
            if f.endswith(".pdf"):
                chooser.set_filename(f)
        chooser.set_current_folder(self.export_directory)
        filter_list = self.__create_filters(['pdf', 'all'])
        for f in filter_list[1:]:
            chooser.add_filter(f)

        response = chooser.run()
        file_out = chooser.get_filename()
        chooser.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            try:
                self.save(mode, file_out)
            except Exception as e:
                traceback.print_exc()
                self.error_message_dialog(e)

    def active_file_names(self):
        """Returns the file names currently associated with pages in the model."""
        r = set(row[1].split('\n')[0] for row in self.model)
        r.discard("")
        return r

    def on_action_new(self, _action, _param, _unknown):
        """Start a new instance."""
        if os.name == 'nt':
            if sys.executable.find('python3.exe') == -1:
                subprocess.Popen(sys.executable)
            else:
                subprocess.Popen([sys.executable, '-mpdfarranger'])
        else:
            display = Gdk.Display.get_default()
            launch_context = display.get_app_launch_context()
            desktop_file = "%s.desktop"%(self.get_application_id())
            try:
                app_info = Gio.DesktopAppInfo.new(desktop_file)
                app_info.launch([], launch_context)
            except TypeError:
                subprocess.Popen([sys.executable, '-mpdfarranger'])

    def on_action_save(self, _action, _param, _unknown):
        self.save_or_choose()

    def save_or_choose(self):
        """Saves to the previously exported file or shows the export dialog if
        there was none."""
        savemode = GLib.Variant('i', 0) # Save all pages in a single document.
        try:
            if self.export_file:
                self.save(savemode, self.export_file)
            else:
                self.choose_export_pdf_name(savemode)
        except Exception as e:
            self.error_message_dialog(e)

    def on_action_save_as(self, _action, _param, _unknown):
        self.choose_export_pdf_name(GLib.Variant('i', 0))

    @warn_dialog
    def save(self, mode, file_out):
        """Saves to the specified file.  May throw exceptions."""
        (path, shortname) = os.path.split(file_out)
        (shortname, ext) = os.path.splitext(shortname)
        if ext.lower() != '.pdf':
            file_out = file_out + '.pdf'

        exportmodes = {0: 'ALL_TO_SINGLE',
                       1: 'ALL_TO_MULTIPLE',
                       2: 'SELECTED_TO_SINGLE',
                       3: 'SELECTED_TO_MULTIPLE'}
        exportmode = exportmodes[mode.get_int32()]

        if exportmode in ['SELECTED_TO_SINGLE', 'SELECTED_TO_MULTIPLE']:
            selection = self.iconview.get_selected_items()
            to_export = [row[0] for row in self.model if row.path in selection]
        else:
            self.export_directory = path
            self.set_export_file(file_out)
            to_export = [row[0] for row in self.model]

        m = metadata.merge(self.metadata, self.pdfqueue)
        if self.config.content_loss_warning():
            res, enabled = exporter.check_content(self.window, self.pdfqueue)
            self.config.set_content_loss_warning(enabled)
            if res == Gtk.ResponseType.CANCEL:
                return # Abort
        exporter.export(self.pdfqueue, to_export, file_out, mode, m)

        if exportmode == 'ALL_TO_SINGLE':
            self.set_unsaved(False)

    def choose_export_selection_pdf_name(self, _action, mode, _unknown):
        self.choose_export_pdf_name(mode)

    def on_action_export_all(self, _action, _param, _unknown):
        self.choose_export_pdf_name(GLib.Variant('i', 1))

    def on_action_add_doc_activate(self, _action, _param, _unknown):
        """Import doc"""
        chooser = Gtk.FileChooserNative.new(title=_('Import…'),
                                            parent=self.window,
                                            action=Gtk.FileChooserAction.OPEN,
                                            )
        chooser.set_current_folder(self.import_directory)
        chooser.set_select_multiple(True)
        file_type_list = ['all', 'pdf']
        if len(img2pdf_supported_img) > 0:
            file_type_list = ['all', 'img2pdf', 'pdf']
        filter_list = self.__create_filters(file_type_list)
        for f in filter_list:
            chooser.add_filter(f)

        response = chooser.run()
        if response == Gtk.ResponseType.ACCEPT:
            adder = PageAdder(self)
            for filename in chooser.get_filenames():
                adder.addpages(filename)
            adder.commit(select_added=False, add_to_undomanager=True)
        chooser.destroy()

    def clear_selected(self):
        """Removes the selected elements in the IconView"""
        self.undomanager.commit("Delete")
        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()
        selection.sort(reverse=True)
        self.set_unsaved(True)
        self.model_lock()
        for path in selection:
            model.remove(model.get_iter(path))
        self.model_unlock()
        path = selection[-1]
        self.iconview.select_path(path)
        if not self.iconview.path_is_selected(path):
            if len(model) > 0:  # select the last row
                row = model[-1]
                path = row.path
                self.iconview.select_path(path)
        self.iconview.grab_focus()
        self.silent_render()
        malloc_trim()

    def copy_pages(self):
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

        return data

    @staticmethod
    def data_to_pageadder(data, pageadder):
        """Data to pageadder."""
        tmp = data.pop(0).split('\n')
        filename = tmp[0]
        npage = int(tmp[1])
        if len(tmp) < 3:  # Only when paste files interleaved
            pageadder.addpages(filename, npage)
        else:
            basename = tmp[2]
            angle = int(tmp[3])
            scale = float(tmp[4])
            crop = [float(side) for side in tmp[5:9]]
            pageadder.addpages(filename, npage, basename, angle, scale, crop)

    def is_data_valid(self, data):
        """Validate data to be pasted from clipboard. Only used in Windows."""
        data_copy = data.copy()
        data_valid = True
        while data_copy:
            try:
                tmp = data_copy.pop(0).split('\n')
                copyname = tmp[0]
                npage = int(tmp[1])
                # basename = tmp[2] but is not validated here
                angle = int(tmp[3])
                scale = float(tmp[4])
                crop = [float(side) for side in tmp[5:9]]
                if not (os.path.isfile(copyname) and
                        npage > 0 and
                        angle in [0, 90, 180, 270] and
                        0 < scale <= 200.0 and
                        all((cr >= 0.0 and cr <= 0.99) for cr in crop) and
                        (crop[0] + crop[1] <= 0.99) and
                        (crop[2] + crop[3] <= 0.99) and
                        len(tmp) == 9):
                    data_valid = False
                    break
            except (ValueError, IndexError):
                data_valid = False
                break
        if not data_valid:
            message = _('Pasted data not valid. Aborting paste.')
            self.error_message_dialog(message)
        return data_valid

    def paste_pages(self, data, before, ref_to, select_added):
        """Paste pages to iconview"""

        pageadder = PageAdder(self)
        if ref_to:
            pageadder.move(ref_to, before)
        if not before and ref_to:
            data.reverse()

        while data:
            self.data_to_pageadder(data, pageadder)
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
        iter_to = None

        self.undomanager.commit("Paste")
        self.set_unsaved(True)

        while data:
            self.data_to_pageadder(data, pageadder)

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

    def on_action_delete(self, _action, _parameter, _unknown):
        """Removes the selected elements in the IconView"""

        self.clear_selected()

    def on_action_cut(self, _action, _param, _unknown):
        """Cut selected pages to clipboard."""
        data = self.copy_pages()
        if os.name == 'posix':
            self.clipboard_pdfarranger.set_text(data, -1)
            self.clipboard_default.set_text('', -1)
        if os.name == 'nt':
            self.clipboard_default.set_text('pdfarranger-clipboard\n' + data, -1)

        self.clear_selected()
        self.window.lookup_action("paste").set_enabled(True)

    def on_action_copy(self, _action, _param, _unknown):
        """Copy selected pages to clipboard."""
        data = self.copy_pages()
        if os.name == 'posix':
            self.clipboard_pdfarranger.set_text(data, -1)
            self.clipboard_default.set_text('', -1)
        if os.name == 'nt':
            self.clipboard_default.set_text('pdfarranger-clipboard\n' + data, -1)
        self.window.lookup_action("paste").set_enabled(True)

    def on_action_paste(self, _action, mode, _unknown):
        """Paste pages or files from clipboard."""
        data, data_is_filepaths = self.read_from_clipboard()
        if not data:
            return

        pastemodes = {0: 'AFTER', 1: 'BEFORE', 2: 'ODD', 3: 'EVEN'}
        pastemode = pastemodes[mode.get_int32()]

        ref_to, before = self.set_paste_location(pastemode, data_is_filepaths)

        if pastemode in ['AFTER', 'BEFORE']:
            if data_is_filepaths:
                self.paste_files(data, before, ref_to)
            else:
                self.paste_pages(data, before, ref_to, select_added=False)
            if pastemode == 'BEFORE':
                self.__update_statusbar()
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
                                filepaths.append('\n'.join([filepath, str(page)]))
                        elif filemime.split('/')[0] == 'image':
                            filepaths.append('\n'.join([filepath, str(1)]))
                        else:
                            raise PDFDocError(filepath + ':\n' + _('File is neither pdf nor image'))
                except PDFDocError as e:
                    print(e.message, file=sys.stderr)
                    self.error_message_dialog(e.message)
                    return
                data = filepaths
            self.paste_pages_interleave(data, before, ref_to)
            GObject.idle_add(self.retitle)
            self.iv_selection_changed_event()
            self.zoom_set(self.zoom_level)
            self.silent_render()

    def read_from_clipboard(self):
        """Read data from clipboards. Check if data is copied pages or files."""
        # In Linux, if default clipboard holds path to pdf or image files,
        # these files will be pasted with precedence over copied pages.
        # In Windows default clipboard is used for both copied pages and copied files.
        # If id "pdfarranger-clipboard" is found pages is expected to be in clipboard, else files.
        data = self.clipboard_default.wait_for_text()
        if not data:
            data = ''

        data_is_filepaths = False
        if os.name == 'posix' and not data:
            data = self.clipboard_pdfarranger.wait_for_text()
            if data:
                data = data.split('\n;\n')
        elif os.name == 'nt' and data.startswith('pdfarranger-clipboard\n'):
            data = data.replace('pdfarranger-clipboard\n', '', 1)
            data = data.split('\n;\n')
            if not self.is_data_valid(data):
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
            data = self.copy_pages()
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
            self.model_lock()
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
            self.model_unlock()
            GObject.idle_add(self.render)

        elif target == 'MODEL_ROW_EXTERN':
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
        self.model_lock()
        for ref_del in ref_del_list:
            path = ref_del.get_path()
            model.remove(model.get_iter(path))
        self.model_unlock()
        GObject.idle_add(self.render)
        malloc_trim()

    def iv_dnd_motion(self, iconview, context, x, y, etime):
        """Handles drag motion: autoscroll, select move or copy, select drag cursor location."""
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
            return True
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
            return True
        elif not path or (path == model[-1].path and x_s < x):
            self.drag_path = model[-1].path
            self.drag_pos = Gtk.IconViewDropPosition.DROP_RIGHT
        else:
            iconview.stop_emission('drag_motion')
            return False
        iconview.set_drag_dest_item(self.drag_path, self.drag_pos)
        return True

    def iv_autoscroll(self, x, y, autoscroll_area):
        """Iconview auto-scrolling."""
        sw_vadj = self.sw.get_vadjustment()
        sw_height = self.sw.get_allocation().height
        if y - sw_vadj.get_value() < autoscroll_area - self.vp_css_margin:
            if not self.iv_auto_scroll_timer:
                self.iv_auto_scroll_direction = Gtk.DirectionType.UP
                self.iv_auto_scroll_timer = GObject.timeout_add(150,
                                                                self.iv_auto_scroll)
        elif y - sw_vadj.get_value() > sw_height - autoscroll_area - self.vp_css_margin:
            if not self.iv_auto_scroll_timer:
                self.iv_auto_scroll_direction = Gtk.DirectionType.DOWN
                self.iv_auto_scroll_timer = GObject.timeout_add(150,
                                                                self.iv_auto_scroll)
        elif self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_dnd_leave_end(self, _widget, _context, _ignored=None):
        """Ends the auto-scroll during DND"""

        if self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_auto_scroll(self):
        """Timeout routine for auto-scroll"""

        sw_vadj = self.sw.get_vadjustment()
        sw_vpos = sw_vadj.get_value()
        if self.iv_auto_scroll_direction == Gtk.DirectionType.UP:
            sw_vpos -= sw_vadj.get_step_increment()
            sw_vadj.set_value(max(sw_vpos, sw_vadj.get_lower()))
        elif self.iv_auto_scroll_direction == Gtk.DirectionType.DOWN:
            sw_vpos += sw_vadj.get_step_increment()
            sw_vadj.set_value(min(sw_vpos, sw_vadj.get_upper() - sw_vadj.get_page_size()))
        return True  # call me again

    def iv_motion(self, iconview, event):
        """Manages mouse movement on the iconview."""
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
        if event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.iv_autoscroll(event.x, event.y, autoscroll_area=4)
            if not self.click_path:
                with GObject.signal_handler_block(iconview, self.id_selection_changed_event):
                    selection_changed = self.iv_drag_select.motion(event)
                if selection_changed:
                    self.iv_selection_changed_event()
                return True  # Don't use iconview's built-in rubberband-selecting

    def iv_button_release_event(self, iconview, event):
        """Manages mouse releases on the iconview"""
        self.iv_drag_select.set_mouse_cursor('default')

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
            iconview.set_cursor(path, None, False)  # for consistent shift+click selection
        self.pressed_button = None

        # Stop drag-select autoscrolling when button is released
        if self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_button_press_event(self, iconview, event):
        """Manages mouse clicks on the iconview"""
        # Toggle full page zoom / set zoom level on double-click
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
            self.pressed_button = None
            if self.zoom_full_page:
                self.zoom_set(self.zoom_level_old)
            else:
                self.zoom_level_old = self.zoom_level
                self.zoom_to_full_page()
                self.update_iconview_geometry()
                self.scroll_to_selection()
            return True

        click_path_old = self.click_path
        self.click_path = iconview.get_path_at_pos(event.x, event.y)

        # Go into drag-select mode if clicked between items
        if event.button == 1 and not self.click_path:
            self.iv_drag_select.click(event)
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                return 1

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
            return 1

        # Forget where cursor was when shift was pressed
        if event.button == 1 and not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.iv_cursor.sel_start_page = None

        # Do not deselect when clicking an already selected item for drag and drop
        if event.button == 1:
            selection = iconview.get_selected_items()
            if self.click_path and self.click_path in selection:
                self.pressed_button = event
                return 1  # prevent propagation i.e. (de-)selection

        # Display right click menu
        if event.button == 3:
            if self.click_path:
                selection = iconview.get_selected_items()
                if self.click_path not in selection:
                    iconview.unselect_all()
                    iconview.select_path(self.click_path)
            else:
                iconview.unselect_all()
            iconview.grab_focus()
            self.popup.popup(None, None, None, None, event.button, event.time)
            return 1

    def iv_key_press_event(self, iconview, event):
        """Manages keyboard press events on the iconview."""
        # Toggle full page zoom / set zoom level on key f
        if event.keyval == Gdk.KEY_f:
            if self.zoom_full_page:
                self.zoom_set(self.zoom_level_old)
            else:
                self.zoom_level_old = self.zoom_level
                self.zoom_to_full_page()
                self.update_iconview_geometry()
                self.scroll_to_selection()

        elif event.keyval in [Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right,
                            Gdk.KEY_Home, Gdk.KEY_End]:
            # Move cursor, select pages and scroll with navigation keys
            with GObject.signal_handler_block(iconview, self.id_selection_changed_event):
                self.iv_cursor.handler(iconview, event)
            self.iv_selection_changed_event(None, move_cursor_event=True)

        elif event.keyval in [Gdk.KEY_Page_Up, Gdk.KEY_Page_Down,
                              Gdk.KEY_KP_Page_Up, Gdk.KEY_KP_Page_Down]:
            # Scroll to next/previous page row
            model = self.iconview.get_model()
            sw_vadj = self.sw.get_vadjustment()
            sw_vpos = sw_vadj.get_value()
            columns_nr = self.iconview.get_columns()
            path_last_page = Gtk.TreePath.new_from_indices([len(model) - 1])
            last_cell_y = iconview.get_cell_rect(path_last_page)[1].y
            sw_vpos_up = sw_vpos_down = page_nr = 0
            extra = 0 if event.keyval in [Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up] else 1
            while sw_vpos_down < sw_vpos + extra:
                path = Gtk.TreePath.new_from_indices([page_nr])
                sw_vpos_up = sw_vpos_down
                sw_vpos_down += iconview.get_cell_rect(path)[1].height + iconview.get_row_spacing()
                page_nr += columns_nr
            if event.keyval in [Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up]:
                sw_vadj.set_value(min(sw_vpos_up, last_cell_y + self.vp_css_margin - 6))
            else:
                sw_vadj.set_value(min(sw_vpos_down, last_cell_y + self.vp_css_margin - 6))
        return True  # Prevent propagation

    def iv_selection_changed_event(self, _iconview=None, move_cursor_event=False):
        selection = self.iconview.get_selected_items()
        ne = len(selection) > 0
        for a, e in [
            ("reverse-order", self.reverse_order_available(selection)),
            ("delete", ne),
            ("duplicate", ne),
            ("page-format", ne),
            ("rotate", ne),
            ("export-selection", ne),
            ("cut", ne),
            ("copy", ne),
            ("split", ne),
            ("select-same-file", ne),
            ("select-same-format", ne),
            ("crop-white-borders", ne),
        ]:
            self.window.lookup_action(a).set_enabled(e)
        self.__update_statusbar()
        if selection and not move_cursor_event:
            self.iv_cursor.cursor_is_visible = False

    def window_focus_in_out_event(self, _widget=None, _event=None):
        """Keyboard focus enter or leave window."""
        self.set_iconview_visible(timeout=False)
        # Enable or disable paste actions based on clipboard content
        cb_d_data = self.clipboard_default.wait_for_text()
        cb_p_data = os.name == 'posix' and self.clipboard_pdfarranger.wait_for_text()
        data_available = True if cb_d_data or cb_p_data else False
        if self.window.lookup_action("paste"):  # Prevent error when closing with Alt+F4
            self.window.lookup_action("paste").set_enabled(data_available)

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

    def sw_button_press_event(self, _scrolledwindow, event):
        """Unselects all items in iconview on mouse click in scrolledwindow"""
        # TODO most likely unreachable code

        if event.button == 1:
            self.iconview.unselect_all()

    def sw_scroll_event(self, _scrolledwindow, event):
        """Manages mouse scroll events in scrolledwindow"""
        if event.get_state() & Gdk.ModifierType.CONTROL_MASK:
            zoom_delta = 0
            if event.direction == Gdk.ScrollDirection.SMOOTH:
                dy = event.get_scroll_deltas()[2]
                if dy > 0:
                    zoom_delta = -1
                elif dy < 0:
                    zoom_delta = 1
            elif event.direction == Gdk.ScrollDirection.UP:
                zoom_delta = 1
            elif event.direction == Gdk.ScrollDirection.DOWN:
                zoom_delta = -1

            if zoom_delta != 0:
                self.zoom_set(self.zoom_level + zoom_delta)
                return 1

    def zoom_set(self, level):
        """Sets the zoom level"""
        level = min(max(level, -10), 40)
        zoom_level_old = self.zoom_level
        self.zoom_level = level
        self.zoom_scale = 0.2 * (1.1 ** level)
        # Limit max zoom level so that thumbnail is max 23Mb
        if len(self.model) > 0:
            max_limit = 6000000  # 6000000 pixels * 4 byte/pixel -> 23Mb
            max_page_size = max(p.size[0] * p.size[1] * p.scale ** 2 for p, _ in self.model)
            max_page_size_zoomed = max_page_size * self.zoom_scale ** 2
            if max_page_size_zoomed > max_limit:
                max_zoom_scale = (max_limit / max_page_size) ** .5
                self.zoom_level = -10
                while max_zoom_scale > 0.2 * (1.1 ** (self.zoom_level + 1)):
                    self.zoom_level += 1
                self.zoom_scale = 0.2 * (1.1 ** self.zoom_level)
        if self.zoom_level == zoom_level_old:
            return
        if self.id_scroll_to_sel:
            GObject.source_remove(self.id_scroll_to_sel)
        self.zoom_full_page = False
        self.quit_rendering()  # For performance reasons
        for row in self.model:
            row[0].zoom = self.zoom_scale
        if len(self.model) > 0:
            self.update_iconview_geometry()
            self.model[0][0] = self.model[0][0]  # Let iconview refresh itself
            self.id_scroll_to_sel = GObject.timeout_add(400, self.scroll_to_selection)
            self.silent_render()

    def zoom_change(self, _action, step, _unknown):
        """ Action handle for zoom change """
        self.zoom_set(self.zoom_level + step.get_int32())

    def get_full_sw_height(self):
        """Get scrolledwindow height as it will be when progressbar is hidden."""
        box = self.sw.get_parent()
        sw_height = box.get_allocated_height()
        sw_height -= self.status_bar.get_allocated_height()
        sw_height -= self.status_bar.get_margin_top()
        sw_height -= self.status_bar.get_margin_bottom()
        sw_height -= box.get_children()[2].get_allocated_height()  # separator
        return sw_height

    def zoom_to_full_page(self):
        """Zoom selected thumbnail to full page."""
        selection = self.iconview.get_selected_items()
        if len(selection) != 1:
            return

        item_padding = self.iconview.get_item_padding()
        cell_image_renderer, cell_text_renderer = self.iconview.get_cells()
        image_padding = cell_image_renderer.get_padding()
        text_rect = self.iconview.get_cell_rect(selection[-1], cell_text_renderer)[1]
        text_rect_height = text_rect.height  # cell_text_renderer padding is included here
        border_and_shadow = 7  # 2*th1+th2 set in iconview.py
        cell_extraX = 2 * (item_padding + image_padding[0]) + border_and_shadow
        cell_extraY = 2 * (item_padding + image_padding[1]) + text_rect_height + border_and_shadow

        sw_width = self.sw.get_allocated_width()
        sw_height = self.get_full_sw_height()
        page_width = max(p.width_in_points() for p, _ in self.model)
        page_height = max(p.height_in_points() for p, _ in self.model)
        margins = 12  # leave 6 pixel at top and 6 pixel at bottom
        zoom_scaleX_new = (sw_width - cell_extraX - margins) / page_width
        zoom_scaleY_new = (sw_height - cell_extraY - margins) / page_height
        self.zoom_scale = min(zoom_scaleY_new, zoom_scaleX_new)
        if self.zoom_scale < 0.2 * (1.1 ** -10):
            return
        self.quit_rendering()  # For performance reasons
        for page, _ in self.model:
            page.zoom = self.zoom_scale

        # Set zoom level to nearest possible so zoom in/out works right
        self.zoom_level = -10
        while self.zoom_scale > 0.2 * (1.1 ** self.zoom_level):
            self.zoom_level += 1
        self.zoom_full_page = True

    def scroll_to_selection(self):
        """Scroll iconview so that selection is in center of window."""
        self.id_scroll_to_sel = None
        GObject.timeout_add(50, self._scroll_to_selection)

    def _scroll_to_selection(self):
        selection = self.iconview.get_selected_items()
        if not selection:
            return
        selection.sort(key=lambda x: x.get_indices()[0])
        if self.zoom_full_page:
            cell_image_renderer = self.iconview.get_cells()[0]
            cell_rect = self.iconview.get_cell_rect(selection[-1], cell_image_renderer)
            thmb_width, thmb_height = self.cellthmb.get_fixed_size()
            if cell_rect[1].width != thmb_width or cell_rect[1].height != thmb_height:
                # thmb_width and thmb_height is the wanted size. If cell_rect size is not
                # yet equal, give it some time and then try again.
                return True
        sw_vadj = self.sw.get_vadjustment()
        first_cell_y = self.iconview.get_cell_rect(selection[0])[1].y
        last_cell_y = self.iconview.get_cell_rect(selection[-1])[1].y
        last_cell_height = self.iconview.get_cell_rect(selection[-1])[1].height
        selection_center = (last_cell_y + last_cell_height - first_cell_y) / 2 + 0.5
        sw_height = self.get_full_sw_height()
        new_value = first_cell_y + selection_center + self.vp_css_margin - sw_height / 2
        if new_value > sw_vadj.get_upper():
            # Scrollable not yet ready. Call function again.
            return True
        sw_vadj.set_value(new_value)
        self.silent_render()

    def rotate_page_action(self, _action, angle, _unknown):
        """Rotates the selected page in the IconView"""
        self.undomanager.commit("Rotate")
        angle = angle.get_int32()
        selection = self.iconview.get_selected_items()
        if self.rotate_page(selection, angle):
            self.set_unsaved(True)

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
            self.update_geometry(treeiter)
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
        self.model_lock()
        for ref in ref_list:
            iterator = model.get_iter(ref.get_path())
            page = model.get_value(iterator, 0)
            newpages = page.split(leftcrops, topcrops)
            for p in newpages:
                model.insert_after(iterator, [p, p.description()])
            model.set_value(iterator, 0, page)
        self.model_unlock()
        self.iv_selection_changed_event()

    def edit_metadata(self, _action, _parameter, _unknown):
        if metadata.edit(self.metadata, self.pdfqueue, self.window):
            self.set_unsaved(True)

    def page_format_dialog(self, _action, _parameter, _unknown):
        """Opens a dialog box to define margins for page cropping and page size"""
        selection = self.iconview.get_selected_items()
        diag = croputils.Dialog(self.iconview.get_model(), selection, self.window)
        crop, newscale = diag.run_get()
        if crop is not None or newscale is not None:
            self.model_lock()
            self.undomanager.commit("Format")
        if crop is not None:
            if self.crop(selection, crop):
                self.set_unsaved(True)
        if newscale is not None:
            if croputils.scale(self.model, selection, newscale):
                self.set_unsaved(True)
        self.model_unlock()
        self.zoom_set(self.zoom_level)
        GObject.idle_add(self.render)

    def crop_white_borders(self, _action, _parameter, _unknown):
        selection = self.iconview.get_selected_items()
        crop = croputils.white_borders(self.iconview.get_model(), selection, self.pdfqueue)
        self.undomanager.commit("Crop white Borders")
        if self.crop(selection, crop):
            self.set_unsaved(True)
        GObject.idle_add(self.render)

    def crop(self, selection, newcrop):
        changed = False
        model = self.iconview.get_model()
        for id_sel, path in enumerate(selection):
            pos = model.get_iter(path)
            page = model.get_value(pos, 0)
            if page.crop != list(newcrop[id_sel]):
                page.crop = list(newcrop[id_sel])
                changed = True
            model.set_value(pos, 0, page)
            self.update_geometry(pos)
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
        self.model_lock()
        for ref in ref_list:
            iterator = model.get_iter(ref.get_path())
            page = model.get_value(iterator, 0).duplicate()
            model.insert_after(iterator, [page, page.description()])
        self.model_unlock()
        self.iv_selection_changed_event()


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
        self.model_lock()
        model.reorder(new_order)
        self.model_unlock()
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
        about_dialog.set_comments(''.join((_(
            '%s is a tool for rearranging and modifying PDF files. '
            'Developed using GTK+ and Python') % APPNAME,
            '\n \n',
            _('(%s uses libqpdf %s and pikepdf %s)') % (APPNAME, qpdf, pike))))
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

    def reset_export_file(self, model, _path, _itr=None, _user_data=None):
        if len(model) == 0:
            self.set_export_file(None)
            self.set_unsaved(False)

    def __update_num_pages(self, model, _path=None, _itr=None, _user_data=None):
        num_pages = len(model)
        self.uiXML.get_object("num_pages").set_text(str(num_pages))
        for a in ["save", "save-as", "select", "export-all"]:
            self.window.lookup_action(a).set_enabled(num_pages > 0)

    def __update_statusbar(self, num=None):
        if num is None:
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
            self.status_bar.push(ctxt_id, _('Selected pages: ') + ', '.join(display))
            if self.sb_timeout_id:
                GObject.source_remove(self.sb_timeout_id)
            self.sb_timeout_id = GObject.timeout_add(600, self.sb_timeout)
        elif not self.sb_timeout_id:
            ctxt_id = self.status_bar.get_context_id("updated_num")
            if num >= 0:
                self.status_bar.push(ctxt_id, 'Updating thumbnail: ' + str(num))
            else:
                self.status_bar.remove_all(ctxt_id)

    def sb_timeout(self):
        self.sb_timeout_id = None

    def error_message_dialog(self, msg, msg_type=Gtk.MessageType.ERROR):
        error_msg_dlg = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
                                          type=msg_type, parent=self.window,
                                          message_format=str(msg),
                                          buttons=Gtk.ButtonsType.OK)
        response = error_msg_dlg.run()
        if response == Gtk.ResponseType.OK:
            error_msg_dlg.destroy()


def main():
    PdfArranger().run(sys.argv)
