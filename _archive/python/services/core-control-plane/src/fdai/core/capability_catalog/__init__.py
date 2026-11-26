"""Capability catalog (SRE-agent slide 20).

A customer-agnostic registry of control-plane capabilities the read-only
console renders so operators can discover what FDAI can do, each entry's
safety class, and its default autonomy mode. Listing a capability grants no
execution eligibility - the entries are inert metadata.
"""

from __future__ import annotations

from fdai.core.capability_catalog.catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    CapabilityParity,
    DuplicateCapabilityError,
    SideEffectClass,
)
from fdai.core.capability_catalog.defaults import default_capability_catalog
from fdai.core.capability_catalog.extensions import (
    ExtensionLifecycleError,
    ExtensionManager,
    ExtensionManifest,
    ExtensionPackage,
    ExtensionState,
    ExtensionTrustVerifier,
    InstalledExtension,
)
from fdai.core.capability_catalog.runtime import (
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityReferences,
    CapabilityRuntime,
    CapabilityRuntimeError,
    ResolvedCapability,
    build_capability_references,
)

__all__ = [
    "Capability",
    "CapabilityCatalog",
    "CapabilityCategory",
    "CapabilityParity",
    "CapabilityBinding",
    "CapabilityBindingKind",
    "CapabilityBundle",
    "CapabilityReferences",
    "CapabilityRuntime",
    "CapabilityRuntimeError",
    "DuplicateCapabilityError",
    "ExtensionLifecycleError",
    "ExtensionManager",
    "ExtensionManifest",
    "ExtensionPackage",
    "ExtensionState",
    "ExtensionTrustVerifier",
    "InstalledExtension",
    "ResolvedCapability",
    "SideEffectClass",
    "default_capability_catalog",
    "build_capability_references",
]
