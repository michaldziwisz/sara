"""Dialog for reporting bugs/suggestions via Sygnalista (GitHub issues proxy)."""

from __future__ import annotations

import logging
import os
import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

import wx

from sara.core.i18n import gettext as _
from sara.ui.services.accessibility import apply_accessible_label
from sygnalista_reporter import ReportError, send_report

ReportKind = Literal["bug", "suggestion"]

_DEFAULT_SYGNALISTA_BASE_URL = "https://sygnalista.michaldziwisz.workers.dev"


def _resolve_base_url() -> str:
    for key in ("SARA_SYGNALISTA_URL", "SYGNALISTA_BASE_URL", "SYGNALISTA_URL"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return _DEFAULT_SYGNALISTA_BASE_URL


def _resolve_app_token() -> str:
    for key in ("SARA_SYGNALISTA_APP_TOKEN", "SYGNALISTA_APP_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def _detect_log_path() -> Path | None:
    candidates: list[Path] = []
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                path = Path(handler.baseFilename)
            except Exception:  # noqa: BLE001
                continue
            if path.exists() and path.is_file():
                candidates.append(path)

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _app_version() -> str:
    try:
        return version("sara")
    except PackageNotFoundError:
        return "0.0.0"


class FeedbackDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title=_("Send feedback"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("feedback_dialog")

        self._sending = False
        self._base_url = _resolve_base_url()
        self._app_token = _resolve_app_token()
        self._default_log_path = _detect_log_path()

        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        self._kind = wx.RadioBox(
            panel,
            label=_("Category"),
            choices=[_("Bug report"), _("Suggestion")],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        apply_accessible_label(self._kind, _("Category"))

        title_label = wx.StaticText(panel, label=_("Title"))
        self._title = wx.TextCtrl(panel)
        apply_accessible_label(self._title, _("Title"))

        description_label = wx.StaticText(panel, label=_("Description"))
        self._description = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 160))
        apply_accessible_label(self._description, _("Description"))

        email_label = wx.StaticText(panel, label=_("Email (optional)"))
        self._email = wx.TextCtrl(panel)
        apply_accessible_label(self._email, _("Email (optional)"))

        warning = wx.StaticText(
            panel,
            label=_("If you provide an email, it will be visible publicly on GitHub."),
        )
        warning.Wrap(520)

        self._include_logs = wx.CheckBox(panel, label=_("Attach log file"))
        self._log_path = wx.TextCtrl(panel)
        browse = wx.Button(panel, label=_("Browse…"))
        browse.Bind(wx.EVT_BUTTON, self._on_browse_log)
        apply_accessible_label(self._include_logs, _("Attach log file"))
        apply_accessible_label(self._log_path, _("Log file"))
        apply_accessible_label(browse, _("Browse…"))

        if self._default_log_path is not None:
            self._log_path.SetValue(str(self._default_log_path))
            self._include_logs.SetValue(True)
        else:
            self._include_logs.SetValue(False)

        self._status = wx.StaticText(panel, label="")

        form = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        form.AddGrowableCol(1, proportion=1)

        form.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self._title, 1, wx.EXPAND)

        form.Add(description_label, 0, wx.ALIGN_TOP)
        form.Add(self._description, 1, wx.EXPAND)

        form.Add(email_label, 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self._email, 1, wx.EXPAND)

        form.Add(wx.StaticText(panel, label=""), 0)
        form.Add(warning, 1, wx.EXPAND)

        log_row = wx.BoxSizer(wx.HORIZONTAL)
        log_row.Add(self._log_path, 1, wx.EXPAND)
        log_row.Add(browse, 0, wx.LEFT, 8)

        form.Add(self._include_logs, 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(log_row, 1, wx.EXPAND)

        root.Add(self._kind, 0, wx.EXPAND | wx.ALL, 12)
        root.Add(form, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        root.Add(self._status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        btns = wx.StdDialogButtonSizer()
        self._send_btn = wx.Button(panel, wx.ID_OK, _("Send"))
        self._cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btns.AddButton(self._send_btn)
        btns.AddButton(self._cancel_btn)
        btns.Realize()
        root.Add(btns, 0, wx.EXPAND | wx.ALL, 12)

        panel.SetSizer(root)
        root.Fit(self)
        self.SetMinSize((520, 520))

        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)

        self.CentreOnParent()

    def _on_browse_log(self, _evt: wx.CommandEvent) -> None:
        default_path = Path(self._log_path.GetValue()) if self._log_path.GetValue().strip() else None
        default_dir = str(default_path.parent) if default_path and default_path.parent.exists() else ""
        wildcard = _("Log files (*.log;*.txt;*.gz)|*.log;*.txt;*.gz|All files|*.*")
        dlg = wx.FileDialog(
            self,
            message=_("Select a log file"),
            defaultDir=default_dir,
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            self._log_path.SetValue(dlg.GetPath())
            self._include_logs.SetValue(True)
        finally:
            dlg.Destroy()

    def _set_sending(self, sending: bool) -> None:
        self._sending = sending
        for ctrl in (
            self._kind,
            self._title,
            self._description,
            self._email,
            self._include_logs,
            self._log_path,
            self._send_btn,
            self._cancel_btn,
        ):
            ctrl.Enable(not sending)
        self._status.SetLabel(_("Sending…") if sending else "")

    def _on_send(self, _evt: wx.CommandEvent) -> None:
        if self._sending:
            return

        base_url = _resolve_base_url()
        if not base_url:
            wx.MessageBox(
                _("Sygnalista is not configured. Set SARA_SYGNALISTA_URL or SYGNALISTA_BASE_URL."),
                _("Error"),
                parent=self,
                style=wx.ICON_ERROR,
            )
            return

        title = self._title.GetValue().strip()
        if not title:
            wx.MessageBox(_("Title is required."), _("Error"), parent=self, style=wx.ICON_ERROR)
            return

        description = self._description.GetValue().strip()
        if not description:
            wx.MessageBox(_("Description is required."), _("Error"), parent=self, style=wx.ICON_ERROR)
            return

        email = self._email.GetValue().strip() or None

        kind: ReportKind = "bug" if self._kind.GetSelection() == 0 else "suggestion"

        log_path = None
        if self._include_logs.GetValue():
            value = self._log_path.GetValue().strip()
            log_path = value or None

        diagnostics_extra: dict[str, Any] = {
            "wx": {"platform": wx.Platform},
        }

        self._set_sending(True)

        thread = threading.Thread(
            target=self._send_worker,
            kwargs={
                "base_url": base_url,
                "kind": kind,
                "title": title,
                "description": description,
                "email": email,
                "log_path": log_path,
                "diagnostics_extra": diagnostics_extra,
            },
            daemon=True,
        )
        thread.start()

    def _send_worker(
        self,
        *,
        base_url: str,
        kind: ReportKind,
        title: str,
        description: str,
        email: str | None,
        log_path: str | None,
        diagnostics_extra: dict[str, Any],
    ) -> None:
        try:
            result = send_report(
                base_url=base_url,
                app_id="sara",
                app_version=_app_version(),
                kind=kind,
                title=title,
                description=description,
                email=email,
                log_path=log_path,
                app_token=self._app_token or None,
                diagnostics_extra=diagnostics_extra,
            )
        except ReportError as err:
            wx.CallAfter(self._on_error, _("Request failed"), f"HTTP {err.status}\n{err.payload!r}")
            return
        except Exception as err:  # noqa: BLE001
            wx.CallAfter(self._on_error, _("Request failed"), str(err))
            return

        wx.CallAfter(self._on_success, result)

    def _on_success(self, result: Any) -> None:
        self._set_sending(False)
        issue_url = None
        try:
            issue_url = (result or {}).get("issue", {}).get("html_url")
        except Exception:  # noqa: BLE001
            issue_url = None

        if issue_url:
            wx.MessageBox(
                _("Created GitHub issue:\n%s") % issue_url,
                _("Thank you"),
                parent=self,
                style=wx.ICON_INFORMATION,
            )
        else:
            wx.MessageBox(_("Report sent."), _("Thank you"), parent=self, style=wx.ICON_INFORMATION)

        self.EndModal(wx.ID_OK)

    def _on_error(self, title: str, message: str) -> None:
        self._set_sending(False)
        wx.MessageBox(message, title, parent=self, style=wx.ICON_ERROR)
