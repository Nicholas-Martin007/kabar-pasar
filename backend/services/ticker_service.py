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

# ── Broader IDX ticker universe (code-only detection) ────────────────────────
# Curated set of actively-traded IDX tickers. Detection matches any bare
# 4-uppercase-letter code in text that is in this set — so news mentioning a
# code (e.g. "ADMR") gets tagged even without a name alias above.
# Not exhaustive of all ~900 listings; covers the liquid universe. Common
# English words that are also tickers (BANK, GOOD, MAIN, BEST, CARE, PORT, FIRE)
# are intentionally omitted to avoid false positives — they match via aliases.
VALID_TICKERS: Set[str] = {
    # Banks
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BBTN", "BNGA", "BJBR", "BJTM",
    "BNLI", "BBKP", "BDMN", "NISP", "MEGA", "BTPS", "BTPN", "PNBN", "SDRA",
    "BBYB", "ARTO", "AGRO", "BBHI", "AMAR", "BABP", "BVIC", "BSIM", "BGTG",
    "BNII", "MAYA", "PNBS",
    # Telco / tower / tech
    "TLKM", "ISAT", "EXCL", "FREN", "MTEL", "TBIG", "TOWR", "GOTO", "BUKA",
    "EMTK", "MTDL", "DCII", "MLPT", "WIFI", "MCAS", "DMMX", "EDGE", "BELI",
    "WIRG", "MSIN",
    # Coal / energy
    "ADRO", "ADMR", "AADI", "PTBA", "ITMG", "INDY", "HRUM", "BUMI", "BYAN",
    "BSSR", "GEMS", "DSSA", "DOID", "PTRO", "RAJA", "ENRG", "ABMM", "TOBA",
    # Oil & gas / chemicals
    "MEDC", "PGAS", "ELSA", "AKRA", "ESSA", "BRPT", "TPIA", "INKP", "TKIM",
    # Metals / mining
    "ANTM", "INCO", "TINS", "MDKA", "NCKL", "MBMA", "BRMS", "PSAB", "DKFT",
    "ZINC", "HRTA", "UNTR", "AMMN",
    # Cement / materials
    "SMGR", "INTP", "SMBR",
    # Consumer / pharma / cigarettes
    "UNVR", "ICBP", "INDF", "MYOR", "SIDO", "KLBF", "KAEF", "TSPC", "PYFA",
    "SOHO", "PEHA", "HMSP", "GGRM", "WIIM", "ULTJ", "ROTI", "CLEO", "KINO",
    "CMRY", "MLBI", "DLTA", "STTP", "CAMP", "AISA",
    # Poultry / plantation
    "CPIN", "JPFA", "AALI", "LSIP", "SIMP", "DSNG", "SGRO", "TAPG", "TBLA",
    "ANJT", "BWPT", "SSMS",
    # Retail
    "AMRT", "MAPI", "ACES", "ERAA", "RALS", "LPPF", "MAPA", "MIDI", "CSAP",
    # Auto / industrial
    "ASII", "AUTO", "IMAS", "GJTL", "DRMA", "SMSM",
    # Property / construction / infra
    "BSDE", "CTRA", "PWON", "SMRA", "LPKR", "DMAS", "ASRI", "APLN", "PANI",
    "KIJA", "SSIA", "ADHI", "WIKA", "WSKT", "PTPP", "WTON", "WSBP", "WEGE",
    "JKON", "TOTL", "NRCA", "DGIK",
    # Toll / transport / logistics
    "JSMR", "META", "CMNP", "ASSA", "BIRD", "SMDR", "TMAS", "IPCC", "HAIS",
    # Healthcare
    "MIKA", "HEAL", "SILO", "SAME", "PRDA", "SRAJ",
    # Media
    "MNCN", "SCMA", "FILM", "VIVA", "TMPO",
    # Finance / multifinance
    "BFIN", "ADMF", "CFIN", "WOMF",
    # Large / popular new listings
    "BREN", "CUAN", "RATU",
}
VALID_TICKERS |= set(TICKER_KEYWORDS.keys())

_CODE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}(?![A-Za-z0-9])")

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

    # 1) Name/alias matching (case-insensitive) for the curated majors.
    for ticker, pattern in _PATTERNS.items():
        if pattern.search(lower_text):
            found.add(ticker)

    # 2) Bare ticker-code matching for the broader IDX universe.
    for code in _CODE_RE.findall(text):
        if code in VALID_TICKERS:
            found.add(code)

    return sorted(found)
