"""
Keyword-based IDX ticker detection.
Matches ticker codes and company name keywords against text.
"""

import re
from typing import Dict, List, Set

# ── Ticker → list of name keywords (lowercase) ───────────────────────────────
# Each entry: ticker: [aliases to match in news text]
TICKER_KEYWORDS: Dict[str, List[str]] = {
    "BBCA": ["bbca", "bank central asia", "bca"],
    "BBRI": ["bbri", "bank rakyat indonesia", "bri"],
    "BMRI": ["bmri", "bank mandiri", "mandiri"],
    "BBNI": ["bbni", "bank negara indonesia", "bni"],
    "BNGA": ["bnga", "bank cimb niaga", "cimb niaga"],
    "TLKM": ["tlkm", "telkom", "telekomunikasi indonesia"],
    "ASII": ["asii", "astra international", "astra"],
    "GOTO": ["goto", "gojek tokopedia", "gojek", "tokopedia", "gotogroup"],
    "BREN": ["bren", "barito renewables", "barito renewable"],
    "ANTM": ["antm", "aneka tambang", "antam"],
    "UNVR": ["unvr", "unilever indonesia", "unilever"],
    "MEDC": ["medc", "medco energi", "medco"],
    "INDF": ["indf", "indofood", "indofood sukses makmur"],
    "ICBP": ["icbp", "indofood cbp"],
    "HMSP": ["hmsp", "hm sampoerna", "sampoerna"],
    "GGRM": ["ggrm", "gudang garam"],
    "SMGR": ["smgr", "semen indonesia", "semen indonesia"],
    "PTBA": ["ptba", "bukit asam", "tambang batubara bukit asam"],
    "ADRO": ["adro", "adaro energy", "adaro"],
    "ITMG": ["itmg", "indo tambangraya megah"],
    "PGAS": ["pgas", "perusahaan gas negara", "pgn"],
    "JSMR": ["jsmr", "jasa marga"],
    "WSKT": ["wskt", "waskita karya", "waskita"],
    "PTPP": ["ptpp", "pp persero", "pp (persero)"],
    "WIKA": ["wika", "wijaya karya"],
    "ACES": ["aces", "ace hardware"],
    "MAPI": ["mapi", "mitra adiperkasa"],
    "ERAA": ["eraa", "erajaya swasembada", "erajaya"],
    "MNCN": ["mncn", "media nusantara citra", "mnc"],
    "SCMA": ["scma", "surya citra media", "sctv"],
    "EMTK": ["emtk", "elang mahkota teknologi"],
    "BUMI": ["bumi", "bumi resources"],
    "BRPT": ["brpt", "barito pacific", "barito"],
    "TPIA": ["tpia", "chandra asri", "chandra asri petrochemical"],
    "INCO": ["inco", "vale indonesia", "vale"],
    "MDKA": ["mdka", "merdeka copper gold"],
    "AMRT": ["amrt", "alfamart", "sumber alfaria"],
    "LSIP": ["lsip", "pp london sumatra", "lonsum"],
    "AALI": ["aali", "astra agro lestari"],
    "DSNG": ["dsng", "dharma satya nusantara"],
    "TBIG": ["tbig", "tower bersama", "tower bersama infrastructure"],
    "MTEL": ["mtel", "mitratel", "dayamitra telekomunikasi"],
    "FILM": ["film", "md pictures", "md entertainment"],
    "SIDO": ["sido", "sidomuncul", "sido muncul"],
    "KLBF": ["klbf", "kalbe farma", "kalbe"],
    "KAEF": ["kaef", "kimia farma"],
    "PYFA": ["pyfa", "pyridam farma"],
    "BJTM": ["bjtm", "bank jatim", "bank pembangunan daerah jawa timur"],
    "BJBR": ["bjbr", "bank bjb", "bank pembangunan daerah jawa barat"],
    "BNLI": ["bnli", "bank permata", "permata"],
}

# Pre-compile patterns for efficiency
_PATTERNS: Dict[str, re.Pattern] = {}

for _ticker, _keywords in TICKER_KEYWORDS.items():
    # Match any keyword surrounded by word-boundary-like context
    escaped = [re.escape(k) for k in _keywords]
    _PATTERNS[_ticker] = re.compile(
        r"(?<![a-zA-Z])(" + "|".join(escaped) + r")(?![a-zA-Z])",
        re.IGNORECASE,
    )


def detect_tickers(text: str) -> List[str]:
    """
    Return sorted list of IDX tickers found in *text*.
    Matches both ticker codes (e.g. 'BBCA') and company names
    (e.g. 'Bank Central Asia', 'BCA').
    """
    found: Set[str] = set()
    lower_text = text.lower()

    for ticker, pattern in _PATTERNS.items():
        if pattern.search(lower_text):
            found.add(ticker)

    return sorted(found)
