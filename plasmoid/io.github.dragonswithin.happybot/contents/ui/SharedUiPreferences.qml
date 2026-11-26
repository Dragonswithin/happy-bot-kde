// SPDX-License-Identifier: MIT
pragma Singleton
import QtQuick

// Plasma replaces the current settings page when another category opens. Keep pending
// writes alive across that change so the sound editor sees the new mascot's choices.
UiPreferences {
    id: preferences
    property string configuredUrl: ""
    client: DaemonClient { configuredUrl: preferences.configuredUrl }

    function preview(event, theme) {
        client.request("POST", "/sound/preview", {event, theme}, () => problem(""),
            data => problem(data.error || i18n("The sound could not be played.")));
    }
}
