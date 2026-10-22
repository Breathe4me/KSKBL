"""Verified HTTPS using Windows' trusted roots in addition to Requests' CA bundle."""

import os
import ssl

import requests


class WindowsTrustAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().proxy_manager_for(proxy, **kwargs)


def canvas_session():
    session = requests.Session()
    if os.name == "nt":
        session.mount("https://", WindowsTrustAdapter())
    return session
