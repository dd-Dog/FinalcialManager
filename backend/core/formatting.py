from decimal import Decimal


def dec2(v: object) -> str:
    """展示/API 输出：固定两位小数。"""
    return f"{Decimal(str(v if v is not None else 0)).quantize(Decimal('0.01')):.2f}"


def dec2_opt(v: object | None) -> str | None:
    """可为空的数值字段；为 None 时保持 None。"""
    if v is None:
        return None
    return dec2(v)
