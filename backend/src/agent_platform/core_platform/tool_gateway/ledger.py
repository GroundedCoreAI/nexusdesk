"""Storage adapter for the Tool Gateway operation ledger."""

from agent_platform.core_platform.platform_services.persistence.store import execute, one
from agent_platform.extension_contracts import OperationRecord


class ToolOperationLedger:
    """Persist normalized operation records in the legacy ``tool_calls`` table.

    Keeping this SQL in one adapter lets the Runtime and capability handlers
    depend on ``OperationLedgerPort`` while the database schema remains
    unchanged during the refactor.
    """

    def __init__(self, engine):
        self.engine = engine

    async def get(self, operation_id):
        async with self.engine.connect() as connection:
            row = await one(
                connection,
                "SELECT id,tenant_id,run_id,tool_name,tool_version,adapter_type,effect,"
                "status,error_code,duration_ms FROM tool_calls WHERE id=:id",
                id=operation_id,
            )
        return OperationRecord.model_validate(row) if row else None

    async def record(self, operation: OperationRecord) -> None:
        async with self.engine.begin() as connection:
            if await one(
                connection,
                "SELECT id FROM tool_calls WHERE id=:id",
                id=operation.id,
            ):
                return
            await execute(
                connection,
                "INSERT INTO tool_calls(id,tenant_id,run_id,tool_name,tool_version,adapter_type,effect,status,error_code,duration_ms) "
                "VALUES(:id,:tenant_id,:run_id,:tool_name,:tool_version,:adapter_type,:effect,:status,:error_code,:duration_ms)",
                id=operation.id,
                tenant_id=operation.tenant_id,
                run_id=operation.run_id,
                tool_name=operation.tool_name,
                tool_version=operation.tool_version,
                adapter_type=operation.adapter_type,
                effect=operation.effect,
                status=operation.status,
                error_code=operation.error_code,
                duration_ms=operation.duration_ms,
            )
