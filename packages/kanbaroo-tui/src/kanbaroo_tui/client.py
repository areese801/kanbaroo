"""
Async HTTP client wrapper for the Kanbaroo TUI.

Same shape as ``kanbaroo_cli.client.ApiClient`` but built on
``httpx.AsyncClient`` so the Textual event loop can interleave
requests with input handling. The CLI client cannot be reused because
it is synchronous and forcing sync HTTP from inside Textual would
block the UI thread.

Callers never inspect raw ``httpx.Response`` status codes: non-2xx
responses become :class:`ApiRequestError` instances carrying the
canonical error-envelope fields documented in ``docs/spec.md`` section
4.1. Transport-level failures (DNS, refused connection, timeout)
become :class:`ApiTransportError`. The ``transport`` constructor
argument exists so tests can inject an :class:`httpx.MockTransport`
without monkey-patching.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

API_PREFIX = "/api/v1"


class ApiError(Exception):
    """
    Base class for every error surfaced from the TUI HTTP client.
    """


class ApiRequestError(ApiError):
    """
    Raised when the server returns a non-2xx response.

    ``code`` and ``message`` come from the canonical error envelope
    defined in ``docs/spec.md`` section 4.1. ``details`` is the
    per-error dict the server chose to attach (or ``None``).
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class ApiTransportError(ApiError):
    """
    Raised when the HTTP round-trip itself fails.
    """


def _extract_error(response: httpx.Response) -> ApiRequestError:
    """
    Parse the canonical error envelope out of a non-2xx response.

    Falls back to a best-effort message when the body is missing, not
    JSON, or not shaped like the envelope; the caller still gets a
    typed exception with the HTTP status code.
    """
    code = "unknown"
    message = response.text or f"HTTP {response.status_code}"
    details: dict[str, Any] | None = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "error" in body and isinstance(body["error"], dict):
        error = body["error"]
        code = str(error.get("code", code))
        message = str(error.get("message", message))
        raw_details = error.get("details")
        if isinstance(raw_details, dict):
            details = raw_details
    return ApiRequestError(
        status_code=response.status_code,
        code=code,
        message=message,
        details=details,
    )


class AsyncApiClient:
    """
    Authenticated async HTTP wrapper around the Kanbaroo REST API.

    Handles base-URL composition, bearer auth, error-envelope
    translation, and the ``If-Match``/``ETag`` round-trip for the
    single action endpoint the board screen uses
    (``/stories/{id}/transition``). Nothing more: the TUI does not need
    the full CRUD helpers the CLI has.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Build a new client.

        ``transport`` is injected so tests can drive the TUI with an
        :class:`httpx.MockTransport` without touching the network.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self._base_url}{API_PREFIX}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            transport=transport,
            timeout=timeout,
        )

    async def __aenter__(self) -> AsyncApiClient:
        """
        Support ``async with AsyncApiClient(...) as client``.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """
        Close the underlying ``httpx.AsyncClient`` on context exit.
        """
        await self.aclose()

    async def aclose(self) -> None:
        """
        Close the underlying ``httpx.AsyncClient``.
        """
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Issue an HTTP request and return the raw response.

        Non-2xx responses raise :class:`ApiRequestError`; transport
        failures raise :class:`ApiTransportError`.
        """
        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.TransportError as exc:
            raise ApiTransportError(f"could not reach {self._base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise _extract_error(response)
        return response

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """
        Issue a GET request.
        """
        return await self.request("GET", path, params=params)

    async def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Issue a POST request.
        """
        return await self.request(
            "POST",
            path,
            params=params,
            json=json,
            headers=headers,
        )

    async def post_with_etag(
        self,
        entity_path: str,
        action_path: str,
        *,
        json: Any | None = None,
    ) -> httpx.Response:
        """
        POST to ``action_path`` after fetching the ETag of
        ``entity_path``.

        Mirrors ``kanbaroo_cli.client.ApiClient.post_with_etag`` and is
        the only ETag-aware helper the TUI needs in this milestone: the
        board's move mode POSTs to ``/stories/{id}/transition`` with
        ``If-Match`` set to the target story's current version.
        """
        etag = await self._fetch_etag(entity_path)
        return await self.post(action_path, json=json, headers={"If-Match": etag})

    async def _fetch_etag(self, path: str) -> str:
        """
        GET ``path`` and return the ``ETag`` header value.

        Raises :class:`ApiError` when the response carries no ETag;
        this only happens for endpoints that do not support optimistic
        concurrency (tags, linkages) and indicates the caller picked
        the wrong helper.
        """
        response = await self.get(path)
        etag = response.headers.get("etag")
        if etag is None:
            raise ApiError(
                f"response for {path} did not include an ETag header; "
                "this resource does not support optimistic concurrency"
            )
        return str(etag)
