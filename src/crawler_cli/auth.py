from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse


AuthType = Literal["basic", "digest", "bearer", ""]


@dataclass(slots=True)
class AuthConfig:
    auth_type: AuthType = ""
    username: str = ""
    password: str = ""
    token: str = ""
    domain: str = ""
    custom_headers: dict[str, str] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        if self.auth_type == "bearer" and self.token:
            return True
        if self.auth_type in {"basic", "digest"} and self.username and self.password:
            return True
        return bool(self.custom_headers)

    def applies_to(self, url: str) -> bool:
        if not self.enabled:
            return False
        if not self.domain:
            return True
        return urlparse(url).netloc.lower() == self.domain.lower()

    def auth_headers(self) -> dict[str, str]:
        headers = dict(self.custom_headers)
        if self.auth_type == "bearer" and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def basic_credentials(self) -> tuple[str, str] | None:
        if self.auth_type in {"basic", "digest"} and self.username and self.password:
            return self.username, self.password
        return None
