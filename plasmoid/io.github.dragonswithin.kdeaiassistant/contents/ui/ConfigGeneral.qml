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
 * "General" page of the applet's settings dialog: how the applet appears in
 * the panel and how large its parts are.
 *
 * Plasma binds each `cfg_<name>` property to the entry of the same name in
 * contents/config/main.xml and writes it back when the user applies. This
 * page holds no other state and makes no requests; ranges here mirror the
 * min/max declared in main.xml.
 */
KCM.SimpleKCM {
    id: page

    property bool cfg_inputInPopup
    property alias cfg_barWidth: barWidth.value
    property alias cfg_popupWidth: popupWidth.value
    property alias cfg_popupHeight: popupHeight.value
    property alias cfg_daemonUrl: daemonUrl.text

    Kirigami.FormLayout {
        QQC2.RadioButton {
            Kirigami.FormData.label: i18n("Show in panel:")
            text: i18n("Search bar")
            checked: !page.cfg_inputInPopup
            onToggled: if (checked) page.cfg_inputInPopup = false
        }

        QQC2.RadioButton {
            text: i18n("Button that opens the assistant")
            checked: page.cfg_inputInPopup
            onToggled: if (checked) page.cfg_inputInPopup = true
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            text: i18n("Vertical panels always show the button.")
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.75
        }

        Item {
            Kirigami.FormData.isSection: true
        }

        QQC2.SpinBox {
            id: barWidth
            Kirigami.FormData.label: i18n("Search bar width:")
            from: 8
            to: 60
            enabled: !page.cfg_inputInPopup
        }

        QQC2.SpinBox {
            id: popupWidth
            Kirigami.FormData.label: i18n("Results width:")
            from: 20
            to: 70
        }

        QQC2.SpinBox {
            id: popupHeight
            Kirigami.FormData.label: i18n("Results height:")
            from: 12
            to: 50
        }

        Item {
            Kirigami.FormData.isSection: true
        }

        QQC2.TextField {
            id: daemonUrl
            Kirigami.FormData.label: i18n("Assistant address:")
            Layout.minimumWidth: Kirigami.Units.gridUnit * 16
            placeholderText: i18n("Automatic")
        }
    }
}
