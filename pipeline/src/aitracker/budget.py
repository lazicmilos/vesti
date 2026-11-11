"""Mesečni budžet za LLM (NFR-C-001, FR-019): provera pre svakog poziva i evidencija troška."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from aitracker.db import Conn

MONTHLY_LIMIT_USD = Decimal("5")


class BudgetExceeded(Exception):
    """Poziv bi prešao mesečni budžet; LLM koraci se preskaču do kraja meseca (FR-019)."""


def spent_this_month(conn: Conn, now: datetime) -> Decimal:
    """Trošak iz `runs` od početka tekućeg kalendarskog meseca (UTC)."""
    start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(
        "SELECT coalesce(sum(cost_usd), 0) FROM runs WHERE started_at >= %s", (start,)
    ).fetchone()
    assert row is not None
    return Decimal(row[0])


@dataclass
class Budget:
    """Trošak pre ovog pokretanja (`spent_before`) plus sve što je ovo pokretanje potrošilo.

    `spent_now` uključuje i pozive čiji izlaz nije prošao validaciju: plaćeni su iako nisu
    upisani u keš. Pokretanje ga na kraju upisuje u `runs.cost_usd`.
    """

    spent_before: Decimal
    limit: Decimal = MONTHLY_LIMIT_USD
    spent_now: Decimal = Decimal(0)
    calls: int = 0

    @classmethod
    def from_db(cls, conn: Conn, now: datetime) -> "Budget":
        return cls(spent_before=spent_this_month(conn, now))

    def check(self, worst_case_usd: Decimal) -> None:
        """Granica je tvrda: poziv ide samo ako ni njegov najgori slučaj ne prelazi budžet."""
        if self.spent_before + self.spent_now + worst_case_usd > self.limit:
            raise BudgetExceeded(
                f"potrošeno {self.spent_before + self.spent_now} od {self.limit} USD"
            )

    def add(self, cost_usd: Decimal) -> None:
        self.spent_now += cost_usd
        self.calls += 1
