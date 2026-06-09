from app.core.storage import JsonStateStore
from app.models import OutboxActionType, OutboxEvent


class OutboxService:
    def __init__(self, store: JsonStateStore):
        self.store = store

    async def record_dispatch(
        self,
        *,
        trace_id: str,
        run_id: str,
        ticket_id: str,
        action_type: OutboxActionType | str,
        destination: str,
        payload: dict,
        status: str = "dispatched",
    ) -> OutboxEvent:
        event = OutboxEvent(
            trace_id=trace_id,
            run_id=run_id,
            ticket_id=ticket_id,
            action_type=OutboxActionType(action_type),
            destination=destination,
            payload=payload,
            status=status,
        )

        def mutate(state):
            state["outbox"][event.outbox_id] = event.model_dump(mode="json")
            return event

        return await self.store.update(mutate)

    async def list_events(self) -> list[OutboxEvent]:
        state = await self.store.load()
        return sorted(
            [OutboxEvent(**item) for item in state["outbox"].values()],
            key=lambda event: event.created_at,
            reverse=True,
        )

    async def get_event(self, outbox_id: str) -> OutboxEvent | None:
        state = await self.store.load()
        raw = state["outbox"].get(outbox_id)
        return OutboxEvent(**raw) if raw else None

