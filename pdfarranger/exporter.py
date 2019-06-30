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

from PyPDF2 import PdfFileWriter, PdfFileReader
from copy import copy


def pypdf2(input_files, pages, file_out):
    pdf_output = PdfFileWriter()
    pdf_input = []
    metadata = None
    for pdfdoc in input_files:
        pdfdoc_inp = PdfFileReader(open(pdfdoc.copyname, 'rb'), strict=False, overwriteWarnings=False)
        if pdfdoc_inp.getIsEncrypted():
            try:  # Workaround for lp:#355479
                stat = pdfdoc_inp.decrypt('')
            except:
                stat = 0
            if stat != 1:
                errmsg = _('File %s is encrypted.\n'
                           'Support for encrypted files has not been implemented yet.\n'
                           'File export failed.') % pdfdoc.filename
                raise Exception(errmsg)
            # FIXME
            # else
            #   ask for password and decrypt file
        if metadata is None:
            # get the metadata of the first imported document
            metadata = pdfdoc_inp.getDocumentInfo()
        pdf_input.append(pdfdoc_inp)

    for row in pages:
        # add pages from input to output document
        nfile = row[2]
        npage = row[3]
        current_page = copy(pdf_input[nfile - 1].getPage(npage - 1))
        angle = row[6]
        angle0 = current_page.get("/Rotate", 0)
        # Workaround for https://github.com/mstamy2/PyPDF2/issues/337
        angle0 = angle0 if isinstance(angle0, int) else angle0.getObject()
        crop = [row[7], row[8], row[9], row[10]]
        if angle != 0:
            current_page.rotateClockwise(angle)
        if crop != [0., 0., 0., 0.]:
            rotate_times = int(round(((angle + angle0) % 360) / 90) % 4)
            crop_init = crop
            if rotate_times != 0:
                perm = [0, 2, 1, 3]
                for it in range(rotate_times):
                    perm.append(perm.pop(0))
                perm.insert(1, perm.pop(2))
                crop = [crop_init[perm[side]] for side in range(4)]
            x1, y1 = [float(xy) for xy in current_page.mediaBox.lowerLeft]
            x2, y2 = [float(xy) for xy in current_page.mediaBox.upperRight]
            x1_new = int(x1 + (x2 - x1) * crop[0])
            x2_new = int(x2 - (x2 - x1) * crop[1])
            y1_new = int(y1 + (y2 - y1) * crop[3])
            y2_new = int(y2 - (y2 - y1) * crop[2])
            current_page.mediaBox.lowerLeft = (x1_new, y1_new)
            current_page.mediaBox.upperRight = (x2_new, y2_new)

        pdf_output.addPage(current_page)
    if metadata is not None:
        metadata = {k: v for k, v in metadata.items()
                    if isinstance(v, (str, bytes))}
        pdf_output.addMetadata(metadata)
    # finally, write "output" to document-output.pdf
    with open(file_out, 'wb') as f:
        pdf_output.write(f)
