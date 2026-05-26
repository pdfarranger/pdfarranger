import unittest
from datetime import timezone, timedelta
from pdfarranger.date_parser import parse_pdf_date


class TestPDFDateParser(unittest.TestCase):
    def test_perfect_pdf_spec_format(self):
        """Should parse a fully compliant PDF date string with timezone apostrophes."""
        res = parse_pdf_date("D:20260526134958+01'00'")
        self.assertIsNotNone(res)
        self.assertEqual(res.year, 2026)
        self.assertEqual(res.month, 5)
        self.assertEqual(res.day, 26)
        self.assertEqual(res.hour, 13)
        self.assertEqual(res.minute, 49)
        self.assertEqual(res.second, 58)
        self.assertEqual(res.tzinfo, timezone(timedelta(hours=1)))

    def test_negative_timezone_offset(self):
        """Should correctly parse negative timezone offsets (e.g., EST/EDT)."""
        res = parse_pdf_date("D:20260526134958-05'00'")
        self.assertEqual(res.tzinfo, timezone(timedelta(hours=-5)))

    def test_lazy_typist_no_apostrophes(self):
        """Should parse a date where the generator skipped the timezone apostrophes."""
        res = parse_pdf_date("D:20260526134958+0100")
        self.assertEqual(res.tzinfo, timezone(timedelta(hours=1)))

    def test_iso_rebel_format(self):
        """Should handle standard web ISO-8601 strings with 'Z' UTC indicator."""
        res = parse_pdf_date("2026-05-26T13:49:58Z")
        self.assertEqual(res.year, 2026)
        self.assertEqual(res.tzinfo, timezone.utc)

    def test_timeless_no_timezone(self):
        """Should gracefully parse a valid date that completely lacks timezone information."""
        res = parse_pdf_date("D:20260526134958")
        self.assertEqual(res.hour, 13)
        self.assertIsNone(res.tzinfo)

    def test_minimalist_short_date(self):
        """Should handle truncated strings containing only the year, month, and day."""
        res = parse_pdf_date("D:20260526")
        self.assertEqual(res.year, 2026)
        self.assertEqual(res.month, 5)
        self.assertEqual(res.day, 26)
        self.assertEqual(res.hour, 0)
        self.assertIsNone(res.tzinfo)

    def test_prefix_less(self):
        """Should parse correctly even if the 'D:' prefix is missing."""
        res = parse_pdf_date("20260526134958")
        self.assertEqual(res.year, 2026)
        self.assertEqual(res.second, 58)

    def test_gap_truncated_year_only(self):
        # This is where D:2026 belongs now!
        res = parse_pdf_date("D:2026")
        self.assertIsNotNone(res)
        self.assertEqual(res.year, 2026)

    def test_invalid_types_and_garbage_strings(self):
        """Should return None without throwing exceptions for bad inputs."""
        self.assertIsNone(parse_pdf_date(""))
        self.assertIsNone(parse_pdf_date(None))  # type: ignore
        self.assertIsNone(parse_pdf_date(12345678))  # type: ignore
        self.assertIsNone(parse_pdf_date("Not a date string at all"))

    # =========================================================================
    # ADVERSARIAL TEST CASES
    # =========================================================================

    def test_adversarial_timezone_with_colon(self):
        res = parse_pdf_date("2026-05-26+01:00")
        self.assertIsNotNone(res)
        self.assertEqual(res.hour, 0)
        self.assertEqual(res.minute, 0)
        self.assertEqual(res.tzinfo, timezone(timedelta(hours=1)))

    def test_adversarial_european_format(self):
        res = parse_pdf_date("26/05/2026")
        self.assertIsNotNone(res)
        self.assertEqual(res.year, 2026)
        self.assertEqual(res.month, 5)
        self.assertEqual(res.day, 26)

    def test_adversarial_chatty_timezone_suffix(self):
        res = parse_pdf_date("D:20260526134958+01'00' (GMT)")
        self.assertIsNotNone(res)
        self.assertEqual(res.tzinfo, timezone(timedelta(hours=1)))

    def test_adversarial_zeroed_metadata_placeholder(self):
        res = parse_pdf_date("D:00000000000000Z")
        self.assertIsNone(res)  # Should handle elegantly without uncaught failures

    def test_advanced_out_of_bounds_timezone(self):
        try:
            res = parse_pdf_date("D:20260526134958+25'00'")
            self.assertIsNone(res)  # Should handle gracefully and return None
        except ValueError as e:
            self.fail(f"Parser crashed with uncaught ValueError: {e}")

    def test_advanced_double_parentheses(self):
        res = parse_pdf_date("D:20260526134958+01'00' (GMT) (Acrobat Custom)")
        self.assertIsNotNone(res)
        self.assertEqual(res.tzinfo, timezone(timedelta(hours=1)))

    def test_advanced_y2k_two_digit_year(self):
        res = parse_pdf_date("26-05-99")
        self.assertIsNotNone(res)
        self.assertEqual(res.year, 1999)
        self.assertEqual(res.month, 5)
        self.assertEqual(res.day, 26)

    # =========================================================================
    # METADATA & CALENDAR BOUNDARY CONFORMANCE TESTS
    # =========================================================================

    def test_pdf_spec_further_truncation(self):
        """Valid PDF spec states date can truncate at any component boundary."""
        # Year and Month only
        res_month = parse_pdf_date("D:202605")
        self.assertIsNotNone(res_month)
        self.assertEqual(res_month.year, 2026)
        self.assertEqual(res_month.month, 5)
        self.assertEqual(res_month.day, 1)       # Python fallback value
        self.assertEqual(res_month.hour, 0)      # Python fallback value

        # Truncated down to the hour
        res_hour = parse_pdf_date("D:2026052613")
        self.assertIsNotNone(res_hour)
        self.assertEqual(res_hour.year, 2026)
        self.assertEqual(res_hour.month, 5)
        self.assertEqual(res_hour.day, 26)
        self.assertEqual(res_hour.hour, 13)
        self.assertEqual(res_hour.minute, 0)     # Python fallback value

    def test_fractional_timezones(self):
        """Handles non-hourly timezone offsets (e.g., India +05:30, Newfoundland -03:30)."""
        res_ist = parse_pdf_date("2026-05-26+05:30")
        self.assertIsNotNone(res_ist)
        self.assertEqual(
            res_ist.tzinfo.utcoffset(res_ist), timedelta(hours=5, minutes=30)
        )

        res_nfl = parse_pdf_date("D:20260526134958-03'30'")
        self.assertIsNotNone(res_nfl)
        self.assertEqual(
            res_nfl.tzinfo.utcoffset(res_nfl), -timedelta(hours=3, minutes=30)
        )

    def test_impossible_calendar_bounds(self):
        """Ensures logic handles impossible dates safely without throwing native crashes."""
        self.assertIsNone(parse_pdf_date("2025-02-29"))  # 2025 is not a leap year
        self.assertIsNone(parse_pdf_date("2026-13-01"))  # Month 13 doesn't exist
        self.assertIsNone(parse_pdf_date("2026-05-32"))  # Day 32 doesn't exist

    def test_extreme_whitespace_resilience(self):
        """Verifies strings corrupted with erratic spacing parse correctly."""
        res = parse_pdf_date("   D:  2026-05-26   13:49:58   +01:00   ")
        self.assertIsNotNone(res)
        self.assertEqual(res.year, 2026)
        self.assertEqual(res.hour, 13)


if __name__ == "__main__":
    unittest.main()
