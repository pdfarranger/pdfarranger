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

import gettext

from gi.repository import Gtk
from gi.repository import GObject  # for using custom signals

from . import pageutils
from .core import img2pdf_supported_img, IMG2PDF_VERSION, POPPLER_VERSION

from .constants import (
    APPNAME,
    LIBQPDF_VERSION,
    PIKEPDF_VERSION,
    PYTHON_VERSION,
    VERSION,
    WEBSITE,
)


_ = gettext.gettext


class Dialogs:
    """Simple dialog boxes for PdfArranger.

    Holds a back-reference to the main application instance so that dialogs
    can access the GTK window and configuration they need without duplicating
    state.
    """

    def __init__(self, app):
        self.app = app

    def confirm(self, msg, action):
        """A dialog for confirmation of an action.

        Returns True if the user confirmed, False otherwise.
        """
        d = Gtk.MessageDialog(
            self.app.window, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.NONE, msg
        )
        d.add_buttons(action, 1, _("_Cancel"), 2)
        response = d.run()
        d.destroy()
        return response == 1

    def save_changes(self, msg):
        """A dialog which asks if changes should be saved.

        Returns:
            1 — Don't Save
            2 — Cancel
            3 — Save
        """
        d = Gtk.MessageDialog(
            self.app.window, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.NONE, msg
        )
        d.format_secondary_markup(
            _("Your changes will be lost if you don't save them.")
        )
        d.add_buttons(_("Do_n’t Save"), 1, _("_Cancel"), 2, _("_Save"), 3)
        response = d.run()
        d.destroy()
        return response

    def error_message(self, msg):
        """Show a modal error message dialog."""
        d = Gtk.MessageDialog(
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.ERROR,
            parent=self.app.window,
            message_format=str(msg),
            buttons=Gtk.ButtonsType.OK,
        )
        response = d.run()
        if response == Gtk.ResponseType.OK:
            d.destroy()

    def save_warning(self, msg):
        """Show a warning dialog after saving produced non-fatal warnings."""
        d = Gtk.MessageDialog(
            type=Gtk.MessageType.WARNING,
            parent=self.app.window,
            text=_("Saving produced some warnings"),
            secondary_text=_(
                "Despite the warnings the document(s) should have no visible issues."
            ),
            buttons=Gtk.ButtonsType.OK,
        )
        sw = Gtk.ScrolledWindow(margin=6)
        label = Gtk.Label(msg, wrap=True, margin=6, xalign=0.0, selectable=True)
        sw.add(label)
        d.vbox.pack_start(sw, False, False, 0)
        cb = Gtk.CheckButton(
            _("Don't show warnings when saving again."), margin=6, can_focus=False
        )
        d.vbox.pack_start(cb, False, False, 0)
        d.show_all()
        sw.set_min_content_height(min(150, label.get_allocated_height()))
        cb.set_can_focus(True)
        d.run()
        self.app.config.set_show_save_warnings(not cb.get_active())
        d.destroy()

    def content_loss_warning(self):
        """Inform the user about crop/hide and outline limitations."""
        d = Gtk.Dialog(
            _("Note"),
            parent=self.app.window,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(_("_OK"), Gtk.ResponseType.OK),
            resizable=False,
        )
        m1 = _("Note the limitations:")
        m2 = _(
            "Cropping/hiding does not remove any content from the PDF file, it only hides it."
        )
        m3 = _("Outlines and links can be preserved only in certain cases.")
        link = "https://github.com/pdfarranger/pdfarranger/wiki/User-Manual"
        section = "#preserving-of-outlines-and-links"
        markup = (
            m1
            + "\n\n"
            + m2
            + "\n\n"
            + m3
            + " "
            + _("For more info see")
            + " "
            + '<a href="'
            + link
            + section
            + '">'
            + _("User Manual")
            + "</a>"
        )
        label = Gtk.Label(
            label=markup, use_markup=True, max_width_chars=50, wrap=True, margin=12
        )
        cb = Gtk.CheckButton(
            _("Do not show this dialog again."), can_focus=False, margin=12
        )
        d.vbox.pack_start(label, False, False, 6)
        d.vbox.pack_start(cb, False, False, 6)
        d.show_all()
        cb.set_can_focus(True)
        d.run()
        self.app.config.set_content_loss_warning(not cb.get_active())
        d.destroy()

    def about(self, _action, _parameter, _unknown):
        """Show the About dialog."""
        d = Gtk.AboutDialog()
        d.set_transient_for(self.app.window)
        d.set_modal(True)
        d.set_name(APPNAME)
        d.set_program_name(APPNAME)
        d.set_version(VERSION)
        d.set_comments(
            "".join(
                (
                    _("%s is a tool for rearranging and modifying PDF files.")
                    % APPNAME,
                    "\n \n",
                    _("Software versions:")
                    + "\n"
                    + "pikepdf %s, libqpdf %s, img2pdf %s, Poppler %s, GTK %s, Python %s"
                    % (
                        PIKEPDF_VERSION,
                        LIBQPDF_VERSION,
                        IMG2PDF_VERSION,
                        POPPLER_VERSION,
                        self.app.gtk_version,
                        PYTHON_VERSION,
                    ),
                    "\n \n",
                    _("Running on %s") % self.app.get_platform(),
                )
            )
        )
        d.set_authors(["Konstantinos Poulios"])
        d.add_credit_section(
            _("Maintainers and contributors"),
            ["https://github.com/pdfarranger/pdfarranger/graphs/contributors"],
        )
        d.set_website(WEBSITE)
        d.set_website_label(WEBSITE)
        d.set_logo_icon_name("com.github.jeromerobert.pdfarranger")
        d.set_license(_("GNU General Public License (GPL) Version 3."))
        d.connect("response", lambda w, *args: w.destroy())
        d.connect("delete_event", lambda w, *args: w.destroy())
        d.show_all()

    def range_select(self):
        """Opens a dialog box to range select"""
        model = self.app.iconview.get_model()
        diag = pageutils.RangeSelectDialog(self.app.window)
        range_selected = diag.run_get()
        # clean up the selection and split the ranges
        if range_selected is not None:
            result_list = []
            # split the string using commas
            comma_split = range_selected.split(",")
            for element in comma_split:
                element = element.strip()
                # check if the element has a dash
                # Consider multiple dashes? Might create problems?
                if "-" in element and element.count("-") == 1:
                    # split the range by the dash
                    range_split = element.split("-")
                    # convert the range to integers
                    # If the dash range is given without the first element (-3)
                    # then the range starts from the first page
                    if len(range_split) == 2 and range_split[0]:
                        range_start = int(range_split[0])
                        if range_start < 1:
                            range_start = 1
                    else:
                        # Set to 1 because the model is zero indexed
                        range_start = 1
                    # If the dash range is given without the last element (3-)
                    # then the range ends at the last page
                    if len(range_split) == 2 and range_split[1]:
                        range_end = int(range_split[1])
                        if range_end > len(model):
                            range_end = len(model)
                    else:
                        range_end = len(model)
                    # add the range to the result list
                    result_list += list(range(range_start, range_end + 1))
                elif element.isdigit():
                    # add the number to the result list
                    # If it includes multiple dashes elif will not be executed
                    # Check if the element is in the range of all pages
                    if int(element) >= 1 and int(element) <= len(model):
                        result_list.append(int(element))
            # Clean selection
            # TO-DO: Maybe an additive selection to the previous selection
            self.app.iconview.unselect_all()
            for page in result_list:
                # Because the model is zero indexed remove 1 from the page number
                row = model[page - 1]
                self.app.iconview.select_path(row.path)
            self.app.update_statusbar()

    def crop(self, _action, _parameter, _unknown):
        """Opens a dialog box to define margins for page cropping."""
        s = self.app.iconview.get_selected_items()
        a = (
            self.app.window,
            s,
            self.app.model,
            self.app.pdfqueue,
            self.app.is_unsaved,
            "CROP",
            self.app.update_crop,
        )
        pageutils.CropHideDialog(*a)

    def hide(self, _action, _parameter, _unknown):
        """Opens a dialog box to define margins for page hiding."""
        s = self.app.iconview.get_selected_items()
        if not self.app.is_paste_layer_available(s):
            return
        a = (
            self.app.window,
            s,
            self.app.model,
            self.app.pdfqueue,
            self.app.is_unsaved,
            "HIDE",
            self.app.update_hide,
        )
        pageutils.CropHideDialog(*a)

    def open(self, title):
        chooser = Gtk.FileChooserNative.new(
            title=title,
            parent=self.app.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=_("_Open"),
            cancel_label=_("_Cancel"),
        )
        if self.app.import_directory is not None:
            chooser.set_current_folder(self.app.import_directory)
        chooser.set_select_multiple(True)
        file_type_list = ["all", "pdf"]
        if len(img2pdf_supported_img) > 0:
            file_type_list = ["all", "img2pdf", "pdf"]
        filter_list = self.app._create_filters(file_type_list)
        for f in filter_list:
            chooser.add_filter(f)

        return chooser.run(), chooser

    def paste_as_layer(self, data, destination, laypos):
        lpage_lists = self.app.convert_page_data_to_layerpage_lists(data, laypos)
        if lpage_lists is None or len(destination) == 0:
            return
        dpage = self.app.model[destination[-1]][0]
        lpage_list = lpage_lists[0]
        a = (
            self.app.window,
            dpage,
            lpage_list,
            self.app.model,
            self.app.pdfqueue,
            laypos,
            self.app.layer_pos,
        )
        result = pageutils.PastePageLayerDialog(*a).get_offset_and_rescale()
        if result is None:
            # Dialog canceled
            return
        offset_xy, rescale = result
        self.app.layer_pos = offset_xy
        self.app.undomanager.commit("Add Layer")
        self.app.set_unsaved(True)
        self.app.paste_as_layer(data, destination, laypos, offset_xy, rescale)

    def page_size(self, _action, _parameter, _unknown):
        """Opens a dialog box to define page size."""
        selection = self.app.iconview.get_selected_items()
        diag = pageutils.ScaleDialog(
            self.app.iconview.get_model(), selection, self.app.window
        )
        result = diag.run_get()
        if result is None:
            return
        newscale, mode = result
        if mode == "SCALE":
            self.app.undomanager.commit("Scale")
            if not pageutils.scale(self.app.model, selection, newscale):
                return
        elif mode == "SCALE-ADD-MARG":
            self.app.undomanager.commit("Scale & add margins")
            pageutils.scale(self.app.model, selection, newscale)
            self.app.center_on_blank_page(selection, newscale)
        else:
            self.app.undomanager.commit("Crop & add margins")
            self.app.center_on_blank_page(selection, newscale)
        self.app.set_unsaved(True)
        self.app.update_statusbar()
        self.app.update_iconview_geometry()
        self.app.update_max_zoom_level()
        self.app.scroll_to_selection(center=False)
        GObject.idle_add(self.app.render)
