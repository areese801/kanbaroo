"""
Thin HTTP client wrapper for the Kanbaroo CLI.

Every command that hits the server goes through :class:`ApiClient` so
that authentication, base URLs, error-envelope handling, and ETag /
``If-Match`` plumbing live in exactly one place. The wrapper is
intentionally not a general-purpose HTTP abstraction: its job is to
turn the server's documented REST surface into Python calls that raise
typed exceptions on failure.

The client is built on top of :class:`httpx.Client` and accepts an
optional ``transport`` argument so tests can swap in
:class:`httpx.MockTransport` without monkey-patching. This is the same
pattern the FastAPI ``TestClient`` uses internally.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

API_PREFIX = "/api/v1"


class ApiError(Exception):
    """
    Base class for every error surfaced from the CLI HTTP client.

    Commands translate this into a Rich-rendered message and a
    non-zero exit code; no command handler should ever let a raw
    :class:`httpx.HTTPError` escape.
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
    Raised when the HTTP round-trip itself fails (DNS, refused
    connection, timeout). Distinct from :class:`ApiRequestError`
    because the user's remediation is different: start the server,
    check the network, fix the URL.
    """


def _extract_error(response: httpx.Response) -> ApiRequestError:
    """
    Parse the canonical error envelope out of a non-2xx response.

    Falls back to a best-effort message if the server returned a
    body that is not valid JSON or does not match the envelope shape;
    the CLI still surfaces a non-zero exit with a human-readable
    message in that case.
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


class ApiClient:
    """
    Authenticated HTTP wrapper around the Kanbaroo REST API.

    The wrapper handles four things the command handlers would
    otherwise duplicate:

    * Base URL composition: every call takes a path (``/workspaces``)
      and the client prepends ``{base_url}{API_PREFIX}``.
    * Auth: ``Authorization: Bearer <token>`` on every request.
    * Error envelope translation: non-2xx responses become
      :class:`ApiRequestError` instances.
    * ETag / If-Match round trips: :meth:`patch_with_etag` and
      :meth:`delete_with_etag` take an entity path and do the GET to
      read the ETag before issuing the mutation.
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

        ``transport`` is injected so tests can drive the CLI with an
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

    def __enter__(self) -> ApiClient:
        """
        Support ``with ApiClient(...) as client`` in command handlers.
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

        Low-level escape hatch: most callers should use the typed
        wrappers (:meth:`get`, :meth:`post`, ...). Non-2xx responses
        still raise :class:`ApiRequestError` so callers never have to
        inspect ``response.status_code`` themselves.
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
            raise ApiTransportError(f"could not reach {self._base_url}: {exc}") from exc
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
        Issue a PATCH request. Callers that need automatic ETag
        round-tripping should use :meth:`patch_with_etag`.
        """
        return self.request("PATCH", path, json=json, headers=headers)

    def delete(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Issue a DELETE request. Callers that need automatic ETag
        round-tripping should use :meth:`delete_with_etag`.
        """
        return self.request("DELETE", path, headers=headers)

    def patch_with_etag(
        self,
        path: str,
        *,
        json: Any | None = None,
    ) -> httpx.Response:
        """
        PATCH ``path`` after fetching its current ETag via GET.

        Convenience for the common CLI flow: fetch, mutate, send back.
        If the server returns a 412 the caller gets the raw
        :class:`ApiRequestError` so it can render a friendly
        "version conflict" message.
        """
        etag = self._fetch_etag(path)
        return self.patch(path, json=json, headers={"If-Match": etag})

    def delete_with_etag(self, path: str) -> httpx.Response:
        """
        DELETE ``path`` after fetching its current ETag via GET.
        """
        etag = self._fetch_etag(path)
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
        ``entity_path``.

        Used for the ``/epics/{id}/close`` and ``/stories/{id}/transition``
        endpoints, which require ``If-Match`` but do not share a URL
        with their parent entity.
        """
        etag = self._fetch_etag(entity_path)
        return self.post(action_path, json=json, headers={"If-Match": etag})

    def _fetch_etag(self, path: str) -> str:
        """
        GET ``path`` and return the ``ETag`` header value.

        Raises :class:`ApiError` if the response did not include an
        ETag header, which signals that the caller mixed up a
        non-versioned resource (tags, linkages) with the versioned
        helper.
        """
        response = self.get(path)
        etag = response.headers.get("etag")
        if etag is None:
            raise ApiError(
                f"response for {path} did not include an ETag header; "
                "this resource does not support optimistic concurrency"
            )
        return str(etag)
