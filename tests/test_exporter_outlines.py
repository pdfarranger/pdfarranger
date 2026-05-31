"""Tests for outline.py — bookmark remapping when pdfarranger reorders/subsets pages.

Each test builds minimal synthetic PDFs with pikepdf directly, so there are no
fixture files and the suite stays fast and self-contained.

Helper conventions:
  make_pdf(n)          → pikepdf.Pdf with n blank pages, no outline
  Row(nfile, npage)    → minimal stand-in for pdfarranger's page-row object
  roundtrip(pdf)       → save + reopen so all object references are resolved
  dest_page_index(pdf, dest_array) → which 0-based page index a dest array points to
"""

import io
import builtins

import pikepdf
import pytest
from unittest.mock import patch
from collections import namedtuple

from pdfarranger.exporter_outlines import (
    rebuild_outlines,
    write_named_dests,
    OutlineRemapper,
    rebuild_links,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_pdf(n_pages: int) -> pikepdf.Pdf:
    """Return a new in-memory Pdf with n_pages blank pages."""
    pdf = pikepdf.new()
    for _ in range(n_pages):
        pdf.pages.append(
            pikepdf.Page(
                pikepdf.Dictionary(
                    Type=pikepdf.Name.Page,
                    MediaBox=[0, 0, 612, 792],
                )
            )
        )
    return pdf


def add_outline(pdf: pikepdf.Pdf, items):
    """Add bookmarks to pdf from a list of tuples.

    Each tuple is either (title, page_idx) or
    (title, page_idx, [(child_title, child_page_idx), ...]) tuples.
    """
    with pdf.open_outline() as ol:
        for entry in items:
            if len(entry) == 2:
                title, page_idx = entry
                children = []
            else:
                title, page_idx, children = entry
            item = pikepdf.OutlineItem(title, page_idx)
            for child_title, child_page_idx in children:
                item.children.append(pikepdf.OutlineItem(child_title, child_page_idx))
            ol.root.append(item)


def add_named_dest(pdf: pikepdf.Pdf, name: str, page_idx: int):
    """Add a single named destination pointing to page_idx."""
    if pikepdf.Name.Names not in pdf.Root:
        pdf.Root.Names = pdf.make_indirect(pikepdf.Dictionary())
    if pikepdf.Name.Dests in pdf.Root.Names:
        nt = pikepdf.NameTree(pdf.Root.Names.Dests)
    else:
        nt = pikepdf.NameTree.new(pdf)
        pdf.Root.Names.Dests = nt.obj
    dest_array = pikepdf.Array([pdf.pages[page_idx].obj, pikepdf.Name.Fit])
    nt[name] = dest_array


def add_named_dest_bookmark(pdf: pikepdf.Pdf, title: str, dest_name: str):
    """Add a bookmark that references a named destination by string."""
    with pdf.open_outline() as ol:
        item = pikepdf.OutlineItem(title, pikepdf.String(dest_name))
        ol.root.append(item)


def roundtrip(pdf: pikepdf.Pdf) -> pikepdf.Pdf:
    """Save to a BytesIO buffer and reopen — resolves all indirect references."""
    buf = io.BytesIO()
    pdf.save(buf)
    buf.seek(0)
    return pikepdf.open(buf)


def dest_page_index(output_pdf: pikepdf.Pdf, dest_array) -> int:
    """
    Given a destination array from an outline item in output_pdf,
    return the 0-based page index it resolves to.
    """
    page_obj = dest_array[0]
    for i, page in enumerate(output_pdf.pages):
        if page.obj.objgen == page_obj.objgen:
            return i
    raise ValueError(f"Destination page not found in output PDF: {dest_array}")


def named_dest_page_index(output_pdf: pikepdf.Pdf, name: str) -> int:
    """Look up a named destination in output_pdf and return its page index."""
    nt = dict(pikepdf.NameTree(output_pdf.Root.Names.Dests).items())
    dest_array = nt[name]
    return dest_page_index(output_pdf, dest_array)


class Row:
    """Minimal stand-in for pdfarranger's page-row model object."""

    def __init__(self, nfile: int, npage: int):
        """Initialize with 1-based file/page indices."""
        self.nfile = nfile
        self.npage = npage


# ---------------------------------------------------------------------------
# Tests: basic single-file cases
# ---------------------------------------------------------------------------


class TestSingleFileIdentity:
    """All pages kept in original order — bookmarks should be preserved as-is."""

    def test_single_bookmark(self):
        src = make_pdf(3)
        add_outline(src, [("Chapter 1", 0), ("Chapter 2", 1), ("Chapter 3", 2)])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 1), Row(1, 2), Row(1, 3)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert [item.title for item in ol.root] == [
                "Chapter 1",
                "Chapter 2",
                "Chapter 3",
            ]
            assert dest_page_index(out, ol.root[0].destination) == 0
            assert dest_page_index(out, ol.root[1].destination) == 1
            assert dest_page_index(out, ol.root[2].destination) == 2

    def test_no_outline_produces_no_outline(self):
        src = make_pdf(2)
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root == []


class TestPageSubset:
    """Only a subset of pages is kept — bookmarks to excluded pages must be dropped."""

    def test_bookmark_to_excluded_page_is_dropped(self):
        src = make_pdf(3)
        add_outline(src, [("Keep", 0), ("Drop", 1), ("Also keep", 2)])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]  # page 2 excluded
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            titles = [item.title for item in ol.root]
            assert "Drop" not in titles
            assert "Keep" in titles
            assert "Also keep" in titles

    def test_bookmark_targets_remapped_to_new_positions(self):
        src = make_pdf(3)
        add_outline(src, [("First", 0), ("Third", 2)])
        src = roundtrip(src)

        # Keep only pages 1 and 3, so output page 0 = src page 0, output page 1 = src page 2
        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert dest_page_index(out, ol.root[0].destination) == 0
            assert dest_page_index(out, ol.root[1].destination) == 1

    def test_all_bookmarks_excluded_leaves_empty_outline(self):
        src = make_pdf(3)
        add_outline(src, [("Page 2", 1), ("Page 3", 2)])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]  # only page 1 kept, neither bookmark target survives
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root == []


class TestPageReordering:
    """Pages reordered — bookmark destinations must follow their pages."""

    def test_reversed_pages(self):
        src = make_pdf(3)
        add_outline(src, [("A", 0), ("B", 1), ("C", 2)])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 3), Row(1, 2), Row(1, 1)]  # reversed
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            # "A" pointed to src page 0, which is now output page 2
            assert dest_page_index(out, ol.root[0].destination) == 2
            # "B" → src page 1 → output page 1
            assert dest_page_index(out, ol.root[1].destination) == 1
            # "C" → src page 2 → output page 0
            assert dest_page_index(out, ol.root[2].destination) == 0


# ---------------------------------------------------------------------------
# Tests: nested bookmarks
# ---------------------------------------------------------------------------


class TestNestedBookmarks:
    def test_nested_children_preserved(self):
        src = make_pdf(3)
        add_outline(src, [("Chapter 1", 0, [("Section 1.1", 1), ("Section 1.2", 2)])])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 1), Row(1, 2), Row(1, 3)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root[0].title == "Chapter 1"
            children = ol.root[0].children
            assert len(children) == 2
            assert children[0].title == "Section 1.1"
            assert children[1].title == "Section 1.2"
            assert dest_page_index(out, children[0].destination) == 1
            assert dest_page_index(out, children[1].destination) == 2

    def test_parent_dropped_but_valid_children_promoted(self):
        """
        Parent bookmark points to an excluded page, but its children point to
        included pages. The parent should still appear (with no valid dest of
        its own) because it has surviving children.
        """
        src = make_pdf(3)
        add_outline(
            src,
            [
                ("Chapter", 0, [("Section", 2)])  # parent→p0 excluded, child→p2 kept
            ],
        )
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 2), Row(1, 3)]  # pages 2 and 3 only
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            # Parent must still exist because child survived
            assert len(ol.root) == 1
            assert ol.root[0].title == "Chapter"
            assert len(ol.root[0].children) == 1
            assert ol.root[0].children[0].title == "Section"

    def test_parent_and_all_children_excluded_produces_nothing(self):
        src = make_pdf(4)
        add_outline(src, [("Drop everything", 0, [("Also drop", 1)])])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 3), Row(1, 4)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root == []

    def test_parent_without_destination_is_kept_if_child_survives(self):
        """A bookmark acting purely as a folder (no dest) hits the fallback return None."""
        src = make_pdf(1)
        with src.open_outline() as ol:
            # Create a parent with no destination or action (this hits line 148)
            parent = pikepdf.OutlineItem("Folder")
            # Give it a child with a valid destination so it survives the prune check
            child = pikepdf.OutlineItem("Child", 0)
            parent.children.append(child)
            ol.root.append(parent)
        src = roundtrip(src)
        out = make_pdf(1)
        pages = [Row(1, 1)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)
        with out.open_outline() as ol:
            assert len(ol.root) == 1
            # Parent survives and remains destination-less
            assert ol.root[0].title == "Folder"
            assert ol.root[0].destination is None
            # Child survives and points to the correct page
            assert len(ol.root[0].children) == 1
            assert ol.root[0].children[0].title == "Child"
            assert dest_page_index(out, ol.root[0].children[0].destination) == 0


# ---------------------------------------------------------------------------
# Tests: named destinations
# ---------------------------------------------------------------------------


class TestNamedDestinations:
    def test_named_dest_bookmark_remapped(self):
        src = make_pdf(3)
        add_named_dest(src, "chapter-one", 1)  # points to page index 1
        add_named_dest_bookmark(src, "Chapter One", "chapter-one")
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 1), Row(1, 2), Row(1, 3)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert len(ol.root) == 1
            assert ol.root[0].title == "Chapter One"

        # The named dest should exist in the output under the remapped name
        assert named_dest_page_index(out, "f0-chapter-one") == 1

    def test_named_dest_to_excluded_page_is_dropped(self):
        src = make_pdf(3)
        add_named_dest(src, "excluded", 1)  # page index 1 will be excluded
        add_named_dest_bookmark(src, "Excluded Chapter", "excluded")
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]  # page 2 (index 1) excluded
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root == []

    def test_named_dest_target_follows_reordering(self):
        src = make_pdf(3)
        add_named_dest(src, "last", 2)  # originally page index 2 (last)
        add_named_dest_bookmark(src, "Last Page", "last")
        src = roundtrip(src)

        # Reverse page order
        out = make_pdf(3)
        pages = [Row(1, 3), Row(1, 2), Row(1, 1)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        # src page 2 is now output page 0 after reversal
        assert named_dest_page_index(out, "f0-last") == 0

    def test_unknown_named_dest_is_dropped(self):
        """Bookmark references a named dest that doesn't exist in the source PDF."""
        src = make_pdf(2)
        # Manually add a bookmark with a named dest that has no entry in the dest table
        with src.open_outline() as ol:
            ol.root.append(pikepdf.OutlineItem("Ghost", pikepdf.String("nonexistent")))
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root == []


# ---------------------------------------------------------------------------
# Tests: multi-file merge
# ---------------------------------------------------------------------------


class TestMultiFileMergeBookmarks:
    def test_bookmarks_from_both_files_appear(self):
        src_a = make_pdf(2)
        add_outline(src_a, [("File A Ch1", 0), ("File A Ch2", 1)])
        src_a = roundtrip(src_a)

        src_b = make_pdf(2)
        add_outline(src_b, [("File B Ch1", 0), ("File B Ch2", 1)])
        src_b = roundtrip(src_b)

        out = make_pdf(4)
        pages = [Row(1, 1), Row(1, 2), Row(2, 1), Row(2, 2)]
        rebuild_outlines([src_a, src_b], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            titles = [item.title for item in ol.root]
            assert "File A Ch1" in titles
            assert "File A Ch2" in titles
            assert "File B Ch1" in titles
            assert "File B Ch2" in titles

    def test_bookmarks_point_to_correct_output_pages_after_merge(self):
        src_a = make_pdf(2)
        add_outline(src_a, [("A1", 0), ("A2", 1)])
        src_a = roundtrip(src_a)

        src_b = make_pdf(2)
        add_outline(src_b, [("B1", 0), ("B2", 1)])
        src_b = roundtrip(src_b)

        # Interleave: A1, B1, A2, B2
        out = make_pdf(4)
        pages = [Row(1, 1), Row(2, 1), Row(1, 2), Row(2, 2)]
        rebuild_outlines([src_a, src_b], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            by_title = {item.title: item for item in ol.root}
            assert dest_page_index(out, by_title["A1"].destination) == 0
            assert dest_page_index(out, by_title["B1"].destination) == 1
            assert dest_page_index(out, by_title["A2"].destination) == 2
            assert dest_page_index(out, by_title["B2"].destination) == 3

    def test_file_with_no_outline_is_skipped_gracefully(self):
        src_a = make_pdf(2)
        add_outline(src_a, [("Only A", 0)])
        src_a = roundtrip(src_a)

        src_b = make_pdf(2)  # no outline
        src_b = roundtrip(src_b)

        out = make_pdf(4)
        pages = [Row(1, 1), Row(1, 2), Row(2, 1), Row(2, 2)]
        rebuild_outlines([src_a, src_b], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert len(ol.root) == 1
            assert ol.root[0].title == "Only A"

    def test_named_dest_collision_across_files_both_survive(self):
        """
        Both files have a named dest called 'intro'. After merge they should
        become 'f0-intro' and 'f1-intro' — neither should overwrite the other.
        """
        src_a = make_pdf(2)
        add_named_dest(src_a, "intro", 0)
        add_named_dest_bookmark(src_a, "Intro A", "intro")
        src_a = roundtrip(src_a)

        src_b = make_pdf(2)
        add_named_dest(src_b, "intro", 0)
        add_named_dest_bookmark(src_b, "Intro B", "intro")
        src_b = roundtrip(src_b)

        out = make_pdf(4)
        pages = [Row(1, 1), Row(1, 2), Row(2, 1), Row(2, 2)]
        rebuild_outlines([src_a, src_b], out, pages)
        out = roundtrip(out)

        # Both named dests must exist
        nt = dict(pikepdf.NameTree(out.Root.Names.Dests).items())
        assert "f0-intro" in nt
        assert "f1-intro" in nt
        # And point to the right output pages
        assert named_dest_page_index(out, "f0-intro") == 0
        assert named_dest_page_index(out, "f1-intro") == 2


# ---------------------------------------------------------------------------
# Tests: duplicate pages
# ---------------------------------------------------------------------------


class TestDuplicatePagesBookmarks:
    def test_bookmark_targets_first_copy_of_duplicated_page(self):
        """
        When a source page appears twice in the output, bookmarks should
        resolve to the first copy (instance 0).
        """
        src = make_pdf(2)
        add_outline(src, [("Chapter", 0)])
        src = roundtrip(src)

        out = make_pdf(3)
        # Page 1 appears at output positions 0 and 2
        pages = [Row(1, 1), Row(1, 2), Row(1, 1)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert dest_page_index(out, ol.root[0].destination) == 0  # first copy


# ---------------------------------------------------------------------------
# Tests: edge cases and error handling
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_pages_list(self):
        src = make_pdf(2)
        add_outline(src, [("Chapter", 0)])
        src = roundtrip(src)

        out = pikepdf.new()
        rebuild_outlines([src], out, [])
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root == []

    def test_none_pdf_in_input_list_is_skipped(self):
        src = make_pdf(2)
        add_outline(src, [("Chapter", 0)])
        src = roundtrip(src)

        out = make_pdf(2)
        # pdf_input[0] is None, pdf_input[1] is our src
        pages = [Row(2, 1), Row(2, 2)]
        rebuild_outlines([None, src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as ol:
            assert ol.root[0].title == "Chapter"

    def test_warning_emitted_on_corrupt_outline(self):
        """
        If pikepdf raises PdfError while reading a source outline,
        rebuild_outlines should warn rather than crash.
        """
        src = make_pdf(2)
        add_outline(src, [("Chapter", 0)])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]

        with patch.object(
            src,
            "open_outline",
            side_effect=pikepdf.PdfError("Corrupt outline structure"),
        ):
            with pytest.warns(
                UserWarning,
                match="Failed to copy bookmarks from document 1:",
            ):
                rebuild_outlines([src], out, pages)

    def test_write_named_dests_no_op_on_empty_list(self):
        pdf = make_pdf(1)
        write_named_dests(pdf, [])  # must not crash or create spurious structure
        assert pikepdf.Name.Names not in pdf.Root

    def test_write_named_dests_creates_name_tree_when_absent(self):
        pdf = make_pdf(2)
        dest_array = pikepdf.Array([pdf.pages[1].obj, pikepdf.Name.Fit])
        write_named_dests(pdf, [("my-dest", dest_array)])
        pdf = roundtrip(pdf)

        nt = dict(pikepdf.NameTree(pdf.Root.Names.Dests).items())
        assert "my-dest" in nt

    def test_write_named_dests_merges_into_existing_name_tree(self):
        pdf = make_pdf(3)
        # Pre-populate a NameTree
        add_named_dest(pdf, "existing", 0)
        # Now add a new one via write_named_dests
        dest_array = pikepdf.Array([pdf.pages[2].obj, pikepdf.Name.Fit])
        write_named_dests(pdf, [("new-dest", dest_array)])
        pdf = roundtrip(pdf)

        nt = dict(pikepdf.NameTree(pdf.Root.Names.Dests).items())
        assert "existing" in nt
        assert "new-dest" in nt

    def test_pdf_1_1_dests_and_indirect_coords(self):
        src = make_pdf(1)
        indirect_zoom = src.make_indirect(pikepdf.Dictionary(Zoom=1))
        dest_arr = pikepdf.Array(
            [src.pages[0].obj, pikepdf.Name.XYZ, 0, 0, indirect_zoom]
        )
        src.Root.Dests = pikepdf.Dictionary({"/old_style_dest": dest_arr})

        with src.open_outline() as outline:
            item = pikepdf.OutlineItem("Old Dest Item")
            item.destination = pikepdf.Name("/old_style_dest")
            outline.root.append(item)
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as outline:
            assert len(outline.root) == 1
            assert outline.root[0].title == "Old Dest Item"

    def test_invalid_destinations_dropped(self):
        src = make_pdf(1)
        with src.open_outline() as outline:
            # Empty array bypassed via action dictionary
            item1 = pikepdf.OutlineItem("Empty Array")
            item1.action = pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=pikepdf.Array())
            outline.root.append(item1)

            # Invalid type (Dictionary) bypassed via action dictionary
            item2 = pikepdf.OutlineItem("Invalid Type")
            item2.action = pikepdf.Dictionary(
                S=pikepdf.Name.GoTo, D=pikepdf.Dictionary()
            )
            outline.root.append(item2)

            # Target page object isn't in rev_map
            dummy_obj = src.make_indirect(pikepdf.String("Not a page"))
            item3 = pikepdf.OutlineItem("Foreign Page Object")
            item3.destination = pikepdf.Array([dummy_obj, pikepdf.Name.Fit])
            outline.root.append(item3)
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as outline:
            assert len(outline.root) == 0

    def test_missing_objgen_dropped(self):
        src = make_pdf(1)
        with src.open_outline() as outline:
            item = pikepdf.OutlineItem("No Objgen")
            item.destination = pikepdf.Array([src.pages[0].obj, pikepdf.Name.Fit])
            outline.root.append(item)
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]

        original_hasattr = builtins.hasattr

        def mock_hasattr(obj, attr_name):
            if attr_name == "objgen":
                return False
            return original_hasattr(obj, attr_name)

        with patch("builtins.hasattr", side_effect=mock_hasattr):
            rebuild_outlines([src], out, pages)

        with out.open_outline() as outline:
            assert len(outline.root) == 0

    def test_goto_action_outline(self):
        src = make_pdf(1)
        with src.open_outline() as outline:
            item = pikepdf.OutlineItem("Action Item")
            item.action = pikepdf.Dictionary(
                S=pikepdf.Name.GoTo,
                D=pikepdf.Array([src.pages[0].obj, pikepdf.Name.Fit]),
            )
            outline.root.append(item)
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)

        with out.open_outline() as outline:
            assert len(outline.root) == 1
            assert outline.root[0].title == "Action Item"

    def test_pdf_error_warning_during_copy(self):
        src = make_pdf(1)
        add_outline(src, [("Trigger", 0)])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]

        with patch(
            "pdfarranger.exporter_outlines.OutlineCopier.copy_item",
            side_effect=pikepdf.PdfError("Corrupted Tree!"),
        ):
            with pytest.warns(
                UserWarning,
                match="Failed to copy bookmarks from document 1: Corrupted Tree!",
            ):
                rebuild_outlines([src], out, pages)


class TestScaling:
    def test_various_fit_types_scaling(self):
        """Test scaling for FitH, FitV, FitBH, FitBV (single coordinate types)."""
        src = make_pdf(1)
        # Each of these takes one coordinate (top or left) at index 2
        types = [
            pikepdf.Name.FitH,
            pikepdf.Name.FitV,
            pikepdf.Name.FitBH,
            pikepdf.Name.FitBV,
        ]
        with src.open_outline() as ol:
            for t in types:
                ol.root.append(
                    pikepdf.OutlineItem(
                        str(t), pikepdf.Array([src.pages[0].obj, t, 50])
                    )
                )
        src = roundtrip(src)

        out = make_pdf(1)
        row = Row(1, 1)
        row.scale = 0.5
        rebuild_outlines([src], out, [row])

        with out.open_outline() as ol:
            for i in range(len(types)):
                assert ol.root[i].destination[2] == 25.0

    def test_invalid_destination_structures(self):
        """Test handling of malformed destination objects."""
        src = make_pdf(1)
        with src.open_outline() as ol:
            # Case 1: Destination array too short
            ol.root.append(
                pikepdf.OutlineItem("Too Short", pikepdf.Array([src.pages[0].obj]))
            )
            # Case 2: First element is not a page reference (no objgen)
            ol.root.append(
                pikepdf.OutlineItem(
                    "No Ref", pikepdf.Array([pikepdf.Name.Fit, pikepdf.Name.Fit])
                )
            )
        src = roundtrip(src)

        out = make_pdf(1)
        rebuild_outlines([src], out, [Row(1, 1)])

        with out.open_outline() as ol:
            # Both should be dropped because they are invalid
            assert len(ol.root) == 0

    def test_named_dest_with_d_attribute(self):
        """Test named destinations defined as dictionaries with a /D key."""
        src = make_pdf(1)
        # Define named dest as << /D [page /Fit] >> instead of just the array
        dest_dict = pikepdf.Dictionary(
            D=pikepdf.Array([src.pages[0].obj, pikepdf.Name.Fit])
        )

        if pikepdf.Name.Names not in src.Root:
            src.Root.Names = src.make_indirect(pikepdf.Dictionary())
        nt = pikepdf.NameTree.new(src)
        nt["complex-dest"] = dest_dict
        src.Root.Names.Dests = nt.obj

        add_named_dest_bookmark(src, "Complex", "complex-dest")
        src = roundtrip(src)

        out = make_pdf(1)
        rebuild_outlines([src], out, [Row(1, 1)])

        with out.open_outline() as ol:
            assert len(ol.root) == 1
            assert named_dest_page_index(out, "f0-complex-dest") == 0

    def test_destination_coordinate_scaling(self):
        """Test scaling of XYZ and FitR coordinates based on row scale factor."""
        src = make_pdf(1)
        # XYZ: [page, /XYZ, left, top, zoom]
        dest_xyz = pikepdf.Array([src.pages[0].obj, pikepdf.Name.XYZ, 100, 200, 0])
        # FitR: [page, /FitR, left, bottom, right, top]
        dest_fitr = pikepdf.Array([src.pages[0].obj, pikepdf.Name.FitR, 10, 20, 30, 40])

        with src.open_outline() as ol:
            ol.root.append(pikepdf.OutlineItem("XYZ", dest_xyz))
            ol.root.append(pikepdf.OutlineItem("FitR", dest_fitr))
        src = roundtrip(src)

        out = make_pdf(1)
        row = Row(1, 1)
        row.scale = 2.0
        pages = [row]

        rebuild_outlines([src], out, pages)
        # Note: We don't roundtrip 'out' yet if we want to check pikepdf object properties
        # before they are serialized/dereferenced.

        with out.open_outline() as ol:
            # Use list() on the destination array to allow standard Python indexing/slicing
            dest0 = list(ol.root[0].destination)
            assert [float(dest0[2]), float(dest0[3])] == [200.0, 400.0]

            dest1 = list(ol.root[1].destination)
            assert [float(x) for x in dest1[2:6]] == [20.0, 40.0, 60.0, 80.0]

    def test_annotation_coordinate_scaling_and_p_removal(self):
        """Test scaling of all auxiliary coordinate types and removal of the /P key."""
        src = make_pdf(1)
        annot = make_goto_action_annot(src, 0)

        # Populate all coordinate types handled by scale_annot_coords
        annot.QuadPoints = pikepdf.Array([10, 10, 20, 20, 30, 30, 40, 40])
        annot.Vertices = pikepdf.Array([5, 5, 15, 15])
        annot.CL = pikepdf.Array([1, 2, 3])
        annot.InkList = pikepdf.Array([pikepdf.Array([1, 2]), pikepdf.Array([3, 4])])

        # Inject a raw string to force survival through copy_foreign, hitting line 273
        annot.P = pikepdf.String("stale-p-ref")

        add_annots(src, 0, [annot])
        src = roundtrip(src)

        out = make_pdf(1)
        row = Row(1, 1)
        row.scale = 2.0  # Trigger scale factor != 1.0

        run_rebuild_links([src], out, [row])
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        new_annot = annots[0]

        # Verify all coordinate dimensions were scaled properly
        assert list(new_annot.QuadPoints) == [
            20.0,
            20.0,
            40.0,
            40.0,
            60.0,
            60.0,
            80.0,
            80.0,
        ]
        assert list(new_annot.Vertices) == [10.0, 10.0, 30.0, 30.0]
        assert list(new_annot.CL) == [2.0, 4.0, 6.0]
        assert list(new_annot.InkList[0]) == [2.0, 4.0]
        assert list(new_annot.InkList[1]) == [6.0, 8.0]

        # Verify old page reference key was dropped and replaced with the new page obj
        assert new_annot.P == out.pages[0].obj


# ---------------------------------------------------------------------------
# Tests: Outline styles and open/closed state
# ---------------------------------------------------------------------------


class TestOutlineStylesAndState:
    """Tests for visual styles (colors/flags) and collapsed/expanded states."""

    def test_styles_and_closed_state_preserved(self):
        """Color, font flags, and default closed state should survive remapping."""
        src = make_pdf(2)
        with src.open_outline() as ol:
            parent = pikepdf.OutlineItem("Styled Parent", 0)
            # Give the new item a dictionary to hold custom styles ---
            parent.obj = pikepdf.Dictionary()
            # Set color to red [1.0, 0.0, 0.0] and font to bold-italic (3)
            parent.obj[pikepdf.Name.C] = pikepdf.Array([1.0, 0.0, 0.0])
            parent.obj[pikepdf.Name.F] = 3
            # Add a child so the parent has something to collapse
            child = pikepdf.OutlineItem("Child", 1)
            parent.children.append(child)
            parent.is_closed = True
            ol.root.append(parent)
        src = roundtrip(src)
        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        rebuild_outlines([src], out, pages)
        out = roundtrip(out)
        with out.open_outline() as ol:
            assert len(ol.root) == 1
            parent_out = ol.root[0]
            # Verify the color and style flags carried over
            assert pikepdf.Name.C in parent_out.obj
            assert list(parent_out.obj[pikepdf.Name.C]) == [1.0, 0.0, 0.0]
            assert pikepdf.Name.F in parent_out.obj
            assert parent_out.obj[pikepdf.Name.F] == 3
            # Verify it is still closed
            assert parent_out.is_closed is True


# ---------------------------------------------------------------------------
# Issue 1395
# ---------------------------------------------------------------------------


def test_null_coordinates_in_xyz_destination():
    """
    XYZ destinations with null coordinates (e.g. [page /XYZ null null null])
    must survive remapping. This is the standard PDF idiom meaning 'inherit
    current position/zoom'. Broke in pikepdf 10.6+ after the pybind11→nanobind
    migration (Array.append(None) stopped accepting None).
    """
    src = make_pdf(2)
    with src.open_outline() as ol:
        for i, title in enumerate(["Chapter 1", "Chapter 2"]):
            ol.root.append(
                pikepdf.OutlineItem(
                    title,
                    pikepdf.Array(
                        [src.pages[i].obj, pikepdf.Name.XYZ, None, None, None]
                    ),
                )
            )
    src = roundtrip(src)

    out = make_pdf(2)
    pages = [Row(1, 1), Row(1, 2)]
    rebuild_outlines([src], out, pages)
    out = roundtrip(out)

    with out.open_outline() as ol:
        assert len(ol.root) == 2
        assert ol.root[0].title == "Chapter 1"
        assert ol.root[1].title == "Chapter 2"
        assert dest_page_index(out, ol.root[0].destination) == 0
        assert dest_page_index(out, ol.root[1].destination) == 1
        # Null coordinates must be preserved, not dropped or mangled
        for item in ol.root:
            dest = item.destination
            assert dest[1] == pikepdf.Name.XYZ
            assert dest[2] is None
            assert dest[3] is None
            assert dest[4] is None


# Mock the Row object that pdfarranger uses for page sequences
PageRow = namedtuple("PageRow", ["nfile", "npage", "scale"])


@pytest.fixture
def sample_input_pdf(tmp_path):
    """Generates an input PDF with a strict nested outline hierarchy."""
    pdf_path = tmp_path / "input.pdf"
    with pikepdf.Pdf.new() as pdf:
        # Add 3 blank pages to map destinations to
        for _ in range(3):
            pdf.add_blank_page()

        with pdf.open_outline() as outline:
            # Level 1 Parent
            p1 = pikepdf.OutlineItem("Root Parent", 0)
            # Level 2 Child
            c1 = pikepdf.OutlineItem("Child Level 1", 1)
            # Level 3 Grandchild
            g1 = pikepdf.OutlineItem("Grandchild Level 2", 2)

            # Assemble tree manually
            c1.children.append(g1)
            p1.children.append(c1)
            outline.root.append(p1)

        pdf.save(pdf_path)
    return pdf_path


def test_rebuild_outlines_preserves_nested_hierarchy(sample_input_pdf):
    # Open the generated test source PDF
    with pikepdf.open(sample_input_pdf) as pdf_in:
        pdf_input = [pdf_in]

        # Create an output PDF context
        with pikepdf.Pdf.new() as pdf_out:
            # Replicate pages sequence mapping from file 1
            pdf_out.add_blank_page()
            pdf_out.add_blank_page()
            pdf_out.add_blank_page()

            pages_map = [
                PageRow(nfile=1, npage=1, scale=1.0),
                PageRow(nfile=1, npage=2, scale=1.0),
                PageRow(nfile=1, npage=3, scale=1.0),
            ]

            # Execute the processor
            rebuild_outlines(pdf_input, pdf_out, pages_map)

            # Verify structural health of output outlines
            with pdf_out.open_outline() as out_outline:
                assert len(out_outline.root) == 1

                root_node = out_outline.root[0]
                assert root_node.title == "Root Parent"
                assert len(root_node.children) == 1

                child_node = root_node.children[0]
                assert child_node.title == "Child Level 1"
                assert len(child_node.children) == 1

                grandchild_node = child_node.children[0]
                assert grandchild_node.title == "Grandchild Level 2"
                assert len(grandchild_node.children) == 0

                # Validate low-level PDF structural binding integrity
                # A broken structural binding usually results in missing target dictionary keys
                assert pikepdf.Name.Parent in grandchild_node.obj
                assert grandchild_node.obj.Parent == child_node.obj


def test_vacon_low_level_structure_regression(tmp_path):
    pdf_path = tmp_path / "mock_vacon.pdf"
    out_path = tmp_path / "out.pdf"

    # 1. Build the PDF "The Hard Way" (Low-level dictionaries)
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()

        # Mirror Vacon's structure:
        # Item 1 has an Action (/A) instead of a Dest, AND a color array (/C)
        item1 = pdf.make_indirect(
            pikepdf.Dictionary(
                Title="Sisällys",
                A=pikepdf.Dictionary(S=pikepdf.Name.GoTo, D="TOC"),
                C=pikepdf.Array([0, 0, 0]),
            )
        )

        # Item 2 is a sibling to prove the linked list breaks
        item2 = pdf.make_indirect(
            pikepdf.Dictionary(
                Title="Esipuhe", A=pikepdf.Dictionary(S=pikepdf.Name.GoTo, D="AN10025")
            )
        )

        # Manually wire the linked list
        item1.Next = item2
        item2.Prev = item1

        outlines = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Outlines, First=item1, Last=item2, Count=2
            )
        )
        item1.Parent = outlines
        item2.Parent = outlines

        pdf.Root.Outlines = outlines

        # Add a NameTree so fixed code can resolve the strings
        dests = pikepdf.NameTree.new(pdf)
        dests["TOC"] = pikepdf.Array(
            [pdf.pages[0].obj, pikepdf.Name.XYZ, None, None, None]
        )
        dests["AN10025"] = pikepdf.Array(
            [pdf.pages[0].obj, pikepdf.Name.XYZ, None, None, None]
        )
        pdf.Root.Names = pikepdf.Dictionary(Dests=dests.obj)

        pdf.save(pdf_path)

    # 2. Run rebuild_outlines
    with pikepdf.open(pdf_path) as pdf_in:
        with pikepdf.Pdf.new() as pdf_out:
            pdf_out.add_blank_page()
            pages_map = [PageRow(nfile=1, npage=1, scale=1.0)]

            rebuild_outlines([pdf_in], pdf_out, pages_map)
            pdf_out.save(out_path)

    # 3. Assertions
    with pikepdf.open(out_path) as pdf_res:
        with pdf_res.open_outline() as res_outline:
            assert len(res_outline.root) == 2, "Outline tree collapsed!"

            item1_out = res_outline.root[0]
            item2_out = res_outline.root[1]

            # --- FAILURE 1: Dead Bookmark ---
            # `main` fails to parse the /A GoTo dictionary, leaving the output bookmark dead
            has_dest = item1_out.destination is not None
            has_action = pikepdf.Name.A in item1_out.obj
            assert has_dest or has_action, (
                "FAIL: Bookmark completely lost its destination/action!"
            )

            # --- FAILURE 2: Direct Object Corruption ---
            # `main` overwrites the obj dictionary to copy the Color array, forcing a Direct Object
            assert item1_out.obj.is_indirect, (
                "FAIL: Bookmark was corrupted into a Direct Object!"
            )

            # --- FAILURE 3: Broken Pointers ---
            # The direct object causes the sibling to point back to (0, 0)
            assert pikepdf.Name.Prev in item2_out.obj
            try:
                obj_num = item2_out.obj.Prev.objgen[0]
            except AttributeError:
                obj_num = 0
            assert obj_num != 0, "FAIL: Sibling has a broken /Prev (0, 0) pointer!"


"""Tests for rebuild_links — internal hyperlink remapping when pdfarranger
reorders, subsets, or merges pages.

Reuses the same helpers as test_exporter_outlines.py (make_pdf, Row, roundtrip,
dest_page_index).  Kept in a separate file so the two test modules stay focused.
"""


# ---------------------------------------------------------------------------
# Annotation factories
# ---------------------------------------------------------------------------


def make_goto_action_annot(
    pdf: pikepdf.Pdf, target_page_idx: int, rect=None
) -> pikepdf.Dictionary:
    """Link annotation whose destination is wrapped in a /GoTo /A action."""
    if rect is None:
        rect = [0, 700, 100, 792]
    return pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Link,
        Rect=pikepdf.Array(rect),
        A=pikepdf.Dictionary(
            S=pikepdf.Name.GoTo,
            D=pikepdf.Array([pdf.pages[target_page_idx].obj, pikepdf.Name.Fit]),
        ),
    )


def make_dest_annot(
    pdf: pikepdf.Pdf, target_page_idx: int, rect=None
) -> pikepdf.Dictionary:
    """Link annotation with a /Dest key directly (no /A wrapper)."""
    if rect is None:
        rect = [0, 700, 100, 792]
    return pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Link,
        Rect=pikepdf.Array(rect),
        Dest=pikepdf.Array([pdf.pages[target_page_idx].obj, pikepdf.Name.Fit]),
    )


def make_uri_annot(uri: str = "https://example.com", rect=None) -> pikepdf.Dictionary:
    """External URI link annotation — should pass through untouched."""
    if rect is None:
        rect = [0, 600, 100, 700]
    return pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Link,
        Rect=pikepdf.Array(rect),
        A=pikepdf.Dictionary(
            S=pikepdf.Name.URI,
            URI=pikepdf.String(uri),
        ),
    )


def make_non_link_annot(rect=None) -> pikepdf.Dictionary:
    """A non-Link annotation (e.g. a text note) — must be preserved as-is."""
    if rect is None:
        rect = [0, 500, 100, 600]
    return pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Text,
        Contents=pikepdf.String("A comment"),
        Rect=pikepdf.Array(rect),
    )


def add_annots(pdf: pikepdf.Pdf, page_idx: int, annots: list) -> None:
    """Attach a list of annotation dicts to a page, making each indirect."""
    pdf.pages[page_idx].Annots = pikepdf.Array([pdf.make_indirect(a) for a in annots])


def get_annots(pdf: pikepdf.Pdf, page_idx: int) -> list:
    """Return annotations on a page as a plain Python list."""
    page = pdf.pages[page_idx]
    if pikepdf.Name.Annots not in page:
        return []
    return list(page.Annots)


def simulate_append_page(pdf_input, pdf_output, pages):
    """Pre-populate out_page.Annots as _append_page does, before rebuild_links."""
    for row in pages:
        file_idx = row.nfile - 1
        src_page = pdf_input[file_idx].pages[row.npage - 1]
        out_page = pdf_output.pages[pages.index(row)]
        if pikepdf.Name.Annots in src_page:
            pdf_temp = pikepdf.Pdf.new()
            pdf_temp.pages.append(src_page)
            indirect_annots = pdf_temp.make_indirect(pdf_temp.pages[0].Annots)
            out_page.Annots = pdf_output.copy_foreign(indirect_annots)


def run_rebuild_links(pdf_input, pdf_output, pages):
    simulate_append_page(pdf_input, pdf_output, pages)
    remapper = OutlineRemapper(pdf_input, pdf_output, pages)
    rebuild_links(pdf_input, pdf_output, pages, remapper)


# ---------------------------------------------------------------------------
# Basic GoTo action link tests
# ---------------------------------------------------------------------------


class TestGoToActionLinks:
    """Link annotations that use /A with S=/GoTo."""

    def test_identity_single_page(self):
        """Single page kept in place — link to self still resolves."""
        src = make_pdf(1)
        add_annots(src, 0, [make_goto_action_annot(src, 0)])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert dest_page_index(out, annots[0].A.D) == 0

    def test_link_follows_target_page_after_reorder(self):
        """Link on page 0 targeting page 2; pages are reversed in output."""
        src = make_pdf(3)
        add_annots(src, 0, [make_goto_action_annot(src, 2)])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 3), Row(1, 2), Row(1, 1)]  # reversed
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        # src page 2 (index) is now output page 0
        annots = get_annots(out, 2)  # source page 0 ended up at output index 2
        assert len(annots) == 1
        assert dest_page_index(out, annots[0].A.D) == 0

    def test_link_to_excluded_page_is_dropped(self):
        """Target page removed from output — annotation must be dropped."""
        src = make_pdf(3)
        add_annots(src, 0, [make_goto_action_annot(src, 1)])  # targets middle page
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]  # page 2 (index 1) excluded
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        assert get_annots(out, 0) == []

    def test_link_source_page_excluded_no_crash(self):
        """Page carrying the annotation is excluded — its output page differs, no crash."""
        src = make_pdf(3)
        add_annots(src, 1, [make_goto_action_annot(src, 2)])
        src = roundtrip(src)

        # Only keep pages 1 and 3; page 2 (index 1) with the annotation is dropped
        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]
        run_rebuild_links([src], out, pages)
        # Page 2 was excluded, so output has 2 pages from pages 1 and 3
        assert get_annots(out, 0) == []  # page 1 had no annots
        assert get_annots(out, 1) == []  # page 3 had no annots
        out = roundtrip(out)
        assert len(out.pages) == 2


# ---------------------------------------------------------------------------
# Direct /Dest link tests
# ---------------------------------------------------------------------------


class TestDirectDestLinks:
    """Link annotations that carry /Dest directly instead of /A."""

    def test_direct_dest_remapped(self):
        src = make_pdf(2)
        add_annots(src, 0, [make_dest_annot(src, 1)])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert dest_page_index(out, annots[0].Dest) == 1

    def test_direct_dest_follows_reorder(self):
        src = make_pdf(3)
        add_annots(src, 0, [make_dest_annot(src, 2)])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 3), Row(1, 2), Row(1, 1)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        # Source page 0 ends up at output index 2
        annots = get_annots(out, 2)
        assert len(annots) == 1
        # Source page 2 ends up at output index 0
        assert dest_page_index(out, annots[0].Dest) == 0

    def test_direct_dest_to_excluded_page_dropped(self):
        src = make_pdf(3)
        add_annots(src, 0, [make_dest_annot(src, 1)])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        assert get_annots(out, 0) == []


# ---------------------------------------------------------------------------
# Passthrough tests — annotations that must not be modified
# ---------------------------------------------------------------------------


class TestPassthroughAnnotations:
    def test_uri_link_preserved(self):
        src = make_pdf(1)
        add_annots(src, 0, [make_uri_annot("https://example.com")])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert str(annots[0].A.S) == "/URI"
        assert str(annots[0].A.URI) == "https://example.com"

    def test_non_link_annotation_preserved(self):
        src = make_pdf(1)
        add_annots(src, 0, [make_non_link_annot()])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert annots[0].Subtype == pikepdf.Name.Text

    def test_mixed_annots_on_same_page(self):
        """GoTo link, URI link, and text note all on one page — each handled correctly."""
        src = make_pdf(2)
        add_annots(
            src,
            0,
            [
                make_goto_action_annot(src, 1),
                make_uri_annot(),
                make_non_link_annot(),
            ],
        )
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 3
        subtypes = [str(a.Subtype) for a in annots]
        assert subtypes.count("/Link") == 2
        assert subtypes.count("/Text") == 1

    def test_gotor_action_preserved(self):
        """GoToR (cross-document) links must pass through without remapping."""
        src = make_pdf(1)
        gotor = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 100, 100]),
            A=pikepdf.Dictionary(
                S=pikepdf.Name.GoToR,
                F=pikepdf.String("other.pdf"),
                D=pikepdf.Array([0, pikepdf.Name.Fit]),
            ),
        )
        add_annots(src, 0, [gotor])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert str(annots[0].A.S) == "/GoToR"

    def test_link_with_no_action_and_no_dest_preserved(self):
        """A Link annotation with neither /A nor /Dest (unusual but valid) is kept."""
        src = make_pdf(1)
        bare_link = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 100, 100]),
        )
        add_annots(src, 0, [bare_link])
        src = roundtrip(src)

        out = make_pdf(1)
        pages = [Row(1, 1)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1


# ---------------------------------------------------------------------------
# Page with no annotations
# ---------------------------------------------------------------------------


class TestNoAnnotations:
    def test_page_without_annots_unchanged(self):
        src = make_pdf(2)
        # Only page 1 has annotations
        add_annots(src, 1, [make_goto_action_annot(src, 0)])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        assert get_annots(out, 0) == []
        assert len(get_annots(out, 1)) == 1

    def test_stale_output_annots_deleted_when_source_has_none(self):
        """Line 301: Output page /Annots gets cleared if the source page has no annotations."""
        src = make_pdf(1)  # Clean source page with no annotations
        src = roundtrip(src)

        out = make_pdf(1)
        # Pre-populate the output page manually with a dummy annotation entry
        stale_annot = out.make_indirect(make_non_link_annot())
        out.pages[0].Annots = pikepdf.Array([stale_annot])

        # Run rebuild_links directly to step into the target branch code path
        remapper = OutlineRemapper([src], out, [Row(1, 1)])
        rebuild_links([src], out, [Row(1, 1)], remapper)

        # Ensure the stale annotations array has been deleted completely
        assert pikepdf.Name.Annots not in out.pages[0]


# ---------------------------------------------------------------------------
# Duplicate pages
# ---------------------------------------------------------------------------


class TestDuplicatePagesLinks:
    def test_both_copies_link_to_first_copy(self):
        """
        Source page 0 is duplicated to output positions 0 and 2.
        Both copies carry a link targeting source page 1 (output page 1).
        Both should resolve correctly.
        """
        src = make_pdf(2)
        add_annots(src, 0, [make_goto_action_annot(src, 1)])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 1), Row(1, 2), Row(1, 1)]  # page 1 duplicated
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        for out_idx in (0, 2):
            annots = get_annots(out, out_idx)
            assert len(annots) == 1
            assert dest_page_index(out, annots[0].A.D) == 1

    def test_link_targeting_duplicated_page_resolves_to_first_copy(self):
        """
        A link points at a page that appears twice in the output.
        It must resolve to the first copy (instance 0).
        """
        src = make_pdf(2)
        add_annots(src, 1, [make_goto_action_annot(src, 0)])
        src = roundtrip(src)

        out = make_pdf(3)
        pages = [Row(1, 1), Row(1, 1), Row(1, 2)]  # page 1 at positions 0 and 1
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 2)
        assert len(annots) == 1
        assert dest_page_index(out, annots[0].A.D) == 0  # first copy


# ---------------------------------------------------------------------------
# Multi-file merge
# ---------------------------------------------------------------------------


class TestMultiFileMergeLinks:
    def test_links_from_both_files_remapped(self):
        src_a = make_pdf(2)
        add_annots(src_a, 0, [make_goto_action_annot(src_a, 1)])
        src_a = roundtrip(src_a)

        src_b = make_pdf(2)
        add_annots(src_b, 0, [make_goto_action_annot(src_b, 1)])
        src_b = roundtrip(src_b)

        out = make_pdf(4)
        pages = [Row(1, 1), Row(1, 2), Row(2, 1), Row(2, 2)]
        run_rebuild_links([src_a, src_b], out, pages)
        out = roundtrip(out)

        # File A: link on output page 0 → output page 1
        assert dest_page_index(out, get_annots(out, 0)[0].A.D) == 1
        # File B: link on output page 2 → output page 3
        assert dest_page_index(out, get_annots(out, 2)[0].A.D) == 3

    def test_cross_file_link_not_remapped(self):
        """
        A GoTo link whose destination page object is not in the source file's
        rev_map cannot be resolved and must be dropped (not crash).

        We simulate this by constructing an annotation whose /D references a
        dummy indirect object (not a real page), so rev_map lookup returns None.
        """
        src_a = make_pdf(2)
        # A dummy indirect object that looks like a page ref but isn't in rev_map
        dummy = src_a.make_indirect(
            pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 612, 792])
        )
        cross_annot = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 100, 100]),
            A=pikepdf.Dictionary(
                S=pikepdf.Name.GoTo,
                D=pikepdf.Array([dummy, pikepdf.Name.Fit]),
            ),
        )
        add_annots(src_a, 0, [cross_annot])
        src_a = roundtrip(src_a)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        run_rebuild_links([src_a], out, pages)
        out = roundtrip(out)

        # The unresolvable link must be dropped
        assert get_annots(out, 0) == []

    def test_file_b_pages_only_no_crash(self):
        """Output contains only pages from file B; file A is in pdf_input but unused."""
        src_a = make_pdf(2)
        src_b = make_pdf(2)
        add_annots(src_b, 0, [make_goto_action_annot(src_b, 1)])
        src_a = roundtrip(src_a)
        src_b = roundtrip(src_b)

        out = make_pdf(2)
        pages = [Row(2, 1), Row(2, 2)]
        run_rebuild_links([src_a, src_b], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert dest_page_index(out, annots[0].A.D) == 1


# ---------------------------------------------------------------------------
# Named destination links
# ---------------------------------------------------------------------------


class TestNamedDestinationLinks:
    """Links that reference named destinations (string /D in a GoTo action)."""

    def _add_named_dest(self, pdf, name, page_idx):
        if pikepdf.Name.Names not in pdf.Root:
            pdf.Root.Names = pdf.make_indirect(pikepdf.Dictionary())
        nt = pikepdf.NameTree.new(pdf)
        nt[name] = pikepdf.Array([pdf.pages[page_idx].obj, pikepdf.Name.Fit])
        pdf.Root.Names.Dests = nt.obj

    def test_named_dest_link_remapped(self):
        src = make_pdf(2)
        self._add_named_dest(src, "section-2", 1)
        annot = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 100, 100]),
            A=pikepdf.Dictionary(
                S=pikepdf.Name.GoTo,
                D=pikepdf.String("section-2"),
            ),
        )
        add_annots(src, 0, [annot])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]
        remapper = OutlineRemapper([src], out, pages)
        rebuild_links([src], out, pages, remapper)
        if remapper.new_named_dests:
            write_named_dests(out, remapper.new_named_dests)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        # The action should now reference the remapped name
        new_name = str(annots[0].A.D)
        assert new_name == "f0-section-2"
        # And that named dest must exist and point to the right page
        nt = dict(pikepdf.NameTree(out.Root.Names.Dests).items())
        assert "f0-section-2" in nt

    def test_named_dest_link_to_excluded_page_dropped(self):
        src = make_pdf(3)
        self._add_named_dest(src, "gone", 1)
        annot = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 100, 100]),
            A=pikepdf.Dictionary(
                S=pikepdf.Name.GoTo,
                D=pikepdf.String("gone"),
            ),
        )
        add_annots(src, 0, [annot])
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        assert get_annots(out, 0) == []


class TestRebuildLinksAnnotsCleaned:
    def test_partial_invalid_links_only_valid_survive(self):
        """
        Mix of valid and invalid GoTo links on same page — only valid ones remain,
        /Annots is replaced not left with stale entries.
        """
        src = make_pdf(3)
        add_annots(
            src,
            0,
            [
                make_goto_action_annot(src, 1),  # valid — page 2 kept
                make_goto_action_annot(src, 2),  # invalid — page 3 excluded
            ],
        )
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 2)]  # page 3 excluded
        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        annots = get_annots(out, 0)
        assert len(annots) == 1
        assert dest_page_index(out, annots[0].A.D) == 1

    def test_all_invalid_goto_links_removed(self):
        """
        Page whose only annotations are GoTo links to an excluded page must
        have /Annots removed entirely — covering the `del out_page.Annots` branch.
        """
        src = make_pdf(3)
        add_annots(src, 0, [make_goto_action_annot(src, 1)])  # target excluded
        src = roundtrip(src)

        out = make_pdf(2)
        pages = [Row(1, 1), Row(1, 3)]  # page 2 (index 1) excluded

        # Simulate what _append_page does: pre-copy stale annots onto the output page
        stale_annot = out.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([0, 0, 100, 100]),
            )
        )
        out.pages[0].Annots = pikepdf.Array([stale_annot])

        run_rebuild_links([src], out, pages)
        out = roundtrip(out)

        assert pikepdf.Name.Annots not in out.pages[0]

