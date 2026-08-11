"""The real ``Transport`` for the HTTP CoreGateway — the only piece that touches
the network (ADR-0017 §3/§5).

Every call to Core's internal API is **dual-authenticated**: SigV4-signed as the
plugin's Lambda role *and* carrying the founder's Cognito token in
``X-Biffo-User-Token``, which Core re-verifies to establish identity and
owner-scope. The plugin's own ingress already verified that token to admit the
request; forwarding it lets Core be the authority (the plugin is defence-in-depth).

Built on ``biffo_plugin_sdk.PrincipalCoreClient`` (>=1.3.0, biffo-template#1490),
which folds the forwarded-user header into its ``_sign()`` override — the single
choke point every verb (and ``_send``) passes through — so there is no second
call site that could add the header after the fact and miss the signature.
This module now only supplies the adapter's own vocabulary: the
404 -> ``CoreNotFoundError`` / 4xx-5xx -> ``CoreHttpError`` mapping the adapter's
owner-scoped reads rely on.
"""

from __future__ import annotations

from typing import Any

from biffo_plugin_sdk import (
    FORWARDED_USER_HEADER,  # noqa: F401  (re-exported for callers/tests)
    BiffoAPIError,
    PrincipalCoreClient,
)

from .adapter import CoreHttpError, CoreNotFoundError


class CoreTransport(PrincipalCoreClient):
    """A SigV4-signed, user-token-forwarding transport that maps Core's HTTP
    responses to the adapter's contract. Constructed per founder request."""

    def __init__(self, *, founder_token: str, **kwargs: Any) -> None:
        super().__init__(founder_token, **kwargs)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """The adapter's :class:`~ideation.adapter.Transport` seam."""
        try:
            return await self._send(method, path, params=params, json_body=json)
        except BiffoAPIError as exc:
            if exc.status_code == 404:
                raise CoreNotFoundError(f"{method} {path} -> 404") from exc
            raise CoreHttpError(
                f"{method} {path} -> {exc.status_code}: {str(exc.body)[:500]}"
            ) from exc
