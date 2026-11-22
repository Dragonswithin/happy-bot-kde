/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * The applet's inline panel form: a single text field that lives in the
 * panel beside the launcher and is the only place the user types.
 *
 * It owns no conversation state. It reports intent through signals and
 * main.qml decides what they do: `focusRequested` when the user clicks the
 * unfocused field (the panel window must be granted keyboard focus before
 * the field can take it), `submitted` on Enter, `dismissed` on Escape, and
 * `inputFocusChanged` so the results popup can follow focus.
 *
 * The click-catching MouseArea exists only while the field is unfocused: a
 * Plasma panel refuses keyboard focus until the applet's status is
 * AcceptingInputStatus, so the first click has to be intercepted to request
 * that before focus is forced. Once focused the area is disabled and the
 * field receives pointer events normally.
 */
Item {
    id: bar

    property bool busy: false
    property string statusText: ""
    property bool offline: false
    readonly property bool inputFocused: field.activeFocus
    readonly property alias text: field.text

    signal focusRequested()
    signal submitted(string text)
    signal dismissed()

    Layout.minimumWidth: Kirigami.Units.gridUnit * 10
    Layout.preferredWidth: Kirigami.Units.gridUnit * 18
    Layout.maximumWidth: Kirigami.Units.gridUnit * 24
    Layout.fillHeight: true

    function takeFocus() {
        field.forceActiveFocus(Qt.ShortcutFocusReason);
        field.selectAll();
    }

    function clear() {
        field.text = "";
    }

    PlasmaComponents3.TextField {
        id: field

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: Math.min(parent.height, implicitHeight)

        placeholderText: bar.offline ? bar.statusText : i18n("Ask or search anything…")
        leftPadding: icon.width + Kirigami.Units.smallSpacing * 2
        rightPadding: spinner.visible ? spinner.width + Kirigami.Units.smallSpacing * 2 : Kirigami.Units.smallSpacing
        Accessible.name: i18n("Ask or search anything")

        Keys.onReturnPressed: bar.submit()
        Keys.onEnterPressed: bar.submit()
        Keys.onEscapePressed: {
            if (field.text.length > 0) {
                field.text = "";
            } else {
                bar.dismissed();
            }
        }

        Kirigami.Icon {
            id: icon
            anchors.left: parent.left
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.verticalCenter: parent.verticalCenter
            width: Kirigami.Units.iconSizes.small
            height: width
            source: "search"
            opacity: bar.offline ? 0.45 : 0.8
        }

        QQC2.BusyIndicator {
            id: spinner
            anchors.right: parent.right
            anchors.rightMargin: Kirigami.Units.smallSpacing
            anchors.verticalCenter: parent.verticalCenter
            width: Kirigami.Units.iconSizes.small
            height: width
            running: bar.busy
            visible: running
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: !field.activeFocus
        cursorShape: Qt.IBeamCursor
        onPressed: bar.focusRequested()
    }

    function submit() {
        const text = field.text.trim();
        if (text.length > 0) {
            bar.submitted(text);
        }
    }
}
