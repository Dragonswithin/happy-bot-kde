/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * "Helping with: Kate — notes.txt", shown in the popup (ResultsView.qml)
 * while the chat knows which application the user came from
 * (`session.helpWith`, set when Happy Bot was opened from the floating
 * button or the hotkey). It shows exactly what is sent with each request,
 * and its close button (`session.forgetApplication`) stops sending it. It
 * keeps no state of its own and is hidden when there is nothing to show.
 */
RowLayout {
    id: chip

    required property var session

    readonly property var about: session.helpWith

    visible: about !== null
    spacing: Kirigami.Units.smallSpacing

    Kirigami.Icon {
        source: "window"
        Layout.preferredWidth: Kirigami.Units.iconSizes.small
        Layout.preferredHeight: Kirigami.Units.iconSizes.small
        opacity: 0.7
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        elide: Text.ElideRight
        font: Kirigami.Theme.smallFont
        text: chip.about === null ? ""
            : chip.about.title && chip.about.title.indexOf(chip.about.app) === -1
                ? i18n("Helping with: %1 — %2", chip.about.app, chip.about.title)
                : i18n("Helping with: %1", chip.about.title || chip.about.app)
    }

    PlasmaComponents3.ToolButton {
        icon.name: "window-close"
        text: i18n("Don't tell Happy Bot which application this is")
        display: PlasmaComponents3.AbstractButton.IconOnly
        PlasmaComponents3.ToolTip.text: text
        PlasmaComponents3.ToolTip.visible: hovered
        onClicked: chip.session.forgetApplication()
    }
}
