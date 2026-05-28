"""
config.py — Central configuration for Sharper Margins.
Import from here instead of scattering constants across files.
"""

# Edge calculation thresholds
EDGE_THRESHOLD = 0.10
KALSHI_ALIGNMENT_THRESHOLD = 0.05
# Minimum vig-adjusted implied probability for a signal to fire.
# Filters extreme underdogs (+300 or longer) where the model's ceiling
# creates false edges against heavily priced favourites.
MIN_SIGNAL_IMPLIED = 0.25

# Kalshi fuzzy-match confidence threshold (0–100 rapidfuzz score)
FUZZY_THRESHOLD = 80

# Hours after game start to still consider a signal "active" on the dashboard
ACTIVE_SIGNAL_HOURS = 6

# HTTP retry settings for external API calls
FETCH_MAX_RETRIES = 3
FETCH_RETRY_BACKOFF = [1, 2, 4]  # seconds between successive retries

# Dashboard history page size (number of rows per page)
HISTORY_PAGE_SIZE = 50
