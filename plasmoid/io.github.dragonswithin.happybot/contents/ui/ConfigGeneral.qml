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
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

/**
 * "Search Bar" page of the applet's settings dialog: the applet's own
 * behaviour in the panel. The assistant's icon (the wand or the robot
 * mascot), what the panel shows (the icon, or a search bar of a chosen
 * width), the floating Happy Bot app (running or not, start it, start it at
 * login; in the app's own settings also how faded and back to its corner)
 * and the hotkey, live file results while typing (on or
 * off, how many characters, how long a pause, how many matches), the size
 * of the popup, and the address of the daemon for unusual setups.
 *
 * The hotkey is the widget's own global shortcut (`Plasmoid.globalShortcut`,
 * the same one as on Plasma's Keyboard Shortcuts page); like that page,
 * this one stores it in `saveConfig`, which the dialog calls on Apply.
 * Both the hotkey and the floating button open Happy Bot knowing which
 * application the user is in (main.qml, `openForApplication`). The app's
 * state comes from the daemon (`GET /app`, `POST /app`,
 * src/happy_bot/app_control.py), read every few seconds while the page is
 * open; the opacity and position values belong to the app's own copy of
 * the widget, so they are shown only in the app (`standalone`).
 *
 * Plasma binds each `cfg_<name>` property to the entry of the same name in
 * contents/config/main.xml and writes it back when the user applies; the
 * ranges here mirror the min/max declared there. Apart from the app's
 * state above, this page holds no state and makes no requests. Everything
 * else the daemon stores is on the other
 * pages (DaemonSettings.qml).
 */
KCM.SimpleKCM {
    id: page

    property bool cfg_inputInPanel
    property alias cfg_barWidth: barWidth.value
    property alias cfg_instantSearch: instantSearch.checked
    property alias cfg_instantMinChars: instantMinChars.value
    property alias cfg_instantDelayMs: instantDelayMs.value
    property alias cfg_instantResults: instantResults.value
    property alias cfg_popupWidth: popupWidth.value
    property alias cfg_popupHeight: popupHeight.value
    property alias cfg_daemonUrl: daemonUrl.text
    property alias cfg_useRobotMascot: robotMascot.checked
    // The Happy Bot app (the floating Happy Bot): whether it runs and starts at login, from the daemon.
    readonly property bool standalone: Plasmoid.formFactor === PlasmaCore.Types.Application
    property bool appRunning: false
    property bool appAutostart: false

    function readApp() {
        appClient.request("GET", "/app", null, function(data) {
            page.appRunning = data.running === true;
            page.appAutostart = data.autostart === true;
        }, function(data) {});
    }

    function changeApp(change) {
        appClient.request("POST", "/app", change, function(data) {
            page.appRunning = data.running === true;
            page.appAutostart = data.autostart === true;
        }, function(data) {});
    }

    DaemonClient {
        id: appClient
        configuredUrl: page.cfg_daemonUrl || ""
    }

    Timer {
        interval: 1500
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: page.readApp()
    }
    property alias cfg_floatingOpacity: floatingOpacity.value
    property int cfg_floatingX
    property int cfg_floatingY
    property bool unsavedChanges: false

    function saveConfig() {
        Plasmoid.globalShortcut = hotkey.keySequence;
        page.unsavedChanges = false;
    }

    Kirigami.FormLayout {
        RowLayout {
            Kirigami.FormData.label: i18n("Assistant icon:")
            QQC2.CheckBox {
                id: robotMascot
                text: i18n("Use robot mascot")
            }
            Kirigami.Icon {
                source: Look.assistantIcon(robotMascot.checked)
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: implicitWidth
                Accessible.ignored: true
            }
        }

        QQC2.RadioButton {
            Kirigami.FormData.label: i18n("Show in panel:")
            text: i18n("Icon that opens the assistant")
            checked: !page.cfg_inputInPanel
            onToggled: if (checked) page.cfg_inputInPanel = false
        }

        QQC2.RadioButton {
            text: i18n("Search bar")
            checked: page.cfg_inputInPanel
            onToggled: if (checked) page.cfg_inputInPanel = true
        }

        QQC2.SpinBox {
            id: barWidth
            Kirigami.FormData.label: i18n("Search bar width:")
            enabled: page.cfg_inputInPanel
            from: 8
            to: 60
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("While you type in the search bar, Plasma outlines the panel in its focus colour; the icon avoids that. Vertical panels always show the icon.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Quick access from any application")
        }

        KeySequenceItem {
            id: hotkey
            Kirigami.FormData.label: i18n("Hotkey:")
            keySequence: Plasmoid.globalShortcut
            patterns: ShortcutPattern.Modifier | ShortcutPattern.ModifierAndKey
            onKeySequenceModified: page.unsavedChanges = keySequence !== Plasmoid.globalShortcut
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Floating Happy Bot:")
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: page.appRunning ? "checkmark" : "dialog-information"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            QQC2.Label {
                text: page.appRunning ? i18n("Running") : i18n("Not running")
            }

            QQC2.Button {
                visible: !page.appRunning
                text: i18n("Start it")
                icon.name: "media-playback-start"
                highlighted: true
                onClicked: page.changeApp({ start: true })
            }
        }

        QQC2.CheckBox {
            text: i18n("Start it when I log in")
            checked: page.appAutostart
            onToggled: page.changeApp({ autostart: checked })
        }

        RowLayout {
            Kirigami.FormData.label: i18n("When not in use:")
            visible: page.standalone
            spacing: Kirigami.Units.smallSpacing

            QQC2.Slider {
                id: floatingOpacity
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                from: 15
                to: 100
                stepSize: 5
            }

            QQC2.Label {
                text: floatingOpacity.value >= 100 ? i18n("fully visible") : i18n("%1% visible", floatingOpacity.value)
            }
        }

        QQC2.Button {
            visible: page.standalone
            enabled: page.cfg_floatingX >= 0 || page.cfg_floatingY >= 0
            text: i18n("Put it back in the corner")
            icon.name: "edit-undo"
            onClicked: {
                page.cfg_floatingX = -1;
                page.cfg_floatingY = -1;
            }
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: page.standalone
                ? i18n("Press the hotkey or click the floating Happy Bot while using any application, and it opens right there knowing which application you are in. Drag it to move it anywhere; it fades until the pointer is over it.")
                : i18n("The floating Happy Bot is an app of its own (Happy Bot in your application menu): it works without this panel widget. Its look and place are set from its own settings (right-click it). The hotkey here opens this panel widget, knowing which application you are in.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("While typing")
        }

        QQC2.CheckBox {
            id: instantSearch
            Kirigami.FormData.label: i18n("Live results:")
            text: i18n("Show matching files as I type")
        }

        QQC2.SpinBox {
            id: instantMinChars
            Kirigami.FormData.label: i18n("Start after:")
            enabled: instantSearch.checked
            from: 1
            to: 10
            textFromValue: (value, locale) => i18np("%1 character", "%1 characters", value)
            valueFromText: (text, locale) => parseInt(text) || 1
        }

        QQC2.SpinBox {
            id: instantDelayMs
            Kirigami.FormData.label: i18n("Wait for a pause of:")
            enabled: instantSearch.checked
            from: 0
            to: 2000
            stepSize: 50
            textFromValue: (value, locale) => i18n("%1 ms", value)
            valueFromText: (text, locale) => parseInt(text) || 0
        }

        QQC2.SpinBox {
            id: instantResults
            Kirigami.FormData.label: i18n("Show up to:")
            enabled: instantSearch.checked
            from: 1
            to: 20
            textFromValue: (value, locale) => i18np("%1 file", "%1 files", value)
            valueFromText: (text, locale) => parseInt(text) || 1
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Live results come from the file search tool chosen under Search & Tools. Enter always sends what you typed to the assistant.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Popup")
        }

        QQC2.SpinBox {
            id: popupWidth
            Kirigami.FormData.label: i18n("Width:")
            from: 20
            to: 70
        }

        QQC2.SpinBox {
            id: popupHeight
            Kirigami.FormData.label: i18n("Height:")
            from: 12
            to: 50
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Sizes are in multiples of the desktop's font size. The keyboard shortcut that opens the popup is on the Keyboard Shortcuts page.")
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
