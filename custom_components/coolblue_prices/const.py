"""Constants for Coolblue Energie Prijzen."""

from datetime import timedelta

DOMAIN = "coolblue_prices"
DEFAULT_NAME = "Coolblue Energie"

CONF_DEBTOR_ID = "debtor_id"
CONF_LOCATION_ID = "location_id"

# Options
CONF_PRICE_MODE = "price_mode"
CONF_PURCHASE_FEE = "purchase_fee"
CONF_ENERGY_TAX = "energy_tax"
CONF_VAT = "vat"
CONF_BLOCK_HOURS = "block_hours"
CONF_GAS_PRICE_FALLBACK = "gas_price_fallback"

DEFAULT_PRICE_MODE = "all_in"
DEFAULT_PURCHASE_FEE = 0.0
# Energiebelasting elektriciteit 2026, eerste schijf, excl. btw. Controleer dit
# tegen je eigen contract; alleen nodig voor de terugleverprijs of 'market'-modus.
DEFAULT_ENERGY_TAX = 0.09161
DEFAULT_VAT = 21.0
DEFAULT_BLOCK_HOURS = 3.0
DEFAULT_GAS_PRICE_FALLBACK = 0.0

UPDATE_INTERVAL = timedelta(minutes=30)
# Day-ahead prices are published around 13:00; Coolblue shows them from 14:30.
TOMORROW_AVAILABLE_FROM_HOUR = 13

SERVICE_GET_PRICES = "get_prices"
SERVICE_CHEAPEST_BLOCK = "find_cheapest_block"
