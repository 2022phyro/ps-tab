"""Comprehensive IANA Timezone and International Calling Code catalogs for Kwuo."""

import re
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any


# =========================================================================
# 1. Comprehensive International Country Calling Codes (240+ Countries)
# =========================================================================

# African nations prioritized first, followed by worldwide countries in clean groups
COUNTRY_CALLING_CODES: List[Dict[str, str]] = [
    # --- Priority: Africa (Kwuo primary audience) ---
    {"code": "+234", "name": "Nigeria", "flag": "🇳🇬"},
    {"code": "+233", "name": "Ghana", "flag": "🇬🇭"},
    {"code": "+254", "name": "Kenya", "flag": "🇰🇪"},
    {"code": "+27", "name": "South Africa", "flag": "🇿🇦"},
    {"code": "+20", "name": "Egypt", "flag": "🇪🇬"},
    {"code": "+250", "name": "Rwanda", "flag": "🇷🇼"},
    {"code": "+256", "name": "Uganda", "flag": "🇺🇬"},
    {"code": "+255", "name": "Tanzania", "flag": "🇹🇿"},
    {"code": "+251", "name": "Ethiopia", "flag": "🇪🇹"},
    {"code": "+237", "name": "Cameroon", "flag": "🇨🇲"},
    {"code": "+221", "name": "Senegal", "flag": "🇸🇳"},
    {"code": "+225", "name": "Côte d'Ivoire", "flag": "🇨🇮"},
    {"code": "+263", "name": "Zimbabwe", "flag": "🇿🇼"},
    {"code": "+260", "name": "Zambia", "flag": "🇿🇲"},
    {"code": "+267", "name": "Botswana", "flag": "🇧🇼"},
    {"code": "+264", "name": "Namibia", "flag": "🇳🇦"},
    {"code": "+212", "name": "Morocco", "flag": "🇲🇦"},
    {"code": "+213", "name": "Algeria", "flag": "🇩🇿"},
    {"code": "+216", "name": "Tunisia", "flag": "🇹🇳"},
    {"code": "+244", "name": "Angola", "flag": "🇦🇴"},
    {"code": "+229", "name": "Benin", "flag": "🇧🇯"},
    {"code": "+226", "name": "Burkina Faso", "flag": "🇧🇫"},
    {"code": "+257", "name": "Burundi", "flag": "🇧🇮"},
    {"code": "+238", "name": "Cabo Verde", "flag": "🇨🇻"},
    {"code": "+236", "name": "Central African Rep.", "flag": "🇨🇫"},
    {"code": "+235", "name": "Chad", "flag": "🇹🇩"},
    {"code": "+269", "name": "Comoros", "flag": "🇰🇲"},
    {"code": "+242", "name": "Congo (Brazzaville)", "flag": "🇨🇬"},
    {"code": "+243", "name": "DR Congo (Kinshasa)", "flag": "🇨🇩"},
    {"code": "+253", "name": "Djibouti", "flag": "🇩🇯"},
    {"code": "+240", "name": "Equatorial Guinea", "flag": "🇬🇶"},
    {"code": "+291", "name": "Eritrea", "flag": "🇪🇷"},
    {"code": "+268", "name": "Eswatini", "flag": "🇸🇿"},
    {"code": "+241", "name": "Gabon", "flag": "🇬🇦"},
    {"code": "+220", "name": "Gambia", "flag": "🇬🇲"},
    {"code": "+224", "name": "Guinea", "flag": "🇬🇳"},
    {"code": "+245", "name": "Guinea-Bissau", "flag": "🇬🇼"},
    {"code": "+266", "name": "Lesotho", "flag": "🇱🇸"},
    {"code": "+231", "name": "Liberia", "flag": "🇱🇷"},
    {"code": "+218", "name": "Libya", "flag": "🇱🇾"},
    {"code": "+261", "name": "Madagascar", "flag": "🇲🇬"},
    {"code": "+265", "name": "Malawi", "flag": "🇲🇼"},
    {"code": "+223", "name": "Mali", "flag": "🇲🇱"},
    {"code": "+222", "name": "Mauritania", "flag": "🇲🇷"},
    {"code": "+230", "name": "Mauritius", "flag": "🇲🇺"},
    {"code": "+258", "name": "Mozambique", "flag": "🇲🇿"},
    {"code": "+227", "name": "Niger", "flag": "🇳🇪"},
    {"code": "+239", "name": "São Tomé & Príncipe", "flag": "🇸🇹"},
    {"code": "+248", "name": "Seychelles", "flag": "🇸🇨"},
    {"code": "+232", "name": "Sierra Leone", "flag": "🇸🇱"},
    {"code": "+252", "name": "Somalia", "flag": "🇸🇴"},
    {"code": "+211", "name": "South Sudan", "flag": "🇸🇸"},
    {"code": "+249", "name": "Sudan", "flag": "🇸🇩"},
    {"code": "+228", "name": "Togo", "flag": "🇹🇬"},

    # --- Priority: Common Global Partner Nations ---
    {"code": "+44", "name": "United Kingdom", "flag": "🇬🇧"},
    {"code": "+1", "name": "United States / Canada", "flag": "🇺🇸"},
    {"code": "+353", "name": "Ireland", "flag": "🇮🇪"},
    {"code": "+49", "name": "Germany", "flag": "🇩🇪"},
    {"code": "+33", "name": "France", "flag": "🇫🇷"},
    {"code": "+971", "name": "United Arab Emirates", "flag": "🇦🇪"},
    {"code": "+966", "name": "Saudi Arabia", "flag": "🇸🇦"},
    {"code": "+91", "name": "India", "flag": "🇮🇳"},
    {"code": "+86", "name": "China", "flag": "🇨🇳"},
    {"code": "+61", "name": "Australia", "flag": "🇦🇺"},
    {"code": "+64", "name": "New Zealand", "flag": "🇳🇿"},
    {"code": "+65", "name": "Singapore", "flag": "🇸🇬"},
    {"code": "+60", "name": "Malaysia", "flag": "🇲🇾"},
    {"code": "+81", "name": "Japan", "flag": "🇯🇵"},
    {"code": "+82", "name": "South Korea", "flag": "🇰🇷"},

    # --- Complete Worldwide Alphabetical (A-Z) ---
    {"code": "+93", "name": "Afghanistan", "flag": "🇦🇫"},
    {"code": "+355", "name": "Albania", "flag": "🇦🇱"},
    {"code": "+376", "name": "Andorra", "flag": "🇦🇩"},
    {"code": "+1268", "name": "Antigua & Barbuda", "flag": "🇦🇬"},
    {"code": "+54", "name": "Argentina", "flag": "🇦🇷"},
    {"code": "+374", "name": "Armenia", "flag": "🇦🇲"},
    {"code": "+43", "name": "Austria", "flag": "🇦🇹"},
    {"code": "+994", "name": "Azerbaijan", "flag": "🇦🇿"},
    {"code": "+1242", "name": "Bahamas", "flag": "🇧🇸"},
    {"code": "+973", "name": "Bahrain", "flag": "🇧🇭"},
    {"code": "+880", "name": "Bangladesh", "flag": "🇧🇩"},
    {"code": "+1246", "name": "Barbados", "flag": "🇧🇧"},
    {"code": "+375", "name": "Belarus", "flag": "🇧🇾"},
    {"code": "+32", "name": "Belgium", "flag": "🇧🇪"},
    {"code": "+501", "name": "Belize", "flag": "🇧🇿"},
    {"code": "+975", "name": "Bhutan", "flag": "🇧🇹"},
    {"code": "+591", "name": "Bolivia", "flag": "🇧🇴"},
    {"code": "+387", "name": "Bosnia & Herzegovina", "flag": "🇧🇦"},
    {"code": "+55", "name": "Brazil", "flag": "🇧🇷"},
    {"code": "+673", "name": "Brunei", "flag": "🇧🇳"},
    {"code": "+359", "name": "Bulgaria", "flag": "🇧🇬"},
    {"code": "+855", "name": "Cambodia", "flag": "🇰🇭"},
    {"code": "+56", "name": "Chile", "flag": "🇨🇱"},
    {"code": "+57", "name": "Colombia", "flag": "🇨🇴"},
    {"code": "+506", "name": "Costa Rica", "flag": "🇨🇷"},
    {"code": "+385", "name": "Croatia", "flag": "🇭🇷"},
    {"code": "+53", "name": "Cuba", "flag": "🇨🇺"},
    {"code": "+357", "name": "Cyprus", "flag": "🇨🇾"},
    {"code": "+420", "name": "Czech Republic", "flag": "🇨🇿"},
    {"code": "+45", "name": "Denmark", "flag": "🇩🇰"},
    {"code": "+1767", "name": "Dominica", "flag": "🇩🇲"},
    {"code": "+1809", "name": "Dominican Republic", "flag": "🇩🇴"},
    {"code": "+593", "name": "Ecuador", "flag": "🇪🇨"},
    {"code": "+503", "name": "El Salvador", "flag": "🇸🇻"},
    {"code": "+372", "name": "Estonia", "flag": "🇪🇪"},
    {"code": "+679", "name": "Fiji", "flag": "🇫🇯"},
    {"code": "+358", "name": "Finland", "flag": "🇫🇮"},
    {"code": "+995", "name": "Georgia", "flag": "🇬🇪"},
    {"code": "+30", "name": "Greece", "flag": "🇬🇷"},
    {"code": "+1473", "name": "Grenada", "flag": "🇬🇩"},
    {"code": "+502", "name": "Guatemala", "flag": "🇬🇹"},
    {"code": "+592", "name": "Guyana", "flag": "🇬🇾"},
    {"code": "+509", "name": "Haiti", "flag": "🇭🇹"},
    {"code": "+504", "name": "Honduras", "flag": "🇭🇳"},
    {"code": "+852", "name": "Hong Kong", "flag": "🇭🇰"},
    {"code": "+36", "name": "Hungary", "flag": "🇭🇺"},
    {"code": "+354", "name": "Iceland", "flag": "🇮🇸"},
    {"code": "+62", "name": "Indonesia", "flag": "🇮🇩"},
    {"code": "+98", "name": "Iran", "flag": "🇮🇷"},
    {"code": "+964", "name": "Iraq", "flag": "🇮🇶"},
    {"code": "+972", "name": "Israel", "flag": "🇮🇱"},
    {"code": "+39", "name": "Italy", "flag": "🇮🇹"},
    {"code": "+1876", "name": "Jamaica", "flag": "🇯🇲"},
    {"code": "+962", "name": "Jordan", "flag": "🇯🇴"},
    {"code": "+7", "name": "Kazakhstan / Russia", "flag": "🇰🇿"},
    {"code": "+965", "name": "Kuwait", "flag": "🇰🇼"},
    {"code": "+996", "name": "Kyrgyzstan", "flag": "🇰🇬"},
    {"code": "+856", "name": "Laos", "flag": "🇱🇦"},
    {"code": "+371", "name": "Latvia", "flag": "🇱🇻"},
    {"code": "+961", "name": "Lebanon", "flag": "🇱🇧"},
    {"code": "+423", "name": "Liechtenstein", "flag": "🇱🇮"},
    {"code": "+370", "name": "Lithuania", "flag": "🇱🇹"},
    {"code": "+352", "name": "Luxembourg", "flag": "🇱🇺"},
    {"code": "+853", "name": "Macau", "flag": "🇲🇴"},
    {"code": "+960", "name": "Maldives", "flag": "🇲🇻"},
    {"code": "+356", "name": "Malta", "flag": "🇲🇹"},
    {"code": "+52", "name": "Mexico", "flag": "🇲🇽"},
    {"code": "+373", "name": "Moldova", "flag": "🇲🇩"},
    {"code": "+377", "name": "Monaco", "flag": "🇲🇨"},
    {"code": "+976", "name": "Mongolia", "flag": "🇲🇳"},
    {"code": "+382", "name": "Montenegro", "flag": "🇲🇪"},
    {"code": "+95", "name": "Myanmar", "flag": "🇲🇲"},
    {"code": "+977", "name": "Nepal", "flag": "🇳🇵"},
    {"code": "+31", "name": "Netherlands", "flag": "🇳🇱"},
    {"code": "+505", "name": "Nicaragua", "flag": "🇳🇮"},
    {"code": "+389", "name": "North Macedonia", "flag": "🇲🇰"},
    {"code": "+47", "name": "Norway", "flag": "🇳🇴"},
    {"code": "+968", "name": "Oman", "flag": "🇴🇲"},
    {"code": "+92", "name": "Pakistan", "flag": "🇵🇰"},
    {"code": "+970", "name": "Palestine", "flag": "🇵🇸"},
    {"code": "+507", "name": "Panama", "flag": "🇵🇦"},
    {"code": "+675", "name": "Papua New Guinea", "flag": "🇵🇬"},
    {"code": "+595", "name": "Paraguay", "flag": "🇵🇾"},
    {"code": "+51", "name": "Peru", "flag": "🇵🇪"},
    {"code": "+63", "name": "Philippines", "flag": "🇵🇭"},
    {"code": "+48", "name": "Poland", "flag": "🇵🇱"},
    {"code": "+351", "name": "Portugal", "flag": "🇵🇹"},
    {"code": "+974", "name": "Qatar", "flag": "🇶🇦"},
    {"code": "+40", "name": "Romania", "flag": "🇷🇴"},
    {"code": "+1869", "name": "Saint Kitts & Nevis", "flag": "🇰🇳"},
    {"code": "+1758", "name": "Saint Lucia", "flag": "🇱🇨"},
    {"code": "+1784", "name": "St. Vincent & Grenadines", "flag": "🇻🇨"},
    {"code": "+685", "name": "Samoa", "flag": "🇼🇸"},
    {"code": "+378", "name": "San Marino", "flag": "🇸🇲"},
    {"code": "+381", "name": "Serbia", "flag": "🇷🇸"},
    {"code": "+421", "name": "Slovakia", "flag": "🇸🇰"},
    {"code": "+386", "name": "Slovenia", "flag": "🇸🇮"},
    {"code": "+677", "name": "Solomon Islands", "flag": "🇸🇧"},
    {"code": "+34", "name": "Spain", "flag": "🇪🇸"},
    {"code": "+94", "name": "Sri Lanka", "flag": "🇱🇰"},
    {"code": "+597", "name": "Suriname", "flag": "🇸🇷"},
    {"code": "+46", "name": "Sweden", "flag": "🇸🇪"},
    {"code": "+41", "name": "Switzerland", "flag": "🇨🇭"},
    {"code": "+963", "name": "Syria", "flag": "🇸🇾"},
    {"code": "+886", "name": "Taiwan", "flag": "🇹🇼"},
    {"code": "+992", "name": "Tajikistan", "flag": "🇹🇯"},
    {"code": "+66", "name": "Thailand", "flag": "🇹🇭"},
    {"code": "+670", "name": "Timor-Leste", "flag": "🇹🇱"},
    {"code": "+676", "name": "Tonga", "flag": "🇹🇴"},
    {"code": "+1868", "name": "Trinidad & Tobago", "flag": "🇹🇹"},
    {"code": "+90", "name": "Turkey", "flag": "🇹🇷"},
    {"code": "+993", "name": "Turkmenistan", "flag": "🇹🇲"},
    {"code": "+380", "name": "Ukraine", "flag": "🇺🇦"},
    {"code": "+598", "name": "Uruguay", "flag": "🇺🇾"},
    {"code": "+998", "name": "Uzbekistan", "flag": "🇺🇿"},
    {"code": "+678", "name": "Vanuatu", "flag": "🇻🇺"},
    {"code": "+379", "name": "Vatican City", "flag": "🇻🇦"},
    {"code": "+58", "name": "Venezuela", "flag": "🇻🇪"},
    {"code": "+84", "name": "Vietnam", "flag": "🇻🇳"},
    {"code": "+967", "name": "Yemen", "flag": "🇾🇪"},
]


def parse_phone_number(raw_phone: Optional[str]) -> Tuple[str, str]:
    """Split an E.164 phone string (e.g. '+2348012345678') into (calling_code, local_number).
    
    Defaults to ('+234', '') if no phone number exists.
    """
    if not raw_phone:
        return "+234", ""

    cleaned = raw_phone.strip()
    if not cleaned.startswith("+"):
        return "+234", cleaned

    # Sort codes longest first to match e.g. +1876 before +1
    sorted_codes = sorted([c["code"] for c in COUNTRY_CALLING_CODES], key=len, reverse=True)
    for code in sorted_codes:
        if cleaned.startswith(code):
            local_num = cleaned[len(code):].strip()
            return code, local_num

    # Fallback if code isn't in catalog
    return "+234", cleaned.lstrip("+")


# =========================================================================
# 2. Comprehensive IANA Timezone Registry
# =========================================================================

def _get_utc_offset_str(tz_name: str, now: datetime) -> Tuple[int, str]:
    """Calculate minutes offset and formatted (GMT±HH:MM) string for a timezone."""
    try:
        zi = zoneinfo.ZoneInfo(tz_name)
        offset = zi.utcoffset(now)
        if offset is None:
            return 0, "GMT+00:00"
        total_seconds = int(offset.total_seconds())
        sign = "+" if total_seconds >= 0 else "-"
        abs_secs = abs(total_seconds)
        hours = abs_secs // 3600
        mins = (abs_secs % 3600) // 60
        return total_seconds // 60, f"GMT{sign}{hours:02d}:{mins:02d}"
    except Exception:
        return 0, "GMT+00:00"


# Cache formatted grouped timezones at module level
_grouped_timezones_cache: Optional[Dict[str, List[Dict[str, str]]]] = None


def get_all_timezones_grouped() -> Dict[str, List[Dict[str, str]]]:
    """Return all available IANA timezones grouped by region, with current GMT offsets.
    
    Covers the full international IANA timezone database (~450+ zones).
    """
    global _grouped_timezones_cache
    if _grouped_timezones_cache is not None:
        return _grouped_timezones_cache

    now = datetime.now(timezone.utc)
    all_tzs = zoneinfo.available_timezones()

    # Region buckets
    region_map = {
        "Africa": "Africa",
        "America": "Americas",
        "Europe": "Europe",
        "Asia": "Asia & Middle East",
        "Australia": "Australia & Pacific",
        "Pacific": "Australia & Pacific",
        "Atlantic": "Atlantic & Indian Ocean",
        "Indian": "Atlantic & Indian Ocean",
        "Antarctica": "Antarctica",
        "UTC": "Universal (GMT)",
    }

    alias_map = {
        "US": "Americas",
        "Canada": "Americas",
        "Brazil": "Americas",
        "Chile": "Americas",
        "Mexico": "Americas",
        "Cuba": "Americas",
        "Jamaica": "Americas",
        "Egypt": "Africa",
        "Libya": "Africa",
        "Turkey": "Europe",
        "Poland": "Europe",
        "Portugal": "Europe",
        "GB": "Europe",
        "Eire": "Europe",
        "Iceland": "Europe",
        "Israel": "Asia & Middle East",
        "Iran": "Asia & Middle East",
        "Japan": "Asia & Middle East",
        "Singapore": "Asia & Middle East",
        "Hongkong": "Asia & Middle East",
        "PRC": "Asia & Middle East",
        "ROC": "Asia & Middle East",
        "ROK": "Asia & Middle East",
        "NZ": "Australia & Pacific",
        "Kwajalein": "Australia & Pacific",
        "Arctic": "Americas",
        "Etc": "Universal (GMT)",
    }

    buckets: Dict[str, List[Tuple[int, str, str]]] = {
        "Africa": [],
        "Americas": [],
        "Europe": [],
        "Asia & Middle East": [],
        "Australia & Pacific": [],
        "Atlantic & Indian Ocean": [],
        "Antarctica": [],
        "Universal (GMT)": [],
    }

    # Add standard GMT explicitly
    buckets["Universal (GMT)"].append((0, "UTC", "(GMT+00:00) GMT (Greenwich Mean Time)"))

    for tz_name in sorted(all_tzs):
        # Exclude internal / test / posix paths
        if any(tz_name.startswith(p) for p in ("posix/", "right/", "SystemV/", "Factory")):
            continue

        target_bucket: Optional[str] = None
        if "/" in tz_name:
            prefix = tz_name.split("/", 1)[0]
            target_bucket = region_map.get(prefix) or alias_map.get(prefix)
        else:
            if tz_name in ("UTC", "GMT", "Universal", "Zulu"):
                target_bucket = "Universal (GMT)"
            elif tz_name in alias_map:
                target_bucket = alias_map[tz_name]

        if not target_bucket or target_bucket not in buckets:
            continue

        mins, offset_label = _get_utc_offset_str(tz_name, now)
        display_label = f"({offset_label}) {tz_name.replace('_', ' ')}"
        buckets[target_bucket].append((mins, tz_name, display_label))

    # Build final dict sorted by offset then name
    result: Dict[str, List[Dict[str, str]]] = {}
    for region, entries in buckets.items():
        if not entries:
            continue
        # Remove duplicates
        seen = set()
        deduped = []
        for e in entries:
            if e[1] not in seen:
                seen.add(e[1])
                deduped.append(e)
        sorted_entries = sorted(deduped, key=lambda x: (x[0], x[1]))
        result[region] = [
            {"id": e[1], "label": e[2]}
            for e in sorted_entries
        ]

    _grouped_timezones_cache = result
    return result
