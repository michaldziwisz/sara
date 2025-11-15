"""Panel presenting a text-based news playlist with edit/read modes."""

from __future__ import annotations

import re
import ctypes
from pathlib import Path
from typing import Callable, Optional, Sequence

import wx
from wx.lib import scrolledpanel

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistModel
from sara.news_service import NewsService, load_news_service, save_news_service


_AUDIO_TOKEN = re.compile(r"\[\[audio:(.+?)\]\]")
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
_SERVICE_WILDCARD = _("News services (*.saranews)|*.saranews|All files|*.*")


class NewsPlaylistPanel(wx.Panel):
    """Playlist panel that stores markdown text and inline audio clips."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        model: PlaylistModel,
        get_line_length: Callable[[], int],
        get_audio_devices: Callable[[], Sequence[tuple[Optional[str], str]]],
        on_focus: Callable[[str], None],
        on_play_audio: Callable[[Path, str | None], None],
        on_device_change: Callable[[PlaylistModel], None],
        enable_line_length_control: bool = False,
        line_length_bounds: tuple[int, int] = (0, 500),
        on_line_length_change: Callable[[int], None] | None = None,
        on_line_length_apply: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self._get_line_length = get_line_length
        self._get_audio_devices = get_audio_devices
        self._on_focus_request = on_focus
        self._on_play_audio = on_play_audio
        self._on_device_change = on_device_change
        self._line_length_bounds = line_length_bounds
        self._on_line_length_change = on_line_length_change if enable_line_length_control else None
        self._on_line_length_apply = on_line_length_apply if enable_line_length_control else None
        self._mode: str = "edit"
        self._read_text_ctrl: wx.TextCtrl | None = None
        self._heading_lines: list[int] = []
        self._suppress_play_shortcut = False
        self._audio_markers: list[tuple[int, str]] = []
        self._line_length_spin: wx.SpinCtrl | None = None
        self._line_length_apply: wx.Button | None = None
        self._caret_position: int = 0

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)

        self._mode_button = wx.Button(self, label=_("Switch to read mode"))
        self._insert_button = wx.Button(self, label=_("Insert audio from clipboard"))
        self._load_button = wx.Button(self, label=_("Load service…"))
        self._save_button = wx.Button(self, label=_("Save service…"))
        toolbar.Add(self._mode_button, 0, wx.RIGHT, 5)
        toolbar.Add(self._insert_button, 0, wx.RIGHT, 5)
        toolbar.Add(self._load_button, 0, wx.RIGHT, 5)
        toolbar.Add(self._save_button, 0, wx.RIGHT, 5)

        if self._on_line_length_change:
            line_label = wx.StaticText(self, label=_("Line length:"))
            toolbar.Add(line_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            min_len, max_len = self._line_length_bounds
            initial_length = max(min_len, min(max_len, self._get_line_length()))
            self._line_length_spin = wx.SpinCtrl(
                self,
                min=min_len,
                max=max_len or 1000,
                initial=initial_length,
                style=wx.TE_PROCESS_TAB | wx.TE_PROCESS_ENTER,
            )
            self._line_length_spin.Bind(wx.EVT_SPINCTRL, self._handle_line_length_change)
            self._line_length_spin.Bind(wx.EVT_TEXT_ENTER, self._handle_line_length_change)
            self._line_length_spin.Bind(wx.EVT_CHAR_HOOK, self._handle_toolbar_char_hook)
            toolbar.Add(self._line_length_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            self._line_length_apply = wx.Button(self, label=_("Apply"))
            self._line_length_apply.Bind(wx.EVT_BUTTON, self._handle_line_apply)
            self._line_length_apply.Bind(wx.EVT_CHAR_HOOK, self._handle_toolbar_char_hook)
            toolbar.Add(self._line_length_apply, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        device_label = wx.StaticText(self, label=_("Playback device:"))
        toolbar.AddStretchSpacer()
        toolbar.Add(device_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._device_choice = wx.Choice(self)
        toolbar.Add(self._device_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        main_sizer.Add(toolbar, 0, wx.EXPAND | wx.BOTTOM, 5)

        self._title = model.name
        self._edit_ctrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_RICH2 | wx.TE_PROCESS_TAB,
        )
        self._edit_ctrl.SetValue(self.model.news_markdown or "")
        self._edit_ctrl.Bind(wx.EVT_TEXT, self._on_text_changed)
        self._edit_ctrl.Bind(wx.EVT_SET_FOCUS, self._notify_focus)
        self._edit_ctrl.Bind(wx.EVT_CHAR_HOOK, self._handle_char_hook)

        self._read_panel = scrolledpanel.ScrolledPanel(self, style=wx.BORDER_SIMPLE)
        self._read_panel.SetupScrolling(scroll_x=False, scroll_y=True)
        self._read_panel.Hide()
        self._read_panel.Bind(wx.EVT_SET_FOCUS, self._notify_focus)

        main_sizer.Add(self._edit_ctrl, 1, wx.EXPAND)
        main_sizer.Add(self._read_panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        self._mode_button.Bind(wx.EVT_BUTTON, self._toggle_mode)
        self._insert_button.Bind(wx.EVT_BUTTON, self._insert_audio_placeholder)
        self._load_button.Bind(wx.EVT_BUTTON, self._on_load_service)
        self._save_button.Bind(wx.EVT_BUTTON, self._on_save_service)
        self._device_choice.Bind(wx.EVT_CHOICE, self._on_device_selected)

        self._populate_devices()
        self._sync_line_length_spin()
        self._update_mode_ui()
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        header_color = wx.Colour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        inactive_color = wx.Colour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        target = header_color if active else inactive_color
        self._mode_button.SetForegroundColour(target)
        self._insert_button.SetForegroundColour(target)
        self._load_button.SetForegroundColour(target)
        self._save_button.SetForegroundColour(target)
        self._device_choice.SetForegroundColour(target)
        self.Refresh()

    # ------------------------------------------------------------------ public
    def refresh_configuration(self) -> None:
        self._populate_devices()
        self._sync_line_length_spin()
        if self._mode == "read":
            self._render_read_panel()
            self._read_panel.Layout()

    # ----------------------------------------------------------------- helpers
    def _notify_focus(self, event: wx.Event | None = None) -> None:
        self._on_focus_request(self.model.id)
        if event is not None:
            event.Skip()

    def _populate_devices(self) -> None:
        devices = list(self._get_audio_devices())
        selection = 0
        self._device_choice.Clear()
        for idx, (device_id, label) in enumerate(devices):
            self._device_choice.Append(label, clientData=device_id)
            if device_id == (self.model.output_device or (self.model.output_slots[0] if self.model.output_slots else None)):
                selection = idx
        if devices:
            self._device_choice.SetSelection(selection)
            self._device_choice.Enable(True)
        else:
            self._device_choice.Enable(False)
    def _on_device_selected(self, event: wx.CommandEvent) -> None:
        index = event.GetSelection()
        if index == wx.NOT_FOUND:
            return
        device_id = self._device_choice.GetClientData(index)
        device_value = str(device_id) if device_id else None
        self.model.output_device = device_value
        if device_value:
            self.model.set_output_slots([device_value])
        else:
            self.model.set_output_slots([])
        self._on_device_change(self.model)

    def _handle_char_hook(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        target = event.GetEventObject()

        if event.ControlDown() and not event.AltDown():
            if keycode in (ord("E"), ord("e")):
                self._toggle_mode(None)
                event.StopPropagation()
                return
            if keycode in (ord("O"), ord("o")):
                self._on_load_service(None)
                event.StopPropagation()
                return
            if keycode in (ord("S"), ord("s")):
                self._on_save_service(None)
                event.StopPropagation()
                return

        if self._mode == "read":
            focused = wx.Window.FindFocus()
            if focused is self._read_text_ctrl:
                if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
                    if self._activate_audio_marker():
                        event.StopPropagation()
                        return
                if keycode in (ord("H"), ord("h")):
                    direction = -1 if event.ShiftDown() else 1
                    self._focus_heading(direction=direction)
                    event.StopPropagation()
                    return
                if keycode in (ord("C"), ord("c")):
                    direction = -1 if event.ShiftDown() else 1
                    self._focus_audio_marker(direction=direction)
                    event.StopPropagation()
                    return
                if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
                    if self._focus_toolbar_from_text(backwards=event.ShiftDown()):
                        event.StopPropagation()
                        return
            event.Skip()
            return

        if target is not self._edit_ctrl:
            event.Skip()
            return

        if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
            flags = wx.NavigationKeyEvent.IsBackward if event.ShiftDown() else wx.NavigationKeyEvent.IsForward
            self.Navigate(flags)
            return

        if event.ControlDown() and not event.AltDown() and keycode in (ord("V"), ord("v")):
            audio_paths = self._clipboard_audio_paths()
            if audio_paths:
                self._insert_audio_tokens(audio_paths)
                event.StopPropagation()
                return

        if not event.ControlDown() and not event.AltDown() and keycode == wx.WXK_SPACE:
            self._suppress_play_shortcut = True
            self._edit_ctrl.WriteText(" ")
            event.StopPropagation()
            return

        event.Skip()

    def _toggle_mode(self, _event: wx.Event | None) -> None:
        self._remember_caret_position()
        self._mode = "read" if self._mode == "edit" else "edit"
        self._update_mode_ui()

    def _update_mode_ui(self) -> None:
        if self._mode == "edit":
            self._mode_button.SetLabel(_("Switch to read mode"))
            self._read_panel.Hide()
            self._edit_ctrl.Show()
            self.Layout()
            self._restore_caret_position(self._edit_ctrl)
            self._edit_ctrl.SetFocus()
            self._on_focus_request(self.model.id)
        else:
            self._mode_button.SetLabel(_("Switch to edit mode"))
            self._edit_ctrl.Hide()
            self._render_read_panel()
            self._read_panel.Show()
            self.Layout()
            if self._read_text_ctrl:
                self._restore_caret_position(self._read_text_ctrl)
                self._read_text_ctrl.SetFocus()
            else:
                self._read_panel.SetFocus()
            self._on_focus_request(self.model.id)

    def _on_text_changed(self, _event: wx.CommandEvent) -> None:
        self.model.news_markdown = self._edit_ctrl.GetValue()

    def _insert_audio_placeholder(self, _event: wx.Event) -> None:
        audio_paths = self._clipboard_audio_paths()
        if not audio_paths:
            wx.MessageBox(_("Clipboard does not contain audio files."), _("Error"), parent=self)
            return
        self._insert_audio_tokens(audio_paths)

    def _insert_audio_tokens(self, audio_paths: list[str]) -> None:
        placeholders = [f"[[audio:{path}]]" for path in audio_paths]
        insertion_point = self._edit_ctrl.GetInsertionPoint()
        text_to_insert = "\n".join(placeholders)
        self._edit_ctrl.WriteText(text_to_insert)
        self._edit_ctrl.SetInsertionPoint(insertion_point + len(text_to_insert))
        self.model.news_markdown = self._edit_ctrl.GetValue()

    def _on_load_service(self, _event: wx.Event | None) -> None:
        dialog = wx.FileDialog(
            self,
            _("Load news service"),
            wildcard=_SERVICE_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        path = Path(dialog.GetPath())
        dialog.Destroy()
        try:
            service = load_news_service(path)
        except Exception as exc:  # pylint: disable=broad-except
            self._show_error(_("Failed to load news service: %s") % exc)
            return
        self._apply_service(service)

    def _on_save_service(self, _event: wx.Event | None) -> None:
        dialog = wx.FileDialog(
            self,
            _("Save news service"),
            wildcard=_SERVICE_WILDCARD,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        raw_path = Path(dialog.GetPath())
        dialog.Destroy()
        if raw_path.suffix.lower() != ".saranews":
            target_path = raw_path.with_suffix(".saranews")
        else:
            target_path = raw_path
        service = NewsService(
            title=self.model.name,
            markdown=self.model.news_markdown or self._edit_ctrl.GetValue(),
            output_device=self.model.output_device,
            line_length=self._get_line_length(),
        )
        try:
            save_news_service(target_path, service)
        except Exception as exc:  # pylint: disable=broad-except
            self._show_error(_("Failed to save news service: %s") % exc)

    def _apply_service(self, service: NewsService) -> None:
        markdown = service.markdown or ""
        self.model.news_markdown = markdown
        self._edit_ctrl.ChangeValue(markdown)
        if service.output_device is not None:
            self.model.output_device = service.output_device or None
            self._populate_devices()
        if self._mode == "read":
            self._render_read_panel()
            self._read_panel.Layout()

    def _show_error(self, message: str) -> None:
        wx.MessageBox(message, _("Error"), parent=self)

    def _normalize_line_length(self, value: int) -> int:
        minimum, maximum = self._line_length_bounds
        normalized = max(minimum, value)
        if maximum > minimum:
            normalized = min(normalized, maximum)
        return normalized

    def _sync_line_length_spin(self) -> None:
        if self._line_length_spin:
            self._line_length_spin.SetValue(self._normalize_line_length(self._get_line_length()))

    def _handle_line_length_change(self, _event: wx.Event | None) -> None:
        if not self._line_length_spin or not self._on_line_length_change:
            return
        value = self._normalize_line_length(self._line_length_spin.GetValue())
        self._line_length_spin.SetValue(value)
        self._on_line_length_change(value)
        self.refresh_configuration()

    def _handle_line_apply(self, _event: wx.Event) -> None:
        self._handle_line_length_change(None)
        if self._on_line_length_apply:
            self._on_line_length_apply()

    def _toolbar_focusables(self) -> list[wx.Window]:
        controls: list[wx.Window] = [
            self._mode_button,
            self._insert_button,
            self._load_button,
            self._save_button,
        ]
        if self._line_length_spin:
            controls.append(self._line_length_spin)
        if self._line_length_apply:
            controls.append(self._line_length_apply)
        controls.append(self._device_choice)
        return [ctrl for ctrl in controls if ctrl and ctrl.IsShown() and ctrl.IsEnabled()]

    def _focus_toolbar_from_text(self, *, backwards: bool) -> bool:
        controls = self._toolbar_focusables()
        if not controls:
            return False
        self._update_caret_from_read()
        target = controls[-1] if backwards else controls[0]
        target.SetFocus()
        return True

    def _handle_toolbar_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
            backwards = event.ShiftDown()
            if self._move_within_toolbar(event.GetEventObject(), backwards=backwards):
                return
        event.Skip()

    def _move_within_toolbar(self, current: wx.Window, *, backwards: bool) -> bool:
        controls = self._toolbar_focusables()
        if not controls:
            return False
        try:
            index = controls.index(current)
        except ValueError:
            return False
        if backwards:
            next_index = (index - 1) % len(controls)
        else:
            next_index = (index + 1) % len(controls)
        controls[next_index].SetFocus()
        return True

    def get_selected_device_id(self) -> str | None:
        selection = self._device_choice.GetSelection()
        if selection == wx.NOT_FOUND:
            return None
        data = self._device_choice.GetClientData(selection)
        return str(data) if data else None

    def _remember_caret_position(self) -> None:
        if self._mode == "edit":
            self._caret_position = self._edit_ctrl.GetInsertionPoint()
        elif self._read_text_ctrl:
            self._caret_position = self._read_text_ctrl.GetInsertionPoint()

    def _restore_caret_position(self, ctrl: wx.TextCtrl | None) -> None:
        if ctrl is None:
            return
        length = ctrl.GetLastPosition()
        position = max(0, min(self._caret_position, length))
        ctrl.SetInsertionPoint(position)
        ctrl.ShowPosition(position)

    def _update_caret_from_read(self) -> None:
        if self._read_text_ctrl:
            self._caret_position = self._read_text_ctrl.GetInsertionPoint()

    def focus_default(self) -> None:
        """Set focus to the active control depending on mode."""
        if self._mode == "edit":
            self._edit_ctrl.SetFocus()
        else:
            if self._read_text_ctrl is None:
                self._render_read_panel()
            if self._read_text_ctrl:
                self._read_text_ctrl.SetFocus()
            else:
                self._read_panel.SetFocus()
        self._on_focus_request(self.model.id)

    def _clipboard_audio_paths(self) -> list[str]:
        candidates = self._collect_clipboard_strings()
        win32_candidates = self._collect_win32_file_drops()
        if win32_candidates:
            candidates.extend(win32_candidates)
        if not candidates:
            return []

        audio_files: list[str] = []

        def collect_from_path(path_str: str) -> None:
            target = Path(path_str.replace("\\\\?\\", "")).expanduser()
            if not target.exists():
                return
            if target.is_dir():
                for file_path in sorted(target.rglob("*")):
                    if file_path.is_file() and file_path.suffix.lower() in _AUDIO_EXTENSIONS:
                        audio_files.append(str(file_path))
                return
            if target.suffix.lower() in _AUDIO_EXTENSIONS:
                audio_files.append(str(target))

        for candidate in candidates:
            collect_from_path(candidate)

        return audio_files

    def _collect_clipboard_strings(self) -> list[str]:
        clipboard = wx.TheClipboard
        if not clipboard.Open():
            return []
        candidates: list[str] = []
        try:
            file_data = wx.FileDataObject()
            if clipboard.GetData(file_data):
                candidates.extend(file_data.GetFilenames())
            text_data = wx.TextDataObject()
            if clipboard.GetData(text_data):
                for raw_entry in text_data.GetText().splitlines():
                    entry = raw_entry.strip().strip('"')
                    if entry:
                        candidates.append(entry)
        finally:
            clipboard.Close()
        return candidates

    def _collect_win32_file_drops(self) -> list[str]:
        if not hasattr(ctypes, "windll"):
            return []
        CF_HDROP = 15
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        if not user32.OpenClipboard(0):
            return []
        filenames: list[str] = []
        try:
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return []
            hdrop = user32.GetClipboardData(CF_HDROP)
            if not hdrop:
                return []
            handle = ctypes.c_void_p(hdrop)
            try:
                count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            except OSError:
                return []
            for index in range(count):
                try:
                    length = shell32.DragQueryFileW(handle, index, None, 0) + 1
                except OSError:
                    continue
                buffer = (ctypes.c_wchar * length)()
                try:
                    success = shell32.DragQueryFileW(handle, index, buffer, length)
                except OSError:
                    success = 0
                if success:
                    filenames.append(buffer.value)
        finally:
            user32.CloseClipboard()
        return filenames

    # ------------------------------ rendering -------------------------------
    def _render_read_panel(self) -> None:
        wrapper = wx.BoxSizer(wx.VERTICAL)
        for child in self._read_panel.GetChildren():
            child.Destroy()
        self._read_text_ctrl = None
        self._heading_lines = []
        self._audio_markers = []

        blocks = self._parse_blocks(self.model.news_markdown or "")
        line_length = self._get_line_length()
        article_lines: list[str] = []
        audio_entries: list[str] = []

        for block in blocks:
            btype = block["type"]
            if btype in {"paragraph", "list", "heading"}:
                text = block["text"]
                prefix = ""
                if btype == "list":
                    prefix = "- "
                if btype == "heading":
                    prefix = "#" * block["level"] + " "
                    self._heading_lines.append(len(article_lines))
                lines = self._wrap_text(prefix + text, line_length)
                if article_lines and article_lines[-1] != "":
                    article_lines.append("")
                article_lines.extend(lines)
            elif btype == "audio":
                filename = Path(block["path"]).name
                line_index = len(article_lines)
                article_lines.append(_("(Audio clip: %s)") % filename)
                self._audio_markers.append((line_index, block["path"]))
                audio_entries.append(block["path"])
            if article_lines and article_lines[-1] != "":
                article_lines.append("")

        if article_lines and article_lines[-1] == "":
            article_lines.pop()

        if article_lines:
            text_value = "\n".join(article_lines)
        else:
            text_value = _("No content. Switch to edit mode to add text.")

        self._read_text_ctrl = wx.TextCtrl(
            self._read_panel,
            value=text_value,
            style=wx.TE_READONLY | wx.TE_MULTILINE | wx.BORDER_NONE | wx.TE_PROCESS_TAB,
        )
        self._read_text_ctrl.Bind(wx.EVT_SET_FOCUS, self._notify_focus)
        self._read_text_ctrl.Bind(wx.EVT_CHAR_HOOK, self._handle_char_hook)
        self._read_text_ctrl.Bind(wx.EVT_KEY_DOWN, self._handle_read_key)
        wrapper.Add(self._read_text_ctrl, 1, wx.EXPAND | wx.ALL, 4)

        for index, path in enumerate(audio_entries, start=1):
            filename = Path(path).name
            button = wx.Button(self._read_panel, label=_("Play audio %d: %s") % (index, filename))
            button.Bind(wx.EVT_BUTTON, lambda evt, clip=path: self._play_clip(clip))
            wrapper.Add(button, 0, wx.ALL, 4)

        self._read_panel.SetSizer(wrapper)
        self._read_panel.SetupScrolling(scroll_x=False, scroll_y=True)
        self._restore_caret_position(self._read_text_ctrl)

    def _activate_audio_marker(self) -> bool:
        if not self._read_text_ctrl or not self._audio_markers:
            return False
        pos = self._read_text_ctrl.GetInsertionPoint()
        success, _, line_index = self._read_text_ctrl.PositionToXY(pos)
        if not success:
            return False
        for marker_line, path in self._audio_markers:
            if marker_line == line_index:
                self._play_clip(path)
                return True
        return False

    def _handle_read_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            if self._activate_audio_marker():
                event.StopPropagation()
                return
        if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
            flags = wx.NavigationKeyEvent.IsBackward if event.ShiftDown() else wx.NavigationKeyEvent.IsForward
            self.Navigate(flags)
            return
        event.Skip()

    def _focus_heading(self, *, direction: int) -> None:
        if not self._heading_lines or not self._read_text_ctrl:
            return
        pos = self._read_text_ctrl.GetInsertionPoint()
        success, _, current_line = self._read_text_ctrl.PositionToXY(pos)
        if not success:
            current_line = -1
        candidate = None
        if direction > 0:
            for line in self._heading_lines:
                if line > current_line:
                    candidate = line
                    break
        else:
            for line in reversed(self._heading_lines):
                if line < current_line:
                    candidate = line
                    break
        if candidate is None:
            return
        pos_target = self._read_text_ctrl.XYToPosition(0, candidate)
        if pos_target != wx.NOT_FOUND:
            self._read_text_ctrl.SetInsertionPoint(pos_target)
            self._read_text_ctrl.ShowPosition(pos_target)
            self._read_text_ctrl.SetFocus()
            self._update_caret_from_read()

    def _focus_audio_marker(self, *, direction: int) -> None:
        if not self._audio_markers or not self._read_text_ctrl:
            return
        pos = self._read_text_ctrl.GetInsertionPoint()
        success, _, current_line = self._read_text_ctrl.PositionToXY(pos)
        if not success:
            current_line = -1 if direction > 0 else 10**9
        lines = [line for line, _ in self._audio_markers]
        candidate = None
        if direction > 0:
            for line in lines:
                if line > current_line:
                    candidate = line
                    break
        else:
            for line in reversed(lines):
                if line < current_line:
                    candidate = line
                    break
        if candidate is None:
            return
        pos_target = self._read_text_ctrl.XYToPosition(0, candidate)
        if pos_target != wx.NOT_FOUND:
            self._read_text_ctrl.SetInsertionPoint(pos_target)
            self._read_text_ctrl.ShowPosition(pos_target)
            self._read_text_ctrl.SetFocus()
            self._update_caret_from_read()

    def _play_clip(self, path_str: str) -> None:
        device_id = self.model.output_device or (self.model.output_slots[0] if self.model.output_slots else None)
        self._on_play_audio(Path(path_str), device_id)

    def _wrap_text(self, text: str, line_length: int) -> list[str]:
        if line_length <= 0:
            return [text]
        segments = text.split("\n")
        lines: list[str] = []
        for segment in segments:
            lines.extend(self._wrap_segment(segment, line_length))
        return lines or [""]

    def _wrap_segment(self, text: str, line_length: int) -> list[str]:
        if not text:
            return [""]
        words = text.split()
        if not words:
            return [""]
        wrapped: list[str] = []
        current = words[0]
        for word in words[1:]:
            tentative = f"{current} {word}"
            if len(tentative) <= line_length:
                current = tentative
            else:
                wrapped.append(current)
                if len(word) > line_length:
                    wrapped.append(word)
                    current = ""
                else:
                    current = word
        if current:
            wrapped.append(current)
        return wrapped

    def _parse_blocks(self, text: str) -> list[dict[str, object]]:
        lines = text.splitlines()
        blocks: list[dict[str, object]] = []
        paragraph: list[str] = []

        def flush_paragraph() -> None:
            if paragraph:
                blocks.append({"type": "paragraph", "text": "\n".join(paragraph)})
                paragraph.clear()

        for raw_line in lines:
            stripped = raw_line.strip()
            audio_match = _AUDIO_TOKEN.fullmatch(stripped)
            if audio_match:
                flush_paragraph()
                blocks.append({"type": "audio", "path": audio_match.group(1)})
                continue
            if not stripped:
                flush_paragraph()
                continue
            heading_match = re.match(r"^(#{1,5})\s+(.*)", stripped)
            if heading_match:
                flush_paragraph()
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                blocks.append({"type": "heading", "text": text, "level": level})
                continue
            if stripped.startswith(("- ", "* ")):
                flush_paragraph()
                blocks.append({"type": "list", "text": stripped[2:].strip()})
                continue
            paragraph.append(stripped)

        flush_paragraph()
        return blocks

    def consume_space_shortcut(self) -> bool:
        if self._suppress_play_shortcut:
            self._suppress_play_shortcut = False
            return True
        return False

    def contains_window(self, window: wx.Window | None) -> bool:
        current = window
        while current:
            if current is self:
                return True
            current = current.GetParent()
        return False

    def is_edit_control(self, window: wx.Window | None) -> bool:
        return window is self._edit_ctrl
