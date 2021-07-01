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
import locale

_ = gettext.gettext

# TODO rename to pageutils

def scale(model, selection, factor):
    """Set the scale factor of a selection of pages."""
    changed = False
    try:
        width, height = factor
    except TypeError:
        width, height = None, None
    for path in selection:
        it = model.get_iter(path)
        page = model.get_value(it, 0)
        if width is None:
            f = factor
        else:
            # TODO: allow to change aspect ratio
            f = max(width / page.size[0], height / page.size[1])
        # Page size must be in [72, 14400] (PDF standard requirement)
        f = max(f, 72 / page.size[0], 72 / page.size[1])
        f = min(f, 14400 / page.size[0], 14400 / page.size[1])
        if page.scale != f:
            changed = True
        page.resample = page.resample * f / page.scale
        page.scale = f
        model.set_value(it, 0, page)
    return changed


class _LinkedSpinButton(Gtk.SpinButton):
    """ A spin button which can be bound to an other button """

    def __init__(self, minval, maxval, step, page=None):
        Gtk.SpinButton.__init__(self)
        self.set_digits(20)
        self.set_width_chars(9)
        self.connect("output", self.__output)
        self.set_range(minval, maxval)
        self.set_increments(step, step if page is None else page)
        self.changing_from_brother = False

    def __output(self, _user_data):
        """ output signal handler to remove unneeded 0 """
        s = locale.format("%.8g", self.get_adjustment().get_value())
        self.get_buffer().set_text(s, len(s))
        return True


class _RadioStackSwitcher(Gtk.VBox):
    """ Same as GtkStackSwitcher but with radio button (i.e different semantic) """

    def __init__(self, margin=10):
        super().__init__()
        self.set_spacing(margin)
        self.props.margin = margin
        self.radiogroup = []
        self.stack = Gtk.Stack()
        self.button_box = Gtk.HBox()
        self.button_box.set_spacing(margin)
        self.add(self.button_box)
        self.add(self.stack)
        self.selected_child = None
        self.selected_name = None

    def add_named(self, child, name, title):
        radio = Gtk.RadioButton.new_with_label(None, title)
        if len(self.radiogroup) > 0:
            radio.join_group(self.radiogroup[-1])
        self.radiogroup.append(radio)
        radio.set_hexpand(True)
        radio.set_halign(Gtk.Align.CENTER)
        radio.connect("toggled", self.__radio_handler, name)
        self.button_box.add(radio)
        self.stack.add_named(child, name)
        if self.selected_child is None:
            self.selected_child = child
            self.selected_name = name

    def __radio_handler(self, button, name):
        if button.props.active:
            self.stack.set_visible_child_name(name)
            self.selected_name = name
            self.selected_child = self.stack.get_child_by_name(name)


class _RelativeScalingWidget(Gtk.HBox):
    """ A form to specify the relative scaling factor """

    def __init__(self, current_scale, margin=10):
        super().__init__()
        self.props.spacing = margin
        self.add(Gtk.Label(label=_("Scale factor")))
        # Largest page size is 200 inch and smallest is 1 inch
        # so we can set a min and max
        self.entry = _LinkedSpinButton(100 / 200.0, 100 * 200.0, 1, 10)
        self.entry.set_activates_default(True)
        self.add(self.entry)
        self.add(Gtk.Label(label=_("%")))
        self.entry.set_value(current_scale * 100)

    def get_value(self):
        return self.entry.get_value() / 100


class _ScalingWidget(Gtk.HBox):
    """ A form to specify the page width or height """

    def __init__(self, label, default):
        super().__init__()
        self.add(Gtk.Label(label=label))
        self.entry = _LinkedSpinButton(25.4, 5080, 1, 10)
        self.entry.set_activates_default(True)
        self.add(self.entry)
        self.add(Gtk.Label(label=_("mm")))
        # A PDF unit is 1/72 inch
        self.entry.set_value(default * 25.4 / 72)

    def get_value(self):
        return self.entry.get_value() / 25.4 * 72


class _CropWidget(Gtk.Frame):
    sides = ('L', 'R', 'T', 'B')
    side_names = {'L': _('Left'), 'R': _('Right'), 'T': _('Top'), 'B': _('Bottom')}
    opposite_sides = {'L': 'R', 'R': 'L', 'T': 'B', 'B': 'T'}

    def __init__(self, model, selection, margin=12):
        super().__init__(label=_('Crop Margins'))
        grid = Gtk.Grid()
        grid.set_column_spacing(margin)
        grid.set_row_spacing(margin)
        grid.props.margin = margin
        self.add(grid)
        label = Gtk.Label(
            label=_(
                'Cropping does not remove any content '
                'from the PDF file, it only hides it.'
            )
        )
        label.props.margin = margin
        label.set_line_wrap(True)
        label.set_max_width_chars(38)
        grid.attach(label, 0, 0, 3, 1)
        self.spin_list = []
        units = 2 * [_('% of width')] + 2 * [_('% of height')]
        crop = [0.0, 0.0, 0.0, 0.0]
        if selection:
            pos = model.get_iter(selection[0])
            crop = list(model.get_value(pos, 0).crop)

        for row, side in enumerate(_CropWidget.sides):
            label = Gtk.Label(label=_CropWidget.side_names[side])
            label.set_alignment(0.0, 0.5)
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
            label.set_alignment(0.0, 0.5)
            grid.attach(label, 2, row + 1, 1, 1)

    @staticmethod
    def __set_crop_value(spinbutton, self, side):
        opp_side = self.opposite_sides[side]
        adj = self.spin_list[self.sides.index(opp_side)].get_adjustment()
        limit = 99.0 - spinbutton.get_value()
        adj.set_upper(limit)
        opp_spinner = self.spin_list[self.sides.index(opp_side)]
        opp_spinner.set_value(min(opp_spinner.get_value(), limit))

    def get_crop(self):
        return [spin.get_value() / 100.0 for spin in self.spin_list]


class Dialog(Gtk.Dialog):
    """ A dialog box to define margins for page cropping and page size or scale factor """

    def __init__(self, model, selection, window):
        super().__init__(
            title=_("Page format"),
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
        page = model.get_value(model.get_iter(selection[-1]), 0)
        size = [page.scale * x for x in page.size]
        rel_widget = _RelativeScalingWidget(page.scale)
        width_widget = _ScalingWidget(_("Width"), size[0])
        height_widget = _ScalingWidget(_("Height"), size[1])
        self.scale_stack = _RadioStackSwitcher()
        self.scale_stack.add_named(rel_widget, "Relative", _("Relative"))
        self.scale_stack.add_named(width_widget, "Width", _("Width"))
        self.scale_stack.add_named(height_widget, "Height", _("Height"))
        pagesizeframe = Gtk.Frame(label=_("Page Size"))
        pagesizeframe.props.margin = 8
        pagesizeframe.props.margin_bottom = 0
        pagesizeframe.add(self.scale_stack)
        self.vbox.pack_start(pagesizeframe, True, True, 0)
        self.crop_widget = _CropWidget(model, selection)
        self.crop_widget.props.margin = 8
        self.vbox.pack_start(self.crop_widget, False, False, 0)
        self.show_all()
        self.selection = selection

    def run_get(self):
        """ Open the dialog and return the crop value """
        result = self.run()
        crop = None
        val = None
        if result == Gtk.ResponseType.OK:
            crop = [self.crop_widget.get_crop()] * len(self.selection)
            val = self.scale_stack.selected_child.get_value()
            if self.scale_stack.selected_name == "Width":
                val = val, 0
            elif self.scale_stack.selected_name == "Height":
                val = 0, val
            # else val is a relative scale so we return it as is
        self.destroy()
        return crop, val


def white_borders(model, selection, pdfqueue):
    crop = []
    for path in selection:
        it = model.get_iter(path)
        p = model.get_value(it, 0)
        pdfdoc = pdfqueue[p.nfile - 1]

        page = pdfdoc.document.get_page(p.npage - 1)
        # Always render pages at 72 dpi whatever the zoom or scale of the page
        w, h = page.get_size()
        # FIXME: No longer ignore p.crop so we could do nested white border crop
        w = int(w)
        h = int(h)
        thumbnail = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(thumbnail)
        with pdfdoc.render_lock:
            page.render(cr)
        # TODO: python list are dead slow compared to memoryview. It would
        # be faster to create a memoryview full of 0 and then compare each row
        # to it. memoryview have full native __eq__ operator which is fast.
        data = thumbnail.get_data().cast("i", shape=[h, w]).tolist()

        crop_this_page = [0.0, 0.0, 0.0, 0.0]
        # TODO: Those 4 copy/paste should be factorized
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

        crop.append(p.rotate_crop(crop_this_page, p.rotate_times(p.angle)))
    return crop


class BlankPageDialog(Gtk.Dialog):
    def __init__(self, size, window):
        super().__init__(
            title=_("Insert Blank Page"),
            parent=window,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(
                Gtk.STOCK_CANCEL,
                Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OK,
                Gtk.ResponseType.OK,
            ),
        )
        self.width_widget = _ScalingWidget(_("Width"), size[0])
        self.height_widget = _ScalingWidget(_("Height"), size[1])
        self.vbox.pack_start(self.width_widget, True, True, 6)
        self.vbox.pack_start(self.height_widget, True, True, 6)
        self.width_widget.props.spacing = 6
        self.height_widget.props.spacing = 6
        self.show_all()
        self.set_resizable(False)
        self.set_default_response(Gtk.ResponseType.OK)

    def run_get(self):
        result = self.run()
        r = None
        if result == Gtk.ResponseType.OK:
            r = self.width_widget.get_value(), self.height_widget.get_value()
        self.destroy()
        return r

