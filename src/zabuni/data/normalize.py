"""Name normalisation, identifier checks and personal-data guards.

The Kenya PPIP feed documents three problems we must live with rather than clean upstream:
supplier identifier schemes that break the org-id pattern, buyer identifiers with no scheme,
and buyer/supplier names missing from `parties`. Supplier identity is therefore resolved by a
normalised name key, and every row keeps flags saying what was wrong with it.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# org-id.guide style scheme, e.g. "KE-KRA", "GB-COH", "XI-PB"
ORG_ID_SCHEME = re.compile(r"^[A-Z]{2}-[A-Z0-9]{2,}$")
# Kenya Revenue Authority PIN: A or P, nine digits, a letter (e.g. P051234567X)
KRA_PIN = re.compile(r"^[AP]\d{9}[A-Z]$")

LEGAL_SUFFIXES = {
    "limited", "ltd", "co", "company", "plc", "llp", "inc", "incorporated", "corp", "corporation",
}
ORG_MARKERS = LEGAL_SUFFIXES | {
    "enterprises", "enterprise", "ventures", "agencies", "agency", "services", "supplies", "suppliers",
    "traders", "trading", "general", "contractors", "contractor", "construction", "builders",
    "engineering", "group", "holdings", "investments", "international", "solutions", "systems",
    "technologies", "technology", "tech", "pharmaceuticals", "pharma", "medical", "hospital",
    "agrovet", "agro", "farm", "farmers", "sacco", "society", "cooperative", "co-operative", "union",
    "association", "foundation", "trust", "university", "college", "school", "institute", "authority",
    "board", "council", "county", "government", "ministry", "department", "bank", "insurance",
    "hardware", "motors", "garage", "consultants", "consultancy", "consulting", "partners", "associates",
    "logistics", "transporters", "transport", "printers", "printing", "stationers", "stores", "store",
    "distributors", "distribution", "industries", "industry", "manufacturers", "mills", "petroleum",
    "energy", "oil", "water", "drilling", "electrical", "electricals", "communications", "media",
    "catering", "hotel", "security", "cleaning", "and", "&", "kenya", "africa", "east",
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?:\+?254|0)[17]\d{8}")


def strip_contacts(text: str | None) -> str | None:
    """Remove e-mail addresses and Kenyan phone numbers that leak into name fields."""
    if not text:
        return text
    text = _EMAIL.sub("[email removed]", text)
    return _PHONE.sub("[phone removed]", text)


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t]
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def looks_like_natural_person(name: str | None) -> bool:
    """Heuristic: 2-4 alphabetic words and no organisational marker.

    Sole proprietors trade under their own names. The challenge rules forbid exposing
    individuals' personal details, so such suppliers are pseudonymised everywhere.
    """
    if not name:
        return False
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " & ")
    tokens = re.findall(r"[a-z&'-]+|\d+", s)
    if not 2 <= len(tokens) <= 4:
        return False
    if any(t.isdigit() for t in tokens):
        return False
    return not any(t.strip(".") in ORG_MARKERS for t in tokens)


def pseudonym(key: str) -> str:
    return "Supplier P-" + hashlib.sha1(key.encode()).hexdigest()[:8].upper()


def check_supplier_identifier(scheme: str | None, ident: str | None) -> list[str]:
    flags: list[str] = []
    if not ident:
        flags.append("supplier_id_missing")
    if not scheme:
        flags.append("supplier_scheme_missing")
    elif not ORG_ID_SCHEME.match(scheme):
        flags.append("supplier_scheme_invalid")
    if ident and scheme in {"KE-KRA", "KE-PIN"} and not KRA_PIN.match(ident):
        flags.append("supplier_pin_malformed")
    return flags


def parse_amount(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None
