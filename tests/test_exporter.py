from dataclasses import dataclass, field
import filecmp
import packaging.version as version
from typing import Any, List
import unittest

import pikepdf

from pdfarranger.exporter import export
from pdfarranger.core import LayerPage as LP


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
    crop: List[float] = field(default_factory=lambda: list((0, 0, 0, 0)))
    size_orig: List[float] = field(default_factory=lambda: list((612, 792)))
    layerpages: List[Any] = field(default_factory=list)


@dataclass
class LayerPage:
    """Mock LayerPage class"""
    npage: int
    nfile: int = 1
    copyname: str = file('basic')
    angle: int = 0
    scale: float = 1.0
    crop: List[float] = field(default_factory=lambda: list((0, 0, 0, 0)))
    offset: List[float] = field(default_factory=lambda: list((0, 0, 0, 0)))
    laypos: str = 'OVERLAY'
    size_orig: List[float] = field(default_factory=lambda: list((612, 792)))
    layerpages: List[Any] = field(default_factory=list)

    @staticmethod
    def rotate_array(array, rotate_times) -> List[float]:
        return LP.rotate_array(array, rotate_times)


class ExporterTest(unittest.TestCase):

    def case(self, test, files, *pages, ignore=None):
        """Run a single test case."""
        if version.parse(pikepdf.__version__) < version.Version('6.0.1'):
            # will disappear in v11
            pass
        else:
            export(files, pages, [], [file('out')], None, None, True)
            with open(file('out'), 'rb') as f:
                actual = f.readlines()
            with open(file(f'test{test}_out'), 'rb') as f:
                expected = f.readlines()
            if ignore is not None:
                ignore.sort()
                ignore.reverse()
                for i in ignore:
                    del expected[i - 1]
                    del actual[i - 1]
            self.assertEqual(actual, expected)

    def basic(self, test, *pages, ignore=None):
        """Test with basic.pdf as single input file."""
        self.case(test, [(file('basic'), '')], *pages, ignore=ignore)

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
        self.basic(5, Page(1, crop=[0.1, 0.2, 0.3, 0.4]))

    def test06(self):
        """Rotate and crop page"""
        self.basic(6, Page(1, angle=90, crop=[0.1, 0.2, 0.3, 0.4]), Page(1, angle=180, crop=[0.1, 0.2, 0.3, 0.4]),
                   Page(1, angle=270, crop=[0.1, 0.2, 0.3, 0.4]))

    def test07(self):
        """Overlay page"""
        self.basic(7, Page(1, layerpages=[LayerPage(6)]), ignore=[38, 57])

    def test08(self):
        """Underlay page"""
        self.basic(8, Page(1, layerpages=[LayerPage(7, laypos='UNDERLAY')]), ignore=[38, 54])

    def test09(self):
        """Rotate overlay"""
        self.basic(9, Page(1, layerpages=[LayerPage(6, angle=90)]),
                   Page(1, layerpages=[LayerPage(6, angle=180)]), ignore=[39, 60, 79, 151])

    def test10(self):
        """Offset overlay horizontal"""
        self.basic(10, Page(1, layerpages=[LayerPage(6, offset=[.5, 0, 0, 0]), LayerPage(6, offset=[0, 0.5, 0, 0])]),
                   ignore=[38, 39, 59, 64, 75, 116])

    def test11(self):
        """Offset overlay vertical"""
        self.basic(11, Page(1, layerpages=[LayerPage(6, offset=[0, 0, 0.5, 0]), LayerPage(6, offset=[0, 0, 0, 0.5])]),
                   ignore=[38, 39, 59, 64, 75, 116])

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
        self.basic(15, Page(5, crop=[0.05, 0.075, 0.2, 0.3]))

    def test16(self):
        """Overlay page with annotations"""
        self.basic(16, Page(1, layerpages=[LayerPage(5)]), ignore=[38, 57])

    def test17(self):
        """File with missing MediaBox"""
        self.case(17, [('./tests/test.pdf', '')], Page(1), Page(2))

    def test18(self):
        """Encrypted file"""
        self.case(18, [('./tests/test_encrypted.pdf', 'foobar')], Page(1), Page(2))
