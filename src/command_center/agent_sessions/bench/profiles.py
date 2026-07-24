"""Discovery and coverage checks for harness-owned bench profiles."""
from __future__ import annotations

import importlib
import inspect
import pkgutil

from .. import adapters
from ..fake_harness import FakeHarness
from ..registry import HarnessRegistry
from .models import BenchProfile


def discover_bench_profiles() -> dict[str, BenchProfile]:
    """Discover profiles; adapter imports remain offline-safe and SDK-lazy."""
    harness_classes: list[type] = [FakeHarness]
    for module_info in pkgutil.iter_modules(adapters.__path__):
        module = importlib.import_module(f"{adapters.__name__}.{module_info.name}")
        harness_classes.extend(
            cls for _, cls in inspect.getmembers(module, inspect.isclass)
            if cls.__module__ == module.__name__ and hasattr(cls, "bench_profile")
        )

    profiles: dict[str, BenchProfile] = {}
    for harness_class in harness_classes:
        profile = getattr(harness_class, "bench_profile", None)
        if not isinstance(profile, BenchProfile):
            raise TypeError(f"{harness_class.__name__} has no typed BenchProfile")
        if profile.adapter != getattr(harness_class, "name", None):
            raise ValueError(
                f"{harness_class.__name__} profile adapter {profile.adapter!r} "
                f"does not match harness name {getattr(harness_class, 'name', None)!r}")
        if profile.adapter in profiles:
            raise ValueError(f"duplicate BenchProfile for {profile.adapter!r}")
        profiles[profile.adapter] = profile
    return profiles


def assert_profile_registry_coverage(
    registry: HarnessRegistry,
    profiles: dict[str, BenchProfile] | None = None,
) -> None:
    declared = set((profiles or discover_bench_profiles()).keys())
    registered = {descriptor.harness_id for descriptor in registry.descriptors()}
    if declared != registered:
        missing = sorted(registered - declared)
        orphaned = sorted(declared - registered)
        raise ValueError(
            f"BenchProfile/registry mismatch: missing={missing}, orphaned={orphaned}")
