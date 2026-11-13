# Copyright (C) 2026 pdfarranger contributors
#
# pdfarranger is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import gettext
from dataclasses import dataclass
from typing import Optional

from gi.repository import Gdk, GLib, Gtk


_ = gettext.gettext


@dataclass
class Command:
    label: str
    path: str
    action: str
    target: Optional[GLib.Variant]


def _clean_label(label):
    if label is None:
        return ""
    label = label.replace("__", "\0")
    label = label.replace("_", "")
    label = label.replace("\0", "_")
    return label


def _get_menu_item_attributes(menu, index):
    attrs = {}
    it = menu.iterate_item_attributes(index)
    while it.next():
        attrs[it.get_name()] = it.get_value()
    return attrs


def _commands_from_menu(menu, path=None):
    commands = []
    path = [] if path is None else path
    for i in range(menu.get_n_items()):
        attrs = _get_menu_item_attributes(menu, i)
        label = _clean_label(attrs["label"].get_string()) if "label" in attrs else ""
        action = attrs["action"].get_string() if "action" in attrs else None
        target = attrs.get("target")
        item_path = path + ([label] if label else [])
        if action is not None and label:
            commands.append(Command(label, " / ".join(item_path), action, target))
        links = menu.iterate_item_links(i)
        while links.next():
            commands.extend(_commands_from_menu(links.get_value(), item_path))
    return commands


class CommandPaletteDialog(Gtk.Dialog):
    def __init__(self, parent, menu_model):
        super().__init__(
            title=_("Command Palette"),
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
        )
        self.set_default_size(520, 420)
        self.commands = _commands_from_menu(menu_model)
        self.filtered_commands = []
        self.selected_command = None

        self.entry = Gtk.SearchEntry(margin=12)
        self.entry.set_placeholder_text(_("Type a command"))
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("activate", self._activate_selected)
        self.entry.connect("key-press-event", self._on_entry_key_press)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._on_row_activated)

        scrolled = Gtk.ScrolledWindow(margin_start=12, margin_end=12, margin_bottom=12)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(self.listbox)

        box = self.get_content_area()
        box.pack_start(self.entry, False, False, 0)
        box.pack_start(scrolled, True, True, 0)
        self._refilter()
        self.show_all()
        self.entry.grab_focus()

    def _on_search_changed(self, _entry):
        self._refilter()

    def _on_entry_key_press(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return Gdk.EVENT_STOP
        if event.keyval in [Gdk.KEY_Down, Gdk.KEY_KP_Down]:
            self._move_selection(1)
            return Gdk.EVENT_STOP
        if event.keyval in [Gdk.KEY_Up, Gdk.KEY_KP_Up]:
            self._move_selection(-1)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _move_selection(self, delta):
        rows = self.listbox.get_children()
        if not rows:
            return
        selected = self.listbox.get_selected_row()
        index = rows.index(selected) if selected in rows else 0
        index = max(0, min(len(rows) - 1, index + delta))
        row = rows[index]
        self.listbox.select_row(row)
        row.grab_focus()
        self.entry.grab_focus()

    def _refilter(self):
        query = self.entry.get_text().lower()
        terms = query.split()
        self.filtered_commands = [
            command for command in self.commands
            if self._is_enabled(command) and self._matches(command, terms)
        ]
        self.filtered_commands.sort(key=lambda command: (
            not command.label.lower().startswith(query),
            command.path.lower(),
        ))
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        for command in self.filtered_commands[:100]:
            self.listbox.add(self._make_row(command))
        self.listbox.show_all()
        rows = self.listbox.get_children()
        if rows:
            self.listbox.select_row(rows[0])

    def _matches(self, command, terms):
        haystack = command.path.lower()
        return all(term in haystack for term in terms)

    def _make_row(self, command):
        row = Gtk.ListBoxRow()
        row.command = command
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=8)
        label = Gtk.Label(label=command.label, xalign=0)
        label.get_style_context().add_class("command-palette-label")
        path = Gtk.Label(label=command.path, xalign=0)
        path.get_style_context().add_class("dim-label")
        box.pack_start(label, False, False, 0)
        box.pack_start(path, False, False, 0)
        row.add(box)
        return row

    def _is_enabled(self, command):
        action = self._lookup_action(command)
        return action is not None and action.get_enabled()

    def _lookup_action(self, command):
        action_name = command.action
        if action_name.startswith("win."):
            action_name = action_name[4:]
        return self.get_transient_for().lookup_action(action_name)

    def _on_row_activated(self, _listbox, row):
        self._activate(row.command)

    def _activate_selected(self, _entry):
        row = self.listbox.get_selected_row()
        if row is not None:
            self._activate(row.command)

    def _activate(self, command):
        action = self._lookup_action(command)
        if action is not None and action.get_enabled():
            self.selected_command = command
            self.response(Gtk.ResponseType.OK)
