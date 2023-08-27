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

from gi.repository import Gtk, Gdk
import gettext
import cairo
import locale

from .core import Sides

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


class PastePageLayerDialog():

    def __init__(self, app, dpage, lpage, laypos):
        title = _("Overlay") if laypos == "OVERLAY" else _("Underlay")
        self.d = BaseDialog(title, app.window)
        self.app = app
        self.dpage = dpage
        self.lpage = lpage
        self.surface = None
        self.scale = 1
        self.spin_scale_x = (self.dpage.width_in_points() - self.lpage.width_in_points()) / 100
        self.spin_scale_y = (self.dpage.height_in_points() - self.lpage.height_in_points()) / 100
        self.click_pos = 0, 0
        self.spin_val = 0, 0

        self.area = Gtk.DrawingArea()
        self.area.set_size_request(400, 400)
        self.area.set_events(self.area.get_events()
                              | Gdk.EventMask.BUTTON_PRESS_MASK
                              | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect('draw', self.on_draw)
        self.area.connect('configure-event', self.on_configure)
        self.area.connect('button-press-event', self.button_press_event)
        self.area.connect('motion-notify-event', self.motion_notify_event)
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
        frame.add(self.area)
        self.d.vbox.pack_start(frame, True, True, 0)
        t1 = _("Layout for the first page in selection")
        t2 = _("(same offset is applied to all pages)")
        label = Gtk.Label(t1 + '\n' + t2, valign=Gtk.Align.START, justify=Gtk.Justification.CENTER)
        self.d.vbox.pack_start(label, True, True, 0)

        self.spin_x = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.spin_x.set_activates_default(True)
        self.spin_x.set_digits(1)
        self.spin_y = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.spin_y.set_activates_default(True)
        self.spin_y.set_digits(1)
        self.spin_x.set_value(self.app.layer_pos[0])
        self.spin_y.set_value(self.app.layer_pos[1])
        self.spin_x.connect('value-changed', self.on_spinbutton_changed)
        self.spin_y.connect('value-changed', self.on_spinbutton_changed)

        xlabel1 = Gtk.Label(_("Horizontal offset"), halign=Gtk.Align.START)
        xlabel2 = Gtk.Label(_("%"), halign=Gtk.Align.START)
        ylabel1 = Gtk.Label(_("Vertical offset"), halign=Gtk.Align.START)
        ylabel2 = Gtk.Label(_("%"), halign=Gtk.Align.START)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=12, halign=Gtk.Align.CENTER)
        grid.attach(xlabel1, 0, 1, 1, 1)
        grid.attach(self.spin_x, 1, 1, 1, 1)
        grid.attach(xlabel2, 2, 1, 1, 1)
        grid.attach(ylabel1, 0, 2, 1, 1)
        grid.attach(self.spin_y, 1, 2, 1, 1)
        grid.attach(ylabel2, 2, 2, 1, 1)
        self.d.vbox.pack_start(grid, False, False, 8)
        self.d.show_all()

    def on_configure(self, area, _event):
        self.init_surface()
        aw = area.get_allocated_width()
        ah = area.get_allocated_height()
        dwidth = self.dpage.width_in_points()
        dheight = self.dpage.height_in_points()
        self.scale = min((aw - 100) / dwidth, (ah - 100) / dheight)
        self.draw_page_boxes()

    def on_draw(self, _area, cairo_ctx):
        if self.surface is not None:
            cairo_ctx.set_source_surface(self.surface, 0, 0)
            cairo_ctx.paint()

    def on_spinbutton_changed(self, _event):
        self.init_surface()
        self.draw_page_boxes()

    def button_press_event(self, _area, event):
        if event.button == 1:
            self.click_pos = event.x, event.y
            self.spin_val = self.spin_x.get_value(), self.spin_y.get_value()

    def motion_notify_event(self, _area, event):
        if event.state & Gdk.ModifierType.BUTTON1_MASK:
            if self.scale * self.spin_scale_x != 0:
                add_x = (event.x - self.click_pos[0]) / (self.scale * self.spin_scale_x)
                self.spin_x.set_value(self.spin_val[0] + add_x)
            if self.scale * self.spin_scale_y != 0:
                add_y = (event.y - self.click_pos[1]) / (self.scale * self.spin_scale_y)
                self.spin_y.set_value(self.spin_val[1] + add_y)
            self.draw_page_boxes()

    def init_surface(self):
        aw = self.area.get_allocated_width()
        ah = self.area.get_allocated_height()
        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, aw, ah)

    def draw_page_boxes(self):
        """Draw the page and the layer page (overlay/underlay)."""
        cairo_ctx = cairo.Context(self.surface)
        aw = self.area.get_allocated_width()
        ah = self.area.get_allocated_height()

        # Destination page rectangle
        dwf = self.dpage.width_in_points() * self.scale
        dhf = self.dpage.height_in_points() * self.scale
        dxf = (aw - dwf) / 2
        dyf = (ah - dhf) / 2
        dx = int(0.5 + dxf)
        dy = int(0.5 + dyf)
        dw = int(0.5 + dwf + dxf - dx)
        dh = int(0.5 + dhf + dyf - dy)

        # Layer page rectangle
        lwf = self.lpage.width_in_points() * self.scale
        lhf = self.lpage.height_in_points() * self.scale
        lxf = dxf + self.spin_x.get_value() * self.spin_scale_x * self.scale
        lyf = dyf + self.spin_y.get_value() * self.spin_scale_y * self.scale
        lx = int(0.5 + dxf + self.spin_x.get_value() * self.spin_scale_x * self.scale)
        ly = int(0.5 + dyf + self.spin_y.get_value() * self.spin_scale_y * self.scale)
        lw = int(0.5 + lwf + lxf - lx)
        lh = int(0.5 + lhf + lyf - ly)

        # Fill white paper
        cairo_ctx.set_source_rgb(1, 1, 1)
        cairo_ctx.rectangle(dx + 1, dy + 1, dw - 2, dh - 2)
        cairo_ctx.fill()

        # Draw layer page border
        cairo_ctx.set_source_rgb(0, 0, 0)
        cairo_ctx.rectangle(lx, ly, lw, lh)
        cairo_ctx.stroke()

        # Fill the layer page
        cairo_ctx.set_source_rgb(0.5, 0.5, 0.5)
        cairo_ctx.rectangle(lx + 1, ly + 1, lw - 2, lh - 2)
        cairo_ctx.fill()

        # Draw the page border
        cairo_ctx.set_source_rgb(0, 0, 0)
        cairo_ctx.rectangle(dx, dy, dw, dh)
        cairo_ctx.stroke()

        # Invalidiate region
        self.area.queue_draw_area(0, 0, aw, ah)

    def get_offset(self):
        """Get layer page x and y offset from top-left edge of the destination page.

        The offset is the fraction of space positioned at left and top of the pasted layer,
        where space is the differance in width and height between the layer and the page.
        """
        result = self.d.run()
        r = None
        if result == Gtk.ResponseType.OK:
            self.app.layer_pos = self.spin_x.get_value(), self.spin_y.get_value()
            r = self.spin_x.get_value() / 100, self.spin_y.get_value() / 100
        self.d.destroy()
        return r
