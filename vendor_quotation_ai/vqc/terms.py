"""Turn free-text commercial terms into numbers the scoring engine can use."""
from __future__ import annotations
import re

_NUM = r"(\d+(?:\.\d+)?)"


def clean(text) -> str:
    if text is None or (isinstance(text, float) and text != text):   # None / NaN
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


# ---------------------------------------------------------------- price basis
def classify_basis(text) -> str:
    t = clean(text)
    if re.search(r"F\.?O\.?B|\bFCA\b", t, re.I):
        return "FOB"
    if re.search(r"C\.?I\.?F|\bCFR\b|C&F|\bCIP\b", t, re.I):
        return "CIF"
    if re.search(r"ex[\s-]*works|\bEXW\b", t, re.I):
        return "EXW"
    if re.search(r"\bF\.?O\.?R\b|\bDAP\b|\bDDP\b|delivered", t, re.I):
        return "DELIVERED"
    return "UNKNOWN"


def is_import(basis: str) -> bool:
    return basis in ("FOB", "CIF")


# ------------------------------------------------------------ payment terms
def parse_payment(text) -> dict:
    t = clean(text)
    if not t:
        return dict(advance_pct=None, secured=False, has_lc=False, has_pbg=False, no_protection=False)
    adv = sum(float(x) for x in re.findall(_NUM + r"\s*%\s*(?:TT\s*)?(?:in\s*)?advance", t, re.I))
    # milestone money paid before manufacturing (e.g. "10% against GAD approval")
    adv += sum(float(x) for x in re.findall(_NUM + r"\s*%\s*against\s*(?:GAD|drawing)", t, re.I))
    secured = bool(re.search(r"\bABG\b|advance bank guarantee", t, re.I))
    has_lc = bool(re.search(r"\bL/?C\b|letter of credit", t, re.I))
    has_pbg = bool(re.search(r"\bPBG\b|performance (?:bank )?guarantee", t, re.I))
    no_protection = not (secured or has_lc or has_pbg)
    return dict(advance_pct=adv, secured=secured, has_lc=has_lc, has_pbg=has_pbg, no_protection=no_protection)


def payment_score(p: dict) -> float:
    """100 = no advance. Unsecured advance counts double; no bank protection at all costs 20 pts."""
    adv = p.get("advance_pct") or 0.0
    s = 100 - adv * (0.5 if p.get("secured") else 1.0) - (20 if p.get("no_protection") else 0)
    return max(0.0, min(100.0, s))


# ----------------------------------------------------------------- delivery
def parse_delivery(text) -> dict:
    """Return first / full delivery in months (weeks and days are converted)."""
    t = clean(text)
    vals = []
    for n, unit in re.findall(_NUM + r"\s*(months?|weeks?|days?)", t, re.I):
        n, unit = float(n), unit.lower()
        vals.append(n if unit.startswith("month") else n * 12 / 52 if unit.startswith("week") else n / 30.4)
    if not vals:
        return dict(first=None, full=None)
    return dict(first=round(min(vals), 1), full=round(max(vals), 1))


# ----------------------------------------------------------------- warranty
def parse_warranty(text):
    """'18/24 months' -> 24 (longest clock, normally from dispatch)."""
    nums = [float(n) for n in re.findall(_NUM, clean(text))]
    return max(nums) if nums else None


# -------------------------------------------------------------- supervision
def classify_supervision(text) -> str:
    t = clean(text).lower()
    if not t:
        return "Not quoted"
    if "additional" in t:
        return "Partly included"
    if "included" in t:
        return "Included"
    if "charge" in t or "manday" in t:
        return "Chargeable"
    return "Unclear"
