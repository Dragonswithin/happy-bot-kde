/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.kquickcontrols
import org.kde.plasma.plasmoid

/**
 * "Appearance" page of the Happy Bot app's settings dialog: how Happy Bot
 * looks and behaves, in the app and in the panel widget alike.
 *
 * - Look and feel (the daemon's `ui` settings, src/happy_bot/ui_settings.py):
 *   the mascot or the wand, the floating Happy Bot's look (how faded while
 *   not in use, back to its corner), the popup's size, and whether search
 *   results include browser bookmarks and recently visited websites
 *   (`search_bookmarks`, `search_history`; src/happy_bot/browsers.py). They are read from `GET /health` and each change is saved
 *   at once with `POST /ui`, so the panel widget, which reads the same
 *   values, always matches the app.
 * - The app itself (`GET /app`, `POST /app`, src/happy_bot/app_control.py):
 *   whether it starts at login, read again every few seconds.
 * - The hotkey: this app copy's global shortcut (`Plasmoid.globalShortcut`),
 *   stored in `saveConfig` when the user applies, as on Plasma's Keyboard
 *   Shortcuts page. It opens the floating Happy Bot knowing which
 *   application the user is in.
 * - The panel widget's look (`GET`/`POST /panel`, src/happy_bot/panel_widget.py):
 *   the icon or a search bar, and the bar's width. They are that widget's own
 *   Plasma settings, changed at once through the Plasma shell, so Happy Bot
 *   has this one settings dialog; the widget's own page only points here.
 *
 * `cfg_daemonUrl` (no field: the address is found by itself) is only read, so
 * this page talks to the daemon the copy was set up for. The page keeps only
 * what it shows: the values read, the app's state and the panel widgets.
 */
KCM.SimpleKCM {
    id: page

    property string cfg_daemonUrl: ""
    property bool unsavedChanges: false
    property var ui: null
    property bool appAutostart: false
    property var panelWidgets: []  // [{id, search_bar, bar_width, vertical}], from GET /panel
    readonly property bool onPanel: panelWidgets.length > 0
    readonly property bool searchBar: panelWidgets.some(widget => widget.search_bar)
    property string problem: ""

    function saveConfig() {
        Plasmoid.globalShortcut = hotkey.keySequence;
        page.unsavedChanges = false;
    }

    function read() {
        client.request("GET", "/health", null, function(data) {
            page.ui = data.ui || null;
        }, function(data) {
            page.problem = data.error || i18n("The assistant is not running");
        });
    }

    function save(changes) {
        client.request("POST", "/ui", { changes: changes }, function(data) {
            page.ui = data.ui;
            page.problem = "";
        }, function(data) {
            page.problem = data.error || i18n("That could not be saved");
            page.read();
        });
    }

    function readPanel() {
        client.request("GET", "/panel", null, data => page.panelWidgets = data.widgets || [], () => page.panelWidgets = []);
    }

    function changePanel(changes) {
        client.request("POST", "/panel", changes, function(data) {
            page.panelWidgets = data.widgets || [];
            page.problem = "";
        }, function(data) {
            page.problem = data.error || i18n("The panel could not be changed");
            page.readPanel();
        });
    }

    function readApp() {
        client.request("GET", "/app", null, data => page.appAutostart = data.autostart === true, () => {});
    }

    DaemonClient {
        id: client
        configuredUrl: page.cfg_daemonUrl || ""
    }

    Component.onCompleted: {
        page.read();
        page.readPanel();
    }

    Timer {
        interval: 2000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: page.readApp()
    }

    Kirigami.FormLayout {
        enabled: page.ui !== null

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.problem.length > 0
            type: Kirigami.MessageType.Error
            text: page.problem
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Happy Bot's picture:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.CheckBox {
                text: i18n("Use the robot mascot")
                checked: page.ui !== null && page.ui.robot_mascot
                onToggled: page.save({ robot_mascot: checked })
            }

            Kirigami.Icon {
                source: Look.assistantIcon(page.ui !== null && page.ui.robot_mascot)
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: implicitWidth
                Accessible.ignored: true
            }
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Shown on the floating Happy Bot, in the panel and beside Happy Bot's replies.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Floating Happy Bot")
        }

        KeySequenceItem {
            id: hotkey
            Kirigami.FormData.label: i18n("Hotkey:")
            keySequence: Plasmoid.globalShortcut
            patterns: ShortcutPattern.Modifier | ShortcutPattern.ModifierAndKey
            onKeySequenceModified: page.unsavedChanges = keySequence !== Plasmoid.globalShortcut
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("At login:")
            text: i18n("Start Happy Bot when I log in")
            checked: page.appAutostart
            onToggled: client.request("POST", "/app", { autostart: checked },
                                      data => page.appAutostart = data.autostart === true, () => page.readApp())
        }

        RowLayout {
            Kirigami.FormData.label: i18n("When not in use:")
            spacing: Kirigami.Units.smallSpacing

            QQC2.Slider {
                id: floatingOpacity
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                from: 15
                to: 100
                stepSize: 5
                value: page.ui !== null ? page.ui.floating_opacity : 40
                onPressedChanged: if (!pressed) page.save({ floating_opacity: Math.round(value) })
            }

            QQC2.Label {
                text: floatingOpacity.value >= 100 ? i18n("fully visible")
                                                   : i18n("%1% visible", Math.round(floatingOpacity.value))
            }
        }

        QQC2.Button {
            enabled: page.ui !== null && (page.ui.floating_x >= 0 || page.ui.floating_y >= 0)
            text: i18n("Put it back in the corner")
            icon.name: "edit-undo"
            onClicked: page.save({ floating_x: -1, floating_y: -1 })
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Press the hotkey or click the floating Happy Bot while using any application, and it opens right there knowing which application you are in. Drag it to move it anywhere; it fades until the pointer is over it.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Popup")
        }

        QQC2.SpinBox {
            wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
            Kirigami.FormData.label: i18n("Width:")
            from: 20
            to: 70
            value: page.ui !== null ? page.ui.popup_width : 30
            onValueModified: page.save({ popup_width: value })
        }

        QQC2.SpinBox {
            wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
            Kirigami.FormData.label: i18n("Height:")
            from: 12
            to: 50
            value: page.ui !== null ? page.ui.popup_height : 26
            onValueModified: page.save({ popup_height: value })
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Sizes are in multiples of the desktop's font size. They apply to the floating Happy Bot and to the panel widget's popup.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Search")
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("Also show:")
            text: i18n("Bookmarks from your web browsers")
            checked: page.ui !== null && page.ui.search_bookmarks === true
            onToggled: page.save({ search_bookmarks: checked })
        }

        QQC2.CheckBox {
            text: i18n("Websites you visited recently")
            checked: page.ui !== null && page.ui.search_history === true
            onToggled: page.save({ search_history: checked })
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("In the panel's search bar and \"Find a file\", from Firefox, Chrome, Chromium, Brave, Vivaldi, Edge, Opera and similar browsers. They are read on this computer and never sent anywhere.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Panel")
        }

        QQC2.RadioButton {
            Kirigami.FormData.label: i18n("In the panel, show:")
            enabled: page.onPanel
            text: i18n("Happy Bot's icon")
            checked: page.onPanel && !page.searchBar
            onToggled: if (checked) page.changePanel({ search_bar: false })
        }

        QQC2.RadioButton {
            enabled: page.onPanel
            text: i18n("A search bar")
            checked: page.searchBar
            onToggled: if (checked) page.changePanel({ search_bar: true })
        }

        QQC2.SpinBox {
            wheelEnabled: false  // scrolling the page must not change it (KDE's style turns the wheel on)
            Kirigami.FormData.label: i18n("Search bar width:")
            enabled: page.searchBar
            from: 8
            to: 60
            value: page.onPanel ? page.panelWidgets[0].bar_width : 18
            onValueModified: page.changePanel({ bar_width: value })
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: page.onPanel
                ? i18n("While you type in the search bar, Plasma outlines the panel in its focus colour; the icon avoids that. A vertical panel always shows the icon. The width is in multiples of the desktop's font size.")
                : i18n("Happy Bot is not on a panel. To add it, right-click the panel, choose Add Widgets…, and drag Happy Bot onto it.")
        }
    }
}
