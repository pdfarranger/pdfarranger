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
import os
import tempfile
from . import metadata
from gi.repository import Gtk
import gettext
_ = gettext.gettext



# Fix pikepdf.Pdf and pikepdf.PageList
# see: https://github.com/pikepdf/pikepdf/issues/196
# see: https://github.com/pikepdf/pikepdf/issues/192
#
# We are augmenting rather than subclassing because we do not instantiate
# the classes directly

@pikepdf._methods.augments(pikepdf._qpdf.PageList)
class FixedPageList:

    def extract(self, p):
        '''extract a page for later reinsertion
           p : 1 based index of page'''
        # We must make sure that there are no duplicate references to the extracted page in the page tree after
        # reinsertion. Replace the extracted page with a copy at its original position in the page tree.
        page = self.p(p)
        self[p-1] = copy.copy(page)
        return page

    def delete_page(self, index):
        '''remove page from the page tree and delete page content(/Contents, /Resources, etc)
           so that it can be removed from the output file'''
        page = self[index]
        for key in page.keys():
            del(page[key])
        del(self[index])

@pikepdf._methods.augments(pikepdf._qpdf.Pdf)
class FixedPdf:

    def append(self, page):
        '''append the actual page, not a copy (so that bookmarks do not get broken)'''
        self._add_page(page)




def create_blank_page(tmpdir, size):
    """
    Create a temporary PDF file with a single empty page.
    The size is in PDF unit (1/72 of inch).
    """
    fd, filename = tempfile.mkstemp(suffix=".pdf", dir=tmpdir)
    os.close(fd)
    f = pikepdf.Pdf.new()
    f.add_blank_page(page_size=size)
    f.save(filename)
    return filename


def _mediabox(page, crop):
    """ Return the media box for a given page. """
    # PDF files which do not have mediabox default to Portrait Letter / ANSI A
    cmb = page.MediaBox if "/MediaBox" in page else [0, 0, 612, 792]
    if "/CropBox" in page:
        cmb = page.CropBox

    if crop == [0., 0., 0., 0.]:
        return cmb
    angle = page.Rotate if '/Rotate' in page else 0
    rotate_times = int(round(((angle) % 360) / 90) % 4)
    crop_init = crop
    if rotate_times != 0:
        perm = [0, 2, 1, 3]
        for _ in range(rotate_times):
            perm.append(perm.pop(0))
        perm.insert(1, perm.pop(2))
        crop = [crop_init[perm[side]] for side in range(4)]
    x1, y1, x2, y2 = [float(x) for x in cmb]
    x1_new = x1 + (x2 - x1) * crop[0]
    x2_new = x2 - (x2 - x1) * crop[1]
    y1_new = y1 + (y2 - y1) * crop[3]
    y2_new = y2 - (y2 - y1) * crop[2]
    return [x1_new, y1_new, x2_new, y2_new]


_report_pikepdf_err = True


def _set_meta(mdata, pdf_input, pdf_output):
    ppae = metadata.PRODUCER not in mdata
    with pdf_output.open_metadata(set_pikepdf_as_editor=ppae) as outmeta:
        if len(pdf_input) > 0:
            metadata.load_from_docinfo(outmeta, pdf_input[0])
        for k, v in mdata.items():
            outmeta[k] = v

def _scale_box(box, factor):
    return [factor * float(x) for x in box]


def _fix_annots(page, factor):
    if '/Annots' in page.keys():
        for annot in page.Annots:
            for key in ('/Rect', '/QuadPoints', '/Vertices', '/CL'):
                if key in annot.keys():
                    annot[key] = _scale_box(annot[key], factor)
            if '/InkList' in annot.keys():
                for i, il in enumerate(annot.InkList):
                    annot.InkList[i] = _scale_box(il, factor)


def _scale(doc, page, factor):
    """ Scale a page """
    if factor == 1:
        return page
    orig_page = page
    page = copy.copy(page)
    page.Rotate = 0
    page = doc.make_indirect(page)
    page_id = len(doc.pages) + 1
    newmediabox = [factor * float(x) for x in page.MediaBox]
    contents = "q {} 0 0 {} 0 0 cm /p{} Do Q".format(factor, factor, page_id)
    xobject = pikepdf.Page(page).as_form_xobject()
    orig_page.MediaBox = newmediabox
    #Question - if we scale a cropped page, do we loose content?
    if '/CropBox' in orig_page.keys(): del(orig_page['/CropBox'])
    orig_page.Contents = doc.make_stream(contents.encode())
    orig_page.Resources = pikepdf.Dictionary({'/XObject': {'/p{}'.format(page_id): xobject}})
    #Question - what else do we need to scale?
    _fix_annots(orig_page, factor)
    return orig_page


def check_content(parent, pdf_list):
    """ Warn about fillable forms or outlines that are lost on export."""
    # TODO: consider further
    # - with new export, only imported pages are affected
    #   - Done
    # - seems wrong to let the user do all the work and only warn him when
    #   he tries to save his work
    warn = False
    for pdf in [pikepdf.open(p.copyname, password=p.password) for p in pdf_list[1:]]:
        if "/AcroForm" in pdf.Root.keys(): # fillable form
            warn = True
            break
        if pdf.open_outline().root: # table of contents
            warn = True
            break
    # the rest is GUI stuff
    # should be moved to different module to facilitate function tests
    # also, providing a warning with a "don't show again" option sounds like
    # a generic requirement that should be factored out into a separate function
    # finally, why are such dialogs not loaded from a .ui file?
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


def export(input_files, pages, file_out, to_multiple, mdata):
    # if exportmode in ['ALL_TO_MULTIPLE', 'SELECTED_TO_MULTIPLE']:
    # this is essentially gui stuff and duplicates code in Pdfarranger
    if to_multiple:
        parts = file_out.rsplit('.', 1)
        for n, page in enumerate(pages):
            # Add page number to filename
            outname = file_out
            if n > 0:
                outname = "".join(parts[:-1]) + str(n + 1) + '.' + parts[-1]
            # This needs rethinking
            # - for selected to multiple these are not page numbers
            #   consider the ase where a document is exported 'TO_MULTIPLE'
            #   The user than crops page 13 nad re-exports it 'SELECTED_TO_MULTIPLE'
            #   result: page 1 gets overwriten with the amended page 13,
            #           the uncorrected page 13 remains as page 13
            #   - needs fixing
            # - page 1 does not get a page number and therefore may potentially overwrite
            #   the source file
            #   - TODO as fix fails test4 (Done, append "page number" to all pages)
            export_single(input_files, [page], outname, mdata)
    else:
        export_single(input_files, pages, file_out, mdata)


def export_single(input_files, pages, file_out, mdata):

    active_files = set()
    appended_pages = set()

    with pikepdf.open(input_files[0].copyname, password=input_files[0].password) as pdf_output:
        # first read the required qpdf pages and attach them to the page list
        for page in pages:
            if page.nfile == 1:
                #
                page.qpdf = pdf_output.pages.extract(page.npage)
            else:
                # might aswell use the opportunity to work out which of the other
                # input_files contain pages in the page list
                active_files.add(page.nfile)

        for nfile, pdfdoc in [(n+1, pdf) for (n, pdf) in enumerate(input_files)
                                if n+1 in active_files ]:
            with pikepdf.open(pdfdoc.copyname, password=pdfdoc.password) as pdf_input:
                for page in pages:
                    if page.nfile == nfile:
                        page.qpdf = pdf_output.copy_foreign(pdf_input.pages.p(page.npage))

        # Fix issue when all pages of main pdf are deleted
        # see https://github.com/pdfarranger/pdfarranger/pull/462#issuecomment-830546209
        # I am not convinced open file - delete all pages - import pages instead of new file - import pages
        # makes sense. Needs further consideration
        dummy = pdf_output.pages.extract(1)

        # delete existing pages
        # could be improved if we want to maintain the page tree
        # rather than flatten it
        while len(pdf_output.pages) > 0:
            pdf_output.pages.delete_page(0)

        # now add the pages
        for page in pages:
            qpdf_page = page.qpdf
            page.qpdf = None
            if qpdf_page.objgen in appended_pages:
                qpdf_page = copy.copy(qpdf_page)
            appended_pages.add(qpdf_page.objgen)
            angle = page.angle
            angle0 = qpdf_page.Rotate if '/Rotate' in qpdf_page else 0

            if angle != 0:
                qpdf_page.Rotate = angle + angle0
            qpdf_page.MediaBox = _mediabox(qpdf_page, page.crop)
            qpdf_page = _scale(pdf_output, qpdf_page, page.scale)

            # Workraround for pikepdf < 2.7.0
            # https://github.com/pikepdf/pikepdf/issues/174
            #
            # removed because it is not required for this version of export

            # Ensure annotations are copied rather than referenced
            # https://github.com/pdfarranger/pdfarranger/issues/437
            # Annotations must be indirect or they cannot be edited
            # Using copy.copy(annot) instead of pikepdf.Dictionary(annot)) to
            # make a new annotations dictionary for compatibility with pikepdf < 2.8.0
            #
            # Temporarily removed because current fix trashes form fields

            # note: we are using our fixed append (
            pdf_output.append(qpdf_page)


        _set_meta(mdata, [pdf_output], pdf_output)

        # Fix issue when all pages of main pdf are deleted (see above)
        del(dummy)

        # see https://github.com/qpdf/qpdf/issues/520
        pdf_output.save(file_out, object_stream_mode=pikepdf.ObjectStreamMode.generate)




def num_pages(filepath):
    """Get number of pages for filepath."""
    try:
        pdf = pikepdf.Pdf.open(filepath)
    except pikepdf._qpdf.PdfError:
        return None
    npages = len(pdf.pages)
    pdf.close()
    return npages
