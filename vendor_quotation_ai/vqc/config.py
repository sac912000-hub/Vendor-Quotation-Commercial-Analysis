"""All tunable assumptions live here, so nothing is hidden inside the logic.
IMPORTANT: the landed-cost percentages below are PLACEHOLDERS for illustration.
Replace them with figures from your logistics / customs team before using the
'landed' or 'tco' basis for a real award decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Assumptions:
    fx_usd_inr: float | None = None          # None -> read "USD to INR" from the sheet
    # --- Import (FOB / CIF) adjustments, % of quoted value --------------------
    freight_insurance_pct: float = 5.0       # sea freight + marine insurance (FOB only)
    import_duty_pct: float = 8.25            # customs duty on CIF value (placeholder)
    clearance_inland_pct: float = 2.5        # port handling, clearing, inland freight to site
    # --- Domestic adjustments --------------------------------------------------
    exworks_inland_pct: float = 2.0          # inland freight for Ex-works quotes
    # --- Time value of money ---------------------------------------------------
    cost_of_capital_pct: float = 10.0        # annual, used for advance-payment financing cost
    transit_months_import: float = 1.5       # port-to-site transit added to import lead time


@dataclass
class Weights:
    price: float = 50.0
    delivery: float = 15.0
    payment: float = 15.0
    warranty: float = 10.0
    technical: float = 10.0                  # ignored unless every vendor has a technical rating

    def as_dict(self):
        return asdict(self)


# Friendly short names (matched as lowercase substrings of the vendor name).
VENDOR_SHORT_NAMES = {
    "shanghai electric": "Shanghai Electric",
    "beijing global": "Beijing Technotrade",
    "abb": "ABB India",
    "sec electric": "SEC Electric",
    "weg": "WEG India",
    "bharat heavy": "BHEL",
}

INDIAN_CITIES = [
    "kolkata", "bangalore", "bengaluru", "delhi", "mumbai", "chennai", "pune",
    "hyderabad", "ahmedabad", "kanpur", "ranchi", "jamshedpur", "india",
]

# Outlier rules (rate / median of the other vendors' rates for the same item)
OUTLIER_HIGH = 1.75
OUTLIER_LOW = 0.55
