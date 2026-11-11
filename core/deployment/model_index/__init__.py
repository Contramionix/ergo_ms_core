"""Verified local model references over existing provider installers."""

__all__ = ['ModelIndexError', 'build_index', 'install_models', 'resolve_local_model', 'write_index']


def __getattr__(name):
    if name in __all__:
        from . import registry
        return getattr(registry, name)
    raise AttributeError(name)
