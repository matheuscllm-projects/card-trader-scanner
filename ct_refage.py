"""ct_refage.py - idade da referência de preço. Módulo PURO, ÚNICO dono do cálculo (scanner e
postprocess usam a mesma função, com o mesmo fuso).

Idade = dias de calendário entre a data do DADO e o dia de `now`, no fuso de `now`. Só existe quando o
rótulo diz que a data é a do DADO ("dado de"); "buscado em" (hora da busca), vazio ou data inválida =
idade DESCONHECIDA (None) — desconhecida nunca é tratada como "atual".
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

LABEL_DATA = "dado de"
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_ref_date(at, tz=None) -> Optional[date]:
    """Data do dado -> `date` (com fuso: convertida para `tz`; sem hora/fuso: a própria data)."""
    s = str(at or "").strip()
    if not s or s.lower() == "nan":
        return None
    if _DATE_ONLY.match(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo:
        d = d.astimezone(tz) if tz else d.astimezone()
    return d.date()


def ref_age_days(at, label, now: datetime) -> Optional[int]:
    """Idade em dias, ou None (desconhecida)."""
    if str(label or "").strip() != LABEL_DATA:
        return None
    d = parse_ref_date(at, now.tzinfo)
    if d is None:
        return None
    days = (now.date() - d).days
    return days if days >= 0 else None      # B1j-B1: data futura = idade desconhecida
