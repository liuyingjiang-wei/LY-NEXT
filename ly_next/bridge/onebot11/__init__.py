__all__ = ["attach_onebot_routes"]


def attach_onebot_routes(*routers):
    from ly_next.bridge.onebot11.router import attach_onebot_routes as _attach

    return _attach(*routers)
