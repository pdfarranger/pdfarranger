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
import os
import traceback
import sys
import warnings
import tempfile
from . import metadata
from gi.repository import Gtk
import gettext
_ = gettext.gettext



def create_blank_page(tmpdir, size):
    """
    Create a temporary PDF file with a single empty page.
    The size is in PDF unit (1/72 of inch).
    """
    f, filename = make_tmp_file(tmpdir)
    f.add_blank_page(page_size=size)
    f.save(filename)
    return filename


def make_tmp_file(tmpdir):
    fd, filename = tempfile.mkstemp(suffix=".pdf", dir=tmpdir)
    os.close(fd)
    f = pikepdf.Pdf.new()
    return f, filename


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


def _scale(doc, page, factor):
    """ Scale a page """
    if factor == 1:
        return page
    rotate = 0
    if "/Rotate" in page:
        # We'll set the rotate attribute on the resulting page so we must
        # unset it on the input page before
        rotate = page.Rotate
        page.Rotate = 0
    page_id = len(doc.pages)
    newmediabox = [factor * float(x) for x in page.MediaBox]
    content = "q {} 0 0 {} 0 0 cm /p{} Do Q".format(factor, factor, page_id)
    xobject = pikepdf.Page(page).as_form_xobject()
    new_page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=newmediabox,
        Contents=doc.make_stream(content.encode()),
        Resources={'/XObject': {'/p{}'.format(page_id): xobject}},
        Rotate=rotate,
    )
    # This was needed for pikepdf <= 2.6.0. See https://github.com/pikepdf/pikepdf/issues/174
    # It's also needed with pikepdf 4.2 else we get:
    # RuntimeError: QPDFPageObjectHelper::getFormXObjectForPage called with a direct object
    # when calling as_form_xobject in generate_booklet
    new_page = doc.make_indirect(new_page)
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
                       buttons=("_Cancel", Gtk.ResponseType.CANCEL,
                                "_OK", Gtk.ResponseType.OK))
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


def _update_angle(model_page, source_page, output_page):
    angle = model_page.angle
    angle0 = source_page.Rotate if '/Rotate' in source_page else 0
    if angle != 0:
        output_page.Rotate = angle + angle0


def _apply_geom_transform(pdf_output, new_page, row):
    _update_angle(row, new_page, new_page)
    new_page.MediaBox = _mediabox(new_page, row.crop)
    return _scale(pdf_output, new_page, row.scale)


def _remove_unreferenced_resources(pdfdoc):
    try:
        pdfdoc.remove_unreferenced_resources()
    except RuntimeError:
	# Catch "RuntimeError: operation for dictionary attempted on object of
	# type null" with old version PikePDF (observed with 1.17 and 1.19).
	# Blindly catch all RuntimeError is dangerous as this may catch
	# unwanted exception so we print it.
        print(traceback.format_exc())

def warn_dialog(func):
    """ Decorator which redirect warnings and error messages to a gtk MessageDialog """
    class ShowWarning:
        def __init__(self):
            self.buffer = ""

        def __call__(self, message, category, filename, lineno, f=None, line=None):
            s = warnings.formatwarning(message, category, filename, lineno, line)
            if sys.stderr is not None:
                sys.stderr.write(s + '\n')
            self.buffer += str(message) + '\n'

    def wrapper(*args, **kwargs):
        export_msg = args[-1]
        backup_showwarning = warnings.showwarning
        warnings.showwarning = ShowWarning()
        try:
            func(*args, **kwargs)
            if len(warnings.showwarning.buffer) > 0:
                export_msg.put([warnings.showwarning.buffer, Gtk.MessageType.WARNING])
        except Exception as e:
            traceback.print_exc()
            export_msg.put([e, Gtk.MessageType.ERROR])
        finally:
            warnings.showwarning = backup_showwarning

    return wrapper

def export_process(*args, **kwargs):
    """Export PDF in a separate process."""
    warn_dialog(export)(*args, **kwargs)

def export(files, pages, mdata, exportmode, file_out, quit_flag, _export_msg):
    global _report_pikepdf_err
    pdf_output = pikepdf.Pdf.new()
    pdf_input = [pikepdf.open(copyname, password=password) for copyname, password in files]
    copied_pages = {}
    # Copy pages from the input PDF files to the output PDF file
    for row in pages:
        if quit_flag.is_set():
            return
        current_page = pdf_input[row.nfile - 1].pages[row.npage - 1]
        # if the page already exists in the output PDF, duplicate it
        new_page = copied_pages.get((row.nfile, row.npage))
        if new_page is None:
            # for backward compatibility with old pikepdf. With pikepdf > 3
            # new_page = current_page should be enough
            new_page = pdf_output.copy_foreign(current_page)
        # let pdf_output adopt new_page
        pdf_output.pages.append(new_page)
        new_page = pdf_output.pages[-1]
        copied_pages[(row.nfile, row.npage)] = new_page
        # Ensure annotations are copied rather than referenced
        # https://github.com/pdfarranger/pdfarranger/issues/437
        if pikepdf.Name.Annots in current_page:
            pdf_temp = pikepdf.Pdf.new()
            pdf_temp.pages.append(current_page)
            indirect_annots = pdf_temp.make_indirect(pdf_temp.pages[0].Annots)
            new_page.Annots = pdf_output.copy_foreign(indirect_annots)

    # Apply geometrical transformations in the output PDF file
    for page_id, row in enumerate(pages):
        if quit_flag.is_set():
            return
        pdf_output.pages[page_id] = _apply_geom_transform(
            pdf_output, pdf_output.pages[page_id], row
        )

    mdata = metadata.merge(mdata, files)
    if exportmode in ['ALL_TO_MULTIPLE', 'SELECTED_TO_MULTIPLE']:
        for n, page in enumerate(pdf_output.pages):
            if quit_flag.is_set():
                return
            outpdf = pikepdf.Pdf.new()
            _set_meta(mdata, pdf_input, outpdf)
            # needed to add this, probably related to pikepdf < 2.7.0 workaround
            page = outpdf.copy_foreign(page)
            # works without make_indirect as already applied to this page
            outpdf.pages.append(page)
            outname = file_out
            parts = file_out.rsplit('.', 1)
            if n > 0:
                # Add page number to filename
                outname = "".join(parts[:-1]) + str(n + 1) + '.' + parts[-1]
            _remove_unreferenced_resources(outpdf)
            outpdf.save(outname)
    else:
        _set_meta(mdata, pdf_input, pdf_output)
        _remove_unreferenced_resources(pdf_output)
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


def generate_booklet(pdfqueue, tmp_dir, pages):
    file, filename = make_tmp_file(tmp_dir)
    content_dict = pikepdf.Dictionary({})
    file_indexes = {p.nfile for p in pages}
    source_files = {n: pikepdf.open(pdfqueue[n - 1].copyname) for n in file_indexes}
    for i in range(len(pages)//2):
        even = i % 2 == 0
        first = pages[-i - 1 if even else i]
        second = pages[i if even else -i - 1]

        second_page_size = second.size_in_points()
        first_page_size = first.size_in_points()
        page_size = [max(second_page_size[0], first_page_size[0]) * 2,
                     max(second_page_size[1], first_page_size[1])]

        first_original = source_files[first.nfile].pages[first.npage - 1]
        first_foreign = _apply_geom_transform(
            file, file.copy_foreign(first_original), first
        )

        second_original = source_files[second.nfile].pages[second.npage - 1]
        second_foreign = _apply_geom_transform(
            file, file.copy_foreign(second_original), second
        )

        content_dict[f'/Page{i*2}'] = pikepdf.Page(first_foreign).as_form_xobject()
        content_dict[f'/Page{i*2 + 1}'] = pikepdf.Page(second_foreign).as_form_xobject()
        # See PDF reference section 4.2.3 Transformation Matrices
        tx1 = -first_foreign.MediaBox[0]
        ty1 = -first_foreign.MediaBox[1]
        tx2 = first_page_size[0] - float(second_foreign.MediaBox[0])
        ty2 = -second_foreign.MediaBox[1]
        content_txt = (
            f"q 1 0 0 1 {tx1} {ty1} cm /Page{i*2} Do Q "
            f"q 1 0 0 1 {tx2} {ty2} cm /Page{i*2 + 1} Do Q "
        )

        newpage = pikepdf.Dictionary(
                Type=pikepdf.Name.Page,
                MediaBox=[0, 0, *page_size],
                Resources=pikepdf.Dictionary(XObject=content_dict),
                Contents=pikepdf.Stream(file, content_txt.encode())
            )

        # workaround for pikepdf <= 2.6.0. See https://github.com/pikepdf/pikepdf/issues/174
        if pikepdf.__version__ < '2.7.0':
            newpage = file.make_indirect(newpage)
        file.pages.append(newpage)

    file.save(filename)
    return filename

