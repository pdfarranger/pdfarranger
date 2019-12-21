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


import pikepdf
import re

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
        crop = [Decimal(x) for x in crop]
        x1, y1, x2, y2 = box
        x1_new = x1 + (x2 - x1) * crop[0]
        x2_new = x2 - (x2 - x1) * crop[1]
        y1_new = y1 + (y2 - y1) * crop[3]
        y2_new = y2 - (y2 - y1) * crop[2]
        return [x1_new, y1_new, x2_new, y2_new]


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


def export(input_files, pages, file_out):
    pdf_output = pikepdf.Pdf.new()
    pdf_input = [pikepdf.open(p.copyname) for p in input_files]
    for row in pages:
        current_page = pdf_input[row[2] - 1].pages[row[3] - 1]
        angle = row[6]
        angle0 = current_page.Rotate if '/Rotate' in current_page else 0
        if angle != 0:
            current_page.Rotate = angle + angle0
        cropped = _mediabox(row, angle, angle0, current_page.MediaBox)
        if cropped:
            current_page.MediaBox = cropped
        pdf_output.pages.append(current_page)
    with pdf_output.open_metadata() as outmeta:
        outmeta.load_from_docinfo(pdf_input[0].docinfo)
        for k, v in pdf_input[0].open_metadata().items():
            if _pikepdf_meta_is_valid(v):
                outmeta[k] = v
    pdf_output.save(file_out)