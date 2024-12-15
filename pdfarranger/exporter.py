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
import io
import gi
import locale
from typing import Any, Dict, List

from . import metadata
from gi.repository import Gtk
gi.require_version("Poppler", "0.18")
from gi.repository import Poppler
import gettext
_ = gettext.gettext

from .core import Page, Sides

# pikepdf.Page.add_overlay()/add_underlay() can't place a page exactly
# if for example LC_NUMERIC=fi_FI
try:
    locale.setlocale(locale.LC_NUMERIC, 'C')
except locale.Error:
    pass  # Gtk already prints a warning

if os.name == 'nt':
    # Work around https://github.com/pdfarranger/pdfarranger/issues/1110
    locale.setlocale(locale.LC_COLLATE, 'C')


def get_blank_doc(pageadder, pdfqueue, tmpdir, size, npages=1):
    """Search pdfqueue for a matching pdf with blank pages. Create it if it does not exist.

    Some notes:
    Blank pdf documents are created prior to export (vs created as needed at export)
    because it will keep code simpler. For example rendering of thumbnails require no
    extra for rendering of a blank page.

    A document with several blank pages is needed if the page number under thumbnail
    need to be something else than 1.
    """
    for i, pdfdoc in enumerate(pdfqueue):
        if size == pdfdoc.blank_size and npages == pdfdoc.document.get_n_pages():
            filename = pdfdoc.copyname
            nfile = i + 1
            return filename, nfile
    filename = _create_blank_page(tmpdir, size, npages)
    doc_data = pageadder.get_pdfdoc(filename, description=None, blank_size=size)
    if doc_data is None:
        return None, None
    nfile = doc_data[1]
    return filename, nfile


def _create_blank_page(tmpdir, size, npages=1):
    """
    Create a temporary PDF file with npages empty pages.
    The size is in PDF unit (1/72 of inch).
    """
    f, filename = make_tmp_file(tmpdir)
    f.add_blank_page(page_size=size)
    for __ in range(npages - 1):
        f.pages.append(f.pages[0])
    f.save(filename)
    return filename


def make_tmp_file(tmpdir):
    fd, filename = tempfile.mkstemp(suffix=".pdf", dir=tmpdir)
    os.close(fd)
    f = pikepdf.Pdf.new()
    return f, filename


def _normalize_rectangle(rect):
    """
    PDF Specification 1.7, 7.9.5, although rectangles are conventionally
    specified by their lower-left and upper-right corners, it is acceptable to
    specify any two diagonally opposite corners. Applications that process PDF
    should be prepared to normalize such rectangles in situations where
    specific corners are required.
    """
    rect = [float(x) for x in rect]
    if rect[0] > rect[2]:
        rect[0], rect[2] = rect[2], rect[0]
    if rect[1] > rect[3]:
        rect[1], rect[3] = rect[3], rect[1]
    return rect


def _intersect_rectangle(rect1, rect2):
    return [
        max(rect1[0], rect2[0]),
        max(rect1[1], rect2[1]),
        min(rect1[2], rect2[2]),
        min(rect1[3], rect2[3]),
    ]


def _mediabox(page, crop=Sides()):
    """ Return the media box for a given page. """
    # PDF files which do not have mediabox default to Portrait Letter / ANSI A
    cmb = page.MediaBox if "/MediaBox" in page else [0, 0, 612, 792]
    cmb = _normalize_rectangle(cmb)
    if "/CropBox" in page:
        # PDF specification §14.11.2.1, "If they do, they are effectively
        # reduced to their intersection with the media box"
        cmb = _intersect_rectangle(cmb, _normalize_rectangle(page.CropBox))

    if crop == Sides():
        return cmb
    angle = page.Rotate if '/Rotate' in page else 0
    rotate_times = int(round(((angle) % 360) / 90) % 4)
    crop_init = crop
    if rotate_times != 0:
        perm = [0, 2, 1, 3]
        for _ in range(rotate_times):
            perm.append(perm.pop(0))
        perm.insert(1, perm.pop(2))
        crop = Sides(*(crop_init[perm[side]] for side in range(4)))
    x1, y1, x2, y2 = [float(x) for x in cmb]
    x1_new = x1 + (x2 - x1) * crop.left
    x2_new = x2 - (x2 - x1) * crop.right
    y1_new = y1 + (y2 - y1) * crop.bottom
    y2_new = y2 - (y2 - y1) * crop.top
    return [x1_new, y1_new, x2_new, y2_new]


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
    # It's also needed for pikepdf 8.8 but not for pikepdf 6.0.1
    new_page = doc.make_indirect(new_page)
    return new_page


def _update_angle(model_page, source_page, output_page):
    angle = model_page.angle
    angle0 = source_page.Rotate if '/Rotate' in source_page else 0
    if angle != 0:
        new_angle = angle + angle0
        if new_angle >= 360:
            new_angle -= 360
        output_page.Rotate = new_angle


def _apply_geom_transform(pdf_output, new_page, row):
    _update_angle(row, new_page, new_page)
    new_page.MediaBox = _mediabox(new_page, row.crop)
    # add_overlay() & add_underlay() will use TrimBox or CropBox if they exist
    if '/TrimBox' in new_page:
        del new_page.TrimBox
    if '/CropBox' in new_page:
        del new_page.CropBox
    return pikepdf.Page(_scale(pdf_output, new_page, row.scale))


def _apply_geom_transform_job(pdf_output:pikepdf.Pdf, new_page:pikepdf.Page, page:Page) -> None:
    new_page.rotate(page.angle, relative=True)
    new_page.MediaBox = _mediabox(new_page, page.crop)
    # add_overlay() & add_underlay() will use TrimBox or CropBox if they exist
    if '/TrimBox' in new_page:
        del new_page.TrimBox
    if '/CropBox' in new_page:
        del new_page.CropBox
    if page.scale != 1:
        pdf_output.pages.append(new_page)
        new_page.obj.emplace(_scale(pdf_output, pdf_output.pages[-1], page.scale))
        del(pdf_output.pages[-1])



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
        export_msg = kwargs["export_msg"]
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


def _copy_n_transform(pdf_input, pdf_output, pages, quit_flag=None):
    # all pages must be copied to pdf_output BEFORE applying geometrical
    # transformation. See https://github.com/pikepdf/pikepdf/issues/271
    copied_pages = {}
    mediaboxes = []
    # Copy pages from the input PDF files to the output PDF file
    for row in pages:
        if quit_flag is not None and quit_flag.is_set():
            return
        current_page = pdf_input[row.nfile - 1].pages[row.npage - 1]
        mediaboxes.append(_mediabox(current_page))
        _append_page(current_page, copied_pages, pdf_output, row)
        # Layer pages are temporary added after the page they belong to
        for lprow in row.layerpages:
            layer_page = pdf_input[lprow.nfile - 1].pages[lprow.npage - 1]
            _append_page(layer_page, copied_pages, pdf_output, lprow)

    # Apply geometrical transformations in the output PDF file
    i = 0
    for row in pages:
        if quit_flag is not None and quit_flag.is_set():
            return

        pdf_output.pages[i] = _apply_geom_transform(pdf_output, pdf_output.pages[i], row)
        for lprow in row.layerpages:
            i += 1
            pdf_output.pages[i] = _apply_geom_transform(pdf_output, pdf_output.pages[i], lprow)
        i += 1

    # Add overlays and underlays
    for i, row in enumerate(pages):
        # The dest page coordinates and size before geometrical transformations
        dx1, dy1, dx2, dy2 = mediaboxes[i]
        dw, dh = dx2 - dx1, dy2 - dy1

        dpage = pdf_output.pages[i]
        dangle0 = dpage.Rotate if '/Rotate' in dpage else 0
        rotate_times = int(round(((dangle0) % 360) / 90) % 4)
        for lprow in row.layerpages:
            # Rotate the offsets so they are relative to dest page
            offset = lprow.offset.rotated(rotate_times)
            offs_left, offs_right, offs_top, offs_bottom = offset
            x1 = row.scale * (dx1 + dw * offs_left)
            y1 = row.scale * (dy1 + dh * offs_bottom)
            x2 = row.scale * (dx1 + dw * (1 - offs_right))
            y2 = row.scale * (dy1 + dh * (1 - offs_top))
            rect = pikepdf.Rectangle(x1, y1, x2, y2)

            layer_page = pdf_output.pages[i + 1]
            if lprow.laypos == 'OVERLAY':
                pdf_output.pages[i].add_overlay(layer_page, rect)
            else:
                pdf_output.pages[i].add_underlay(layer_page, rect)
            # Remove the temporary added page
            del pdf_output.pages[i + 1]


def _append_page(current_page, copied_pages, pdf_output, row):
    """Add a page to the output pdf. A page that already exist is duplicated."""
    new_page = copied_pages.get((row.nfile, row.npage))
    if new_page is None:
        new_page = current_page
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


def _transform_job(pdf_output: pikepdf.Pdf, pages: List[Page], quit_flag = None) -> None:
    """ Same as _copy_n_transform, except it doesn't copy. Requires pikepdf >= 8.0 """
    # Fix missing MediaBoxes
    for page in pdf_output.pages:
        if page.mediabox is None:
            page.mediabox = pikepdf.Array((0, 0, 612, 792))

    # We don't need to call _append_page as the Job interface copies pages / annotations as necessary.
    mediaboxes:List[pikepdf.Rectangle] = []
    i = 0
    for page in pages:
        if quit_flag is not None and quit_flag.is_set():
            return
        mediaboxes.append(pikepdf.Rectangle(pdf_output.pages[i].mediabox))
        _apply_geom_transform_job(pdf_output, pdf_output.pages[i], page)
        for lpage in page.layerpages:
            i += 1
            _apply_geom_transform_job(pdf_output, pdf_output.pages[i], lpage)
        i += 1

    # # Add overlays and underlays
    for i, page in enumerate(pages):
        # The dest page coordinates and size before geometrical transformations
        mb = mediaboxes[i]

        # Call to rotate in _apply_geom_transform_job ensures /Rotate exists
        rotate_times = int(round((pdf_output.pages[i].Rotate % 360) / 90) % 4)
        for lpage in page.layerpages:
            # Rotate the offsets so they are relative to dest page
            offset = lpage.offset.rotated(rotate_times)
            offs_left, offs_right, offs_top, offs_bottom = offset
            x1 = page.scale * (mb.llx + mb.width * offs_left)
            y1 = page.scale * (mb.lly + mb.height * offs_bottom)
            x2 = page.scale * (mb.llx + mb.width * (1 - offs_right))
            y2 = page.scale * (mb.lly + mb.height * (1 - offs_top))
            rect = pikepdf.Rectangle(x1, y1, x2, y2)

            if lpage.laypos == 'OVERLAY':
                pdf_output.pages[i].add_overlay(pdf_output.pages[i + 1], rect)
            else:
                pdf_output.pages[i].add_underlay(pdf_output.pages[i + 1], rect)
            # Remove the temporary added page
            del pdf_output.pages[i + 1]


def get_max_pdf_version(pdf_list: List[pikepdf.Pdf]) -> str:
    """Return the highest pdf version used in pdf list"""
    versions = []
    for pdf in pdf_list:
        if pdf is None:
            # Can be None when printing
            continue
        versions.append(pdf.pdf_version)
    return max(*versions)


def export_doc(pdf_input, pages, mdata, files_out, quit_flag, test_mode=False):
    """Same as export() but with pikepdf.PDF objects instead of files"""
    pdf_output = pikepdf.Pdf.new()
    max_version = get_max_pdf_version([pdf_output, *pdf_input])
    _copy_n_transform(pdf_input, pdf_output, pages, quit_flag)
    if quit_flag is not None and quit_flag.is_set():
        return
    if isinstance(files_out[0], str):
        # Only needed when saving to file, not when printing
        mdata = metadata.merge_doc(mdata, pdf_input)
    if len(files_out) > 1:
        for n, page in enumerate(pdf_output.pages):
            if quit_flag is not None and quit_flag.is_set():
                return
            outpdf = pikepdf.Pdf.new()
            _set_meta(mdata, pdf_input, outpdf)
            # works without make_indirect as already applied to this page
            outpdf.pages.append(page)
            _remove_unreferenced_resources(outpdf)
            outpdf.save(files_out[n], min_version=max_version)
    else:
        if isinstance(files_out[0], str):
            if not test_mode:
                _set_meta(mdata, pdf_input, pdf_output)
            _remove_unreferenced_resources(pdf_output)
        if test_mode:
            pdf_output.save(files_out[0], qdf=True, static_id=True, compress_streams=False,
                stream_decode_level=pikepdf.StreamDecodeLevel.all,
                min_version=max_version,
            )
        else:
            pdf_output.save(files_out[0], min_version=max_version)


def _add_json_entries(json: Dict[str, Any], files: List[List[str]], page: Page) -> None:
    """Create an entry for the job json "pages" list."""
    pages_entry = {"file": files[page.nfile - 1][0],  # copyname
                   "range": str(page.npage)}
    if len(files[page.nfile - 1][1]) > 0:
        pages_entry["password"] = files[page.nfile - 1][1]
    json["pages"].append(pages_entry)


def _create_job(files: List[List[str]], pages: List[Page], files_out: List[str], quit_flag=None,
                test_mode: bool = False):
    """ Same as _copy_n_transform, except it use the pikepdf Job interface. Requires pikepdf >= 8.0 """
    # Generate the output PDF file including temporary overlay/ underlay pages. We don't need to call
    # _append_page as the Job interface copies pages / annotations as necessary. We can also delay getting
    # our MediaBoxes until the transformation stage.
    json = dict(outputFile=files_out[0], pages=[], removeUnreferencedResources="yes")
    if test_mode:
        json.update(qdf="", staticId="", compressStreams="n", decodeLevel="all")
    if len(files) > 0 and len(files[0][0]) > 0:
        json["inputFile"] = files[0][0]  # We are treating files [0] as the main document
        if len(files[0][1]) > 0:
            json["password"] = files[0][1]
    else:
        json["inputFile"] = "."

    for page in pages:
        if quit_flag is not None and quit_flag.is_set():
            return None
        _add_json_entries(json, files, page)
        for lpage in page.layerpages:
            # Layer pages are temporarily added after the page they belong to
            _add_json_entries(json, files, lpage)
    return pikepdf.Job(json)


def export_doc_job(pdf_input: List[pikepdf.Pdf], files: List[List[str]], pages: List[Page], mdata, files_out: List[str],
                   quit_flag, test_mode: bool = False) -> None:
    """  Same as export() but uses the pikepdf Job interface. Requires pikedf >= 8.0. """
    job = _create_job(files, pages, files_out, quit_flag, test_mode)
    pdf_output = job.create_pdf()
    max_version = get_max_pdf_version([pdf_output, *pdf_input])

    _transform_job(pdf_output, pages, quit_flag)

    if quit_flag is not None and quit_flag.is_set():
        return
    if isinstance(files_out[0], str):
        # Only needed when saving to file, not when printing
        mdata = metadata.merge_doc(mdata, pdf_input)
    if len(files_out) > 1:
        for n, page in enumerate(pdf_output.pages):
            if quit_flag is not None and quit_flag.is_set():
                return
            outpdf = pikepdf.Pdf.new()
            _set_meta(mdata, pdf_input, outpdf)
            outpdf.pages.append(page)
            _remove_unreferenced_resources(outpdf)
            outpdf.save(files_out[n], min_version=max_version)
    else:
        if isinstance(files_out[0], str) and not test_mode:
            _set_meta(mdata, [pdf_output], pdf_output)
        job.write_pdf(pdf_output)


def export(files, pages, mdata, files_out, quit_flag, config, test_mode=False, **kwargs):
    pdf_input = [
        pikepdf.open(copyname, password=password) for copyname, password in files
    ]
    if config.start_with_empty():
        export_doc(pdf_input, pages, mdata, files_out, quit_flag, test_mode)
    else:
        export_doc_job(pdf_input, files, pages, mdata, files_out, quit_flag, test_mode)


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
    file_indexes = set()
    for p in pages:
        file_indexes.add(p.nfile)
        for lp in p.layerpages:
            file_indexes.add(lp.nfile)
    source_files = {n-1: pikepdf.open(pdfqueue[n - 1].copyname) for n in file_indexes}
    max_version = max(pdf.pdf_version for pdf in source_files.values())
    _copy_n_transform(source_files, file, pages)
    to_remove = len(file.pages)
    npages = len(pages)
    for i in range(npages//2):
        even = i % 2 == 0
        first_id = -i - 1 if even else i
        second_id = i if even else -i - 1
        if first_id < 0:
            first_id += npages
        if second_id < 0:
            second_id += npages
        first = pages[first_id]
        second = pages[second_id]
        first_foreign = file.pages[first_id]
        second_foreign = file.pages[second_id]
        second_page_size = second.size_in_points()
        first_page_size = first.size_in_points()
        page_size = [max(second_page_size[0], first_page_size[0]) * 2,
                     max(second_page_size[1], first_page_size[1])]

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

        file.pages.append(pikepdf.Page(newpage))
    for __ in range(to_remove):
        del file.pages[0]
    file.save(filename, min_version=max_version)
    return filename


class PrintSettingsWidget(Gtk.Grid):
    def __init__(self, scale_mode, auto_rotate):
        super().__init__(margin=0, row_spacing=6, column_spacing=12, border_width=12)
        lbl = Gtk.Label(_("Scale mode:"), margin=0)
        self.combo = Gtk.ComboBoxText(margin=0)
        self.combo.append("NONE", _("None"))
        self.combo.append("PRINTABLE", _("Fit to Printable Area"))
        self.combo.append("FULL", _("Fit to Full Page"))
        self.combo.set_active_id(scale_mode)
        self.cb = Gtk.CheckButton(label=_("Auto Rotate"), margin=0)
        self.cb.set_active(auto_rotate)
        self.attach(lbl, 0, 1, 1, 1)
        self.attach(self.combo, 1, 1, 2, 1)
        self.attach(self.cb, 0, 2, 2, 1)
        self.show_all()

    def get_scale_mode(self):
        return self.combo.get_active_id()

    def get_auto_rotate(self):
        return self.cb.get_active()


# Adapted from https://stackoverflow.com/questions/28325525/python-gtk-printoperation-print-a-pdf
class PrintOperation(Gtk.PrintOperation):
    MESSAGE=_("Printing…")
    def __init__(self, app):
        super().__init__(embed_page_setup=True, support_selection=True)
        self.app = app
        self.connect("create-custom-widget", self.create_custom_widget)
        self.connect("custom-widget-apply", self.custom_widget_apply)
        self.connect("request-page-setup", self.request_page_setup)
        self.connect("begin-print", self.begin_print, None)
        self.connect("end-print", self.end_print, None)
        self.connect("draw-page", self.draw_page, None)
        self.connect("preview", self.preview, None)
        self.pdf_input = None
        self.message = self.MESSAGE
        self.scale_mode = self.app.config.scale_mode()
        self.auto_rotate = self.app.config.auto_rotate()
        self.set_use_full_page(self.scale_mode != 'PRINTABLE')
        self.snums = [p.get_indices() for p in reversed(app.iconview.get_selected_items())]
        self.set_has_selection(len(self.snums) > 0)

    def create_custom_widget(self, operation):
        self.set_custom_tab_label(_("Page Handling"))
        return PrintSettingsWidget(self.scale_mode, self.auto_rotate)

    def custom_widget_apply(self, operation, widget):
        self.scale_mode = widget.get_scale_mode()
        self.auto_rotate = widget.get_auto_rotate()
        self.set_use_full_page(self.scale_mode != 'PRINTABLE')

    def request_page_setup(self, operation, print_ctx, page_num, setup):
        if self.auto_rotate:
            w_page = self.pages[page_num].width_in_points()
            h_page = self.pages[page_num].height_in_points()
            if w_page >= h_page:
                setup.set_orientation(Gtk.PageOrientation.LANDSCAPE)
            else:
                setup.set_orientation(Gtk.PageOrientation.PORTRAIT)

    def preview(self, operation, preview_op, print_ctx, parent, user_data):
        self.message = _("Rendering Preview…")

    def begin_print(self, operation, print_ctx, print_data):
        self.app.set_export_state(True, self.message)
        psel = self.get_print_settings().get_print_pages() == Gtk.PrintPages.SELECTION
        nums = self.snums if psel else range(len(self.app.model))
        self.pages = [self.app.model[n][0].duplicate(incl_thumbnail=False) for n in nums]
        self.app.apply_hide_margins_on_pages(self.pages)
        self.set_n_pages(len(self.pages))

        # Open pikepdf objects for all pages that has been modified
        nfiles = set()
        for p in self.pages:
            if p.unmodified():
                continue
            nfiles.add(p.nfile)
            for lp in p.layerpages:
                nfiles.add(lp.nfile)
        self.pdf_input = [None] * len(self.app.pdfqueue)
        for nfile in nfiles:
            pdf = self.app.pdfqueue[nfile - 1]
            self.pdf_input[nfile - 1] = pikepdf.open(pdf.copyname, password=pdf.password)

    def end_print(self, operation, print_ctx, print_data):
        self.app.set_export_state(False)
        self.message = self.MESSAGE
        self.app.config.set_scale_mode(self.scale_mode)
        self.app.config.set_auto_rotate(self.auto_rotate)

    def draw_page(self, operation, print_ctx, page_num, print_data):
        cairo_ctx = print_ctx.get_cairo_context()
        # Poppler context is always 72 dpi
        cairo_ctx.scale(print_ctx.get_dpi_x() / 72, print_ctx.get_dpi_y() / 72)
        if page_num >= len(self.app.model):
            return
        setup = print_ctx.get_page_setup()
        if self.scale_mode == 'PRINTABLE':
            w_paper = setup.get_page_width(Gtk.Unit.POINTS)
            h_paper = setup.get_page_height(Gtk.Unit.POINTS)
        else:
            w_paper = setup.get_paper_width(Gtk.Unit.POINTS)
            h_paper = setup.get_paper_height(Gtk.Unit.POINTS)
        w_page = self.pages[page_num].width_in_points()
        h_page = self.pages[page_num].height_in_points()
        print_scale = self.get_print_settings().get_scale() / 100
        scale = 1
        if self.scale_mode != 'NONE':
            w_scale = w_paper / (w_page * print_scale)
            h_scale = h_paper / (h_page * print_scale)
            scale = min(w_scale, h_scale)
            cairo_ctx.scale(scale, scale)

        # Center page on paper
        dx = w_paper / (scale * print_scale) - w_page
        dy = h_paper / (scale * print_scale) - h_page
        cairo_ctx.translate(dx / 2, dy / 2)

        p = self.pages[page_num]
        if p.unmodified():
            pdfdoc = self.app.pdfqueue[p.nfile - 1]
            page = pdfdoc.document.get_page(p.npage - 1)
            with pdfdoc.render_lock:
                page.render_for_printing(cairo_ctx)
        else:
            buf = io.BytesIO()
            export_doc(self.pdf_input, [p], {}, [buf], None)
            page = Poppler.Document.new_from_data(buf.getvalue()).get_page(0)
            page.render_for_printing(cairo_ctx)

    def run(self):
        result = super().run(Gtk.PrintOperationAction.PRINT_DIALOG, self.app.window)
        if result == Gtk.PrintOperationResult.ERROR:
            dialog = Gtk.MessageDialog(
                self.app.window,
                0,
                Gtk.MessageType.ERROR,
                Gtk.ButtonsType.CLOSE,
                self.get_error(),
            )
            dialog.run()
            dialog.destroy()
