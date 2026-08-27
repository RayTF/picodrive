"""Bounded, paced and retrying HTTP transport."""

from __future__ import annotations

import email.utils
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from .identity import ProviderOperationalError


@dataclass
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Return redirects to the caller instead of following them."""

    def redirect_request(self, request: object, file_pointer: object, code: int,
                         message: str, headers: object, new_url: str) -> None:
        return None


def build_url_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(NoRedirectHandler())


def urllib_transport(url: str, timeout: float, limit: int,
                     opener: Optional[urllib.request.OpenerDirector] = None) -> HttpResponse:
    request = urllib.request.Request(url, headers={"User-Agent": "VectorDrive-metadata/1"})
    try:
        response = (opener or build_url_opener()).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        headers = dict(error.headers.items()) if error.headers is not None else {}
        try:
            body = error.read(limit + 1)
        finally:
            error.close()
        return HttpResponse(error.code, headers, body)
    with response:
        body = response.read(limit + 1)
        return HttpResponse(response.status, dict(response.headers.items()), body)


class HttpClient:
    def __init__(self, transport: Optional[Callable[[str, float, int], HttpResponse]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 minimum_interval: float = 1.2, attempts: int = 3) -> None:
        self.transport = transport or urllib_transport
        self.clock = clock
        self.sleep = sleep
        self.minimum_interval = minimum_interval
        self.attempts = attempts
        self._last_request: Optional[float] = None

    def _pace(self) -> None:
        if self._last_request is not None:
            delay = self.minimum_interval - (self.clock() - self._last_request)
            if delay > 0:
                self.sleep(delay)
        self._last_request = self.clock()

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> float:
        value = next((v for k, v in headers.items() if k.lower() == "retry-after"), "")
        try:
            return min(30.0, max(0.0, float(value)))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
                return min(30.0, max(0.0, parsed))
            except (TypeError, ValueError, OverflowError):
                return 0.0

    def get(self, url: str, timeout: float, limit: int) -> HttpResponse:
        for attempt in range(self.attempts):
            self._pace()
            try:
                response = self.transport(url, timeout, limit)
            except urllib.error.HTTPError as error:
                headers = dict(error.headers.items()) if error.headers is not None else {}
                try:
                    body = error.read(limit + 1)
                finally:
                    error.close()
                response = HttpResponse(error.code, headers, body)
            except (OSError, TimeoutError, urllib.error.URLError):
                if attempt + 1 == self.attempts:
                    raise ProviderOperationalError(
                        "provider network request exhausted retries", "network"
                    )
                self.sleep(min(8.0, 1.0 * (2 ** attempt)))
                continue
            if len(response.body) > limit:
                raise ProviderOperationalError("provider response exceeds its size limit", "malformed")
            if response.status == 429 or 500 <= response.status <= 599:
                if attempt + 1 == self.attempts:
                    category = "quota" if response.status == 429 else "service"
                    raise ProviderOperationalError(
                        f"provider HTTP {response.status} exhausted retries", category
                    )
                delay = self._retry_after(response.headers) if response.status == 429 else 2 ** attempt
                self.sleep(min(30.0, max(0.0, delay)))
                continue
            return response
        raise ProviderOperationalError("provider request failed", "network")
