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
 * "Appearance" page of the applet's settings dialog: the size of the
 * assistant's popup, and the address of the daemon for unusual setups.
 *
 * Plasma binds each `cfg_<name>` property to the entry of the same name in
 * contents/config/main.xml and writes it back when the user applies. This
 * page holds no other state and makes no requests; ranges here mirror the
 * min/max declared in main.xml.
 */
KCM.SimpleKCM {
    id: page

    property alias cfg_popupWidth: popupWidth.value
    property alias cfg_popupHeight: popupHeight.value
    property alias cfg_daemonUrl: daemonUrl.text

    Kirigami.FormLayout {
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
