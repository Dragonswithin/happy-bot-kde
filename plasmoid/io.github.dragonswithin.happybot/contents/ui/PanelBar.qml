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
 * The applet's search-bar panel form: a text field in the panel beside the
 * launcher, used when the user picks "Search bar" under "Show in panel"
 * (the `inputInPanel` setting) on a horizontal panel. In this form the user
 * types here, and ResultsPopup.qml only shows results without taking focus.
 *
 * While the field has focus, Plasma draws its blue panel focus indicator
 * along the panel. A widget cannot switch that off; users who choose this
 * form accept it, and the icon form (CompactRepresentation.qml) avoids it.
 *
 * It owns no conversation or search state. It reports intent through
 * signals and main.qml decides what they do:
 *
 * - `focusRequested`: the user clicked the unfocused field. The panel
 *   window must be granted keyboard focus before the field can take it.
 * - `queryEdited(text)`: the text changed, by typing or by `setText`.
 * - `accepted(text)`: Enter. `text` is trimmed and may be empty.
 * - `selectionMove(delta)`: Down (+1) or Up (-1).
 * - `completeRequested`: Tab, to complete the text from the top result.
 * - `dismissed`: Escape on an empty field. Escape on text clears it first.
 * - `iconClicked`: a left click on the logo at the bar's left end. It works
 *   with nothing typed, so saved conversations are always one click away.
 * - `menuRequested`: a right-click anywhere on the bar. The text field
 *   would otherwise swallow it, so Plasma's own widget menu never appears.
 * - `inputFocusedChanged`: so the popup can close when focus leaves,
 *   including when the user clicks anywhere outside the panel.
 *
 * Its width is fixed at `widthInGridUnits` (the applet's `barWidth`
 * setting): minimum, preferred and maximum are the same so the panel
 * neither squeezes nor stretches it.
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
    property string iconName: "search"
    property int widthInGridUnits: 18
    // Focused means the field has focus AND its panel window is the active
    // window. A click anywhere outside deactivates the panel; focus is then
    // dropped explicitly so the popup closes and the next click on the
    // field goes through `focusRequested` again.
    readonly property bool windowActive: Window.active
    readonly property bool inputFocused: field.activeFocus && windowActive
    onWindowActiveChanged: {
        if (!windowActive) {
            field.focus = false;
        }
    }
    readonly property alias text: field.text

    signal focusRequested()
    signal queryEdited(string text)
    signal accepted(string text)
    signal selectionMove(int delta)
    signal completeRequested()
    signal dismissed()
    signal menuRequested()
    signal iconClicked()

    Layout.minimumWidth: Kirigami.Units.gridUnit * widthInGridUnits
    Layout.preferredWidth: Layout.minimumWidth
    Layout.maximumWidth: Layout.minimumWidth
    Layout.fillHeight: true

    function takeFocus() {
        field.forceActiveFocus(Qt.ShortcutFocusReason);
        field.selectAll();
    }

    function setText(text) {
        field.text = text;
        field.cursorPosition = text.length;
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

        onTextChanged: bar.queryEdited(text)
        Keys.onReturnPressed: bar.accepted(text.trim())
        Keys.onEnterPressed: bar.accepted(text.trim())
        Keys.onDownPressed: bar.selectionMove(1)
        Keys.onUpPressed: bar.selectionMove(-1)
        Keys.onTabPressed: bar.completeRequested()
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
            source: bar.iconName
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

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        cursorShape: Qt.IBeamCursor
        onClicked: bar.menuRequested()
    }

    // The logo is a button of its own, above the click-to-type areas; right
    // clicks fall through to the menu area below.
    MouseArea {
        x: field.x
        width: icon.width + Kirigami.Units.smallSpacing * 2
        height: parent.height
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: bar.iconClicked()
        Accessible.role: Accessible.Button
        Accessible.name: i18n("Show conversations")
        Accessible.onPressAction: bar.iconClicked()

        QQC2.ToolTip.text: i18n("Show conversations")
        QQC2.ToolTip.visible: containsMouse
        QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
    }
}
