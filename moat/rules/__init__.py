"""Rule registry.

Rules are plain functions that take a parsed :class:`Target` and yield
:class:`Finding` objects. Registration is by decorator so adding a check never
means editing a central list.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Callable

from ..models import Finding, Rule, Target

REGISTRY: list[Rule] = []
#: Rules that need the whole project at once, not one file at a time. The
#: interesting risks in agent config are combinations across files, and a
#: per-file rule structurally cannot see them.
PROJECT_REGISTRY: list[Rule] = []

CheckFn = Callable[[Target], Iterator[Finding]]


def rule(rule_id: str, name: str, kinds: tuple[str, ...]) -> Callable[[CheckFn], CheckFn]:
    def decorate(func: CheckFn) -> CheckFn:
        REGISTRY.append(Rule(id=rule_id, name=name, kinds=kinds, check=func))
        return func

    return decorate


def project_rule(rule_id: str, name: str) -> Callable[..., Any]:
    def decorate(func):
        PROJECT_REGISTRY.append(Rule(id=rule_id, name=name, kinds=("*",), check=func))
        return func

    return decorate


def load_all() -> list[Rule]:
    """Import every rule module once and return the populated registry."""
    from . import hooks, injection, permissions, secrets, supply_chain, trifecta  # noqa: F401

    return REGISTRY


def load_project_rules() -> list[Rule]:
    load_all()
    return PROJECT_REGISTRY
