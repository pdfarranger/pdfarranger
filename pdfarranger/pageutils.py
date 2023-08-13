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

from gi.repository import Gtk, Gdk, GObject
import gettext
import cairo
import locale

from math import pi

from .core import Sides, PDFRenderer

_ = gettext.gettext


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
        for lp in page.layerpages:
            lp.scale = lp.scale * f / page.scale
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


class _RadioStackSwitcher(Gtk.Box):
    """ Same as GtkStackSwitcher but with radio button (i.e different semantic) """

    def __init__(self, margin=10):
        super().__init__()
        self.props.orientation = Gtk.Orientation.VERTICAL
        self.set_spacing(margin)
        self.props.margin = margin
        self.radiogroup = []
        self.stack = Gtk.Stack()
        self.button_box = Gtk.Box()
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


class _RelativeScalingWidget(Gtk.Box):
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


class _ScalingWidget(Gtk.Box):
    """ A form to specify the page width or height """

    def __init__(self, label, default, margin=10):
        super().__init__()
        self.props.spacing = margin
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
                upper=90.0,
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
        limit = 90.0 - spinbutton.get_value()
        adj.set_upper(limit)
        opp_spinner = self.spin_list[self.sides.index(opp_side)]
        opp_spinner.set_value(min(opp_spinner.get_value(), limit))

    def get_crop(self):
        return [spin.get_value() / 100.0 for spin in self.spin_list]


class BaseDialog(Gtk.Dialog):
    def __init__(self, title, parent):
        super().__init__(
            title=title,
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(
                _("_Cancel"), Gtk.ResponseType.CANCEL,
                _("_OK"), Gtk.ResponseType.OK,
            ),
        )
        self.set_default_response(Gtk.ResponseType.OK)


class Dialog(BaseDialog):
    """ A dialog box to define margins for page cropping and page size or scale factor """

    def __init__(self, model, selection, window):
        super().__init__(title=_("Page format"), parent=window)
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
        orig_crop = p.crop.rotated(-p.rotate_times(p.angle))

        first_col = int(w * orig_crop.left)
        last_col = min(int(w), int(w * (1 - orig_crop.right) + 1))
        first_row = int(h * orig_crop.top)
        last_row = min(int(h), int(h * (1 - orig_crop.bottom) + 1))
        w = int(w)
        h = int(h)
        thumbnail = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(thumbnail)
        with pdfdoc.render_lock:
            page.render(cr)
        data = thumbnail.get_data().cast("i")
        whitecol = memoryview(b"\0" * h * 4).cast("i")
        whiterow = memoryview(b"\0" * w * 4).cast("i")
        crop_this_page = [0.0, 0.0, 0.0, 0.0]
        # Left
        for col in range(first_col, last_col):
            if data[col::w] != whitecol:
                crop_this_page[0] = col / w
                break

        # Right
        for col in range(last_col - 1, first_col - 1, -1):
            if data[col::w] != whitecol:
                crop_this_page[1] = (w - col) / w
                break

        # Top
        for row in range(first_row, last_row):
            if data[row * w : (row + 1) * w] != whiterow:
                crop_this_page[2] = (row) / h
                break

        # Bottom
        for row in range(last_row - 1, first_row - 1, -1):
            if data[row * w : (row + 1) * w] != whiterow:
                crop_this_page[3] = (h - row) / h
                break

        crop.append(Sides(*crop_this_page).rotated(p.rotate_times(p.angle)))
    return crop


class BlankPageDialog(BaseDialog):
    def __init__(self, size, window):
        super().__init__(title=_("Insert Blank Page"), parent=window)
        self.set_resizable(False)
        self.width_widget = _ScalingWidget(_("Width"), size[0])
        self.height_widget = _ScalingWidget(_("Height"), size[1])
        self.vbox.pack_start(self.width_widget, True, True, 6)
        self.vbox.pack_start(self.height_widget, True, True, 6)
        self.width_widget.props.spacing = 6
        self.height_widget.props.spacing = 6
        self.show_all()

    def run_get(self):
        result = self.run()
        r = None
        if result == Gtk.ResponseType.OK:
            r = self.width_widget.get_value(), self.height_widget.get_value()
        self.destroy()
        return r


class MergePagesDialog(BaseDialog):

    def __init__(self, window, size, equal):
        super().__init__(title=_("Merge Pages"), parent=window)
        self.size = size
        self.set_resizable(False)
        max_margin = int(((14400 - max(*size)) / 2) * 25.4 / 72)
        self.marg = Gtk.SpinButton.new_with_range(0, max_margin, 1)
        self.marg.set_activates_default(True)
        self.marg.connect('value-changed', self.on_sb_value_changed)
        self.cols = Gtk.SpinButton.new_with_range(1, 2, 1)
        self.cols.set_activates_default(True)
        self.cols.connect('value-changed', self.on_sb_value_changed)
        self.rows = Gtk.SpinButton.new_with_range(1, 1, 1)
        self.rows.set_activates_default(True)
        self.rows.connect('value-changed', self.on_sb_value_changed)

        marg_lbl1 = Gtk.Label(_("Margin"), halign=Gtk.Align.START)
        marg_lbl2 = Gtk.Label(_("mm"), halign=Gtk.Align.START)
        cols_lbl1 = Gtk.Label(_("Columns"), halign=Gtk.Align.START)
        rows_lbl1 = Gtk.Label(_("Rows"), halign=Gtk.Align.START)
        grid1 = Gtk.Grid(column_spacing=12, row_spacing=12, margin=12, halign=Gtk.Align.CENTER)
        grid1.attach(marg_lbl1, 0, 1, 1, 1)
        grid1.attach(self.marg, 1, 1, 1, 1)
        grid1.attach(marg_lbl2, 2, 1, 1, 1)
        grid1.attach(cols_lbl1, 0, 2, 1, 1)
        grid1.attach(self.cols, 1, 2, 1, 1)
        grid1.attach(rows_lbl1, 0, 3, 1, 1)
        grid1.attach(self.rows, 1, 3, 1, 1)
        self.vbox.pack_start(grid1, False, False, 8)

        self.hor = Gtk.RadioButton(label=_("Horizontal"), group=None)
        vrt = Gtk.RadioButton(label=_("Vertical"), group=self.hor)
        self.l_r = Gtk.RadioButton(label=_("Left to Right"), group=None)
        r_l = Gtk.RadioButton(label=_("Right to Left"), group=self.l_r)
        self.t_b = Gtk.RadioButton(label=_("Top to Bottom"), group=None)
        b_t = Gtk.RadioButton(label=_("Bottom to Top"), group=self.t_b)
        grid2 = Gtk.Grid(column_spacing=6, row_spacing=12, margin=12, halign=Gtk.Align.CENTER)
        grid2.attach(self.hor, 0, 1, 1, 1)
        grid2.attach(vrt, 1, 1, 1, 1)
        grid2.attach(self.l_r, 0, 2, 1, 1)
        grid2.attach(r_l, 1, 2, 1, 1)
        grid2.attach(self.t_b, 0, 3, 1, 1)
        grid2.attach(b_t, 1, 3, 1, 1)
        frame1 = Gtk.Frame(label=_("Page Order"), margin=8)
        frame1.add(grid2)
        self.vbox.pack_start(frame1, False, False, 0)

        t = "" if equal else _("Non-uniform page size - using max size")
        warn_lbl = Gtk.Label(t, margin=8, wrap=True, width_chars=36, max_width_chars=36)
        self.vbox.pack_start(warn_lbl, False, False, 0)
        self.size_lbl = Gtk.Label(halign=Gtk.Align.CENTER, margin_bottom=16)
        self.vbox.pack_start(self.size_lbl, False, False, 0)
        self.show_all()

    def size_with_margin(self):
        width = self.size[0] + 2 * self.marg.get_value() * 72 / 25.4
        height = self.size[1] + 2 * self.marg.get_value() * 72 / 25.4
        return width, height

    def on_sb_value_changed(self, _button):
        width, height = self.size_with_margin()
        self.cols.set_range(1, 14400 // width)
        self.rows.set_range(1, 14400 // height)
        cols = int(self.cols.get_value())
        rows = int(self.rows.get_value())
        width = str(round(cols * width * 25.4 / 72, 1))
        height = str(round(rows * height * 25.4 / 72, 1))
        t =  _("Merged page size:") + " " + width + _("mm") + " \u00D7 " + height + _("mm")
        self.size_lbl.set_label(t)

    def run_get(self):
        self.cols.set_value(2)
        result = self.run()
        if result != Gtk.ResponseType.OK:
            self.destroy()
            return None
        cols = int(self.cols.get_value())
        rows = int(self.rows.get_value())
        range_cols = range(cols) if self.l_r.get_active() else range(cols)[::-1]
        range_rows = range(rows) if self.t_b.get_active() else range(rows)[::-1]
        if self.hor.get_active():
            order = [(row, col) for row in range_rows for col in range_cols]
        else:
            order = [(row, col) for col in range_cols for row in range_rows]
        self.destroy()
        return cols, rows, order, self.size_with_margin()


class _OffsetWidget(Gtk.Frame):
    def __init__(self, offset, dpage, lpage):
        super().__init__(shadow_type=Gtk.ShadowType.NONE)
        self.spinb_x = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.spinb_x.set_activates_default(True)
        self.spinb_x.set_digits(1)
        self.spinb_x.connect('value-changed', self.spinb_val_changed)
        self.spinb_y = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.spinb_y.set_activates_default(True)
        self.spinb_y.set_digits(1)
        self.spinb_y.connect('value-changed', self.spinb_val_changed)
        self.spinb_changed_callback = None

        lbl1_x = Gtk.Label(_("Horizontal offset"), halign=Gtk.Align.START)
        lbl2_x = Gtk.Label(_("%"), halign=Gtk.Align.START)
        lbl1_y = Gtk.Label(_("Vertical offset"), halign=Gtk.Align.START)
        lbl2_y = Gtk.Label(_("%"), halign=Gtk.Align.START)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=12, halign=Gtk.Align.CENTER)
        grid.attach(lbl1_x, 0, 1, 1, 1)
        grid.attach(self.spinb_x, 1, 1, 1, 1)
        grid.attach(lbl2_x, 2, 1, 1, 1)
        grid.attach(lbl1_y, 0, 2, 1, 1)
        grid.attach(self.spinb_y, 1, 2, 1, 1)
        grid.attach(lbl2_y, 2, 2, 1, 1)
        self.add(grid)

        self.spinb_x.set_value(offset[0] * 100)
        self.spinb_y.set_value(offset[1] * 100)
        self.set_scale(dpage, lpage)

    def spinb_val_changed(self, spinbutton):
        if callable(self.spinb_changed_callback):
            self.spinb_changed_callback()

    def set_spinb_changed_callback(self, callback):
        self.spinb_changed_callback = callback

    def set_val(self, values):
        self.spinb_x.set_value(values.left * self.scale.left)
        self.spinb_y.set_value(values.top * self.scale.top)

    def get_val(self):
        """Get left, right, top, bottom offset from dest page edges."""
        xval = self.spinb_x.get_value()
        yval = self.spinb_y.get_value()
        return Sides(xval, 100 - xval, yval, 100 - yval) / self.scale

    def get_diff_offset(self):
        """Get the fraction of page size differenace at top-left."""
        return self.spinb_x.get_value() / 100, self.spinb_y.get_value() / 100

    def set_scale(self, dpage, lpage):
        """Set scale between 'destination page edge offset' and 'page size diff offset'."""
        dw, dh = dpage.size_in_pixel()
        lw, lh = lpage.size_in_pixel()
        scalex = 100 * dw / (dw - lw) if dw - lw != 0 else 1e10
        scaley = 100 * dh / (dh - lh) if dh - lh != 0 else 1e10
        self.scale = Sides(scalex, scalex, scaley, scaley)


class DrawingAreaWidget(Gtk.Box):
    """A widget which draws a page. It has tools for editing a rectangle (offset)."""

    def __init__(self, page, pdfqueue, spinbutton_widget=None, draw_on_page_func=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        page = page.duplicate()
        page.thumbnail = page.thumbnail if page.crop == Sides() else None
        page.resample = -1
        self.damodel = Gtk.ListStore(GObject.TYPE_PYOBJECT)
        self.damodel.append([page])
        self.pdfqueue = pdfqueue
        self.spinbutton_widget = spinbutton_widget
        self.padding = 25  # Around thumbnail
        self.click_pos = 0, 0
        self.click_val = [0] * 4
        self.x_po_rel_thmb = 0
        self.y_po_rel_thmb = 0
        self.x_po_rel_sw = 0
        self.y_po_rel_sw = 0
        self.cursor_name = 'default'
        self.rendering_thread = None
        self.render_id = None
        self.surface = None
        self.adjust_rect = [0] * 4
        self.allow_adjust_rect_resize = True
        self.handle_move_limits = True
        self.draw_on_page = draw_on_page_func
        self.da = Gtk.DrawingArea()
        self.da.set_events(self.da.get_events()
                              | Gdk.EventMask.BUTTON_PRESS_MASK
                              | Gdk.EventMask.BUTTON_RELEASE_MASK
                              | Gdk.EventMask.POINTER_MOTION_MASK)
        self.da.connect('draw', self.on_draw)
        self.da.connect('button-press-event', self.button_press_event)
        self.da.connect('button-release-event', self.button_release_event)
        self.da.connect('motion-notify-event', self.motion_notify_event)
        self.da.connect('size_allocate', self.size_allocate)

        self.sw = Gtk.ScrolledWindow()
        self.sw.set_size_request(self.padding + 100, self.padding + 100)
        self.sw.add(self.da)
        self.sw.connect('size_allocate', self.draw_page)
        self.sw.connect('scroll_event', self.sw_scroll_event)
        self.sw.connect('leave_notify_event', self.sw_leave_notify_event)
        self.pack_start(self.sw, True, True, 0)

        if self.spinbutton_widget is not None:
            self.spinbutton_widget.set_spinb_changed_callback(self.draw_page)
            self.pack_start(self.spinbutton_widget, False, False, 0)
            cb = Gtk.CheckButton(label=_("Show values"), margin=12, halign=Gtk.Align.CENTER)
            cb.connect('toggled', self.cb_show_val_toggled)
            cb.connect('realize', self.cb_realize)
            self.pack_start(cb, False, False, 0)

    def cb_realize(self, _cb):
        self.spinbutton_widget.hide()

    def cb_show_val_toggled(self, cb):
        self.spinbutton_widget.set_visible(cb.get_active())

    def store_pointer_location(self, sw, event):
        """Store pointer location relative to thumbnail and scrolled window."""
        ha = sw.get_hadjustment()
        thmb_x = event.x - self.padding + ha.get_value()
        self.x_po_rel_thmb = thmb_x / (ha.get_upper() - self.padding * 2)
        self.x_po_rel_sw = event.x / ha.get_page_size()

        va = sw.get_vadjustment()
        thmb_y = event.y - self.padding + va.get_value()
        self.y_po_rel_thmb = thmb_y / (va.get_upper() - self.padding * 2)
        self.y_po_rel_sw = event.y / va.get_page_size()

    def sw_scroll_event(self, sw, event):
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return Gdk.EVENT_PROPAGATE
        w = max(p.width_in_pixel() for [p] in self.damodel)
        h = max(p.height_in_pixel() for [p] in self.damodel)
        maxfactor = (80000000 / (w * h)) ** .5  # Limit zoom at about 304Mb

        if event.direction == Gdk.ScrollDirection.SMOOTH:
            dy = event.get_scroll_deltas()[2]
            if dy < 0:
                factor = round(min(1.3, maxfactor), 2)
            elif dy > 0:
                factor = 0.7
            else:
                return Gdk.EVENT_PROPAGATE
        elif event.direction == Gdk.ScrollDirection.UP:
            factor = round(min(1.3, maxfactor), 2)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            factor = 0.7
        else:
            return Gdk.EVENT_PROPAGATE
        self.store_pointer_location(sw, event)
        dpage = self.damodel[0][0]
        self.da.set_size_request((dpage.width_in_pixel() + self.padding * 2) * factor,
                                 (dpage.height_in_pixel() + self.padding * 2) * factor)
        return Gdk.EVENT_STOP

    def size_allocate(self, _da, da_rect):
        self.set_adjustment_values()
        self.set_zoom(da_rect)
        self.init_surface()
        self.silent_render()

    def set_adjustment_values(self):
        """Update adjustment values so it does zoom in at cursor."""
        ha = self.sw.get_hadjustment()
        thmb_x = (ha.get_upper() - self.padding * 2) * self.x_po_rel_thmb
        sw_x = ha.get_page_size() * self.x_po_rel_sw
        ha.set_value(self.padding + thmb_x - sw_x)

        va = self.sw.get_vadjustment()
        thmb_y = (va.get_upper() - self.padding * 2) * self.y_po_rel_thmb
        sw_y = va.get_page_size() * self.y_po_rel_sw
        va.set_value(self.padding + thmb_y - sw_y)

    def set_zoom(self, da_rect):
        dpage = self.damodel[0][0]
        thmb_max_w = da_rect.width - self.padding * 2
        thmb_max_h = da_rect.height - self.padding * 2
        zoom_x = thmb_max_w / dpage.width_in_points()
        zoom_y = thmb_max_h / dpage.height_in_points()
        for [page] in self.damodel:
            page.zoom = min(zoom_x, zoom_y)

    def silent_render(self):
        if self.render_id:
            GObject.source_remove(self.render_id)
        self.render_id = GObject.timeout_add(149, self.render)

    def quit_rendering(self):
        if self.rendering_thread is None:
            return False
        self.rendering_thread.quit = True
        self.rendering_thread.join(timeout=0.01)
        return self.rendering_thread.is_alive()

    def render(self):
        self.render_id = None
        alive = self.quit_rendering()
        if alive:
            self.silent_render()
            return
        self.rendering_thread = PDFRenderer(self.damodel, self.pdfqueue, [0, 1] , 1)
        self.rendering_thread.connect('update_thumbnail', self.update_thumbnail)
        self.rendering_thread.start()

    def update_thumbnail(self, _obj, ref, thumbnail, _zoom, _scale, _is_preview):
        if thumbnail is None:
            return
        path = ref.get_path()
        page = self.damodel[path][0]
        page.thumbnail = thumbnail
        self.draw_page()

    def button_press_event(self, _darea, event):
        self.click_pos = event.x, event.y
        if event.button == 2:
            self.set_cursor('move')
        elif event.button == 1 and self.spinbutton_widget is not None:
            self.click_val = self.spinbutton_widget.get_val()

    def button_release_event(self, _darea, event):
        sc = self.get_suggested_cursor(event)
        self.set_cursor(sc)

    def get_suggested_cursor(self, event):
        """Get appropriate cursor when moving mouse over adjust rect (offset)."""
        margin = 5
        r = self.adjust_rect
        if self.allow_adjust_rect_resize:
            w = r[0] - margin < event.x < r[0] + margin
            e = r[0] + r[2] - margin < event.x < r[0] + r[2] + margin
            n = r[1] - margin < event.y < r[1] + margin
            s = r[1] + r[3] - margin < event.y < r[1] + r[3] + margin
        else:
            w = e = n = s = False
        x_area = r[0] + margin < event.x < r[0] + r[2] - margin
        y_area = r[1] + margin < event.y < r[1] + r[3] - margin

        if n and w:
            cursor_name = 'nw-resize'
        elif s and w:
            cursor_name = 'sw-resize'
        elif s and e:
            cursor_name = 'se-resize'
        elif n and e:
            cursor_name = 'ne-resize'
        elif w and y_area:
            cursor_name = 'w-resize'
        elif e and y_area:
            cursor_name = 'e-resize'
        elif n and x_area:
            cursor_name = 'n-resize'
        elif s and x_area:
            cursor_name = 's-resize'
        elif x_area and y_area:
            cursor_name = 'move'
        else:
            cursor_name = 'default'
        return cursor_name

    def set_cursor(self, cursor_name):
        if cursor_name != self.cursor_name:
            self.cursor_name = cursor_name
            cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), cursor_name)
            self.get_window().set_cursor(cursor)

    def motion_notify_event(self, _darea, event):
        if event.state & Gdk.ModifierType.BUTTON2_MASK:
            self.pan_view(event)
            self.set_cursor('move')
        elif event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.adjust_val(event)
        else:
            sc = self.get_suggested_cursor(event)
            self.set_cursor(sc)

    def pan_view(self, event):
        ha = self.sw.get_hadjustment()
        va = self.sw.get_vadjustment()
        ha.set_value(ha.get_value() + self.click_pos[0] - event.x)
        va.set_value(va.get_value() + self.click_pos[1] - event.y)

    def adjust_val(self, event):
        if self.spinbutton_widget is None:
            return
        left, right, top, bottom = self.spinbutton_widget.get_val()
        page = self.damodel[0][0]
        if self.cursor_name in ['w-resize', 'nw-resize', 'sw-resize', 'move']:
            left = self.click_val[0] + ((event.x - self.click_pos[0]) / page.width_in_pixel())
        if self.cursor_name in ['e-resize', 'ne-resize', 'se-resize', 'move']:
            right = self.click_val[1] - ((event.x - self.click_pos[0]) / page.width_in_pixel())
        if self.cursor_name in ['n-resize', 'nw-resize', 'ne-resize', 'move']:
            top = self.click_val[2] + ((event.y - self.click_pos[1]) / page.height_in_pixel())
        if self.cursor_name in ['s-resize', 'sw-resize', 'se-resize', 'move']:
            bottom = self.click_val[3] - ((event.y - self.click_pos[1]) / page.height_in_pixel())
        v = Sides(left, right, top, bottom)
        if self.cursor_name in ['move'] and self.handle_move_limits:
            v += Sides(*(min(0, v[i]) for i in [1, 0, 3, 2]))
        self.spinbutton_widget.set_spinb_changed_callback(None)
        self.spinbutton_widget.set_val(v)
        self.spinbutton_widget.set_spinb_changed_callback(self.draw_page)
        self.draw_page()

    def sw_leave_notify_event(self, _sw, event):
        if event.state & Gdk.ModifierType.BUTTON1_MASK:
            return
        self.set_cursor('default')

    def init_surface(self):
        aw = self.da.get_allocated_width()
        ah = self.da.get_allocated_height()
        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, aw, ah)

    def on_draw(self, _darea, cr):
        if self.surface is not None:
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()

    def draw_page(self, _widget=None, _rect=None):
        """Draw the 'destination' thumbnail page."""
        if len(self.damodel) == 0 or self.surface is None:
            return
        dpage = self.damodel[0][0]
        if dpage.thumbnail is None:
            return
        cr = cairo.Context(self.surface)
        aw = self.da.get_allocated_width()
        ah = self.da.get_allocated_height()

        # Destination page rectangle
        dw = dpage.width_in_pixel()
        dh = dpage.height_in_pixel()
        dx = int(.5 + (aw - dw) / 2)
        dy = int(.5 + (ah - dh) / 2)

        # Page border
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(dx - 2, dy - 2, dw + 4, dh + 4)
        cr.fill_preserve()
        cr.clip()

        # Fill white paper
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(dx, dy, dw, dh)
        cr.fill()

        # Add the thumbnail
        (dw0, dh0) = (dh, dw) if dpage.angle in [90, 270] else (dw, dh)
        cr.translate(dx, dy)
        if dpage.angle > 0:
            cr.translate(dw / 2, dh / 2)
            cr.rotate(dpage.angle * pi / 180)
            cr.translate(-dw0 / 2, -dh0 / 2)
        tw, th = dpage.thumbnail.get_width(), dpage.thumbnail.get_height()
        tw, th = (th, tw) if dpage.angle in [90, 270] else (tw, th)
        cr.scale(dw / tw, dh / th)
        cr.set_source_surface(dpage.thumbnail)
        cr.get_source().set_filter(cairo.FILTER_FAST)
        cr.paint()

        cr.identity_matrix()
        cr.set_line_width(1)

        if callable(self.draw_on_page):
            self.adjust_rect = self.draw_on_page(cr, dx, dy, dw, dh, self.damodel)
            # Draw the adjust rectangle
            cr.identity_matrix()
            cr.set_source_rgb(1, 1, 1)
            cr.set_dash([])
            cr.rectangle(*self.adjust_rect)
            cr.stroke()
            cr.set_source_rgb(0, 0, 0)
            cr.set_dash([4.0, 4.0])
            cr.rectangle(*self.adjust_rect)
            cr.stroke()

        # Invalidiate region
        ha = self.sw.get_hadjustment()
        va = self.sw.get_vadjustment()
        r = ha.get_value(), va.get_value(), ha.get_page_size(), va.get_page_size()
        self.da.queue_draw_area(*r)


class PastePageLayerDialog():
    def __init__(self, window, dpage, lpage_stack, model, pdfqueue, mode, layer_pos):
        title = _("Overlay") if mode == 'OVERLAY' else _("Underlay")
        lpage = lpage_stack[0].duplicate()
        lpage.layerpages = [lp.duplicate() for lp in lpage_stack[1:]]
        lpage.zoom = dpage.zoom
        lpage.resample = -1
        lpage.thumbnail = None
        self.spinbutton_widget = _OffsetWidget(layer_pos, dpage, lpage)
        dawidget = DrawingAreaWidget(dpage, pdfqueue, self.spinbutton_widget, self.draw_on_page)
        dawidget.allow_adjust_rect_resize = False
        dawidget.handle_move_limits = False
        dawidget.damodel.append([lpage])

        self.dialog = BaseDialog(title, window)
        self.dialog.vbox.pack_start(dawidget, True, True, 0)
        self.dialog.set_size_request(350, 500)
        self.dialog.show_all()

    def draw_on_page(self, cr, dx, dy, dw, dh, damodel):
        """Draw on the thumbnail page."""
        dpage, lpage = [page for [page] in damodel]
        if lpage.thumbnail is None:
            return [0] * 4
        self.spinbutton_widget.set_scale(dpage, lpage)

        # Layer page rectangle
        offset = self.spinbutton_widget.get_val()
        lx = round(dx + dw * offset.left)
        ly = round(dy + dh * offset.top)
        lw = round(lpage.zoom * lpage.width_in_points())
        lh = round(lpage.zoom * lpage.height_in_points())

        # Add the overlay/underlay
        (pw0, ph0) = (lh, lw) if lpage.angle in [90, 270] else (lw, lh)
        cr.translate(lx, ly)
        if lpage.angle > 0:
            cr.translate(lw / 2, lh / 2)
            cr.rotate(lpage.angle * pi / 180)
            cr.translate(-pw0 / 2, -ph0 / 2)
        ltw, lth = lpage.thumbnail.get_width(), lpage.thumbnail.get_height()
        ltw, lth = (lth, ltw) if lpage.angle in [90, 270] else (ltw, lth)
        cr.scale(lw / ltw, lh / lth)
        cr.set_source_surface(lpage.thumbnail)
        cr.get_source().set_filter(cairo.FILTER_FAST)
        cr.paint()

        return [lx - .5, ly - .5, lw + 1, lh + 1]

    def get_offset(self):
        """Get layer page x and y offset from top-left edge of the destination page.

        The offset is the fraction of space positioned at left and top of the pasted layer,
        where space is the differance in width and height between the layer and the page.
        """
        result = self.dialog.run()
        r = None
        if result == Gtk.ResponseType.OK:
            r = self.spinbutton_widget.get_diff_offset()
        self.dialog.destroy()
        return r
