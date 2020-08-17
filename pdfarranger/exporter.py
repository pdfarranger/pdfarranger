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

from decimal import Decimal


def _mediabox(row, angle, angle0, box):
    """ Return the cropped media box for a given page """
    crop = row[7:11]
    if crop != [0., 0., 0., 0.]:
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


def export(input_files, pages, file_out, mode, mdata):
    exportmodes = {0: 'ALL_TO_SINGLE',
                   1: 'ALL_TO_MULTIPLE',
                   2: 'SELECTED_TO_SINGLE',
                   3: 'SELECTED_TO_MULTIPLE'}
    exportmode = exportmodes[mode.get_int32()]

    global _report_pikepdf_err
    pdf_output = pikepdf.Pdf.new()
    pdf_input = [pikepdf.open(p.copyname) for p in input_files]
    for row in pages:
        current_page = pdf_input[row[2] - 1].pages[row[3] - 1]
        angle = row[6]
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
        cropped = _mediabox(row, angle, angle0, current_page.MediaBox)
        if cropped:
            new_page.MediaBox = cropped
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
            outpdf.save(outname)
    else:
        _set_meta(mdata, pdf_input, pdf_output)
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
