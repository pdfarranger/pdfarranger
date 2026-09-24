import re
from datetime import datetime, timezone, timedelta


def parse_pdf_date(date_str: str) -> datetime | None:
    """
    A PDF metadata date parser engineered to handle spec-compliant
    formats, ISO-8601, RFC 2822 (XMP blocks), dot-separated regional dates,
    ctime() styles, and completely arbitrary spec truncation down to year/month.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    # 1. Strip standard PDF prefix and outer whitespace
    if date_str.startswith("D:"):
        date_str = date_str[2:]
    date_str = date_str.strip()

    # 2. Early exit for zeroed metadata placeholders (e.g., D:00000000000000Z)
    only_digits = re.sub(r"\D", "", date_str)
    if only_digits and only_digits == "0" * len(only_digits):
        return None

    # 3. Timezone Extraction & Validation
    tz_info = None

    if re.search(r"Z\s*$", date_str, re.IGNORECASE):
        tz_info = timezone.utc
        date_str = re.sub(r"Z\s*$", "", date_str, flags=re.IGNORECASE).strip()
    elif re.search(r"\bUTC\b", date_str, re.IGNORECASE):
        tz_info = timezone.utc
        date_str = re.sub(r"\bUTC\b", "", date_str, flags=re.IGNORECASE).strip()
    else:
        # Match timezone patterns at the end of the string (+HH'mm', +HHmm, +HH:mm)
        tz_match = re.search(
            r"([+-])(\d{2})[:']?(\d{2})?'?(?:\s*\([^)]+\))*\s*$", date_str
        )
        if tz_match:
            sign, hours, minutes = (
                tz_match.group(1),
                tz_match.group(2),
                tz_match.group(3),
            )

            # GUARD: Distinguish a 2-digit year/day delimiter (like -99) from an actual timezone offset
            if (
                int(hours) > 14
                and ":" not in tz_match.group(0)
                and "'" not in tz_match.group(0)
                and sign == "-"
            ):
                tz_match = None

            if tz_match:
                minutes = minutes or "00"
                offset_minutes = int(hours) * 60 + int(minutes)
                if sign == "-":
                    offset_minutes = -offset_minutes

                try:
                    tz_info = timezone(timedelta(minutes=offset_minutes))
                    date_str = date_str[: tz_match.start()].strip()
                except ValueError:
                    return None

    # Clean up any consecutive whitespaces left behind by parsing routines
    date_str = re.sub(r"\s+", " ", date_str).strip()

    # 4. Strategy A: Structured calendar formats
    structured_formats = [
        "%Y-%m-%dT%H:%M:%S",  # ISO-8601 Long
        "%Y-%m-%d %H:%M:%S",  # Space-separated ISO
        "%Y-%m-%d",  # ISO Short
        "%d/%m/%Y %H:%M:%S",  # European Long
        "%d/%m/%Y",  # European Short
        "%m/%d/%Y %H:%M:%S",  # US Long
        "%m/%d/%Y",  # US Short
        # RFC 2822 / XMP Variants
        "%a, %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%a, %d %b %Y",
        "%d %b %Y",
        # Dot-Separated European
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
        # ctime()-style Outputs
        "%a %b %d %H:%M:%S %Y",
        "%a %b %d %Y",
        # Truncated PDF Specification Case (4 digits)
        "%Y",
        # 2-Digit Year Fallbacks (Y2K compliance)
        "%d-%m-%y",
        "%d/%m/%y",
        "%m-%d-%y",
        "%m/%d/%y",
    ]

    for fmt in structured_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=tz_info) if tz_info else dt
        except ValueError:
            continue

    # 5. Strategy B: Fall back to raw digit sequencing (Handles PDF spec truncation steps seamlessly)
    date_digits = re.sub(r"\D", "", date_str)

    # GUARD: If the string had hyphens or slashes and contains exactly 6 digits, it's a 2-digit year format.
    # It already failed Strategy A, so don't let it misparse here as a truncated year + month (YYYYMM).
    if len(date_digits) == 6 and any(char in date_str for char in ["-", "/", "."]):
        return None

    try:
        if len(date_digits) >= 14:
            dt = datetime.strptime(date_digits[:14], "%Y%m%d%H%M%S")
        elif len(date_digits) >= 12:
            dt = datetime.strptime(date_digits[:12], "%Y%m%d%H%M")
        elif len(date_digits) >= 10:
            dt = datetime.strptime(date_digits[:10], "%Y%m%d%H")
        elif len(date_digits) >= 8:
            dt = datetime.strptime(date_digits[:8], "%Y%m%d")
        elif len(date_digits) >= 6:
            dt = datetime.strptime(date_digits[:6], "%Y%m")
        else:
            return None
        return dt.replace(tzinfo=tz_info) if tz_info else dt
    except ValueError:
        return None
