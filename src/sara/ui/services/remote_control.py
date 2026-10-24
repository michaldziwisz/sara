"""Cykl życia lokalnego sterowania, powiązany z główną ramką wx."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.remote.commands import CommandSession, app_version
from sara.remote.hold import get_hold_controller
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
    owner = wx.EvtHandler()
    timer = wx.Timer(owner)
    hold = get_hold_controller(frame)
    def sync(event):
        hold.sync()
        owner = getattr(frame, "_remote_mix_owner", None)
        if owner is not None and owner.mix is not None:
            owner.mix.tick()
    owner.Bind(wx.EVT_TIMER, sync, timer)
    frame._remote_hold_timer_owner = owner
    frame._remote_hold_timer = timer
    timer.Start(100)
    logger.info("Remote control listening on 127.0.0.1:%s", port)


def stop_remote_control(frame) -> None:
    owner = getattr(frame, "_remote_mix_owner", None)
    if owner is not None:
        owner.close()
    server = getattr(frame, "_remote_server", None)
    frame._remote_server = None
    if server:
        server.stop()
    timer = getattr(frame, "_remote_hold_timer", None)
    if timer is not None:
        timer.Stop()
        frame._remote_hold_timer_owner.Unbind(wx.EVT_TIMER, source=timer)
        frame._remote_hold_timer = None
        frame._remote_hold_timer_owner = None
    hold = getattr(frame, "_remote_hold", None)
    if hold is not None:
        hold.set_enabled(False)
