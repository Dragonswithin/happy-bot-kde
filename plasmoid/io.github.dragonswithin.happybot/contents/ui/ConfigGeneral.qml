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
 * "Search Bar" page of the applet's settings dialog: the applet's own
 * behaviour in the panel. The assistant's icon (the wand or the robot
 * mascot), what the panel shows (the icon, or a search bar of a chosen
 * width), the floating button over other windows (on or off, how faded,
 * back to its corner) and the hotkey, live file results while typing (on or
 * off, how many characters, how long a pause, how many matches), the size
 * of the popup, and the address of the daemon for unusual setups.
 *
 * The hotkey is the widget's own global shortcut (`Plasmoid.globalShortcut`,
 * the same one as on Plasma's Keyboard Shortcuts page); like that page,
 * this one stores it in `saveConfig`, which the dialog calls on Apply.
 * Both the hotkey and the floating button open Happy Bot knowing which
 * application the user is in (main.qml, `openForApplication`).
 *
 * Plasma binds each `cfg_<name>` property to the entry of the same name in
 * contents/config/main.xml and writes it back when the user applies; the
 * ranges here mirror the min/max declared there. This page holds no other
 * state and makes no requests. Everything the daemon stores is on the other
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
    property alias cfg_floatingButton: floatingButton.checked
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

        QQC2.CheckBox {
            id: floatingButton
            Kirigami.FormData.label: i18n("Floating button:")
            text: i18n("Show a Happy Bot button over other windows")
        }

        RowLayout {
            Kirigami.FormData.label: i18n("When not in use:")
            enabled: floatingButton.checked
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
            enabled: floatingButton.checked && (page.cfg_floatingX >= 0 || page.cfg_floatingY >= 0)
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
            text: i18n("Press the hotkey or click the button while using any application, and Happy Bot opens knowing which application you are in, so you can ask about it. Drag the button to move it anywhere; it fades until the pointer is over it.")
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
