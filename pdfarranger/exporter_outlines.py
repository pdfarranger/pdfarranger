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

"""Rebuild PDF outlines after page reorder, subset, or merge."""

import warnings
import pikepdf


class OutlineRemapper:
    """Build page index maps and destination caches for remapping bookmarks."""

    def __init__(self, pdf_input, pdf_output, pages):
        """Build page index maps and destination caches from the input PDFs."""
        self.pdf_input = pdf_input
        self.pdf_output = pdf_output
        self.rev_maps = {}
        self.dest_caches = {}
        self.new_named_dests = []
        self.page_index_map = {}
        instance_counts = {}
        for out_idx, row in enumerate(pages):
            file_idx = row.nfile - 1
            src_page_idx = row.npage - 1
            key = (file_idx, src_page_idx)
            inst_num = instance_counts.get(key, 0)
            # Map (file_idx, source_page_idx, instance_num) -> output_page_index
            self.page_index_map[(*key, inst_num)] = out_idx
            instance_counts[key] = inst_num + 1
        for file_idx, pdf in enumerate(pdf_input):
            if pdf is None:
                continue
            self.rev_maps[file_idx] = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
            dests = {}
            if pikepdf.Name.Dests in pdf.Root:
                for k, v in pdf.Root.Dests.items():
                    dests[str(k).lstrip("/")] = v
            if pikepdf.Name.Names in pdf.Root and pikepdf.Name.Dests in pdf.Root.Names:
                dests.update(dict(pikepdf.NameTree(pdf.Root.Names.Dests).items()))
            self.dest_caches[file_idx] = dests

    def remap_destination(self, file_idx, dest):
        """Remap a bookmark destination to its new location in the output PDF."""
        original_name = None
        if isinstance(dest, (pikepdf.String, pikepdf.Name)):
            original_name = str(dest).lstrip("/")
            dest_obj = self.dest_caches[file_idx].get(original_name)
            if not dest_obj:
                return None
            try:
                dest_array = dest_obj.D
            except (AttributeError, ValueError):
                dest_array = dest_obj
        else:
            dest_array = dest
        if not isinstance(dest_array, pikepdf.Array) or len(dest_array) == 0:
            return None
        target_ref = dest_array[0]
        if not hasattr(target_ref, "objgen"):
            return None
        source_page_idx = self.rev_maps[file_idx].get(target_ref.objgen)
        if source_page_idx is None:
            return None
        # Target first copy (0) of each page. Other copies are not bookmarked.
        target_out_idx = self.page_index_map.get((file_idx, source_page_idx, 0))
        if target_out_idx is None:
            return None
        target_page_obj = self.pdf_output.pages[target_out_idx].obj
        new_dest_array = pikepdf.Array()
        new_dest_array.append(target_page_obj)
        for i in range(1, len(dest_array)):
            item = dest_array[i]
            if isinstance(item, pikepdf.Object) and item.is_indirect:
                new_dest_array.append(self.pdf_output.copy_foreign(item))
            else:
                new_dest_array.append(item)
        if original_name:
            new_name_str = f"f{file_idx}-{original_name}"
            self.new_named_dests.append((new_name_str, new_dest_array))
            return pikepdf.String(new_name_str)
        return new_dest_array


class OutlineCopier:
    """Copy outline items from a source PDF, remapping destinations."""

    def __init__(self, remapper, file_idx):
        """Initialize with a remapper and the source file index."""
        self.remapper = remapper
        self.file_idx = file_idx

    def copy_item(self, source_item, new_parent_list):
        """Copy a single outline item and its children, dropping invalid destinations."""
        dest = None
        if source_item.destination is not None:
            dest = source_item.destination
        elif (
            source_item.action
            and source_item.action.get(pikepdf.Name.S) == pikepdf.Name.GoTo
        ):
            dest = source_item.action.get(pikepdf.Name.D)
        final_dest = None
        is_valid = False
        if dest is not None:
            final_dest = self.remapper.remap_destination(self.file_idx, dest)
            if final_dest is not None:
                is_valid = True
        new_item = pikepdf.OutlineItem(title=source_item.title, destination=final_dest)
        for child in source_item.children:
            self.copy_item(child, new_item.children)
        # only copy bookmark if it is needed
        if is_valid or len(new_item.children) > 0:
            new_parent_list.append(new_item)


def write_named_dests(pdf, named_dests):
    """Write a list of (name, dest_array) pairs into the PDF's name tree."""
    if not named_dests:
        return
    if pikepdf.Name.Names not in pdf.Root:
        pdf.Root.Names = pdf.make_indirect(pikepdf.Dictionary())
    if pikepdf.Name.Dests in pdf.Root.Names:
        nt = pikepdf.NameTree(pdf.Root.Names.Dests)
    else:
        nt = pikepdf.NameTree.new(pdf)
        pdf.Root.Names.Dests = nt.obj
    for name_str, dest_array in named_dests:
        nt[name_str] = dest_array


def rebuild_outlines(pdf_input, pdf_output, pages):
    """Rebuild outlines in pdf_output by remapping bookmarks from pdf_input."""
    remapper = OutlineRemapper(pdf_input, pdf_output, pages)
    ordered_file_indices = list(dict.fromkeys(row.nfile - 1 for row in pages))
    with pdf_output.open_outline() as new_outline:
        for file_idx in ordered_file_indices:
            source_pdf = pdf_input[file_idx]
            if source_pdf is None or pikepdf.Name.Outlines not in source_pdf.Root:
                continue
            try:
                with source_pdf.open_outline() as source_outline:
                    copier = OutlineCopier(remapper, file_idx)
                    for item in source_outline.root:
                        copier.copy_item(item, new_outline.root)
            except pikepdf.PdfError as e:
                warnings.warn(
                    f"Failed to copy bookmarks from document {file_idx + 1}: {e}"
                )
    if remapper.new_named_dests:
        write_named_dests(pdf_output, remapper.new_named_dests)
