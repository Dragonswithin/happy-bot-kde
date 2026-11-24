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
 * "Search Bar" page of the applet's settings dialog: the applet's own
 * behaviour in the panel. Live file results while typing (on or off, how
 * many characters, how long a pause, how many matches), the size of the
 * popup, and the address of the daemon for unusual setups.
 *
 * Plasma binds each `cfg_<name>` property to the entry of the same name in
 * contents/config/main.xml and writes it back when the user applies; the
 * ranges here mirror the min/max declared there. This page holds no other
 * state and makes no requests. Everything the daemon stores is on the other
 * pages (DaemonSettings.qml).
 */
KCM.SimpleKCM {
    id: page

    property alias cfg_instantSearch: instantSearch.checked
    property alias cfg_instantMinChars: instantMinChars.value
    property alias cfg_instantDelayMs: instantDelayMs.value
    property alias cfg_instantResults: instantResults.value
    property alias cfg_popupWidth: popupWidth.value
    property alias cfg_popupHeight: popupHeight.value
    property alias cfg_daemonUrl: daemonUrl.text

    Kirigami.FormLayout {
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
