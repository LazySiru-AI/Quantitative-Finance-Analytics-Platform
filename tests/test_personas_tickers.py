"""Unit tests for `app.personas.tickers` -- the layered check deciding whether a symbol a model
extracted from an auto-generated transcript is real enough to write into a persona's permanent
memory.

**Nothing here makes a network call.** The `allow_network=False` tests prove that structurally by
monkeypatching `app.market.registry.default_registry` to raise if it is ever reached; the
`allow_network=True` tests never touch it either, because they monkeypatch the module-private
`_confirmed_by_provider` instead, per the module's own note that it is the seam meant for tests.

Every test uses the `settings` fixture from `tests/conftest.py`, which redirects `INVDASH_VAULT_DIR`
and friends into `tmp_path` -- so `_ledger_symbols` always sees "no ledger yet" (an empty, unmigrated
`tmp_path`) rather than the developer's real one.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.personas import tickers as tickers_module
from app.personas.tickers import build_symbol_validator, structurally_plausible

# --- structurally_plausible -------------------------------------------------


def test_structurally_plausible_accepts_real_ticker_shapes() -> None:
    """The four shapes the module docstring names as real: a plain symbol, both class-share
    separator spellings this repo normalises elsewhere, and a genuine single-letter ticker."""
    for symbol in ("NVDA", "BRK.B", "BRK-B", "F"):
        assert structurally_plausible(symbol) is True


def test_structurally_plausible_rejects_empty_and_wrong_shaped_input() -> None:
    """Empty text, a run longer than any real US ticker, and an all-digit token are prose or noise,
    not tickers, and this layer is the cheap, local filter meant to drop them before anything else
    runs."""
    assert structurally_plausible("") is False
    assert structurally_plausible("TOOLONG") is False
    assert structurally_plausible("123") is False


def test_structurally_plausible_strips_and_uppercases_before_matching() -> None:
    """`structurally_plausible` normalises its input before checking the shape, which makes it
    accept things a caller might reflexively expect it to reject.

    Read literally rather than assumed: a trailing space is stripped, so `"nvda "` passes exactly
    like `"NVDA"`. And because the regex only constrains *shape* (letters/digits/length), not
    real-world ticker validity, ordinary short English words that happen to be all-alphabetic and
    five characters or fewer -- `"light"`, `"the"`, `"onthe"` -- pass here too. That is not a bug in
    this function: the module docstring is explicit that structural plausibility is "the only check
    that runs for the overwhelming majority of the garbage an auto-caption produces", with actual
    garbage rejection left to the ledger/universe/provider layers in `build_symbol_validator`. This
    test documents that division of labour so a future reader does not mistake the permissiveness
    here for an oversight.
    """
    assert structurally_plausible("nvda ") is True
    assert structurally_plausible("light") is True
    assert structurally_plausible("the") is True
    assert structurally_plausible("onthe") is True


def test_the_research_universe_layer_actually_contributes_symbols() -> None:
    """A direct guard on the layer that was once silently empty.

    `_universe_symbols()` originally walked `dir(app.evolution.universe)` looking for anything with a
    callable `all_symbols`; the pools live in a module-private dict, so it matched nothing and every
    failure was swallowed by a bare `except`. Nothing observable broke -- symbols just quietly fell
    through to the network layer, or were rejected outright when it was disabled. A behavioural test
    can be satisfied by an accident elsewhere; this asserts the layer itself is alive.
    """
    from app.personas.tickers import _universe_symbols

    symbols = _universe_symbols()
    assert symbols, "the research universe contributed no symbols at all"
    assert "NVDA" in symbols


# --- build_symbol_validator: allow_network=False never touches the network -


def test_allow_network_false_never_reaches_the_provider_registry(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of `allow_network=False` is that the suite (and any other network-free
    caller) can call the validator with zero risk of an HTTP request. Proven here by making the
    provider registry constructor itself an assertion failure -- if the validator ever reached it,
    this test would fail with `AssertionError`, not just an unexpected `True`/`False`."""

    def _must_not_be_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("default_registry() must not be called when allow_network=False")

    monkeypatch.setattr("app.market.registry.default_registry", _must_not_be_called)

    validate = build_symbol_validator(settings, allow_network=False)

    # Both outcomes must be reachable without the registry: an accept resolved by the local layers,
    # and a reject that never escalates. Asserting only the reject would pass just as well if the
    # local layers were dead -- which is exactly the bug this test originally encoded, when
    # `_universe_symbols()` silently returned nothing and AAPL was rejected for the wrong reason.
    assert validate("AAPL") is True, "a researched symbol must resolve from the local universe"
    assert validate("ZZZZQ") is False, "an unknown symbol is rejected, not escalated"


def test_autocaption_garbage_is_rejected_with_network_disallowed(settings: Settings) -> None:
    """The motivating case from the module docstring: an auto-caption turning ordinary words into
    ticker-shaped tokens must not survive into a note. With no network layer to confirm them and an
    empty ledger/universe, `build_symbol_validator` is the layer that actually drops them --
    `structurally_plausible` alone (see above) does not."""
    validate = build_symbol_validator(settings, allow_network=False)
    for garbage in ("light", "the", "onthe"):
        assert validate(garbage) is False


# --- build_symbol_validator: memoisation -------------------------------------


def test_validator_memoises_provider_calls_per_symbol(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transcript naming the same symbol nine times must cost one provider lookup, not nine --
    this is the module docstring's explicit promise. Proven by counting calls to a monkeypatched
    `_confirmed_by_provider` rather than a real provider."""
    calls: list[str] = []

    def _fake_confirmed(settings_: Settings, symbol: str) -> bool:
        calls.append(symbol)
        return True

    monkeypatch.setattr(tickers_module, "_confirmed_by_provider", _fake_confirmed)

    validate = build_symbol_validator(settings, allow_network=True)
    assert validate("zzzz") is True
    assert validate("zzzz") is True
    assert validate("ZZZZ") is True  # same symbol, different case in the caller's raw text
    assert calls == ["ZZZZ"], "the underlying provider check must run exactly once for one symbol"


def test_validator_honours_the_provider_stub_when_network_is_allowed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With `allow_network=True`, a symbol unknown to the ledger and the research universe must be
    accepted or rejected according to whatever the (stubbed) provider says -- this is the
    "interesting case" the module docstring calls out: an influencer naming a stock the user has
    never held is exactly what this layer exists to let through, not reject for being unfamiliar."""
    monkeypatch.setattr(
        tickers_module, "_confirmed_by_provider", lambda settings_, symbol: symbol == "AAAA"
    )

    validate = build_symbol_validator(settings, allow_network=True)
    assert validate("AAAA") is True
    assert validate("BBBB") is False
