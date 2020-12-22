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


import copy
import pikepdf
import traceback
import sys
from . import metadata
from gi.repository import Gtk
import gettext
_ = gettext.gettext

from decimal import Decimal


def _mediabox(crop, angle, angle0, box):
    """ Return the cropped media box for a given page """
    if crop != (0., 0., 0., 0.):
        rotate_times = int(round(((angle + angle0) % 360) / 90) % 4)
        crop_init = crop
        if rotate_times != 0:
            perm = [0, 2, 1, 3]
            for _ in range(rotate_times):
                perm.append(perm.pop(0))
            perm.insert(1, perm.pop(2))
            crop = [crop_init[perm[side]] for side in range(4)]
        # PyPDF2 FloatObject instances are decimal.Decimal objects
        x1, y1, x2, y2 = [float(x) for x in box]
        x1_new = x1 + (x2 - x1) * crop[0]
        x2_new = x2 - (x2 - x1) * crop[1]
        y1_new = y1 + (y2 - y1) * crop[3]
        y2_new = y2 - (y2 - y1) * crop[2]
        # pikepdf converts float to Decimal in most cases
        return [Decimal(v) for v in [x1_new, y1_new, x2_new, y2_new]]


_report_pikepdf_err = True


def _set_meta(mdata, pdf_input, pdf_output):
    ppae = metadata.PRODUCER not in mdata
    with pdf_output.open_metadata(set_pikepdf_as_editor=ppae) as outmeta:
        if len(pdf_input) > 0:
            metadata.load_from_docinfo(outmeta, pdf_input[0])
        for k, v in mdata.items():
            outmeta[k] = v


def _scale(doc, page, factor):
    """ Scale a page """
    if factor == 1:
        return page
    page = doc.make_indirect(page)
    page_id = len(doc.pages)
    newmediabox = [factor * float(x) for x in page.MediaBox]
    content = "q {} 0 0 {} 0 0 cm /p{} Do Q".format(factor, factor, page_id)
    xobject = pikepdf.Page(page).as_form_xobject()
    new_page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=newmediabox,
        Contents=doc.make_stream(content.encode()),
        Resources={'/XObject': {'/p{}'.format(page_id): xobject}},
    )
    return new_page

def check_content(parent, pdf_list):
    """ Warn about fillable forms or outlines that are lost on export."""
    warn = False
    for pdf in [pikepdf.open(p.copyname, password=p.password) for p in pdf_list]:
        if "/AcroForm" in pdf.Root.keys(): # fillable form
            warn = True
            break
        if pdf.open_outline().root: # table of contents
            warn = True
            break
    if warn:
        d = Gtk.Dialog(_('Warning'),
                       parent=parent,
                       flags=Gtk.DialogFlags.MODAL,
                       buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                Gtk.STOCK_OK, Gtk.ResponseType.OK))
        label = Gtk.Label(_('Forms and outlines are lost on saving.'))
        d.vbox.pack_start(label, False, False, 6)
        checkbutton = Gtk.CheckButton(_('Do not show this dialog again.'))
        d.vbox.pack_start(checkbutton, False, False, 6)
        buttonbox = d.get_action_area()
        buttons = buttonbox.get_children()
        d.set_focus(buttons[1])
        d.show_all()
        response = d.run()
        enable_warnings = not checkbutton.get_active()
        d.destroy()
        return response, enable_warnings
    return Gtk.ResponseType.OK, True


def export(input_files, pages, file_out, mode, mdata):
    exportmodes = {0: 'ALL_TO_SINGLE',
                   1: 'ALL_TO_MULTIPLE',
                   2: 'SELECTED_TO_SINGLE',
                   3: 'SELECTED_TO_MULTIPLE'}
    exportmode = exportmodes[mode.get_int32()]

    global _report_pikepdf_err
    pdf_output = pikepdf.Pdf.new()
    pdf_input = [pikepdf.open(p.copyname, password=p.password) for p in input_files]
    for row in pages:
        current_page = pdf_input[row.nfile - 1].pages[row.npage - 1]
        angle = row.angle
        angle0 = current_page.Rotate if '/Rotate' in current_page else 0
        new_page = pdf_output.copy_foreign(current_page)
        # Workaround for pikepdf <= 1.10.1
        # https://github.com/pikepdf/pikepdf/issues/80#issuecomment-590533474
        try:
            new_page = copy.copy(new_page)
        except TypeError:
            if _report_pikepdf_err:
                _report_pikepdf_err = False
                traceback.print_exc()
                print("Current pikepdf version {}, required pikepdf version "
                      "1.7.0 or greater. Continuing but pdfarranger will not "
                      "work properly.".format(pikepdf.__version__),
                      file=sys.stderr)
        if angle != 0:
            new_page.Rotate = angle + angle0
        # PDF files which do not have mediabox default to Portrait Letter / ANSI A
        cmb = current_page.MediaBox if "/MediaBox" in current_page else [0, 0, 612, 792]
        cropped = _mediabox(row.crop, angle, angle0, cmb)
        if cropped:
            new_page.MediaBox = cropped
        new_page = _scale(pdf_output, new_page, row.scale)
        pdf_output.pages.append(new_page)

    if exportmode in ['ALL_TO_MULTIPLE', 'SELECTED_TO_MULTIPLE']:
        for n, page in enumerate(pdf_output.pages):
            outpdf = pikepdf.Pdf.new()
            _set_meta(mdata, pdf_input, outpdf)
            outpdf.pages.append(page)
            outname = file_out
            parts = file_out.rsplit('.', 1)
            if n > 0:
                # Add page number to filename
                outname = "".join(parts[:-1]) + str(n + 1) + '.' + parts[-1]
            outpdf.remove_unreferenced_resources()
            outpdf.save(outname)
    else:
        _set_meta(mdata, pdf_input, pdf_output)
        pdf_output.remove_unreferenced_resources()
        pdf_output.save(file_out)

def num_pages(filepath):
    """Get number of pages for filepath."""
    try:
        pdf = pikepdf.Pdf.open(filepath)
    except pikepdf._qpdf.PdfError:
        return None
    npages = len(pdf.pages)
    pdf.close()
    return npages
