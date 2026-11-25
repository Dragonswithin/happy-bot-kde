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
 * One row of the conversation in ResultsView.qml, drawn according to its
 * `kind` (see AssistantSession.qml for the model's fields).
 *
 * Every row uses the same two columns: a narrow gutter for a small icon and
 * a text column, so all text in the conversation starts at one edge. Cards
 * draw their tint across both columns.
 *
 * - "user": the request, with a person icon, after a thin rule when it is
 *   not the first turn.
 * - "tool": one step the assistant took, small and grey, with a symbolic
 *   tick or warning in the gutter. While it runs, a small spinner takes the
 *   gutter, the line shows how long it has been running, and the latest
 *   output line it reported appears underneath in fixed-width text, so a
 *   long command visibly makes progress. A step whose result came with a
 *   card (`card`, the weather) shows it underneath, drawn by WeatherCard.qml.
 *   Answer buttons the assistant offered (`ask_user`, `suggest_next`: a card
 *   of kind "choices") replace the step line, drawn by ChoicesCard.qml; a
 *   click emits `choiceChosen(text)`, enabled only while `choicesEnabled`.
 * - "notice": a quiet step-like line ("Stopped.").
 * - "assistant": the answer in a tinted card, drawn by AnswerBody.qml
 *   (Markdown, code blocks each with their own Copy button, lists of files
 *   that open with a click), with a Copy button that puts the whole answer
 *   on the clipboard; links and opened files are passed out through
 *   `linkActivated`. Its gutter shows the robot mascot
 *   when `useRobotMascot` is set, and is empty otherwise.
 * - "approval": an action waiting for the user, in an attention-coloured
 *   card: "Allow this?", what will run in small fixed-width text, why it
 *   asks when that adds something, then Deny / Always this session / Allow.
 *   After an answer the buttons give way to a one-line outcome.
 * - "error" and "setup": a red or blue card with a short headline and, for
 *   errors, the technical detail underneath; setup adds Open settings.
 *
 * Actions are reported through signals; the entry holds no state.
 */
Item {
    id: entry

    required property int index
    required property string kind
    required property string text
    required property string stage
    required property string callId
    required property string approvalId
    required property string detail
    required property bool canRemember
    required property real started
    required property string progress
    required property string card
    // Answer buttons are clickable only while the assistant is not working (set by ResultsView.qml).
    property bool choicesEnabled: true
    readonly property var cardData: {
        try {
            return card ? JSON.parse(card) : null;
        } catch (error) {
            return null;
        }
    }
    readonly property bool hasChoices: kind === "tool" && cardData !== null && cardData.kind === "choices"
    property bool useRobotMascot: false
    readonly property bool running: kind === "tool" && stage === "running"
    property real now: Date.now()

    readonly property int gutter: Kirigami.Units.iconSizes.small + Kirigami.Units.largeSpacing
    readonly property bool isCard: kind === "assistant" || kind === "approval" || kind === "error" || kind === "setup"
    readonly property color cardColor: kind === "approval" ? Kirigami.Theme.neutralTextColor
        : kind === "error" ? Kirigami.Theme.negativeTextColor
        : kind === "setup" ? Kirigami.Theme.highlightColor
        : Kirigami.Theme.textColor
    // Error messages from the daemon are one line; a known prefix becomes a
    // short headline and the rest the detail.
    readonly property var errorParts: {
        const unreachable = text.match(/^Could not reach the model at (\S+): (.*)$/);
        if (unreachable) {
            return [i18n("Can't reach the AI model"), unreachable[1] + " — " + unreachable[2]];
        }
        const split = text.indexOf(": ");
        return split > 0 && split < 80 ? [text.substring(0, split), text.substring(split + 2)] : [text, ""];
    }

    signal linkActivated(string link)
    signal choiceChosen(string text)
    signal approvalAnswered(string approvalId, string decision, bool remember)
    signal settingsRequested()

    implicitHeight: layout.implicitHeight

    function elapsed() {
        const seconds = Math.max(0, Math.floor((entry.now - entry.started) / 1000));
        const minutes = Math.floor(seconds / 60);
        return minutes + ":" + String(seconds % 60).padStart(2, "0");
    }

    Timer {
        interval: 1000
        repeat: true
        running: entry.running
        triggeredOnStart: true
        onTriggered: entry.now = Date.now()
    }

    ColumnLayout {
        id: layout
        width: parent.width
        spacing: 0

        Kirigami.Separator {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            visible: entry.kind === "user" && entry.index > 0
            opacity: 0.5
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: entry.isCard ? Kirigami.Units.smallSpacing / 2 : 0
            implicitHeight: row.implicitHeight + (entry.isCard ? Kirigami.Units.largeSpacing * 2 : 0)
            radius: Kirigami.Units.cornerRadius * 2
            color: entry.isCard
                ? Qt.alpha(entry.cardColor, entry.kind === "assistant" ? 0.05 : entry.kind === "approval" && entry.stage === "waiting" ? 0.12 : 0.08)
                : "transparent"
            border.width: entry.isCard ? 1 : 0
            border.color: Qt.alpha(entry.cardColor, entry.kind === "assistant" ? 0.08
                : entry.kind === "approval" && entry.stage === "waiting" ? 0.7 : 0.35)

            RowLayout {
                id: row

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: entry.isCard ? Kirigami.Units.largeSpacing : 0
                anchors.rightMargin: entry.isCard ? Kirigami.Units.largeSpacing : 0
                spacing: 0

                // Gutter: one small icon, centred, the same width for every row.
                Item {
                    Layout.preferredWidth: entry.gutter
                    Layout.alignment: Qt.AlignTop
                    implicitHeight: Kirigami.Units.iconSizes.small

                    PlasmaComponents3.BusyIndicator {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.small
                        height: width
                        running: entry.running
                        visible: running
                    }

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        visible: !entry.running
                        width: Kirigami.Units.iconSizes.small
                        height: width
                        isMask: entry.kind === "tool" || entry.kind === "notice"
                        color: entry.kind === "tool" && entry.stage === "failed" ? Kirigami.Theme.neutralTextColor
                            : Kirigami.Theme.disabledTextColor
                        opacity: entry.kind === "user" ? 0.7 : entry.kind === "notice" ? 0.5 : 1
                        source: {
                            switch (entry.kind) {
                            case "user": return "im-user";
                            case "assistant": return entry.useRobotMascot ? Look.robotIcon : "";
                            case "tool": return entry.hasChoices ? (entry.cardData.follow_up ? "go-next" : "dialog-question")
                                : entry.stage === "failed" ? "dialog-warning"
                                : entry.stage === "ok" ? "checkmark" : "chronometer";
                            case "notice": return "media-playback-stop-symbolic";
                            case "approval": return "dialog-warning";
                            case "error": return "dialog-error";
                            case "setup": return "configure";
                            default: return "";
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing / 2

                    // user request
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.kind === "user"
                        text: entry.text
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        font.weight: Font.DemiBold
                    }

                    // a step, or a notice (not for answer buttons: the card says it all)
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: (entry.kind === "tool" || entry.kind === "notice") && !entry.hasChoices
                        text: entry.kind === "tool" && entry.stage === "failed" ? i18n("%1 — failed", entry.text)
                            : entry.running ? i18n("%1 · %2", entry.text, entry.elapsed())
                            : entry.text
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        font: Kirigami.Theme.smallFont
                        opacity: entry.running ? 0.9 : 0.7
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.running && entry.progress.length > 0
                        text: entry.progress
                        textFormat: Text.PlainText
                        elide: Text.ElideMiddle
                        font.family: Kirigami.Theme.fixedWidthFont.family
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        opacity: 0.6
                    }

                    // a card the tool's result came with (WeatherCard.qml)
                    Loader {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        active: entry.kind === "tool" && entry.cardData !== null && entry.cardData.kind === "weather"
                        visible: active
                        sourceComponent: WeatherCard {
                            weather: entry.cardData
                        }
                    }

                    // answer buttons the assistant offered (ChoicesCard.qml); a click is the user's next message
                    Loader {
                        Layout.fillWidth: true
                        active: entry.hasChoices
                        visible: active
                        sourceComponent: ChoicesCard {
                            choices: entry.cardData
                            enabled: entry.choicesEnabled
                            onChosen: text => entry.choiceChosen(text)
                        }
                    }

                    // the answer: Markdown, code blocks with Copy, file lists that open
                    AnswerBody {
                        id: answerText
                        Layout.fillWidth: true
                        visible: entry.kind === "assistant"
                        text: entry.kind === "assistant" ? entry.text : ""
                        onLinkActivated: link => entry.linkActivated(link)
                    }

                    PlasmaComponents3.ToolButton {
                        Layout.alignment: Qt.AlignRight
                        visible: entry.kind === "assistant" && entry.text.length > 0
                        icon.name: "edit-copy"
                        text: i18n("Copy answer")
                        display: PlasmaComponents3.AbstractButton.IconOnly
                        PlasmaComponents3.ToolTip.text: text
                        PlasmaComponents3.ToolTip.visible: hovered
                        onClicked: answerText.copyAll()
                    }

                    // approval
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.kind === "approval"
                        text: i18n("Allow this?")
                        font.weight: Font.Bold
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.kind === "approval"
                        text: entry.text
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        maximumLineCount: 6
                        elide: Text.ElideRight
                        font.family: Kirigami.Theme.fixedWidthFont.family
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        // Shown only when the reason says more than the action itself.
                        visible: entry.kind === "approval" && entry.detail.length > 0
                            && entry.detail !== "moves it to the trash"
                        text: i18n("Asks because it %1", entry.detail)
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        font: Kirigami.Theme.smallFont
                        opacity: 0.75
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        visible: entry.kind === "approval" && entry.stage === "waiting"
                        spacing: Kirigami.Units.smallSpacing

                        Item {
                            Layout.fillWidth: true
                        }

                        PlasmaComponents3.Button {
                            text: i18n("Deny")
                            icon.name: "dialog-cancel"
                            onClicked: entry.approvalAnswered(entry.approvalId, "deny", false)
                        }

                        PlasmaComponents3.Button {
                            text: i18n("Always this session")
                            visible: entry.canRemember
                            onClicked: entry.approvalAnswered(entry.approvalId, "allow", true)
                        }

                        PlasmaComponents3.Button {
                            text: i18n("Allow")
                            icon.name: "dialog-ok-apply"
                            onClicked: entry.approvalAnswered(entry.approvalId, "allow", false)
                        }
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.kind === "approval" && entry.stage !== "waiting"
                        text: entry.stage === "allow" ? i18n("Allowed")
                            : entry.stage === "deny" ? i18n("Declined — not run")
                            : entry.stage === "timeout" ? i18n("Not answered in time — not run")
                            : i18n("Cancelled — not run")
                        font: Kirigami.Theme.smallFont
                        opacity: 0.75
                    }

                    // error and setup
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.kind === "error"
                        text: entry.errorParts[0]
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        font.weight: Font.DemiBold
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: entry.kind === "error" && entry.errorParts[1].length > 0
                        text: entry.errorParts[1]
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        font: Kirigami.Theme.smallFont
                        opacity: 0.75
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: entry.kind === "setup"
                        spacing: Kirigami.Units.largeSpacing

                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            text: entry.text
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                        }

                        PlasmaComponents3.Button {
                            text: i18n("Open settings")
                            icon.name: "configure"
                            onClicked: entry.settingsRequested()
                        }
                    }
                }
            }
        }

        Item {
            // Breathing room under a card before the next row.
            Layout.preferredHeight: entry.isCard ? Kirigami.Units.smallSpacing / 2 : 0
        }
    }
}
