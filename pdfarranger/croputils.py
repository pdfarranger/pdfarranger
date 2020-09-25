# Copyright (C) 2020 pdfarranger contributors
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

from gi.repository import Gtk
import gettext
import cairo


_ = gettext.gettext


class _CropWidget(Gtk.Frame):
    sides = ('L', 'R', 'T', 'B')
    side_names = {'L': _('Left'), 'R': _('Right'), 'T': _('Top'), 'B': _('Bottom')}
    opposite_sides = {'L': 'R', 'R': 'L', 'T': 'B', 'B': 'T'}

    def __init__(self, model, selection, margin=12):
        super().__init__(label=_('Crop Margins'))
        self.props.margin = margin
        grid = Gtk.Grid()
        grid.set_column_spacing(margin)
        grid.set_row_spacing(margin)
        grid.props.margin = margin
        self.add(grid)
        label = Gtk.Label(
            label=_(
                'Cropping does not remove any content\n'
                'from the PDF file, it only hides it.'
            )
        )
        label.props.margin = margin
        grid.attach(label, 0, 0, 3, 1)
        self.spin_list = []
        units = 2 * [_('% of width')] + 2 * [_('% of height')]
        crop = [0.0, 0.0, 0.0, 0.0]
        if selection:
            pos = model.get_iter(selection[0])
            crop = list(model.get_value(pos, 0).crop)

        for row, side in enumerate(_CropWidget.sides):
            label = Gtk.Label(label=_CropWidget.side_names[side])
            label.set_alignment(0, 0)
            grid.attach(label, 0, row + 1, 1, 1)

            adj = Gtk.Adjustment(
                value=100.0 * crop.pop(0),
                lower=0.0,
                upper=99.0,
                step_increment=1.0,
                page_increment=5.0,
                page_size=0.0,
            )
            spin = Gtk.SpinButton(adjustment=adj, climb_rate=0, digits=1)
            spin.set_activates_default(True)
            spin.connect('value-changed', self.__set_crop_value, self, side)
            self.spin_list.append(spin)
            grid.attach(spin, 1, row + 1, 1, 1)

            label = Gtk.Label(label=units.pop(0))
            label.set_alignment(0, 0)
            grid.attach(label, 2, row + 1, 1, 1)

    @staticmethod
    def __set_crop_value(spinbutton, self, side):
        opp_side = self.opposite_sides[side]
        adj = self.spin_list[self.sides.index(opp_side)].get_adjustment()
        adj.set_upper(99.0 - spinbutton.get_value())

    def get_crop(self):
        return [spin.get_value() / 100.0 for spin in self.spin_list]


class Dialog(Gtk.Dialog):
    """ A dialog box to define margins for page cropping """

    def __init__(self, model, selection, window):
        super().__init__(
            title=(_('Crop Selected Pages')),
            parent=window,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(
                Gtk.STOCK_CANCEL,
                Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OK,
                Gtk.ResponseType.OK,
            ),
        )
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_resizable(False)
        self.crop_widget = _CropWidget(model, selection)
        self.vbox.pack_start(self.crop_widget, False, False, 0)
        self.show_all()
        self.selection = selection

    def run_get(self):
        """ Open the dialog and return the crop value """
        result = self.run()
        crop = None
        if result == Gtk.ResponseType.OK:
            crop = [self.crop_widget.get_crop()] * len(self.selection)
        self.destroy()
        return crop


def white_borders(model, selection, pdfqueue):
    crop = []
    for path in selection:
        it = model.get_iter(path)
        p = model.get_value(it, 0)
        pdfdoc = pdfqueue[p.nfile - 1]

        page = pdfdoc.document.get_page(p.npage - 1)
        w, h = page.get_size()
        w = int(w)
        h = int(h)
        thumbnail = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(thumbnail)
        page.render(cr)
        data = thumbnail.get_data().cast("i", shape=[h, w]).tolist()

        crop_this_page = [0.0, 0.0, 0.0, 0.0]

        # Left
        allwhite = True
        for col in range(w - 1):
            for row in range(h - 1):
                if data[row][col] != 0:
                    allwhite = False
                    crop_this_page[0] = (col) / w
                    break
            if not allwhite:
                break

        # Right
        allwhite = True
        for col in range(w - 1, 0, -1):
            for row in range(h - 1):
                if data[row][col] != 0:
                    allwhite = False
                    crop_this_page[1] = (w - col) / w
                    break
            if not allwhite:
                break

        # Top
        allwhite = True
        for row in range(h - 1):
            for col in range(w - 1):
                if data[row][col] != 0:
                    allwhite = False
                    crop_this_page[2] = (row) / h
                    break
            if not allwhite:
                break

        # Bottom
        allwhite = True
        for row in range(h - 1, 0, -1):
            for col in range(w - 1):
                if data[row][col] != 0:
                    allwhite = False
                    crop_this_page[3] = (h - row) / h
                    break
            if not allwhite:
                break

        crop.append(crop_this_page)
    return crop
