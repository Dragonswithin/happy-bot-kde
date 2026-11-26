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
 * types here to search: main.qml shows what matches right above the bar
 * (PanelResults.qml) while the keyboard stays here, and Enter opens the
 * selected result. Enter on an empty bar, the logo, or the widget shortcut
 * opens ResultsPopup.qml, the assistant.
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
 * - `accepted(text)`: Enter. `text` is trimmed and may be empty.
 * - `textEdited(text)`: the user typed, deleted or cleared the text with
 *   Escape (not `setText`); main.qml searches it.
 * - `selectionMove(delta)`: Down (+1) or Up (-1), through those results
 *   (or earlier requests when there are none).
 * - `dismissed`: Escape on an empty field. Escape on text clears it first.
 * - `iconClicked`: a left click on the logo at the bar's left end. It works
 *   with nothing typed, so saved conversations are always one click away.
 * - `micClicked`: a click on the microphone at the bar's right end, shown
 *   when `voiceEnabled`; it reads "Listening…" while `listening`.
 * - `menuRequested`: a right-click anywhere on the bar. The text field
 *   would otherwise swallow it, so Plasma's own widget menu never appears.
 * - `inputFocusedChanged`: releases the panel's keyboard focus request.
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

    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor
    property bool busy: false
    property string statusText: ""
    property bool offline: false
    property string iconDescription: ""
    property string iconName: "search"
    property alias activity: icon.activity
    property alias animateMascot: icon.animateMascot
    property alias robotStyle: icon.robotStyle
    property int widthInGridUnits: 18
    property bool voiceEnabled: false  // show the microphone at the bar's right end
    property bool listening: false
    property string voiceProblem: ""  // shown in place of the placeholder for a few seconds
    // Focused means the field has focus AND its panel window is the active
    // window. A click anywhere outside deactivates the panel; focus is then
    // dropped explicitly so the next click on the
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
    signal accepted(string text)
    signal textEdited(string text)
    signal selectionMove(int delta)
    signal dismissed()
    signal menuRequested()
    signal iconClicked()
    signal micClicked()

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

        placeholderText: bar.listening ? i18n("Listening… talk, then pause")
            : bar.voiceProblem.length > 0 ? bar.voiceProblem
            : bar.offline ? bar.statusText : i18n("Ask or search anything…")
        leftPadding: icon.width + Kirigami.Units.smallSpacing * 2
        rightPadding: (spinner.visible ? spinner.width + Kirigami.Units.smallSpacing : 0)
            + (mic.visible ? mic.width + Kirigami.Units.smallSpacing : 0) + Kirigami.Units.smallSpacing
        Accessible.name: i18n("Ask or search anything")

        onTextEdited: bar.textEdited(text)
        Keys.onReturnPressed: bar.accepted(text.trim())
        Keys.onEnterPressed: bar.accepted(text.trim())
        Keys.onDownPressed: bar.selectionMove(1)
        Keys.onUpPressed: bar.selectionMove(-1)
        Keys.onEscapePressed: {
            if (field.text.length > 0) {
                field.text = "";
                bar.textEdited("");
            } else {
                bar.dismissed();
            }
        }

        PanelIcon {
            id: icon
            anchors.left: parent.left
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.verticalCenter: parent.verticalCenter
            width: Kirigami.Units.iconSizes.small
            height: width
            iconName: bar.iconName
            hovered: logoButton.containsMouse
            opacity: bar.offline ? 0.45 : 0.8
        }

        MicrophoneIcon {
            id: mic
            anchors.right: parent.right
            anchors.rightMargin: Kirigami.Units.smallSpacing
            anchors.verticalCenter: parent.verticalCenter
            width: Kirigami.Units.iconSizes.small
            height: width
            visible: bar.voiceEnabled
            accent: bar.accent
            nativeLook: bar.nativeLook
            recording: bar.listening
        }

        QQC2.BusyIndicator {
            id: spinner
            anchors.right: mic.visible ? mic.left : parent.right
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

    // The microphone is a button of its own too, at the right end: talk instead of typing.
    MouseArea {
        id: micButton
        visible: mic.visible
        x: field.x + field.width - width
        width: mic.width + Kirigami.Units.smallSpacing * 2
        height: parent.height
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: bar.micClicked()
        Accessible.role: Accessible.Button
        Accessible.name: bar.listening ? i18n("Stop listening") : i18n("Talk to Happy Bot")
        Accessible.onPressAction: bar.micClicked()

        AssistantToolTip {
            nativeLook: bar.nativeLook
            accent: bar.accent
            text: bar.listening ? i18n("Stop listening") : i18n("Talk to Happy Bot")
            visible: micButton.containsMouse
        }
    }

    // The logo is a button of its own, above the click-to-type areas; right
    // clicks fall through to the menu area below.
    MouseArea {
        id: logoButton
        x: field.x
        width: icon.width + Kirigami.Units.smallSpacing * 2
        height: parent.height
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: bar.iconClicked()
        Accessible.role: Accessible.Button
        Accessible.name: i18n("Open Happy Bot")
        Accessible.description: bar.iconDescription
        Accessible.onPressAction: bar.iconClicked()

        AssistantToolTip {
            nativeLook: bar.nativeLook
            accent: bar.accent
            text: bar.iconDescription || i18n("Open Happy Bot")
            visible: logoButton.containsMouse
        }
    }
}
