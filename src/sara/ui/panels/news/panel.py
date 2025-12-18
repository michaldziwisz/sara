"""Panel presenting a text-based news playlist with edit/read modes."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence

import wx
from wx.lib import scrolledpanel

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistModel
from sara.news.clipboard import clipboard_audio_paths
from sara.news.service_manager import NewsServiceManager
from sara.news_service import NewsService
from sara.ui.news_mode_controller import NewsEditController, NewsReadController

from .service_io import NewsServiceIO


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
        service_manager: NewsServiceManager | None = None,
        on_preview_audio: Callable[[Path], bool] | None = None,
        on_stop_preview_audio: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.SetName(model.name)
        self.model = model
        self._get_line_length = get_line_length
        self._get_audio_devices = get_audio_devices
        self._on_focus_request = on_focus
        self._on_play_audio = on_play_audio
        self._on_device_change = on_device_change
        self._on_preview_audio = on_preview_audio
        self._on_stop_preview_audio = on_stop_preview_audio
        self._line_length_bounds = line_length_bounds
        self._on_line_length_change = on_line_length_change if enable_line_length_control else None
        self._on_line_length_apply = on_line_length_apply if enable_line_length_control else None
        self._mode: str = "edit"
        self._read_text_ctrl: wx.TextCtrl | None = None
        self._suppress_play_shortcut = False
        self._line_length_spin: wx.SpinCtrl | None = None
        self._line_length_apply: wx.Button | None = None
        self._caret_position: int = 0
        self._service_manager = service_manager or NewsServiceManager(error_handler=self._show_error)
        self._service_io = NewsServiceIO(
            self,
            self._service_manager,
            apply_service=self._apply_service,
            build_service=self._build_service,
        )
        self._read_controller = NewsReadController(get_line_length)

        self._title = model.name
        self._edit_ctrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_RICH2 | wx.TE_PROCESS_TAB,
        )
        self._edit_ctrl.SetValue(self.model.news_markdown or "")
        self._edit_ctrl.Bind(wx.EVT_TEXT, self._on_text_changed)
        self._edit_ctrl.Bind(wx.EVT_SET_FOCUS, self._notify_focus)
        self._edit_ctrl.Bind(wx.EVT_CHAR_HOOK, self._handle_char_hook)
        self._edit_controller = NewsEditController(
            self._edit_ctrl,
            clipboard_reader=clipboard_audio_paths,
            insert_audio_tokens=self._insert_audio_tokens,
            show_error=self._show_error,
            start_preview=self._on_preview_audio,
            stop_preview=self._stop_preview_audio,
        )

        self._read_panel = scrolledpanel.ScrolledPanel(self, style=wx.BORDER_SIMPLE)
        self._read_panel.SetupScrolling(scroll_x=False, scroll_y=True)
        self._read_panel.Hide()
        self._read_panel.Bind(wx.EVT_SET_FOCUS, self._notify_focus)
        self.Bind(wx.EVT_WINDOW_DESTROY, lambda _evt: self._stop_preview_audio())

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

        main_sizer.Add(self._edit_ctrl, 1, wx.EXPAND)
        main_sizer.Add(self._read_panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        for button, handler in (
            (self._mode_button, self._toggle_mode),
            (self._insert_button, self._insert_audio_placeholder),
            (self._load_button, self._on_load_service),
            (self._save_button, self._on_save_service),
        ):
            button.Bind(wx.EVT_BUTTON, handler)
            button.Bind(wx.EVT_CHAR_HOOK, self._handle_toolbar_char_hook)
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
            if keycode in (ord("P"), ord("p")):
                if event.ShiftDown():
                    self._edit_controller.stop_preview()
                else:
                    self._edit_controller.preview_audio_at_caret()
                event.StopPropagation()
                return

        if self._mode == "read":
            focused = wx.Window.FindFocus()
            if focused is self._read_text_ctrl:
                if self._handle_read_action(event):
                    event.StopPropagation()
                    return
                if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
                    if event.ShiftDown():
                        self.Navigate(wx.NavigationKeyEvent.IsBackward)
                    else:
                        if self._focus_toolbar_from_text(backwards=False):
                            event.StopPropagation()
                            return
                    event.StopPropagation()
                    return
            event.Skip()
            return

        if target is not self._edit_ctrl:
            event.Skip()
            return

        if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
            if event.ShiftDown():
                self.Navigate(wx.NavigationKeyEvent.IsBackward)
            else:
                if self._focus_toolbar_from_text(backwards=False):
                    event.StopPropagation()
                    return
            event.StopPropagation()
            return

        if event.ControlDown() and not event.AltDown() and keycode in (ord("V"), ord("v")):
            if self._edit_controller.paste_audio_from_clipboard(silent_if_empty=True):
                event.StopPropagation()
                return
            # allow default paste behaviour when clipboard has text only

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
        self._stop_preview_audio()
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
        self._edit_controller.paste_audio_from_clipboard()

    def _insert_audio_tokens(self, audio_paths: list[str]) -> None:
        placeholders = [f"[[audio:{path}]]" for path in audio_paths]
        insertion_point = self._edit_ctrl.GetInsertionPoint()
        text_to_insert = "\n".join(placeholders)
        self._edit_ctrl.WriteText(text_to_insert)
        self._edit_ctrl.SetInsertionPoint(insertion_point + len(text_to_insert))
        self.model.news_markdown = self._edit_ctrl.GetValue()

    def _stop_preview_audio(self) -> None:
        if self._on_stop_preview_audio:
            self._on_stop_preview_audio()

    def prompt_load_service(self) -> Path | None:
        return self._service_io.prompt_load_service()

    def _load_service_from_path(self, path: Path) -> bool:
        return self._service_io.load_service_from_path(path)

    def _on_load_service(self, _event: wx.Event | None) -> None:
        self.prompt_load_service()

    def prompt_save_service(self) -> Path | None:
        return self._service_io.prompt_save_service()

    def _save_service_to_path(self, target_path: Path) -> bool:
        return self._service_io.save_service_to_path(target_path)

    def _on_save_service(self, _event: wx.Event | None) -> None:
        self.prompt_save_service()

    def _build_service(self) -> NewsService:
        return NewsService(
            title=self.model.name,
            markdown=self.model.news_markdown or self._edit_ctrl.GetValue(),
            output_device=self.model.output_device,
            line_length=self._get_line_length(),
        )

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

    def activate_toolbar_control(self, window: wx.Window | None) -> bool:
        if window is None:
            return False
        buttons: list[wx.Button] = [
            self._mode_button,
            self._insert_button,
            self._load_button,
            self._save_button,
        ]
        if self._line_length_apply:
            buttons.append(self._line_length_apply)
        for button in buttons:
            if window is button:
                event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
                event.SetEventObject(button)
                button.GetEventHandler().ProcessEvent(event)
                return True
        return False

    def _handle_toolbar_char_hook(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_SPACE and not event.ControlDown() and not event.AltDown():
            self._suppress_play_shortcut = True
            event.Skip()
            return
        if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
            if self._move_within_toolbar(event.GetEventObject(), backwards=event.ShiftDown()):
                event.StopPropagation()
                return
        event.Skip()

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

    def _move_within_toolbar(self, current: wx.Window, *, backwards: bool) -> bool:
        controls = self._toolbar_focusables()
        if not controls:
            return False
        try:
            index = controls.index(current)
        except ValueError:
            return False
        if backwards:
            if index > 0:
                controls[index - 1].SetFocus()
                return True
            if self._focus_content_area():
                return True
            self.Navigate(wx.NavigationKeyEvent.IsBackward)
            return True
        if index < len(controls) - 1:
            controls[index + 1].SetFocus()
            return True
        flags = wx.NavigationKeyEvent.IsForward
        self.Navigate(flags)
        return True

    def _focus_content_area(self) -> bool:
        if self._mode == "edit":
            self._edit_ctrl.SetFocus()
            return True
        if self._mode == "read":
            if self._read_text_ctrl:
                self._read_text_ctrl.SetFocus()
                return True
            self._read_panel.SetFocus()
            return True
        return False

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

    # ------------------------------ rendering -------------------------------
    def _render_read_panel(self) -> None:
        wrapper = wx.BoxSizer(wx.VERTICAL)
        for child in self._read_panel.GetChildren():
            child.Destroy()
        self._read_text_ctrl = None
        view_model = self._read_controller.build_view(self.model.news_markdown or "")
        article_lines = view_model.lines
        audio_entries = view_model.audio_paths

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

    def _handle_read_action(self, event: wx.KeyEvent) -> bool:
        line_index = self._current_read_line()
        action = self._read_controller.handle_key(
            event.GetKeyCode(),
            shift=event.ShiftDown(),
            control=event.ControlDown(),
            alt=event.AltDown(),
            current_line=line_index,
        )
        if action.play_path:
            self._play_clip(action.play_path)
        if action.focus_line is not None:
            self._focus_read_line(action.focus_line)
        return action.handled

    def _current_read_line(self) -> int | None:
        if not self._read_text_ctrl:
            return None
        pos = self._read_text_ctrl.GetInsertionPoint()
        success, _, line_index = self._read_text_ctrl.PositionToXY(pos)
        return line_index if success else None

    def _focus_read_line(self, line_index: int | None) -> None:
        if line_index is None or not self._read_text_ctrl:
            return
        pos_target = self._read_text_ctrl.XYToPosition(0, line_index)
        if pos_target == wx.NOT_FOUND:
            return
        self._read_text_ctrl.SetInsertionPoint(pos_target)
        self._read_text_ctrl.ShowPosition(pos_target)
        self._read_text_ctrl.SetFocus()
        self._update_caret_from_read()

    def _handle_read_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        handled = self._handle_read_action(event)
        if handled:
            event.StopPropagation()
            return
        if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
            if event.ShiftDown():
                self.Navigate(wx.NavigationKeyEvent.IsBackward)
            else:
                if self._focus_toolbar_from_text(backwards=False):
                    event.StopPropagation()
                    return
            event.StopPropagation()
            return
        event.Skip()

    def _play_clip(self, path_str: str) -> None:
        device_id = self.model.output_device or (self.model.output_slots[0] if self.model.output_slots else None)
        self._on_play_audio(Path(path_str), device_id)

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
