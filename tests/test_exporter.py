from dataclasses import dataclass, field
import filecmp
import packaging.version as version
from typing import Any, List
import unittest

import pikepdf

from pdfarranger.exporter import export


# The test files used for the tests in this file are in QDF format (see
# https://qpdf.readthedocs.io/en/stable/qdf.html).  They can be inspected with a simple text editor or compared with
# standard tools such as 'Meld' providing the encoding is set to UTF-8. The files are likely to contain some invalid
# UTF-8 characters (e.g. in streams), which is expected and can be ignored.

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


class ExporterTest(unittest.TestCase):

    def basic(self, test, *pages):
        """Test with basic.pdf as single input file."""
        if version.parse(pikepdf.__version__) < version.Version('6.0.1'):
            # will disappear in v11
            pass
        else:
            export([(file('basic'), '')], pages, [], [file('out')], None, None, True)
            self.assertTrue(filecmp.cmp(file('out'), file(f'test{test}_out'), False))

    def test1(self):
        """No transformations"""
        self.basic(1, Page(1), Page(2))

    def test2(self):
        """Rotate pages"""
        self.basic(2, Page(1, angle=90), Page(2, angle=180))

    def test3(self):
        """Rotate pages with existing /Rotate"""
        self.basic(3, Page(3, angle=90), Page(3, angle=180))
