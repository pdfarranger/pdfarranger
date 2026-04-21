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

from pdfarranger.exporter_outlines import rebuild_outlines, write_named_dests


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


class TestMultiFileMerge:
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


class TestDuplicatePages:
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
