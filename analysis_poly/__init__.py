__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from .web import app

        return app
    raise AttributeError(name)
