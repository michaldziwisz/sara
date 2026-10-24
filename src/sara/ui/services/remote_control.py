"""Cykl życia lokalnego sterowania, powiązany z główną ramką wx."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.remote.commands import CommandSession, app_version
from sara.remote.server import MainThreadDispatcher, RemoteServer


logger = logging.getLogger(__name__)


def configure_remote_control(frame) -> None:
    enabled = frame._settings.get_remote_enabled()
    port = frame._settings.get_remote_port()
    current = getattr(frame, "_remote_server", None)
    if current and enabled and current.address[1] == port:
        return
    stop_remote_control(frame)
    if not enabled:
        return
    dispatcher = MainThreadDispatcher(wx.CallAfter)
    program_version = app_version()
    try:
        server = RemoteServer(
            dispatcher,
            lambda: CommandSession(frame, program_version=program_version),
            port=port,
        )
        server.start()
    except OSError as exc:
        dispatcher.close()
        logger.warning("Remote control could not bind 127.0.0.1:%s: %s", port, exc)
        frame._announce_event("general", _("Remote control unavailable on port %d") % port)
        return
    frame._remote_server = server
    logger.info("Remote control listening on 127.0.0.1:%s", port)


def stop_remote_control(frame) -> None:
    server = getattr(frame, "_remote_server", None)
    frame._remote_server = None
    if server:
        server.stop()
