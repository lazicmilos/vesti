"""Mesečni budžet LLM-a (NFR-C-001): provera pre poziva i upis troška u tekući red `runs`."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from aitracker.db import Conn

LIMIT_USD = Decimal("5")
# ponytail: trošak poziva se zna tek posle odgovora, pa rezerva pokriva poslednji poziv koji
# prelazi granicu. Dovoljno dok je jedan poziv << 0,05 USD; inače procenjivati iz max_tokens.
RESERVE_USD = Decimal("0.05")


class BudgetExceeded(Exception):
    """Mesečni budžet je potrošen; LLM koraci se preskaču do kraja meseca (FR-019)."""


@dataclass
class Budget:
    """Trošak se upisuje u `runs` odmah posle svakog poziva, pa ga pad pokretanja ne gubi."""

    conn: Conn
    run_id: int
    now: datetime

    def spent(self) -> Decimal:
        month_start = self.now.astimezone(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        row = self.conn.execute(
            "SELECT coalesce(sum(cost_usd), 0) FROM runs WHERE started_at >= %s", (month_start,)
        ).fetchone()
        assert row is not None
        return Decimal(row[0])

    def check(self) -> None:
        spent = self.spent()
        if spent >= LIMIT_USD - RESERVE_USD:
            raise BudgetExceeded(f"potrošeno {spent} od {LIMIT_USD} USD ovog meseca")

    def charge(self, cost_usd: Decimal) -> None:
        self.conn.execute(
            "UPDATE runs SET cost_usd = cost_usd + %s, llm_calls = llm_calls + 1 WHERE id = %s",
            (cost_usd, self.run_id),
        )
