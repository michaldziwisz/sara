# SARA Focus Silencer

This NVDA add-on silences focus announcements while the SARA automation suite is
active. Focus still follows the playing track, but NVDA no longer starts speaking
as soon as the selection changes. When you need the details, press `NVDA+Shift+I`
(the add-on calls the default focus announcement on demand).

## Installation

1. Build the add-on package (from the project root):

   ```bash
   cd nvda_addon/sara_focus_silencer
   zip -r ../sara_focus_silencer.nvda-addon *
   ```

2. Copy the generated `sara_focus_silencer.nvda-addon` file to the machine where
   NVDA runs and install it through NVDA → Tools → Manage add-ons → Install…

3. Restart NVDA.

## Usage

- Focus continues to follow the playing track in SARA, but NVDA will stay quiet.
- Use `NVDA+Shift+I` to manually announce the currently selected track whenever
  you need the information.

## Removing

Disable or uninstall the add-on from NVDA’s add-on manager whenever you want to
return to the default behaviour.
