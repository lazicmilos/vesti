from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aitracker.budget import Budget, BudgetExceeded, spent_this_month
from aitracker.db import Conn

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)


def test_check_propusta_poziv_koji_staje_tacno_u_budzet() -> None:
    budget = Budget(spent_before=Decimal("4.90"))
    budget.add(Decimal("0.05"))

    budget.check(Decimal("0.05"))  # 4.90 + 0.05 + 0.05 = 5.00, granica je uključiva


def test_check_odbija_poziv_ciji_najgori_slucaj_prelazi_budzet() -> None:
    budget = Budget(spent_before=Decimal("4.99"))

    with pytest.raises(BudgetExceeded):
        budget.check(Decimal("0.02"))


def test_add_sabira_trosak_i_broji_pozive() -> None:
    budget = Budget(spent_before=Decimal(0))
    budget.add(Decimal("0.01"))
    budget.add(Decimal("0.02"))

    assert (budget.spent_now, budget.calls) == (Decimal("0.03"), 2)


@pytest.mark.db
def test_spent_this_month_broji_samo_tekuci_mesec(conn: Conn) -> None:
    conn.execute(
        "INSERT INTO runs (started_at, cost_usd) VALUES "
        "('2026-10-31 23:59+00', 1.00), ('2026-11-01 00:00+00', 0.25), "
        "('2026-11-10 05:00+00', 0.50)"
    )

    assert spent_this_month(conn, NOW) == Decimal("0.75")
    assert Budget.from_db(conn, NOW).spent_before == Decimal("0.75")


@pytest.mark.db
def test_spent_this_month_bez_pokretanja_je_nula(conn: Conn) -> None:
    assert spent_this_month(conn, NOW) == Decimal(0)
