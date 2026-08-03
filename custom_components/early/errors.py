"""Turning EARLY API errors into messages a user can act on."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from homeassistant.exceptions import HomeAssistantError

from .api import EarlyConflictError, EarlyError
from .const import DOMAIN


@contextmanager
def translated_errors(
    failure_key: str, *, conflict_key: str | None = None
) -> Iterator[None]:
    """Report a failed EARLY call as a Home Assistant error.

    A 409 means different things per endpoint, so only callers that know what
    the clash is about pass conflict_key; everyone else falls back to relaying
    EARLY's own wording.
    """
    try:
        yield
    except EarlyConflictError as err:
        if conflict_key is None:
            raise _failure(failure_key, err) from err
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key=conflict_key
        ) from err
    except EarlyError as err:
        raise _failure(failure_key, err) from err


def _failure(key: str, err: EarlyError) -> HomeAssistantError:
    """Build the generic error that relays what EARLY said."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"error": str(err)},
    )
