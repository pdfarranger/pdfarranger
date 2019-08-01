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
import threading
import tempfile
import signal
import pathlib
import pkg_resources
import platform
import configparser
import warnings
import traceback
from urllib.request import url2pathname

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

import locale  # for multilanguage support
import gettext

locale.setlocale(locale.LC_ALL, '')
DOMAIN = 'pdfarranger'
if os.name == 'nt':
    from ctypes import cdll

    libintl = cdll['libintl-8']
    libintl.bindtextdomain(DOMAIN.encode(), localedir.encode(sys.getfilesystemencoding()))
    libintl.bind_textdomain_codeset(DOMAIN.encode(), 'UTF-8'.encode())
    del libintl
else:
    locale.bindtextdomain(DOMAIN, localedir)
    try:
        locale.bind_textdomain_codeset(DOMAIN, 'UTF-8')
    except AttributeError:
        pass

APPNAME = 'PDF Arranger'
VERSION = '1.3.0'
WEBSITE = 'https://github.com/jeromerobert/pdfarranger'
LICENSE = 'GNU General Public License (GPL) Version 3.'

import gi

# check that we don't need GObject.threads_init()
gi.check_version('3.10.2')
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

if Gtk.check_version(3, 4, 0):
    raise Exception('You do not have the required version of GTK+ installed. ' +
                    'Installed GTK+ version is ' +
                    '.'.join([str(Gtk.get_major_version()),
                              str(Gtk.get_minor_version()),
                              str(Gtk.get_micro_version())]) +
                    '. Required GTK+ version is 3.4 or higher.')

from gi.repository import Gdk
from gi.repository import GObject  # for using custom signals
from gi.repository import Gio  # for inquiring mime types information
from gi.repository import GLib
from gi.repository import Pango

gi.require_version('Poppler', '0.18')
from gi.repository import Poppler  # for the rendering of pdf pages
import cairo

from .iconview import CellRendererImage

GObject.type_register(CellRendererImage)
from . import undo
from . import exporter

if os.name == 'nt' and GLib.get_language_names():
    os.environ['LANG'] = GLib.get_language_names()[0]
gettext.bindtextdomain(DOMAIN, localedir)
gettext.textdomain(DOMAIN)
_ = gettext.gettext


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


class Config(object):
    """ Wrap a ConfigParser object for PDFArranger """

    @staticmethod
    def _config_file():
        """ Return the location of the configuration file """
        home = os.path.expanduser("~")
        if platform.system() == 'Darwin':
            p = os.path.join(home, 'Library', 'Caches')
        elif 'LOCALAPPDATA' in os.environ:
            p = os.getenv('LOCALAPPDATA')
        elif 'XDG_CACHE_HOME' in os.environ:
            p = os.getenv('XDG_CACHE_HOME')
        else:
            p = os.path.join(home, '.cache')
        p = os.path.join(p, DOMAIN)
        os.makedirs(p, exist_ok=True)
        return os.path.join(p, 'config.ini')

    def __init__(self):
        self.data = configparser.ConfigParser()
        self.data.add_section('window')
        self.data.read(Config._config_file())

    def window_size(self):
        ds = Gdk.Screen.get_default()
        return self.data.getint('window', 'width', fallback=int(min(700, ds.get_width() / 2))), \
               self.data.getint('window', 'height', fallback=int(min(600, ds.get_height() - 50)))

    def set_window_size(self, size):
        self.data.set('window', 'width', str(size[0]))
        self.data.set('window', 'height', str(size[1]))

    def maximized(self):
        return self.data.getboolean('window', 'maximized', fallback=False)

    def set_maximized(self, m):
        self.data.set('window', 'maximized', str(m))

    def zoom_level(self):
        return self.data.getint('DEFAULT', 'zoom-level', fallback=0)

    def set_zoom_level(self, l):
        self.data.set('DEFAULT', 'zoom-level', str(l))

    def save(self):
        conffile = Config._config_file()
        os.makedirs(os.path.dirname(conffile), exist_ok=True)
        with open(conffile, 'w') as f:
            self.data.write(f)


def warn_dialog(func):
    """ Decorator which redirect warnings module messages to a gkt MessageDialog """

    class ShowWarning(object):
        def __init__(self):
            self.buffer = ""

        def __call__(self, message, category, filename, lineno, f=None, line=None):
            s = warnings.formatwarning(message, category, filename, lineno, line)
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


class PdfArranger(Gtk.Application):
    # Drag and drop ID for pages coming from the same pdfarranger instance
    MODEL_ROW_INTERN = 1001
    # Drag and drop ID for pages coming from an other pdfarranger instance
    MODEL_ROW_EXTERN = 1002
    # Drag and drop ID for pages coming from a non-pdfarranger application
    TEXT_URI_LIST = 1003
    TARGETS_IV = [Gtk.TargetEntry.new('MODEL_ROW_INTERN', Gtk.TargetFlags.SAME_WIDGET, MODEL_ROW_INTERN),
                  Gtk.TargetEntry.new('MODEL_ROW_EXTERN', Gtk.TargetFlags.OTHER_APP, MODEL_ROW_EXTERN)]
    TARGETS_SW = [Gtk.TargetEntry.new('text/uri-list', 0, TEXT_URI_LIST),
                  Gtk.TargetEntry.new('MODEL_ROW_EXTERN', Gtk.TargetFlags.OTHER_APP, MODEL_ROW_EXTERN)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id="com.github.jeromerobert.pdfarranger",
                         flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE,
                         **kwargs)

    def do_open(self, files, n, hints):
        """ https://lazka.github.io/pgi-docs/Gio-2.0/classes/Application.html#Gio.Application.do_open """
        self.activate()
        # Importing documents passed as command line arguments
        a = PageAdder(self)
        for f in files:
            a.addpages(f.get_path())
        a.commit()

    def __create_actions(self):
        # Both Gtk.ApplicationWindow and Gtk.Application are Gio.ActionMap. Some action are window
        # related some other are application related. As pdfarrager is a single window app does not
        # matter that much.
        self.window.add_action_entries([
            ('rotate', self.rotate_page_action, 'i'),
            ('delete', self.clear_selected),
            ('crop', self.crop_page_dialog),
            ('export-selection', self.choose_export_selection_pdf_name),
            ('reverse-order', self.reverse_order),
            ('save', self.on_action_save),
            ('save-as', self.on_action_save_as),
            ('import', self.on_action_add_doc_activate),
            ('zoom', self.zoom_change, 'i'),
            ('quit', self.on_quit),
            ('undo', self.undomanager.undo),
            ('redo', self.undomanager.redo),
        ])
        accels = [
            ('delete', 'Delete'),
            ('crop', 'c'),
            ('rotate(90)', '<Ctrl>Right'),
            ('rotate(-90)', '<Ctrl>Left'),
            ('save', '<Ctrl>s'),
            ('save-as', '<Ctrl><Shift>s'),
            ('export-selection', '<Ctrl>e'),
            ('quit', '<Ctrl>q'),
            ('import', 'Insert'),
            ('zoom(5)', 'plus'),
            ('zoom(-5)', 'minus'),
            ('undo', '<Ctrl>z'),
            ('redo', '<Ctrl>y'),
        ]
        for a, k in accels:
            self.set_accels_for_action("win." + a, [k])
        # Disable actions
        self.iv_selection_changed_event()
        # Display accelerators in the menus
        for o in self.uiXML.get_objects():
            if isinstance(o, Gtk.MenuItem) and o.get_action_name() is not None:
                an = Gio.Action.print_detailed_name(o.get_action_name(), o.get_action_target_value())
                a = self.get_accels_for_action(an)
                if len(a) > 0:
                    o.get_child().set_accel(*Gtk.accelerator_parse(a[0]))
        self.undomanager.set_actions(self.window.lookup_action('undo'),
                                     self.window.lookup_action('redo'))

    def do_activate(self):
        """ https://lazka.github.io/pgi-docs/Gio-2.0/classes/Application.html#Gio.Application.do_activate """
        # TODO: huge method that should be splitted
        # Create the temporary directory
        self.tmp_dir = tempfile.mkdtemp(DOMAIN)
        os.chmod(self.tmp_dir, 0o700)
        iconsdir = os.path.join(sharedir, 'icons')
        if not os.path.exists(iconsdir):
            iconsdir = os.path.join(sharedir, 'data', 'icons')
        Gtk.IconTheme.get_default().append_search_path(iconsdir)
        Gtk.Window.set_default_icon_name(DOMAIN)
        # Import the user interface file, trying different possible locations
        ui_path = os.path.join(basedir, 'share', DOMAIN, DOMAIN + '.ui')
        if not os.path.exists(ui_path):
            ui_path = os.path.join(basedir, 'data', DOMAIN + '.ui')
        if not os.path.exists(ui_path):
            ui_path = '/usr/share/{}/{}.ui'.format(DOMAIN, DOMAIN)
        if not os.path.exists(ui_path):
            ui_path = '/usr/local/share/{}/{}.ui'.format(DOMAIN, DOMAIN)
        if not os.path.exists(ui_path):
            dist = pkg_resources.get_distribution('pdfarranger')
            ui_path = os.path.join(dist.location, "data",
                                  DOMAIN + ".ui")

        self.config = Config()
        self.uiXML = Gtk.Builder()
        self.uiXML.set_translation_domain(DOMAIN)
        self.uiXML.add_from_file(ui_path)
        self.uiXML.connect_signals(self)

        # Create the main window, and attach delete_event signal to terminating
        # the application
        self.window = self.uiXML.get_object('main_window')
        self.window.set_title(APPNAME)
        self.window.set_border_width(0)
        self.window.set_application(self)
        if self.config.maximized():
            self.window.maximize()
        self.window.set_default_size(*self.config.window_size())
        self.window.connect('delete_event', self.close_application)

        if hasattr(GLib, "unix_signal_add"):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.close_application)

        # Create a scrolled window to hold the thumbnails-container
        self.sw = self.uiXML.get_object('scrolledwindow')
        self.sw.drag_dest_set(Gtk.DestDefaults.MOTION |
                              Gtk.DestDefaults.HIGHLIGHT |
                              Gtk.DestDefaults.DROP |
                              Gtk.DestDefaults.MOTION,
                              self.TARGETS_SW,
                              Gdk.DragAction.COPY |
                              Gdk.DragAction.MOVE)
        self.sw.connect('drag_data_received', self.sw_dnd_received_data)
        self.sw.connect('button_press_event', self.sw_button_press_event)
        self.sw.connect('scroll_event', self.sw_scroll_event)

        # Create ListStore model and IconView
        self.model = Gtk.ListStore(str,         # 0.Text descriptor
                                   GObject.TYPE_PYOBJECT,
                                                # 1.Cached page image
                                   int,         # 2.Document number
                                   int,         # 3.Page number
                                   float,       # 4.Scale
                                   str,         # 5.Document filename
                                   int,         # 6.Rotation angle
                                   float,       # 7.Crop left
                                   float,       # 8.Crop right
                                   float,       # 9.Crop top
                                   float,       # 10.Crop bottom
                                   float,       # 11.Page width
                                   float,       # 12.Page height
                                   float)       # 13.Resampling factor
        self.undomanager = undo.Manager(self)
        self.zoom_set(self.config.zoom_level())

        self.iconview = Gtk.IconView(self.model)
        self.iconview.clear()
        self.iconview.set_item_width(-1)

        self.cellthmb = CellRendererImage()
        self.iconview.pack_start(self.cellthmb, False)
        self.iconview.set_cell_data_func(self.cellthmb, self.set_cellrenderer_data, None)
        self.iconview.set_text_column(0)
        cell_text_renderer = self.iconview.get_cells()[1]
        cell_text_renderer.props.ellipsize = Pango.EllipsizeMode.MIDDLE

        self.iconview.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.iconview.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                               self.TARGETS_IV,
                                               Gdk.DragAction.COPY |
                                               Gdk.DragAction.MOVE)
        self.iconview.enable_model_drag_dest(self.TARGETS_IV,
                                             Gdk.DragAction.DEFAULT)
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
        self.iconview.connect('selection_changed', self.iv_selection_changed_event)

        self.sw.add_with_viewport(self.iconview)

        # Progress bar
        self.progress_bar = self.uiXML.get_object('progressbar')
        self.progress_bar_timeout_id = 0

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
            self.iconview.override_background_color \
                (state, style_context_sw.get_background_color(state))
        self.iconview.override_background_color(Gtk.StateFlags.SELECTED,
                                                color_selected)
        self.iconview.override_background_color(Gtk.StateFlags.PRELIGHT,
                                                color_prelight)

        self.popup = self.uiXML.get_object('popup_menu')
        self.popup.attach_to_widget(self.window, None)

        # Initializing variables
        self.export_directory = os.path.expanduser('~')
        self.import_directory = self.export_directory
        self.nfile = 0
        self.iv_auto_scroll_direction = 0
        self.iv_auto_scroll_timer = None
        self.pdfqueue = []
        self.pressed_button = None

        GObject.type_register(PDFRenderer)
        GObject.signal_new('update_thumbnail', PDFRenderer,
                           GObject.SignalFlags.RUN_FIRST, None,
                           [GObject.TYPE_INT, GObject.TYPE_PYOBJECT,
                            GObject.TYPE_FLOAT])
        self.rendering_thread = None

        self.set_unsaved(False)
        self.export_file = None
        self.__create_actions()

    @staticmethod
    def set_cellrenderer_data(column, cell, model, it, data=None):
        cell.set_property('image', model.get_value(it, 1))
        cell.set_property('scale', model.get_value(it, 4))
        cell.set_property('rotation', model.get_value(it, 6))
        cell.set_property('cropL', model.get_value(it, 7))
        cell.set_property('cropR', model.get_value(it, 8))
        cell.set_property('cropT', model.get_value(it, 9))
        cell.set_property('cropB', model.get_value(it, 10))
        cell.set_property('width', model.get_value(it, 11))
        cell.set_property('height', model.get_value(it, 12))
        cell.set_property('resample', model.get_value(it, 13))

    def render(self):
        if self.rendering_thread:
            self.rendering_thread.quit = True
            self.rendering_thread.join()
        self.rendering_thread = PDFRenderer(self.model, self.pdfqueue, 1 / self.zoom_scale)
        self.rendering_thread.connect('update_thumbnail', self.update_thumbnail)
        self.rendering_thread.start()

        if self.progress_bar_timeout_id:
            GObject.source_remove(self.progress_bar_timeout_id)
        self.progress_bar_timout_id = \
            GObject.timeout_add(50, self.progress_bar_timeout)

    def set_unsaved(self, flag):
        self.is_unsaved = flag
        GObject.idle_add(self.retitle)

    def retitle(self):
        all_files = self.active_file_names()
        title = ''
        if len(all_files) == 1:
            title += all_files.pop()
        elif len(all_files) == 0:
            title += _("No document")
        else:
            title += _("Several documents")
        if self.is_unsaved:
            title += '*'
        title += ' - ' + APPNAME
        self.window.set_title(title)
        return False

    def progress_bar_timeout(self):
        cnt_finished = 0
        cnt_all = 0
        for row in self.model:
            cnt_all += 1
            if row[1]:
                cnt_finished += 1
        fraction = 1 if cnt_all == 0 else cnt_finished / cnt_all

        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(_('Rendering thumbnails... [%(i1)s/%(i2)s]')
                                   % {'i1': cnt_finished, 'i2': cnt_all})
        if fraction >= 0.999:
            self.progress_bar.hide()
            return False
        elif not self.progress_bar.get_visible():
            self.progress_bar.show()

        return True

    def update_thumbnail(self, obj, num, thumbnail, resample):
        row = self.model[num]
        row[13] = resample
        row[4] = self.zoom_scale
        row[1] = thumbnail

    def on_window_size_request(self, window):
        """Main Window resize - workaround for autosetting of
           iconview cols no."""
        if len(self.model) > 0:
            # scale*page_width*(1-crop_left-crop_right)
            item_width = int(max(row[4] * row[11] * (1. - row[7] - row[8]) \
                                 for row in self.model))
            # FIXME: those are magic number found with my current GTK style. This might not be portable.
            min_col_spacing = 19
            min_margin = 14
            iw_width = window.get_size()[0]
            # 2 * min_margin + col_num * item_width + min_col_spacing * (col_num-1) = iw_width
            # min_margin+margin = min_col_spacing+col_spacing = (iw_width - col_num * item_width) / (col_num+1)
            col_num = (iw_width - 2 * min_margin - min_col_spacing) // (item_width + min_col_spacing)
            spacing = (iw_width - col_num * item_width) // (col_num + 1)
            if col_num == 0:
                col_num = 1
                spacing = min_margin
            self.iconview.set_columns(col_num)
            self.iconview.set_column_spacing(spacing - min_col_spacing)
            self.iconview.set_margin_left(spacing - min_margin)

    def update_geometry(self, treeiter):
        """Recomputes the width and height of the rotated page and saves
           the result in the ListStore"""

        if not self.model.iter_is_valid(treeiter):
            return

        nfile, npage, rotation = self.model.get(treeiter, 2, 3, 6)
        page = self.pdfqueue[nfile - 1].document.get_page(npage - 1)
        w0, h0 = page.get_size()

        rotation = int(rotation) % 360
        rotation = round(rotation / 90) * 90
        if rotation == 90 or rotation == 270:
            w1, h1 = h0, w0
        else:
            w1, h1 = w0, h0

        self.model.set(treeiter, 11, w1, 12, h1)

    def on_quit(self, action, param, unknown):
        self.close_application()

    def close_application(self, widget=None, event=None, data=None):
        """Termination"""

        if self.rendering_thread:
            self.rendering_thread.quit = True
            self.rendering_thread.join()
            self.rendering_thread.pdfqueue = []

        # Release Poppler.Document instances to unlock all temporay files
        self.pdfqueue = []
        self.config.set_window_size(self.window.get_size())
        self.config.set_maximized(self.window.is_maximized())
        self.config.set_zoom_level(self.zoom_level)
        self.config.save()
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)
        self.quit()

    def choose_export_pdf_name(self, only_selected=False):
        """Handles choosing a name for exporting """

        chooser = Gtk.FileChooserNative(title=_('Export ...'),
                                        action=Gtk.FileChooserAction.SAVE)
        chooser.set_do_overwrite_confirmation(True)
        if len(self.pdfqueue) > 0:
            chooser.set_filename(self.pdfqueue[0].filename)
        chooser.set_current_folder(self.export_directory)
        filter_pdf = Gtk.FileFilter()
        filter_pdf.set_name(_('PDF files'))
        filter_pdf.add_mime_type('application/pdf')
        chooser.add_filter(filter_pdf)

        filter_all = Gtk.FileFilter()
        filter_all.set_name(_('All files'))
        filter_all.add_pattern('*')
        chooser.add_filter(filter_all)

        while True:
            response = chooser.run()
            if response == Gtk.ResponseType.ACCEPT:
                file_out = chooser.get_filename()
                try:
                    self.save(only_selected, file_out)
                except Exception as e:
                    traceback.print_exc()
                    chooser.destroy()
                    self.error_message_dialog(e)
                    return
            break
        chooser.destroy()

    def active_file_names(self):
        """Returns the file names currently associated with pages in the model."""
        all_files = set()
        for row in self.model:
            nfile = row[2]
            f = self.pdfqueue[nfile - 1]
            all_files.add(f.filename)
        return all_files

    def on_action_save(self, action, param, unknown):
        try:
            if self.export_file:
                self.save(False, self.export_file)
            else:
                self.choose_export_pdf_name()
        except Exception as e:
            self.error_message_dialog(e)

    def on_action_save_as(self, action, param, unknown):
        self.choose_export_pdf_name()

    @warn_dialog
    def save(self, only_selected, file_out):
        """Saves to the specified file.  May throw exceptions."""
        (path, shortname) = os.path.split(file_out)
        (shortname, ext) = os.path.splitext(shortname)
        if ext.lower() != '.pdf':
            file_out = file_out + '.pdf'
        to_export = self.model
        if only_selected:
            selection = self.iconview.get_selected_items()
            to_export = [row for row in self.model if row.path in selection]
        exporter.export(self.pdfqueue, to_export, file_out)
        self.export_directory = path
        self.export_file = file_out
        self.set_unsaved(False)

    def choose_export_selection_pdf_name(self, action, target, unknown):
        self.choose_export_pdf_name(True)

    def on_action_add_doc_activate(self, action, param, unknown):
        """Import doc"""
        chooser = Gtk.FileChooserNative(title=_('Import...'),
                                        action=Gtk.FileChooserAction.OPEN)
        chooser.set_current_folder(self.import_directory)
        chooser.set_select_multiple(True)

        filter_all = Gtk.FileFilter()
        filter_all.set_name(_('All files'))
        filter_all.add_pattern('*')
        chooser.add_filter(filter_all)

        filter_pdf = Gtk.FileFilter()
        filter_pdf.set_name(_('PDF files'))
        filter_pdf.add_mime_type('application/pdf')
        chooser.add_filter(filter_pdf)
        chooser.set_filter(filter_pdf)

        response = chooser.run()
        if response == Gtk.ResponseType.ACCEPT:
            adder = PageAdder(self)
            for filename in chooser.get_filenames():
                try:
                    warnmsg = adder.addpages(filename)
                    if warnmsg:
                        print(warnmsg)
                except Exception as e:
                    traceback.print_exc()
                    chooser.destroy()
                    self.error_message_dialog(e)
                    return
            adder.commit()
        chooser.destroy()

    def clear_selected(self, action, parameter, unknown):
        """Removes the selected elements in the IconView"""

        self.undomanager.commit("Delete")
        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()
        selection.sort(reverse=True)
        self.set_unsaved(True)
        for path in selection:
            model.remove(model.get_iter(path))
        path = selection[-1]
        self.iconview.select_path(path)
        if not self.iconview.path_is_selected(path):
            if len(model) > 0:  # select the last row
                row = model[-1]
                path = row.path
                self.iconview.select_path(path)
        self.iconview.grab_focus()

    @staticmethod
    def iv_drag_begin(iconview, context):
        """Sets custom icon on drag begin for multiple items selected"""
        if len(iconview.get_selected_items()) > 1:
            iconview.stop_emission('drag_begin')
            Gtk.drag_set_icon_name(context, "gtk-dnd-multiple", 0, 0)

    def iv_dnd_get_data(self, iconview, context,
                        selection_data, target_id, etime):
        """Handles requests for data by drag and drop in iconview"""

        model = iconview.get_model()
        selection = self.iconview.get_selected_items()
        selection.sort(key=lambda x: x.get_indices()[0])
        data = []
        for path in selection:
            target = str(selection_data.get_target())
            if target == 'MODEL_ROW_INTERN':
                data.append(str(path[0]))
            elif target == 'MODEL_ROW_EXTERN':
                it = model.get_iter(path)
                nfile, npage, angle = model.get(it, 2, 3, 6)
                crop = model.get(it, 7, 8, 9, 10)
                pdfdoc = self.pdfqueue[nfile - 1]
                data.append('\n'.join([pdfdoc.filename,
                                       str(npage),
                                       str(angle)] +
                                      [str(side) for side in crop]))
        if data:
            data = '\n;\n'.join(data)
            selection_data.set(selection_data.get_target(), 8, data.encode())

    def iv_dnd_received_data(self, iconview, context, x, y,
                             selection_data, target_id, etime):
        """Handles received data by drag and drop in iconview"""

        model = iconview.get_model()
        data = selection_data.get_data()
        if data:
            data = data.decode().split('\n;\n')
            item = iconview.get_dest_item_at_pos(x, y)
            if item:
                path, position = item
                ref_to = Gtk.TreeRowReference.new(model, path)
            else:
                ref_to = None
                position = Gtk.IconViewDropPosition.DROP_RIGHT
                if len(model) > 0:  # find the iterator of the last row
                    row = model[-1]
                    ref_to = Gtk.TreeRowReference.new(model, row.path)
            if ref_to:
                before = (position == Gtk.IconViewDropPosition.DROP_LEFT
                          or position == Gtk.IconViewDropPosition.DROP_ABOVE)
                target = selection_data.get_target().name()
                if target == 'MODEL_ROW_INTERN':
                    move = context.get_actions() & Gdk.DragAction.MOVE
                    self.undomanager.commit("Move" if move else "Copy")
                    data.sort(key=int, reverse=not before)
                    ref_from_list = [Gtk.TreeRowReference.new(model, Gtk.TreePath(p))
                                     for p in data]
                    iter_to = self.model.get_iter(ref_to.get_path())
                    for ref_from in ref_from_list:
                        row = model[model.get_iter(ref_from.get_path())]
                        if before:
                            model.insert_before(iter_to, row[:])
                        else:
                            model.insert_after(iter_to, row[:])
                    if move:
                        for ref_from in ref_from_list:
                            model.remove(model.get_iter(ref_from.get_path()))

                elif target == 'MODEL_ROW_EXTERN':
                    pageadder = PageAdder(self)
                    pageadder.move(ref_to, before)
                    if not before:
                        data.reverse()
                    while data:
                        tmp = data.pop(0).split('\n')
                        filename = tmp[0]
                        npage, angle = [int(k) for k in tmp[1:3]]
                        crop = [float(side) for side in tmp[3:7]]
                        pageadder.addpages(filename, npage, angle, crop)
                    if pageadder.commit() and context.get_actions() & Gdk.DragAction.MOVE:
                        context.finish(True, True, etime)

    def iv_dnd_data_delete(self, widget, context):
        """ Delete pages from a pdfarranger instance after they have been moved to another instance """
        selection = self.iconview.get_selected_items()
        if len(selection) == 0:
            # On Windows this method is triggered even for drag & drop within the same
            # pdfarranger instance
            return
        self.undomanager.commit("Move")
        model = self.iconview.get_model()
        ref_del_list = [Gtk.TreeRowReference.new(model, path) for path in selection]
        for ref_del in ref_del_list:
            path = ref_del.get_path()
            model.remove(model.get_iter(path))

    def iv_dnd_motion(self, iconview, context, x, y, etime):
        """Handles the drag-motion signal in order to auto-scroll the view"""

        autoscroll_area = 40
        sw_vadj = self.sw.get_vadjustment()
        sw_height = self.sw.get_allocation().height
        if y - sw_vadj.get_value() < autoscroll_area:
            if not self.iv_auto_scroll_timer:
                self.iv_auto_scroll_direction = Gtk.DirectionType.UP
                self.iv_auto_scroll_timer = GObject.timeout_add(150,
                                                                self.iv_auto_scroll)
        elif y - sw_vadj.get_value() > sw_height - autoscroll_area:
            if not self.iv_auto_scroll_timer:
                self.iv_auto_scroll_direction = Gtk.DirectionType.DOWN
                self.iv_auto_scroll_timer = GObject.timeout_add(150,
                                                                self.iv_auto_scroll)
        elif self.iv_auto_scroll_timer:
            GObject.source_remove(self.iv_auto_scroll_timer)
            self.iv_auto_scroll_timer = None

    def iv_dnd_leave_end(self, widget, context, ignored=None):
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
        """Manages mouse movement on the iconview to detect drag and drop events"""

        if self.pressed_button:
            if iconview.drag_check_threshold(self.pressed_button.x,
                                             self.pressed_button.y,
                                             event.x, event.y):
                iconview.drag_begin_with_coordinates(Gtk.TargetList.new(self.TARGETS_IV),
                                                     Gdk.DragAction.COPY | Gdk.DragAction.MOVE,
                                                     self.pressed_button.button, event, -1, -1)
                self.pressed_button = None

    def iv_button_release_event(self, iconview, event):
        """Manages mouse releases on the iconview"""

        if self.pressed_button:
            # Button was pressed and released on a previously selected item
            # without causing a drag and drop: Deselect everything except
            # the clicked item.
            iconview.unselect_all()
            path = iconview.get_path_at_pos(event.x, event.y)
            iconview.select_path(path)
            iconview.set_cursor(path, None, False)  # for consistent shift+click selection
        self.pressed_button = None

    def iv_button_press_event(self, iconview, event):
        """Manages mouse clicks on the iconview"""

        x = int(event.x)
        y = int(event.y)
        click_path = iconview.get_path_at_pos(x, y)

        # On shift-click, select (or, with the Control key, toggle) items
        # from the item after the cursor up to the shift-clicked item,
        # inclusive, where 'after' means towards the shift-clicked item.
        #
        # IconView's built-in multiple-selection mode performs rubber-band
        # (rectangular) selection, which is not what we want. We override
        # it by handling the shift-click here.
        if event.button == 1 and event.state & Gdk.ModifierType.SHIFT_MASK:
            cursor_path = iconview.get_cursor()[1]
            click_path = iconview.get_path_at_pos(x, y)
            if cursor_path and click_path:
                i_cursor = cursor_path[0]
                i_click = click_path[0]
                step = 1 if i_cursor <= i_click else -1
                for i in range(i_cursor + step, i_click + step, step):
                    path = Gtk.TreePath.new_from_indices([i])
                    if (event.state & Gdk.ModifierType.CONTROL_MASK and
                            iconview.path_is_selected(path)):
                        iconview.unselect_path(path)
                    else:
                        iconview.select_path(path)
            return 1

        # Do not deselect when clicking an already selected item for drag and drop
        if event.button == 1:
            selection = iconview.get_selected_items()
            if click_path and click_path in selection:
                self.pressed_button = event
                return 1  # prevent propagation i.e. (de-)selection

        # Display right click menu
        if event.button == 3:
            selection = iconview.get_selected_items()
            if click_path:
                if click_path not in selection:
                    iconview.unselect_all()
                iconview.select_path(click_path)
                iconview.grab_focus()
                self.popup.popup(None, None, None, None, event.button, event.time)
            return 1

    def iv_selection_changed_event(self, user_data=None):
        selection = self.iconview.get_selected_items()
        ne = len(selection) > 0
        for a, e in [("reverse-order", self.reverse_order_available(selection)),
                     ("delete", ne), ("crop", ne), ("rotate", ne),
                     ("export-selection", ne)]:
            self.window.lookup_action(a).set_enabled(e)

    def sw_dnd_received_data(self, scrolledwindow, context, x, y,
                             selection_data, target_id, etime):
        """Handles received data by drag and drop in scrolledwindow"""
        if target_id == self.TEXT_URI_LIST:
            pageadder = PageAdder(self)
            for uri in selection_data.get_uris():
                filename = self.get_file_path_from_dnd_dropped_uri(uri)
                msg = pageadder.addpages(filename)
                if msg:
                    self.error_message_dialog(msg)
            pageadder.commit()

    def sw_button_press_event(self, scrolledwindow, event):
        """Unselects all items in iconview on mouse click in scrolledwindow"""
        # TODO most likely unreachable code

        if event.button == 1:
            self.iconview.unselect_all()

    def sw_scroll_event(self, scrolledwindow, event):
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
        self.zoom_level = max(min(level, 40), -10)
        self.zoom_scale = 0.2 * (1.1 ** self.zoom_level)
        for row in self.model:
            row[4] = self.zoom_scale
        GObject.idle_add(self.render)

    def zoom_change(self, action, step, unknown):
        """ Action handle for zoom change """
        self.zoom_set(self.zoom_level + step.get_int32())

    def get_file_path_from_dnd_dropped_uri(self, uri):
        """Extracts the path from an uri"""
        path = url2pathname(uri)  # escape special chars
        path = path.strip('\r\n\x00')  # remove \r\n and NULL

        # get the path to file
        if path.startswith('file:\\\\\\'):  # windows
            path = path[8:]  # 8 is len('file:///')
        elif path.startswith('file://'):  # nautilus, rox
            path = path[7:]  # 7 is len('file://')
        elif path.startswith('file:'):  # xffm
            path = path[5:]  # 5 is len('file:')
        return path

    def rotate_page_action(self, action, angle, unknown):
        """Rotates the selected page in the IconView"""
        self.undomanager.commit("Rotate")
        angle = angle.get_int32()
        selection = self.iconview.get_selected_items()
        if self.rotate_page(selection, angle):
            self.set_unsaved(True)

    def rotate_page(self, selection, angle):
        rotate_times = int(round(((-angle) % 360) / 90) % 4)
        model = self.iconview.get_model()
        for path in selection:
            treeiter = model.get_iter(path)
            perm = [0, 2, 1, 3]
            for it in range(rotate_times):
                perm.append(perm.pop(0))
            perm.insert(1, perm.pop(2))
            crop = [model.get_value(treeiter, 7 + perm[side]) for side in range(4)]
            for side in range(4):
                model.set_value(treeiter, 7 + side, crop[side])

            new_angle = model.get_value(treeiter, 6) + int(angle)
            new_angle = new_angle % 360
            model.set_value(treeiter, 6, new_angle)
            self.update_geometry(treeiter)
        return rotate_times is not 0 and len(selection) > 0

    def crop_page_dialog(self, action, parameter, unknown):
        """Opens a dialog box to define margins for page cropping"""

        sides = ('L', 'R', 'T', 'B')
        side_names = {'L': _('Left'), 'R': _('Right'),
                      'T': _('Top'), 'B': _('Bottom')}
        opposite_sides = {'L': 'R', 'R': 'L', 'T': 'B', 'B': 'T'}

        def set_crop_value(spinbutton, side):
            opp_side = opposite_sides[side]
            adjustment = spin_list[sides.index(opp_side)].get_adjustment()
            adjustment.set_upper(99.0 - spinbutton.get_value())

        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()

        crop = [0., 0., 0., 0.]
        if selection:
            path = selection[0]
            pos = model.get_iter(path)
            crop = [model.get_value(pos, 7 + side) for side in range(4)]

        dialog = Gtk.Dialog(title=(_('Crop Selected Pages')),
                            parent=self.window,
                            flags=Gtk.DialogFlags.MODAL,
                            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                     Gtk.STOCK_OK, Gtk.ResponseType.OK))
        dialog.set_default_response(Gtk.ResponseType.OK)
        margin = 12
        label = Gtk.Label(label=_('Cropping does not remove any content\nfrom the PDF file, it only hides it.'))
        dialog.vbox.pack_start(label, False, False, 0)
        frame = Gtk.Frame(label=_('Crop Margins'))
        frame.props.margin = margin
        dialog.vbox.pack_start(frame, True, True, 0)
        grid = Gtk.Grid()
        grid.set_column_spacing(margin)
        grid.set_row_spacing(margin)
        grid.props.margin = margin
        frame.add(grid)

        spin_list = []
        units = 2 * [_('% of width')] + 2 * [_('% of height')]
        for row, side in enumerate(sides):
            label = Gtk.Label(label=side_names[side])
            label.set_alignment(0, 0)
            grid.attach(label, 0, row, 1, 1)

            adj = Gtk.Adjustment(100. * crop.pop(0), 0.0, 99.0, 1.0, 5.0, 0.0)
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=0, digits=1)
            spin.set_activates_default(True)
            spin.connect('value-changed', set_crop_value, side)
            spin_list.append(spin)
            grid.attach(spin, 1, row, 1, 1)

            label = Gtk.Label(label=units.pop(0))
            label.set_alignment(0, 0)
            grid.attach(label, 2, row, 1, 1)

        dialog.show_all()
        result = dialog.run()

        if result == Gtk.ResponseType.OK:
            crop = [spin.get_value() / 100. for spin in spin_list]
            crop = [crop] * len(selection)
            self.undomanager.commit("Crop")
            oldcrop = self.crop(selection, crop)
            if oldcrop != crop:
                self.set_unsaved(True)
        dialog.destroy()

    def crop(self, selection, newcrop):
        oldcrop = [[0] * 4 for x in range(len(selection))]
        model = self.iconview.get_model()
        for id_sel, path in enumerate(selection):
            pos = model.get_iter(path)
            for it in range(4):
                oldcrop[id_sel][it] = model.get_value(pos, 7 + it)
                model.set_value(pos, 7 + it, newcrop[id_sel][it])
            self.update_geometry(pos)
        return oldcrop

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
        if not contiguous:
            return False

        return True

    def reverse_order(self, action, parameter, unknown):
        """Reverses the selected elements in the IconView"""

        model = self.iconview.get_model()
        selection = self.iconview.get_selected_items()
        if not self.reverse_order_available(selection):
            return

        # selection is a list of 1-tuples, not in order
        indices = sorted([i[0] for i in selection])
        first = indices[0]
        last = indices[-1]

        self.set_unsaved(True)
        indices.reverse()
        new_order = list(range(first)) + indices + list(range(last + 1, len(model)))
        self.undomanager.commit("Reorder")
        model.reorder(new_order)

    def about_dialog(self, widget, data=None):
        about_dialog = Gtk.AboutDialog()
        try:
            about_dialog.set_transient_for(self.window)
            about_dialog.set_modal(True)
        except:
            pass
        # FIXME
        about_dialog.set_name(APPNAME)
        about_dialog.set_program_name(APPNAME)
        about_dialog.set_version(VERSION)
        about_dialog.set_comments(_(
            '%s is a tool for rearranging and modifying PDF files. '
            'Developed using GTK+ and Python') % APPNAME)
        about_dialog.set_authors(['Konstantinos Poulios'])
        about_dialog.add_credit_section('Maintainers and contributors', [
            'https://github.com/jeromerobert/pdfarranger/graphs/contributors'])
        about_dialog.set_website_label(WEBSITE)
        about_dialog.set_logo_icon_name(DOMAIN)
        about_dialog.set_license(LICENSE)
        about_dialog.connect('response', lambda w, *args: w.destroy())
        about_dialog.connect('delete_event', lambda w, *args: w.destroy())
        about_dialog.show_all()

    def error_message_dialog(self, msg, msg_type=Gtk.MessageType.ERROR):
        error_msg_dlg = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
                                          type=msg_type, parent=self.window,
                                          message_format=str(msg),
                                          buttons=Gtk.ButtonsType.OK)
        response = error_msg_dlg.run()
        if response == Gtk.ResponseType.OK:
            error_msg_dlg.destroy()


class PDFDoc:
    """Class handling PDF documents"""

    def __init__(self, filename, tmp_dir):

        self.filename = os.path.abspath(filename)
        self.shortname = os.path.splitext(os.path.split(self.filename)[1])[0]
        self.mtime = os.path.getmtime(filename)
        fd, self.copyname = tempfile.mkstemp(dir=tmp_dir)
        os.close(fd)
        shutil.copy(self.filename, self.copyname)
        uri = pathlib.Path(self.copyname).as_uri()
        self.document = Poppler.Document.new_from_file(uri, None)


class PageAdder(object):
    """ Helper class to add pages to the current model """

    def __init__(self, app):
        #: A PdfArranger instance
        self.app = app
        #: The pages which will be added by the commit method
        self.pages = []
        #: Where to insert pages relatively to treerowref
        self.before = False
        #: Where to insert pages. If None pages are inserted at the end
        self.treerowref = None

    @staticmethod
    def __validate(filename):
        if not os.path.isfile(filename):
            return _('File %s does not exist') % filename
        f = Gio.File.new_for_path(filename)
        mime_type = f.query_info('standard::content-type', 0, None).get_content_type()
        expected_mime_type = 'application/pdf' if os.name != 'nt' else '.pdf'
        if mime_type == expected_mime_type:
            return ""
        elif mime_type[:34] == 'application/vnd.oasis.opendocument':
            return _('OpenDocument not supported yet!')
        elif mime_type[:5] == 'image':
            return _('Image file not supported yet!')
        else:
            return _('File type "%s" not supported!') % mime_type

    def move(self, treerowref, before):
        """ Insert pages at the given location """
        self.before = before
        self.treerowref = treerowref

    def addpages(self, filename, page=-1, angle=0, crop=None):
        warnmsg = self.__validate(filename)
        if warnmsg:
            return warnmsg
        crop = [0] * 4 if crop is None else crop
        pdfdoc = None
        for i, it_pdfdoc in enumerate(self.app.pdfqueue):
            if os.path.isfile(it_pdfdoc.filename) and \
                    os.path.samefile(filename, it_pdfdoc.filename) and \
                    os.path.getmtime(filename) is it_pdfdoc.mtime:
                pdfdoc = it_pdfdoc
                nfile = i + 1
                break

        if not pdfdoc:
            pdfdoc = PDFDoc(filename, self.app.tmp_dir)
            self.app.import_directory = os.path.split(filename)[0]
            self.app.export_directory = self.app.import_directory
            self.app.pdfqueue.append(pdfdoc)
            nfile = len(self.app.pdfqueue)

        n_end = pdfdoc.document.get_n_pages()
        n_start = min(n_end, max(1, page))
        if page != -1:
            n_end = max(n_start, min(n_end, page))

        for npage in range(n_start, n_end + 1):
            descriptor = ''.join([pdfdoc.shortname, '\n', _('page'), ' ', str(npage)])
            page = pdfdoc.document.get_page(npage - 1)
            w, h = page.get_size()
            self.pages.append((descriptor,          # 0
                               None,                # 1
                               nfile,               # 2
                               npage,               # 3
                               self.app.zoom_scale, # 4
                               pdfdoc.filename,     # 5
                               angle,               # 6
                               crop[0], crop[1],     # 7-8
                               crop[2], crop[3],     # 9-10
                               w,h,                 # 11-12
                               2.))                 # 13 FIXME
        return ""

    def commit(self):
        if len(self.pages) == 0:
            return False
        self.app.undomanager.commit("Add")
        for p in self.pages:
            it = self.app.model.append(p)
            if self.treerowref:
                iter_to = self.app.model.get_iter(self.treerowref.get_path())
                if self.before:
                    self.app.model.move_before(it, iter_to)
                else:
                    self.app.model.move_after(it, iter_to)
            self.app.update_geometry(it)
        GObject.idle_add(self.app.retitle)
        GObject.idle_add(self.app.render)
        return True


class PDFRenderer(threading.Thread, GObject.GObject):

    def __init__(self, model, pdfqueue, resample):
        threading.Thread.__init__(self)
        GObject.GObject.__init__(self)
        self.model = model
        self.pdfqueue = pdfqueue
        self.resample = resample
        self.quit = False

    def run(self):
        for idx, row in enumerate(self.model):
            if self.quit:
                return
            try:
                nfile = row[2]
                npage = row[3]
                pdfdoc = self.pdfqueue[nfile - 1]
                page = pdfdoc.document.get_page(npage - 1)
                w, h = page.get_size()
                thumbnail = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                               int(w / self.resample),
                                               int(h / self.resample))
                cr = cairo.Context(thumbnail)
                if self.resample != 1.:
                    cr.scale(1. / self.resample, 1. / self.resample)
                page.render(cr)
                GObject.idle_add(self.emit, 'update_thumbnail',
                                 idx, thumbnail, self.resample,
                                 priority=GObject.PRIORITY_LOW)
            except:
                traceback.print_exc()


def main():
    PdfArranger().run(sys.argv)
