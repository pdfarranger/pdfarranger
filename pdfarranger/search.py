# Copyright (C) 2025 pdfarranger contributors
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

from .core import Sides
from .exporter import get_in_memory_poppler_doc

_ = gettext.gettext


class SearchBarWidget(Gtk.SearchBar):
    """A widget for searching of text in PDF"""
    def __init__(self, window, iconview, pdfqueue, show_find_results, clear_find_results):
        super().__init__(show_close_button=True)
        self.button_box = Gtk.Box(homogeneous=True, halign=Gtk.Align.START, margin_start=6)

        button_prev = Gtk.Button.new_from_icon_name('go-up-symbolic', True)
        button_prev.set_tooltip_text(_("Find Previous"))
        button_prev.connect('clicked', self.find_sequent, -1)
        self.button_box.pack_start(button_prev, True, True, 0)

        button_next = Gtk.Button.new_from_icon_name('go-down-symbolic', True)
        button_next.set_tooltip_text(_("Find Next"))
        button_next.connect('clicked', self.find_sequent, 1)
        self.button_box.pack_start(button_next, True, True, 0)

        button_all = Gtk.Button(label=_("All"))
        button_all.set_tooltip_text(_("Find All"))
        button_all.connect('clicked', self.find_all)
        self.button_box.pack_start(button_all, True, True, 0)

        self.entry = Gtk.SearchEntry(width_chars=32)
        self.entry.connect('search_changed', self.enable_actions)
        entry_tools = Gtk.Box()
        entry_tools.pack_start(self.entry, True, True, 0)
        entry_tools.pack_start(self.button_box, True, True, 0)
        entry_tools.connect('unmap', self.close)

        self.add(entry_tools)
        self.connect_entry(self.entry)
        self.window = window
        self.iconview = iconview
        self.pdfqueue = pdfqueue
        self.model = self.iconview.get_model()
        self.show_find_results = show_find_results
        self.clear_find_results = clear_find_results
        self.text_old = ""
        self.page = None
        self.npage = 0
        self.rectangles = []
        self.nrect = 0
        self.event_cnt = 0

    def reveal(self):
        if not self.get_search_mode():
            self.entry.set_text(self.text_old)
            self.entry.grab_focus()
            self.set_search_mode(True)
        else:
            self.entry.grab_focus_without_selecting()

    def handle_event(self, event):
        """Forward key press events to entry"""
        handled = False
        if self.get_search_mode():
            if event.keyval == Gdk.KEY_Escape:
                handled = True
                self.set_search_mode(False)
            elif self.entry.has_focus():
                handled = True
                if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_x:
                    self.entry.cut_clipboard()
                elif event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_c:
                    self.entry.copy_clipboard()
                elif event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_v:
                    self.entry.paste_clipboard()
                elif event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_a:
                    self.entry.grab_focus()
                elif event.keyval in [Gdk.KEY_Return, Gdk.KEY_KP_Enter]:
                    self.find_sequent(step=1)
                else:
                    handled = self.entry.handle_event(event)
        return handled

    def enable_actions(self, _widget=None):
        enable = (self.entry.get_text() and self.get_search_mode() or
                  self.text_old and not self.get_search_mode())
        self.button_box.set_sensitive(enable)
        self.window.lookup_action("find_prev").set_enabled(enable)
        self.window.lookup_action("find_next").set_enabled(enable)
        self.window.lookup_action("find_all").set_enabled(enable)

    def find(self, _action, _option, _unknown):
        self.reveal()

    def find_prev(self, _action, _option, _unknown):
        self.find_sequent(step=-1)

    def find_next(self, _action, _option, _unknown):
        self.find_sequent(step=1)

    def find_all(self, _widget, _option=None, _unknown=None):
        self.event_cnt += 1
        event_cnt = self.event_cnt
        if len(self.model) == 0:
            return
        self.reveal()
        self.clear_find_results(unselect_all=True)
        text = self.entry.get_text()
        if text == "":
            return
        for npage in range(len(self.model)):
            rectangles = self.find_text(npage, text)
            if len(rectangles) > 0:
                self.show_find_results(npage, rectangles)
            self.entry.set_progress_fraction((npage + 1) / max(1, len(self.model)))
            if self.abort(event_cnt):
                break
        self.entry.set_progress_fraction(1)
        self.entry.set_progress_fraction(0)

    def find_sequent(self, _widget=None, step=1):
        self.event_cnt += 1
        event_cnt = self.event_cnt
        if len(self.model) == 0:
            return
        self.reveal()
        selection = self.iconview.get_selected_items()
        if len(selection) > 0:
            self.npage = selection[-1].get_indices()[0]
        self.npage = min(self.npage, len(self.model) - 1)
        self.clear_find_results(unselect_all=True)
        text = self.entry.get_text()
        if text == "":
            return
        text_changed = text != self.text_old
        page_changed = self.model[self.npage][0].__repr__() != self.page.__repr__()
        if text_changed or page_changed:
            # Search in current page
            self.rectangles = self.find_text(self.npage, text)
            self.nrect = -1 if step == 1 else len(self.rectangles)

        if 0 <= self.nrect + step < len(self.rectangles):
            # Get next rectangle index
            self.nrect += step
        else:
            # Continue searching until text is found or all has been searched
            self.rectangles = []
            cnt = 0
            while len(self.rectangles) == 0 and cnt < len(self.model):
                self.npage = (self.npage + step) % len(self.model)
                self.rectangles = self.find_text(self.npage, text)
                cnt += 1
                self.entry.set_progress_fraction(cnt / max(1, len(self.model)))
                if self.abort(event_cnt):
                    break
            self.nrect = 0 if step == 1 else len(self.rectangles) - 1

        if len(self.rectangles) > 0 and self.event_cnt == event_cnt:
            rectangle = self.rectangles[self.nrect]
            self.show_find_results(self.npage, [rectangle])
        self.entry.set_progress_fraction(1)
        self.entry.set_progress_fraction(0)

    def find_text(self, npage, text):
        if len(self.model) == 0:
            return []
        npage = min(npage, len(self.model) - 1)
        self.page = self.model[npage][0].duplicate(incl_thumbnail=False)
        page = self.page.duplicate(incl_thumbnail=False)
        page.rotate(-page.angle)
        crop = page.crop
        if len(page.layerpages) == 0:
            doc = self.pdfqueue[page.nfile - 1]
            poppler_page = doc.get_page(page.npage - 1)
        else:
            # Page has layers -> for simplicity export and search in exported pdf.
            # This is slower but easier than recalculating rectangle coordinates.
            rescale = 1 / page.scale
            page.scale = 1
            for lp in page.layerpages:
                lp.scale *= rescale
            page.crop = Sides()
            page.hide = Sides()
            doc, _buf = get_in_memory_poppler_doc([page], self.pdfqueue)
            poppler_page = doc.get_page(0)
        rectangles = poppler_page.find_text(text)
        rectangles = self.apply_crop(rectangles, poppler_page.get_size(), crop)
        if text != "":
            self.text_old = text
        return rectangles

    def apply_crop(self, rectangles, size, crop):
        for r in rectangles:
            r.x1 -= size[0] * crop.left
            r.x2 -= size[0] * crop.left
            r.y1 -= size[1] * crop.bottom
            r.y2 -= size[1] * crop.bottom
        rectangles = self.visible_rectangles(rectangles, size, crop)
        return rectangles

    def visible_rectangles(self, rectangles, size, crop):
        """Remove rectangles which are cropped away"""
        to_remove = []
        for num, r in enumerate(rectangles):
            if (r.x1 > size[0] * (1 - crop.left - crop.right) or
                r.x2 < 0 or
                r.y1 > size[1] * (1 - crop.top - crop.bottom) or
                r.y2 < 0
                ):
                to_remove.append(num)
        for num in reversed(to_remove):
            del rectangles[num]
        return rectangles

    def abort(self, event_cnt):
        while Gtk.events_pending():
            Gtk.main_iteration()
        closed = not self.get_search_mode()
        cleared = not self.entry.get_text()
        old_event = self.event_cnt > event_cnt
        return closed or cleared or old_event

    def close(self, _widget):
        self.clear_find_results(unselect_all=False)
