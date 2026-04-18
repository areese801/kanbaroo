"""
HTTP client for the Kanberoo MCP server.

The MCP server exposes tools; under the hood every tool call is a
request to the Kanberoo REST API. This module is the one place where
the server speaks HTTP: bearer-token auth, base URL composition,
``If-Match`` plumbing for optimistic concurrency, and translation of
the canonical error envelope into typed exceptions all live here.

The client is deliberately its own thing rather than an import from
``kanberoo-cli``: sibling front-end packages do not import each
other. The small amount of duplication is cheaper than the coupling.

The client is built on top of :class:`httpx.Client` and accepts an
optional ``transport`` argument so tests can swap in
:class:`httpx.MockTransport` without monkey-patching.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

API_PREFIX = "/api/v1"


class McpApiError(Exception):
    """
    Base class for every error surfaced from the MCP HTTP client.

    Tool handlers translate this into an MCP ``isError`` result;
    no handler should ever let a raw :class:`httpx.HTTPError` escape.
    """


class McpApiRequestError(McpApiError):
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


class McpApiTransportError(McpApiError):
    """
    Raised when the HTTP round-trip itself fails (DNS, refused
    connection, timeout).
    """


def _extract_error(response: httpx.Response) -> McpApiRequestError:
    """
    Parse the canonical error envelope out of a non-2xx response.

    Falls back to a best-effort message if the server returned a
    body that is not valid JSON or does not match the envelope
    shape.
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
    return McpApiRequestError(
        status_code=response.status_code,
        code=code,
        message=message,
        details=details,
    )


class McpApiClient:
    """
    Authenticated HTTP wrapper around the Kanberoo REST API.

    This is the sync counterpart to the CLI's :class:`ApiClient`. It
    lives in the MCP package to avoid cross-sibling imports; the two
    clients are intentionally separate so evolutions of either can
    proceed without coordination.

    Responsibilities:

    * Base URL composition: every call takes a path (``/workspaces``)
      and the client prepends ``{base_url}{API_PREFIX}``.
    * Auth: ``Authorization: Bearer <token>`` on every request.
    * Error envelope translation: non-2xx responses become
      :class:`McpApiRequestError` instances.
    * ETag / If-Match round trips via :meth:`patch_with_etag`,
      :meth:`delete_with_etag`, and :meth:`post_with_etag`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Build a new client.

        ``transport`` is injected so tests can drive the server with an
        :class:`httpx.MockTransport` without touching the network.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self._base_url}{API_PREFIX}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            transport=transport,
            timeout=timeout,
        )

    def __enter__(self) -> McpApiClient:
        """
        Support ``with McpApiClient(...) as client`` in tool handlers.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """
        Close the underlying ``httpx.Client`` on context exit.
        """
        self.close()

    def close(self) -> None:
        """
        Close the underlying ``httpx.Client``.
        """
        self._client.close()

    def request(
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

        Non-2xx responses raise :class:`McpApiRequestError`. Transport
        failures raise :class:`McpApiTransportError`.
        """
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.TransportError as exc:
            raise McpApiTransportError(
                f"could not reach {self._base_url}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise _extract_error(response)
        return response

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """
        Issue a GET request.
        """
        return self.request("GET", path, params=params)

    def post(
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
        return self.request("POST", path, params=params, json=json, headers=headers)

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Issue a PATCH request.
        """
        return self.request("PATCH", path, json=json, headers=headers)

    def delete(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Issue a DELETE request.
        """
        return self.request("DELETE", path, headers=headers)

    def fetch_etag(self, path: str) -> str:
        """
        GET ``path`` and return the ``ETag`` header value.

        Raises :class:`McpApiError` if the response did not include an
        ETag header; the caller mixed a non-versioned resource (tags,
        linkages) with the versioned helper.
        """
        response = self.get(path)
        etag = response.headers.get("etag")
        if etag is None:
            raise McpApiError(
                f"response for {path} did not include an ETag header; "
                "this resource does not support optimistic concurrency"
            )
        return str(etag)

    def patch_with_etag(
        self,
        path: str,
        *,
        json: Any | None = None,
    ) -> httpx.Response:
        """
        PATCH ``path`` after fetching its current ETag via GET.
        """
        etag = self.fetch_etag(path)
        return self.patch(path, json=json, headers={"If-Match": etag})

    def delete_with_etag(self, path: str) -> httpx.Response:
        """
        DELETE ``path`` after fetching its current ETag via GET.
        """
        etag = self.fetch_etag(path)
        return self.delete(path, headers={"If-Match": etag})

    def post_with_etag(
        self,
        entity_path: str,
        action_path: str,
        *,
        json: Any | None = None,
    ) -> httpx.Response:
        """
        POST to ``action_path`` after fetching the ETag of
        ``entity_path``. Used by ``/stories/{id}/transition`` and
        ``/epics/{id}/close`` style endpoints.
        """
        etag = self.fetch_etag(entity_path)
        return self.post(action_path, json=json, headers={"If-Match": etag})
