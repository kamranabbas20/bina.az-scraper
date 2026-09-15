"""HTML -> typed records."""

from .detail import parse_detail
from .listing import parse_listing_page

__all__ = ["parse_detail", "parse_listing_page"]
