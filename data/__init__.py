"""Shipped JSON manifests (installer registry, scanner profiles, devices).

This package exists so ``pip install`` places the bundled ``*.json`` files
at ``<site-packages>/data/``, where the runtime resolves them via
``Path(__file__).resolve().parents[1] / "data"`` (see
``core.uniden_tools`` and ``scanner_profiles.registry``). It is a data
container, not an importable API — nothing should ``import data``.
"""
