# Lazy imports to avoid triggering pystray/PIL at module load time
# (pystray fails on headless systems without a display)

__all__ = ["TrayApp", "ToastWindow", "DiffWindow", "create_tray_icon"]


def __getattr__(name):
    if name in __all__:
        from . import app as _app
        return getattr(_app, name)
    raise AttributeError(f"module 'tray' has no attribute {name!r}")
