from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class ConnectionState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    LIMITED = "limited"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class ConnectionStatus:
    """Provider-neutral connection state shared by platform pages."""

    provider: str
    state: ConnectionState
    message: str
    account_id: str | None = None
    account_name: str | None = None
    granted_scopes: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    expires_at: str | None = None
    last_validated_at: str | None = None
    last_error: str | None = None
    credential_storage: str = "Operating-system credential vault"

    @property
    def missing_scopes(self) -> tuple[str, ...]:
        granted = set(self.granted_scopes)
        return tuple(scope for scope in self.required_scopes if scope not in granted)

    @property
    def configured(self) -> bool:
        return self.state not in {
            ConnectionState.NOT_CONFIGURED,
            ConnectionState.DISCONNECTED,
        }

    @property
    def can_sync(self) -> bool:
        return self.state in {ConnectionState.CONNECTED, ConnectionState.LIMITED}

    @property
    def can_disconnect(self) -> bool:
        return self.configured

    def as_dict(self) -> dict:
        result = asdict(self)
        result["state"] = self.state.value
        result["configured"] = self.configured
        result["can_sync"] = self.can_sync
        result["can_disconnect"] = self.can_disconnect
        result["missing_scopes"] = list(self.missing_scopes)
        result["granted_scopes"] = list(self.granted_scopes)
        result["required_scopes"] = list(self.required_scopes)
        return result
