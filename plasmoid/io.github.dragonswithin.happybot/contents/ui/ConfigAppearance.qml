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
 *   not in use, back to its corner), search while typing (on or off, after
 *   how many characters and how long a pause, how many matches) and the
 *   popup's size. They are read from `GET /health` and each change is saved
 *   at once with `POST /ui`, so the panel widget, which reads the same
 *   values, always matches the app.
 * - The app itself (`GET /app`, `POST /app`, src/happy_bot/app_control.py):
 *   whether it starts at login, read again every few seconds.
 * - The hotkey: this app copy's global shortcut (`Plasmoid.globalShortcut`),
 *   stored in `saveConfig` when the user applies, as on Plasma's Keyboard
 *   Shortcuts page. It opens the floating Happy Bot knowing which
 *   application the user is in.
 * - The daemon's address (`daemonUrl`, this copy's Plasma setting, written
 *   on Apply), for unusual setups.
 *
 * The page keeps only what it shows: the values read and the app's state.
 */
KCM.SimpleKCM {
    id: page

    property alias cfg_daemonUrl: daemonUrl.text
    property bool unsavedChanges: false
    property var ui: null
    property bool appAutostart: false
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

    function readApp() {
        client.request("GET", "/app", null, data => page.appAutostart = data.autostart === true, () => {});
    }

    DaemonClient {
        id: client
        configuredUrl: page.cfg_daemonUrl || ""
    }

    Component.onCompleted: page.read()

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
            Kirigami.FormData.label: i18n("While typing")
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("Live results:")
            text: i18n("Show matching files as I type")
            checked: page.ui !== null && page.ui.instant_search
            onToggled: page.save({ instant_search: checked })
        }

        QQC2.SpinBox {
            Kirigami.FormData.label: i18n("Start after:")
            enabled: page.ui !== null && page.ui.instant_search
            from: 1
            to: 10
            value: page.ui !== null ? page.ui.instant_min_chars : 2
            textFromValue: (value, locale) => i18np("%1 character", "%1 characters", value)
            valueFromText: (text, locale) => parseInt(text) || 1
            onValueModified: page.save({ instant_min_chars: value })
        }

        QQC2.SpinBox {
            Kirigami.FormData.label: i18n("Wait for a pause of:")
            enabled: page.ui !== null && page.ui.instant_search
            from: 0
            to: 2000
            stepSize: 50
            value: page.ui !== null ? page.ui.instant_delay_ms : 200
            textFromValue: (value, locale) => i18n("%1 ms", value)
            valueFromText: (text, locale) => parseInt(text) || 0
            onValueModified: page.save({ instant_delay_ms: value })
        }

        QQC2.SpinBox {
            Kirigami.FormData.label: i18n("Show up to:")
            enabled: page.ui !== null && page.ui.instant_search
            from: 1
            to: 20
            value: page.ui !== null ? page.ui.instant_results : 8
            textFromValue: (value, locale) => i18np("%1 file", "%1 files", value)
            valueFromText: (text, locale) => parseInt(text) || 1
            onValueModified: page.save({ instant_results: value })
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Live results come from the file search tool chosen under Search & Tools. Enter always sends what you typed to Happy Bot.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Popup")
        }

        QQC2.SpinBox {
            Kirigami.FormData.label: i18n("Width:")
            from: 20
            to: 70
            value: page.ui !== null ? page.ui.popup_width : 30
            onValueModified: page.save({ popup_width: value })
        }

        QQC2.SpinBox {
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
            Kirigami.FormData.label: i18n("Advanced")
        }

        QQC2.TextField {
            id: daemonUrl
            Kirigami.FormData.label: i18n("Assistant address:")
            Layout.minimumWidth: Kirigami.Units.gridUnit * 16
            placeholderText: i18n("Automatic")
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Leave empty. Only needed when the assistant's background service was started on a different port.")
        }
    }
}
