from pydantic_settings import SettingsConfigDict

from reelix_runtime.settings import RuntimeSettings


class McpSettings(RuntimeSettings):
    """MCP-server settings on top of the shared runtime settings.

    v1 runs anonymous: every request uses ``anon_user_id``, which also
    satisfies the ticket-ownership check when explanations are redeemed.
    Must be a valid UUID — telemetry tables type user_id as uuid; the nil
    UUID marks anonymous MCP traffic (endpoint/request_meta are the primary
    transport discriminators).
    """

    anon_user_id: str = "00000000-0000-0000-0000-000000000000"
    why_ticket_ttl_sec: int = 15 * 60  # sliding TTL, mirrors explore's IDLE_TTL_SEC

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
