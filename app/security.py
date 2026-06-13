from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.responses import JSONResponse

from app.config import Settings, get_settings


basic_security = HTTPBasic(auto_error=False)


@dataclass(frozen=True)
class ClientAddress:
    raw: str
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None

    @property
    def is_local(self) -> bool:
        return self.ip is not None and self.ip.is_loopback

    @property
    def is_lan(self) -> bool:
        if self.ip is None:
            return self.raw in {"testclient", "localhost"}
        return self.ip.is_loopback or self.ip.is_private or self.ip.is_link_local


def parse_client_address(raw: str | None) -> ClientAddress:
    value = (raw or "").strip()
    try:
        return ClientAddress(raw=value, ip=ipaddress.ip_address(value))
    except ValueError:
        return ClientAddress(raw=value, ip=None)


def address_in_entries(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    entries: list[str],
) -> bool:
    for entry in entries:
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            elif address == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def get_client_address(request: Request, settings: Settings) -> ClientAddress:
    direct = parse_client_address(request.client.host if request.client else "")
    if not settings.trust_proxy_headers:
        return direct

    if direct.ip is None or not address_in_entries(direct.ip, settings.trusted_proxy_ips):
        return direct

    forwarded_for = request.headers.get("x-forwarded-for", "")
    first_forwarded = forwarded_for.split(",", 1)[0].strip()
    if not first_forwarded:
        return direct
    return parse_client_address(first_forwarded)


def is_request_allowed(request: Request, settings: Settings) -> bool:
    client = get_client_address(request, settings)
    if client.is_lan:
        return True
    if client.ip is None or not settings.public_access_enabled:
        return False
    return address_in_entries(client.ip, settings.public_ip_whitelist)


async def ip_access_middleware(request: Request, call_next):
    settings = get_settings()
    if not is_request_allowed(request, settings):
        client = get_client_address(request, settings)
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": f"client IP is not allowed: {client.raw or 'unknown'}"},
        )
    return await call_next(request)


def _credentials_match(credentials: HTTPBasicCredentials, settings: Settings) -> bool:
    username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    return username_ok and password_ok


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(basic_security),
    settings: Settings = Depends(get_settings),
) -> None:
    if credentials is None or not _credentials_match(credentials, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要管理员认证",
            headers={"WWW-Authenticate": "Basic"},
        )


def require_upload_auth(
    credentials: HTTPBasicCredentials | None = Depends(basic_security),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.require_auth_for_upload:
        return
    if credentials is None or not _credentials_match(credentials, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要上传认证",
            headers={"WWW-Authenticate": "Basic"},
        )


def require_local_request(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    client = get_client_address(request, settings)
    if not client.is_local:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作只能在服务端本机执行",
        )
