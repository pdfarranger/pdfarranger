import unittest

from pdfarranger.core import LayerPage as LPage
from pdfarranger.core import Dims, Page


class PTest(unittest.TestCase):
    """Base class for Page and LayerPage tests"""

    @staticmethod
    def _lpage1() -> LPage:
        """Sample layer page 1"""
        return LPage(2, 4, 'lcopy', 90, 2, [0.11, 0.21, 0.31, 0.41], [0.12, 0.22, 0.32, 0.42], 'OVERLAY', Dims(10, 20))

    @staticmethod
    def _lpage1_90() -> LPage:
        """Sample layer page 1 rotated 90 degrees"""
        return LPage(2, 4, 'lcopy', 180, 2, [0.41, 0.31, 0.11, 0.21], [0.42, 0.32, 0.12, 0.22], 'OVERLAY', Dims(10, 20))

    @staticmethod
    def _lpage1_180() -> LPage:
        """Sample layer page 1 rotated 180 degrees"""
        return LPage(2, 4, 'lcopy', 270, 2, [0.21, 0.11, 0.41, 0.31], [0.22, 0.12, 0.42, 0.32], 'OVERLAY', Dims(10, 20))

    @staticmethod
    def _lpage1_270() -> LPage:
        """Sample layer page 1 rotated 180 degrees"""
        return LPage(2, 4, 'lcopy', 0, 2, [0.31, 0.41, 0.21, 0.11], [0.32, 0.42, 0.22, 0.12], 'OVERLAY', Dims(10, 20))

    def _page1(self) -> Page:
        """Sample page 1"""
        return Page(1, 2, 0.5, 'copy', 0, 2, [0.1, 0.2, 0.3, 0.4], Dims(100, 200), 'base', [self._lpage1()])

    def _page1_90(self) -> Page:
        """Sample page 1 rotated 90 degrees"""
        return Page(1, 2, 0.5, 'copy', 90, 2, [0.4, 0.3, 0.1, 0.2], Dims(100, 200), 'base', [self._lpage1_90()])

    def _page1_180(self) -> Page:
        """Sample page 1 rotated 90 degrees"""
        return Page(1, 2, 0.5, 'copy', 180, 2, [0.2, 0.1, 0.4, 0.3], Dims(100, 200), 'base', [self._lpage1_180()])

    def _page1_270(self) -> Page:
        """Sample page 1 rotated 90 degrees"""
        return Page(1, 2, 0.5, 'copy', 270, 2, [0.3, 0.4, 0.2, 0.1], Dims(100, 200), 'base', [self._lpage1_270()])


class BasePageTest(PTest):

    def test01(self):
        """Test width | height | size_in_points"""
        self.assertAlmostEquals(self._page1().size_in_points()[0], 140)
        self.assertAlmostEquals(self._page1().width_in_points(), 140)
        self.assertAlmostEquals(self._page1().size_in_points()[1], 120)
        self.assertAlmostEquals(self._page1().height_in_points(), 120)
        self.assertAlmostEquals(self._page1_90().size_in_points()[0], 120)
        self.assertAlmostEquals(self._page1_90().width_in_points(), 120)
        self.assertAlmostEquals(self._page1_90().size_in_points()[1], 140)
        self.assertAlmostEquals(self._page1_90().height_in_points(), 140)

    def test02(self):
        """Test rotate_times"""
        #  Remember - counter-clockwise !
        self.assertEqual(Page.rotate_times(0), 0)
        self.assertEqual(Page.rotate_times(90), 3)
        self.assertEqual(Page.rotate_times(134), 3)
        self.assertEqual(Page.rotate_times(-270), 3)
        self.assertEqual(Page.rotate_times(3690), 3)


class PageTest(PTest):

    def _rotate(self, angle: int) -> Page:
        """Return sample page 1 rotated by angle"""
        p = self._page1()
        p.rotate(angle)
        return p

    def test01(self):
        """Test rotate"""
        self.assertEqual(repr(self._rotate(0)), repr(self._page1()))
        self.assertEqual(repr(self._rotate(3600)), repr(self._page1()))
        self.assertEqual(repr(self._rotate(-7200)), repr(self._page1()))
        self.assertEqual(repr(self._rotate(90)), repr(self._page1_90()))
        self.assertEqual(repr(self._rotate(-270)), repr(self._page1_90()))
        self.assertEqual(repr(self._rotate(180)), repr(self._page1_180()))
        self.assertEqual(repr(self._rotate(270)), repr(self._page1_270()))
        self.assertEqual(self._rotate(0).size, Dims(100, 200))
        self.assertEqual(self._rotate(90).size, Dims(200, 100))
        self.assertEqual(self._rotate(180).size, Dims(100, 200))
        self.assertEqual(self._rotate(270).size, Dims(200, 100))

    def test02(self):
        """Test duplicate"""
        p = self._page1()
        d = p.duplicate()
        self.assertEqual(repr(p), repr(d))
        p.rotate(90)
        self.assertEqual(repr(d), repr(self._page1()))
        self.assertNotEquals(repr(p), repr(self._page1()))

    def test03(self):
        """Test serialize"""
        self.assertEqual(self._page1().serialize(),
                         'copy\n2\nbase\n0\n2\n0.1\n0.2\n0.3\n0.4\nlcopy\n4\n90\n2\nOVERLAY\n0.11\n0.21\n0.31\n0.41\n'
                         '0.12\n0.22\n0.32\n0.42')


class LayerPageTest(PTest):

    def _rotate(self, angle: int) -> LPage:
        """Return sample layer page 1 rotated by angle"""
        p = self._lpage1()
        p.rotate(angle)
        return p

    def test01(self):
        """Test rotate"""
        self.assertEqual(repr(self._rotate(0)), repr(self._lpage1()))
        self.assertEqual(repr(self._rotate(3600)), repr(self._lpage1()))
        self.assertEqual(repr(self._rotate(-7200)), repr(self._lpage1()))
        self.assertEqual(repr(self._rotate(90)), repr(self._lpage1_90()))
        self.assertEqual(repr(self._rotate(-270)), repr(self._lpage1_90()))
        self.assertEqual(repr(self._rotate(180)), repr(self._lpage1_180()))
        self.assertEqual(repr(self._rotate(270)), repr(self._lpage1_270()))
        self.assertEqual(self._rotate(0).size, Dims(20, 10))
        self.assertEqual(self._rotate(90).size, Dims(10, 20))
        self.assertEqual(self._rotate(180).size, Dims(20, 10))
        self.assertEqual(self._rotate(270).size, Dims(10, 20))

    def test02(self):
        """Test duplicate"""
        p = self._lpage1()
        d = p.duplicate()
        self.assertEqual(repr(p), repr(d))
        p.rotate(90)
        self.assertEqual(repr(d), repr(self._lpage1()))
        self.assertNotEquals(repr(p), repr(self._lpage1()))

    def test03(self):
        """Test serialize"""
        self.assertEqual(self._lpage1().serialize(),
                         'lcopy\n4\n90\n2\nOVERLAY\n0.11\n0.21\n0.31\n0.41\n0.12\n0.22\n0.32\n0.42')
