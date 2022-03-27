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

_ = gettext.gettext

class Dialog(Gtk.Dialog):
    """ A dialog box to split pages into a grid of pages"""
    def __init__(self, window):
        super().__init__(
            title=_("Split Pages"),
            parent=window,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(
                "_Cancel",
                Gtk.ResponseType.CANCEL,
                "_OK",
                Gtk.ResponseType.OK,
            ),
        )
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_resizable(False)
        self.split_count = {'vertical' : 2, 'horizontal' : 1}
        self.even_splits = {'vertical' : True, 'horizontal' : True}
        self.vmodel = Gtk.ListStore(int, int)
        self.hmodel = Gtk.ListStore(int, int)
        self.model = {'vertical' : self.vmodel, 'horizontal' : self.hmodel}
        self.vspin = Gtk.SpinButton()
        self.hspin = Gtk.SpinButton()
        self.spinbuttons = {'vertical' : self.vspin, 'horizontal' : self.hspin}
        self.vcheck = Gtk.CheckButton()
        self.hcheck = Gtk.CheckButton()
        self.checkbuttons = {'vertical' : self.vcheck, 'horizontal' : self.hcheck}

        hbox = Gtk.HBox()
        self.vbox.pack_start(hbox, True, True, 0)
        for direction in ['vertical', 'horizontal']:
            frame = self._build_frame(direction)
            hbox.pack_start(frame, True, True, 0)
        self.show_all()

    def _build_frame(self, direction):
        frame_txt = {'vertical' : _("Columns"), 'horizontal' : _("Rows")}
        label_txt = {'vertical' : _("Vertical Splits"), 'horizontal' : _("Horizontal Splits")}
        checkbutton_txt = {'vertical' : _("Equal column width"), 'horizontal' : _("Equal row height")}

        frame = Gtk.Frame(label=frame_txt[direction])
        frame.props.margin = 8
        frame.props.margin_bottom = 0
        grid = Gtk.Grid()
        frame.add(grid)
        label = Gtk.Label(label_txt[direction])
        label.set_alignment(0.0, 0.5)
        label.props.margin = 8
        label.props.margin_bottom = 6
        grid.attach(label, 0, 0, width=1, height=1)
        adjustment = Gtk.Adjustment(value=self.split_count[direction], lower=1, upper=10, step_incr=1)
        self.spinbuttons[direction].set_adjustment(adjustment)
        self.spinbuttons[direction].connect("value-changed", self._update_split, direction)
        grid.attach(self.spinbuttons[direction], 1, 0, width=1, height=1)
        self.checkbuttons[direction].set_label(checkbutton_txt[direction])
        self.checkbuttons[direction].set_active(True)
        self.checkbuttons[direction].connect("toggled", self._even_split_toggled, direction)
        grid.attach(self.checkbuttons[direction], 0, 1, width=2, height=1)
        treeview = self._build_model(direction)
        grid.attach(treeview, 0, 2, width=2, height=1)
        return frame

    def _build_model(self, direction):
        label1 = {'vertical' : _("#Col"), 'horizontal' : _("#Row")}
        label2 = {'vertical' : _("Width in %"), 'horizontal' : _("Height in %")}

        split_count = self.split_count[direction]
        for s in range(1, split_count + 1):
            self.model[direction].append([s, 100 // split_count])
        treeview = Gtk.TreeView(model=self.model[direction])
        cr = Gtk.CellRendererText()
        heading = Gtk.TreeViewColumn(label1[direction], cr, text=0)
        treeview.append_column(heading)
        cr = Gtk.CellRendererSpin()
        cr.connect("edited", self._edited, direction)
        cr.set_property("editable", True)
        adjustment = Gtk.Adjustment(value=100, lower=0, upper=100, step_increment=1)
        cr.set_property("adjustment", adjustment)
        heading = Gtk.TreeViewColumn(label2[direction], cr, text=1)
        treeview.append_column(heading)
        return treeview

    def _edited(self, widget, path, value, direction):
        # Avoid that a user bypasses the limits of the spin buttons
        # via keyboard input and pressing enter.
        value = min(max(0, int(value)), 100)
        if self.model[direction][path][1] == int(value):
            return
        if self.checkbuttons[direction].get_active():
            # Populate all entries with the new value
            # The sum may exceed 100, allowing for overlap.
            crop_sum = len(self.model[direction]) * value
            if crop_sum >= 100:
                for i in range(len(self.model[direction])):
                    self.model[direction][i][1] = value
        else:
            # Unevenly sized tiles. Fix the sum to match 100,
            # adjusting entries from bottom to top.
            self.model[direction][path][1] = value
            crop_sum = 0
            for i in range(len(self.model[direction])):
                crop_sum += self.model[direction][i][1]
            delta = 100 - crop_sum
            cur_idx = int(path)
            for i in reversed(range(len(self.model[direction]))):
                if i != cur_idx:
                    sign = delta/abs(delta)
                    s = sign * min(abs(delta), self.model[direction][i][1])
                    self.model[direction][i][1] += s
                    delta -= s
                    if delta == 0:
                        break

    def _update_split(self, _event, direction):
        self.split_count[direction] = self.spinbuttons[direction].get_value_as_int()
        if self.even_splits[direction]:
            self.model[direction].clear()
            # Partition evenly
            count = self.split_count[direction]
            frac = 100 // count
            partition = [frac] * (count - 1)
            partition.append(100 - (count - 1) * frac)
            for i, frac in enumerate(partition, start = 1):
                self.model[direction].append([i, frac])
        else:
            delta = self.split_count[direction] - len(self.model[direction])
            if delta > 0:
                # Add delta zero rows
                idx = len(self.model[direction]) + 1
                for i in range(delta):
                    self.model[direction].append([idx + i, 0])
            if delta < 0:
                # Delete the last delta entries and ensure that the sum is 100
                s = 0
                for i in range(abs(delta)):
                    s += self.model[direction][-1][1]
                    del self.model[direction][-1]
                self.model[direction][-1][1] += s

    def _even_split_toggled(self, button, direction):
        self.even_splits[direction] = button.get_active()
        self._update_split(None, direction)

    def _crops(self, direction):
        # Convert the tile sizes into a list of tuples (start, end) such that
        # tile size = end - start.
        num_splits = len(self.model[direction])
        crops = [(0, 0.01 * self.model[direction][0][1])] * num_splits
        crop_sum = 0.01 * self.model[direction][0][1]
        for i in range(1, num_splits):
            size = 0.01 * self.model[direction][i][1]
            crop_sum += size
            crops[i] = (crops[i-1][1], crops[i-1][1] + size)

        # Remove zero-sized tiles
        crops = [t for t in crops if t[0] < t[1]]

        overlap = crop_sum - 1.0 # nonnegative
        if overlap == 0.0:
            return crops

        # We have multiple splits and crop_sum > 1.0
        # 35,35,35 => [0,35],[32.5,67.5],[65,100]; overlap = 5
        # 60,60 => [0,60],[40,100]; overlap = 20
        # In general:
        #   [start=last-overlap/(num_splits-1),end=start+size]
        overlap_per_tile = overlap / (num_splits - 1)

        # Overlap is only defined when all tiles have the same size.
        size = 0.01 * self.model[direction][0][1]
        crops[0] = (0, size)
        for i in range(1, num_splits - 1):
            start = crops[i-1][1] - overlap_per_tile
            end = start + size
            crops[i] = (start, end)
        crops[-1] = (1.0 - size, 1.0)
        return crops


    def run_get(self):
        result = self.run()
        vcrops = None
        hcrops = None
        if result == Gtk.ResponseType.OK:
            vcrops = self._crops('vertical')
            hcrops = self._crops('horizontal')
        self.destroy()
        return vcrops, hcrops
