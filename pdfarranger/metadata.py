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
from gi.repository import Gtk
_ = gettext.gettext

PRODUCER = '{http://ns.adobe.com/pdf/1.3/}Producer'
# List of supported meta data with their user representation
# see https://wwwimages2.adobe.com/content/dam/acom/en/devnet/xmp/pdfs/XMP%20SDK%20Release%20cc-2016-08/XMPSpecificationPart1.pdf
# if you want to add more
_LABELS = {
    '{http://purl.org/dc/elements/1.1/}title': _('Title'),
    '{http://purl.org/dc/elements/1.1/}creator': _('Creator'),
    PRODUCER: _('Producer'),
    '{http://ns.adobe.com/xap/1.0/}CreatorTool': _('Creator tool')
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


def merge(metadata, input_files):
    """ Merge current global metadata and each imported files meta data """
    r = metadata.copy()
    for p in input_files:
        doc = pikepdf.open(p.copyname)
        with doc.open_metadata() as meta:
            meta.load_from_docinfo(doc.docinfo)
            for k, v in meta.items():
                if k not in metadata and _pikepdf_meta_is_valid(v):
                    r[k] = v
    return r


def _metatostr(meta):
    """ Convert a meta data value from list to string if it's not a string """
    if isinstance(meta, str):
        return meta, False
    elif isinstance(meta, list):
        return json.dumps(meta), True
    else:
        None, None


class _EditedEventHandler(object):
    def __init__(self, liststore):
        self.liststore = liststore

    def __call__(self, renderer, path, newtext):
        self.liststore[path][1] = newtext


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
                        buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                 Gtk.STOCK_OK, Gtk.ResponseType.OK))
    dialog.set_default_response(Gtk.ResponseType.OK)
    # Property, Value, is json (hidden), XMP name (hidden)
    liststore = Gtk.ListStore(str, str, bool, str)
    mergedmetadata = merge(metadata, pdffiles)
    for xlabel, label in _LABELS.items():
        metastr, isjson = _metatostr(mergedmetadata.get(xlabel, ''))
        liststore.append([label, metastr, isjson, xlabel])
    treeview = Gtk.TreeView.new_with_model(liststore)
    for i, v in enumerate([(_("Property"), False), (_("Value")+" "*30, True)]):
        title, editable = v
        renderer = Gtk.CellRendererText()
        if editable:
            renderer.set_property("editable", True)
            renderer.connect("edited", _EditedEventHandler(liststore))
        column = Gtk.TreeViewColumn(title, renderer, text=i)
        treeview.append_column(column)
    treeview.props.margin = 12
    dialog.vbox.pack_start(treeview, True, True, 0)
    dialog.show_all()
    result = dialog.run()
    r = result == Gtk.ResponseType.OK
    dialog.destroy()
    if r:
        for row in liststore:
            value = json.loads(row[1]) if row[2] else row[1]
            metadata[row[3]] = value
    return r
