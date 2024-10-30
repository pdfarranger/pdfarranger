from dataclasses import dataclass, field
import os
import packaging.version as version
from typing import Any, List, Tuple
import unittest

import pikepdf

from pdfarranger.exporter import export
from pdfarranger.core import Dims, Sides


# The test files used for the tests in this file are in QDF format (see
# https://qpdf.readthedocs.io/en/stable/qdf.html).  They can be inspected with a simple text editor or compared with
# standard tools such as 'Meld'

def file(name):
    """Expand name to full filename"""
    return f'./tests/exporter/{name}.pdf'


@dataclass
class Page:
    """Mock Page class"""
    npage: int
    nfile: int = 1
    copyname: str = file('basic')
    angle: int = 0
    scale: float = 1.0
    crop: Sides = Sides()
    size_orig: Dims = Dims(612, 792)
    layerpages: List[Any] = field(default_factory=list)


@dataclass
class LayerPage:
    """Mock LayerPage class"""
    npage: int
    nfile: int = 1
    copyname: str = file('basic')
    angle: int = 0
    scale: float = 1.0
    crop: Sides = Sides()
    offset: Sides = Sides()
    laypos: str = 'OVERLAY'
    size_orig: Dims = Dims(612, 792)
    layerpages: List[Any] = field(default_factory=list)


class ExporterTest(unittest.TestCase):

    def compare_files(self, actual_file: str, expected_file: str) -> Tuple[bool, str]:
        """
        Compare two PDF files

        The following are ignored in the comparison:
        - blank lines
        - lines starting or ending with '%'
        - lines containing the name /Length
        - anything following the first '/' in line containing a Do operator
        - anything following the xref entry
        """
        with open(actual_file, 'rb') as f:
            actual = f.readlines()
        with open(expected_file, 'rb') as f:
            expected = f.readlines()

        actual_no = 0
        last_match = -1
        for line_no, line in enumerate(expected):
            if len(line) == 0 or line.isspace() or line.startswith(b'%') or line.endswith(b'%\n') or b'/Length' in line:
                pass
            elif line.startswith(b'xref'):
                return True, ''
            else:
                if b' Do ' in line or b' Do\n' in line:
                    line = line[:line.find(b'/')]

                try:
                    while not actual[actual_no].startswith(line):
                        actual_no += 1
                    last_match = actual_no
                    actual_no += 1
                except IndexError: # pragma: no cover
                    # Only get executed for failing test
                    print(line_no, line, last_match)
                    return (False, f'Failed to match line {line_no + 1} in expected  file {expected_file} : {line} \n'
                                   f'Last match in line {last_match + 1} of {actual_file}')

        return True, ''

    def case(self, test, files, *pages):
        """Run a single test case."""
        if version.parse(pikepdf.__version__) < version.Version('8.0.0'):
            expected_file = file(f'test{test}_out')
        else:
            expected_file = file(f'test{test}_8_out')
            if not os.path.exists(expected_file):
                expected_file = file(f'test{test}_out')

        export(files, pages, {}, [file('out')], None, None, True)
        self.assertTrue(*self.compare_files(file('out'), expected_file))

    def basic(self, test, *pages):
        """Test with basic.pdf as single input file."""
        self.case(test, [(file('basic'), '')], *pages)

    def outlines(self, test, *pages, ignore_8=None):
        """Test with outlines.pdf as single input file."""
        if version.parse(pikepdf.__version__) >= version.Version('8.0.0'):
            self.case(test, [(file('outlines'), '')], *pages)

    def test01(self):
        """No transformations"""
        self.basic(1, Page(1), Page(2))

    def test02(self):
        """Rotate pages"""
        self.basic(2, Page(1, angle=90), Page(2, angle=180))

    def test03(self):
        """Rotate pages with existing /Rotate"""
        self.basic(3, Page(3, angle=90), Page(3, angle=180))

    def test04(self):
        """Scale page"""
        self.basic(4, Page(1, scale=0.25))

    def test05(self):
        """Crop page"""
        self.basic(5, Page(1, crop=Sides(0.1, 0.2, 0.3, 0.4)))

    def test06(self):
        """Rotate and crop page"""
        self.basic(6, Page(1, angle=90, crop=Sides(0.1, 0.2, 0.3, 0.4)),
                   Page(1, angle=180, crop=Sides(0.1, 0.2, 0.3, 0.4)),
                   Page(1, angle=270, crop=Sides(0.1, 0.2, 0.3, 0.4)))

    def test07(self):
        """Overlay page"""
        self.basic(7, Page(1, layerpages=[LayerPage(6)]))

    def test08(self):
        """Underlay page"""
        self.basic(8, Page(1, layerpages=[LayerPage(7, laypos='UNDERLAY')]))

    def test09(self):
        """Rotate overlay"""
        self.basic(9, Page(1, layerpages=[LayerPage(6, angle=90)]),
                   Page(1, layerpages=[LayerPage(6, angle=180)]))

    def test095(self):
        """Overlay page with itself - MediaBox with non-integer values"""
        self.case(95, [(file('overlay'), '')], Page(1, layerpages=[LayerPage(1)]))

    def test096(self):
        """Overlay page with itself - MediaBox with non-standard corners"""
        self.case(96, [(file('overlay'), '')], Page(2, layerpages=[LayerPage(2)]))

    def test10(self):
        """Offset overlay horizontal"""
        self.basic(10, Page(1, layerpages=[LayerPage(6, offset=Sides(.5, 0, 0, 0)),
                                           LayerPage(6, offset=Sides(0, 0.5, 0, 0))]))

    def test11(self):
        """Offset overlay vertical"""
        self.basic(11, Page(1, layerpages=[LayerPage(6, offset=Sides(0, 0, 0.5, 0)),
                                           LayerPage(6, offset=Sides(0, 0, 0, 0.5))]))

    def test12(self):
        """Duplicate page with annotations"""
        self.basic(12, Page(5), Page(5))

    def test13(self):
        """Rotate page with  annotations"""
        self.basic(13, Page(5, angle=90), Page(5, angle=180))

    def test14(self):
        """Scale page with annotations"""
        self.basic(14, Page(5, scale=0.25))

    def test15(self):
        """Crop page with annotations"""
        self.basic(15, Page(5, crop=Sides(0.05, 0.075, 0.2, 0.3)))

    def test16(self):
        """Overlay page with annotations"""
        self.basic(16, Page(1, layerpages=[LayerPage(5)]))

    def test17(self):
        """File with missing MediaBox"""
        self.case(17, [('./tests/test.pdf', '')], Page(1), Page(2))

    def test18(self):
        """Encrypted file"""
        self.case(18, [('./tests/test_encrypted.pdf', 'foobar')], Page(1), Page(2))

    def test19(self):
        """Copy file with outlines"""
        self.outlines(19, Page(1), Page(2), Page(3), Page(4))

    def test20(self):
        """Reorder pages in file with outlines"""
        self.outlines(20, Page(4), Page(2), Page(1), Page(3))

    def test21(self):
        """Duplicate pages in file with outlines"""
        self.outlines(21, Page(4), Page(2), Page(3), Page(4))

    def test22(self):
        """Rotate pages in file with outlines"""
        self.outlines(22, Page(1), Page(2, angle=90), Page(3, angle=180), Page(4, angle=270))

    def test23(self):
        """Scale pages in file with outlines"""
        self.outlines(23, Page(1), Page(2, scale=0.5), Page(3), Page(4))

    def test24(self):
        """Import page with interactive form elements"""
        self.case(24, [(file('basic'), ''), (file('forms'), '')], Page(1), Page(1, nfile=2))

    def test25(self):
        """Duplicate page with interactive form elements"""
        self.case(25, [(file('forms'), '')], Page(1), Page(1))

    def test26(self):
        """Export with highest PDF versions of input files"""
        # gs -o exporter/test26_pdf1-4.pdf -sDEVICE=pdfwrite -g6120x7920 -dCompatibilityLevel=1.4 -c "showpage"
        # gs -o exporter/test26_pdf1-5.pdf -sDEVICE=pdfwrite -g6120x7920 -dCompatibilityLevel=1.5 -c "showpage"
        # to check versions
        # pdfinfo <pdf> | grep 'PDF version'
        self.case(
            26,
            [(file('test26_pdf1-4'), ''), (file('test26_pdf1-5'), '')],
            Page(1),
            Page(1, nfile=2),
        )
