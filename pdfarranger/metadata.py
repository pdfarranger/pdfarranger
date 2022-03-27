# Copyright (C) 2020 Jerome Robert
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

""" PDF meta data edition """

import pikepdf
import gettext
import re
import json
import traceback
from datetime import datetime
from dateutil import parser
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
_ = gettext.gettext

# The producer property can be overriden by pikepdf
PRODUCER = '{http://ns.adobe.com/pdf/1.3/}Producer'
# Currently the only property which support lists as values. If you add more
# please implement a generic mecanism.
_CREATOR = '{http://purl.org/dc/elements/1.1/}creator'
_CREATED = '{http://ns.adobe.com/xap/1.0/}CreateDate'
_MODIFIED = '{http://ns.adobe.com/xap/1.0/}ModifyDate'
# List of supported meta data with their user representation
# see https://wwwimages2.adobe.com/content/dam/acom/en/devnet/xmp/pdfs/XMP%20SDK%20Release%20cc-2016-08/XMPSpecificationPart1.pdf
# if you want to add more
_LABELS = {
    '{http://purl.org/dc/elements/1.1/}title': _('Title'),
    '{http://purl.org/dc/elements/1.1/}description': _('Subject'),
    '{http://ns.adobe.com/pdf/1.3/}Keywords': _('Keywords'),
    PRODUCER: _('Producer'),
    _CREATOR: _('Creator'),
    '{http://ns.adobe.com/xap/1.0/}CreatorTool': _('Creator tool'),
    _CREATED: _('Created'),
    _MODIFIED: _('Modified'),
}


def _pikepdf_meta_is_valid(meta):
    """
    Return true if m is a valid PikePDF meta data value.
    PikePDF pass meta data to re.sub which only accept str or byte-like object.
    """
    if not isinstance(meta, list):
        meta = [meta]
    for s in meta:
        try:
            re.sub('', '', s)
        except TypeError:
            return False
    return True


def load_from_docinfo(meta, doc):
    """
    wrapper of pikepdf.models.PdfMetadata.load_from_docinfo with a workaround
    for https://github.com/pikepdf/pikepdf/issues/100 & 162
    """
    try:
        meta.load_from_docinfo(doc.docinfo)
    except (NotImplementedError, TypeError):
        # DocumentInfo cannot be loaded and will be lost. Not a that big issue.
        traceback.print_exc()


def _safeiter(elements):
    it = iter(elements)
    while True:
        try:
            yield next(it)
        except StopIteration:
            break
        except ValueError:
            traceback.print_exc()


def merge(metadata, input_files):
    """ Merge current global metadata and each imported files meta data """
    r = metadata.copy()
    for copyname, password in input_files:
        doc = pikepdf.open(copyname, password=password)
        with doc.open_metadata() as meta:
            load_from_docinfo(meta, doc)
            for k, v in _safeiter(meta.items()):
                if not _pikepdf_meta_is_valid(v):
                    # workaround for https://github.com/pikepdf/pikepdf/issues/84
                    del meta[k]
                elif k not in metadata:
                    r[k] = v
    return r


def _metatostr(value, name):
    """ Convert a meta data value from list to string if it's not a string """
    if isinstance(value, str):
        return value
    elif isinstance(value, list) and name == _CREATOR:
        if len(value) == 1:
            return _metatostr(value[0], name)
        else:
            return json.dumps(value)
    return ''


def _strtometa(value, name):
    try:
        r = json.loads(value) if name == _CREATOR else value
        if isinstance(r, list):
            return None if len(r) == 0 else r
        else:
            # r is a dict which is not supported so we revert back
            # to a plain string
            return value
    except json.decoder.JSONDecodeError:
        return value


class _EditedEventHandler(object):
    """
    Callbacks to save the data entered into the "Edit properties" fields.

    For basic saving just the edited method would be needed. The rest is a
    workaround for Gtk interpreting a lost focus (including clicking "Apply")
    as a cancelled edit and therefore discarding the edit currently in progress.
    To avoid that, we need to save the text on each changed event to
    self.new_text and then save it to the liststore on canceled. We can not
    save it directly to the liststore since that stops editing after each
    keypress.
    """

    def __init__(self, liststore):
        self.liststore = liststore
        self.path = None
        self.new_text = None

    def started(self, _renderer, editable, path):
        self.path = path
        editable.connect("changed", self.editable_changed)

    def editable_changed(self, editable):
        self.new_text = editable.get_text()

    @staticmethod
    def _parse_date(string, parent):
        try:
            date = parser.parse(string)
            return datetime.isoformat(date) # ISO-8601 formatted date
        except ValueError:
            if string:
                msg = _('Invalid date format. Input discarded.')
                d = Gtk.MessageDialog(parent=parent,
                                      flags=Gtk.DialogFlags.MODAL,
                                      type=Gtk.MessageType.ERROR,
                                      buttons=Gtk.ButtonsType.OK,
                                      message_format=msg)
                d.run()
                d.destroy()
            return ''

    def edited(self, _renderer, path, new_text, parent):
        date_labels = [_LABELS[l] for l in [_CREATED, _MODIFIED]]
        if self.liststore[path][0] in date_labels:
            new_text = self._parse_date(new_text, parent)
        self.liststore[path][1] = new_text

    def canceled(self, _renderer):
        if self.new_text is not None:
            self.liststore[self.path][1] = self.new_text


def edit(metadata, pdffiles, parent):
    """
    Edit the current meta data

    :param metadata: The dictionnary of meta data to modify
    :param pdffiles: A list of PDF from witch to take the initial meta data
    :param parent: The parent window
    """
    dialog = Gtk.Dialog(title=_('Edit properties'),
                        parent=parent,
                        flags=Gtk.DialogFlags.MODAL,
                        buttons=("_Cancel", Gtk.ResponseType.CANCEL,
                                 "_OK", Gtk.ResponseType.OK))
    ok_button = dialog.get_widget_for_response(response_id = Gtk.ResponseType.OK)
    ok_button.grab_focus()
    # Property, Value, XMP name (hidden)
    liststore = Gtk.ListStore(str, str, str)
    mergedmetadata = merge(metadata, pdffiles)
    for xlabel, label in _LABELS.items():
        metastr = _metatostr(mergedmetadata.get(xlabel, ''), xlabel)
        liststore.append([label, metastr, xlabel])
    treeview = Gtk.TreeView.new_with_model(liststore)
    for i, v in enumerate([(_("Property"), False), (_("Value")+" "*30, True)]):
        title, editable = v
        renderer = Gtk.CellRendererText()
        if editable:
            renderer.set_property("editable", True)
            handler = _EditedEventHandler(liststore)
            renderer.connect("editing-started", handler.started)
            renderer.connect("edited", handler.edited, parent)
            renderer.connect("editing-canceled", handler.canceled)
        column = Gtk.TreeViewColumn(title, renderer, text=i)
        treeview.append_column(column)
    treeview.props.margin = 12
    treeview.set_enable_search(False)
    treeview.set_cursor(Gtk.TreePath(0), treeview.get_column(1), True)
    dialog.vbox.pack_start(treeview, True, True, 0)
    dialog.show_all()
    result = dialog.run()
    r = result == Gtk.ResponseType.OK
    dialog.destroy()
    if r:
        for row in liststore:
            # Capture invalid input when the emission of the edited signal is
            # bypassed by pressing OK while editing.
            if row[2] in [_CREATED, _MODIFIED]:
                row[1] = handler._parse_date(row[1], parent)

            metadata[row[2]] = _strtometa(row[1], row[2])
    return r
