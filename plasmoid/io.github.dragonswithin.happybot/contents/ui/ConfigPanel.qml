/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * The panel widget's own Plasma settings page, which Plasma opens from its
 * panel edit mode. Happy Bot has one settings dialog, the app's: everything,
 * including how this widget looks in the panel (the icon or a search bar,
 * the bar's width), is on the app's pages (ConfigAppearance.qml changes this
 * widget's `inputInPanel` and `barWidth` through `POST /panel`,
 * src/happy_bot/panel_widget.py). So this page only says so and opens them,
 * starting the app if needed (`POST /app`, then `POST /app/show` with
 * "settings", src/happy_bot/app_control.py). The widget's right-click menu
 * goes straight there.
 *
 * `cfg_daemonUrl` (no field) is only read, so the button reaches the daemon
 * this copy was set up for. The page keeps no state.
 */
KCM.SimpleKCM {
    id: page

    property string cfg_daemonUrl: ""

    DaemonClient {
        id: client
        configuredUrl: page.cfg_daemonUrl || ""
    }

    SettingsSection {
        title: i18n("Panel widget")
        iconName: "preferences-desktop-plasma"
        description: i18n("Choose an icon or a search bar for this panel in Happy Bot’s Appearance settings.")

        QQC2.Button {
            text: i18n("Open Happy Bot settings…")
            icon.name: "configure"
            highlighted: true
            onClicked: client.request("POST", "/app", { start: true }, function(data) {
                client.request("POST", "/app/show", { action: "settings" }, function(data) {}, function(data) {});
            }, function(data) {})
        }
    }
}
