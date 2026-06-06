from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class NewsSource(str, Enum):
    CNBC_INDONESIA   = "CNBC Indonesia"
    DETIK_FINANCE    = "Detik Finance"
    KONTAN           = "Kontan"
    BISNIS_INDONESIA = "Bisnis Indonesia"
    BEI              = "BEI"
    IR_EMITEN        = "IR Emiten"


class NewsImportance(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class NewsCategory(str, Enum):
    CORPORATE_ACTION = "corporate_action"
    EARNINGS         = "earnings"
    MARKET_NEWS      = "market_news"
    REGULATORY       = "regulatory"
    MACRO            = "macro"


class News(BaseModel):
    """
    Mirrors the frontend News interface (src/types/news.ts).
    Serialised with camelCase aliases so the React Native app
    can consume the API without any field mapping.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    id:           str
    title:        str
    source:       NewsSource
    published_at: str                          # ISO 8601
    excerpt:      str
    ai_summary:   List[str]       = Field(default_factory=list)
    impact:       Optional[str]   = None        # 1-kalimat dampak buat investor
    tickers:      List[str]       = Field(default_factory=list)
    importance:   NewsImportance  = NewsImportance.MEDIUM
    category:     NewsCategory    = NewsCategory.MARKET_NEWS
    url:          Optional[str]   = None
