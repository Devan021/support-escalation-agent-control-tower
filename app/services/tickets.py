import json
from pathlib import Path

from app.core.storage import JsonStateStore
from app.models import Ticket, TicketCreate, TicketStatus


class TicketService:
    def __init__(self, store: JsonStateStore):
        self.store = store

    async def ingest(self, payload: TicketCreate) -> Ticket:
        ticket = Ticket(**payload.model_dump())

        def mutate(state):
            state["tickets"][ticket.ticket_id] = ticket.model_dump(mode="json")
            return ticket

        return await self.store.update(mutate)

    async def get(self, ticket_id: str) -> Ticket | None:
        state = await self.store.load()
        raw = state["tickets"].get(ticket_id)
        return Ticket(**raw) if raw else None

    async def get_by_external_id(self, external_id: str) -> Ticket | None:
        state = await self.store.load()
        for raw in state["tickets"].values():
            if raw.get("external_id") == external_id:
                return Ticket(**raw)
        return None

    async def list(self) -> list[Ticket]:
        state = await self.store.load()
        if not state["tickets"]:
            await self._seed_samples()
            state = await self.store.load()
        return sorted([Ticket(**item) for item in state["tickets"].values()], key=lambda t: t.created_at, reverse=True)

    async def update_status(self, ticket_id: str, status: TicketStatus) -> None:
        def mutate(state):
            if ticket_id in state["tickets"]:
                state["tickets"][ticket_id]["status"] = status

        await self.store.update(mutate)

    async def _seed_samples(self) -> None:
        sample_path = Path("sample_data/tickets.json")
        if not sample_path.exists():
            return
        rows = json.loads(sample_path.read_text(encoding="utf-8"))

        def mutate(state):
            if state["tickets"]:
                return
            for row in rows:
                ticket = Ticket(**TicketCreate(**row).model_dump())
                state["tickets"][ticket.ticket_id] = ticket.model_dump(mode="json")

        await self.store.update(mutate)
