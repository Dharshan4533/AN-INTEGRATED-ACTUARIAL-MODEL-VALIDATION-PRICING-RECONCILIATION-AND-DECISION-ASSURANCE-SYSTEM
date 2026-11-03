"""
Rounding Policy and ISO 4217 Currency Precision Module.
Provides deterministic currency quantization and statutory rounding rules.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
from typing import Dict, Optional, Union

# ISO 4217 Minor Unit (Decimal Places) Reference Table
ISO_4217_MINOR_UNITS: Dict[str, int] = {
    # 0 Minor Units (Zero decimal places)
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0,
    "KRW": 0, "PYG": 0, "RWF": 0, "UGX": 0, "UYI": 0, "VND": 0, "VUV": 0, "XAF": 0, "XOF": 0, "XPF": 0,
    # 3 Minor Units (Three decimal places)
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    # 2 Minor Units (Standard two decimal places - default for major currencies)
    "USD": 2, "EUR": 2, "GBP": 2, "INR": 2, "CAD": 2, "AUD": 2, "CHF": 2,
    "CNY": 2, "SGD": 2, "HKD": 2, "NZD": 2, "SEK": 2, "NOK": 2, "MXN": 2,
    "BRL": 2, "ZAR": 2, "AED": 2, "SAR": 2
}


class RoundingMethod(str, Enum):
    ROUND_HALF_UP = "ROUND_HALF_UP"
    ROUND_HALF_EVEN = "ROUND_HALF_EVEN"
    ROUND_CEILING = "ROUND_CEILING"
    ROUND_FLOOR = "ROUND_FLOOR"


_DECIMAL_ROUND_MAP = {
    RoundingMethod.ROUND_HALF_UP: ROUND_HALF_UP,
    RoundingMethod.ROUND_HALF_EVEN: ROUND_HALF_EVEN,
    RoundingMethod.ROUND_CEILING: ROUND_CEILING,
    RoundingMethod.ROUND_FLOOR: ROUND_FLOOR,
}


def get_currency_precision(currency_code: str, override: Optional[int] = None) -> int:
    """
    Determine currency decimal precision based on ISO 4217 standard or explicit statutory override.
    """
    if override is not None:
        if not (0 <= override <= 8):
            raise ValueError(f"Invalid currency precision override: {override}. Must be between 0 and 8.")
        return override
    code_upper = currency_code.upper().strip()
    return ISO_4217_MINOR_UNITS.get(code_upper, 2)


def quantize_currency(
    amount: Union[float, int, str, Decimal],
    precision: int = 2,
    method: Union[str, RoundingMethod] = RoundingMethod.ROUND_HALF_UP
) -> Decimal:
    """
    Quantize an amount to the specified currency minor unit precision using exact Decimal arithmetic.
    """
    if isinstance(method, str):
        method = RoundingMethod(method)
    
    decimal_mode = _DECIMAL_ROUND_MAP.get(method, ROUND_HALF_UP)
    d_amount = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    
    if precision == 0:
        step = Decimal("1")
    else:
        step = Decimal("1e-" + str(precision))
        
    return d_amount.quantize(step, rounding=decimal_mode)
