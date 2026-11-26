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
 * "Fix selected text": what ResultsView.qml shows while `session.fixing` is
 * set (the "Fix selected text" shortcut, `AssistantSession.startFixing`).
 *
 * From top to bottom: the selected text and the application it is in (a
 * few lines, the rest elided); one button per way to change it (Fix
 * grammar, Shorter, Translate, Explain: `session.fixSelection(style)`), with
 * a hint that the field below takes an instruction of the user's own, which
 * main.qml sends the same way; while the AI works, which AI it is; any
 * problem (`session.fixProblem`); and the result, selectable, with
 * "Replace" (pastes it over the selection in that application,
 * `session.replaceSelection`; not for an explanation or a terminal) and
 * "Copy". With nothing selected it says how to select text instead.
 *
 * All state lives in the session; this component only draws it and calls
 * the session, so the panel popup and the floating Happy Bot show the same
 * thing. `naturalHeight` is its exact unscrolled height, for the window to
 * size to.
 */
ColumnLayout {
    id: card
    property color accent: Kirigami.Theme.highlightColor

    required property var session
    readonly property var fixing: session.fixing || ({})
    readonly property bool hasText: (fixing.text || "").length > 0
    readonly property real naturalHeight: implicitHeight

    spacing: Kirigami.Units.largeSpacing

    Kirigami.Heading {
        Layout.fillWidth: true
        level: 4
        wrapMode: Text.Wrap
        text: card.fixing.app ? i18n("Selected text in %1", card.fixing.app) : i18n("Selected text")
    }

    // The selection itself, framed, a few lines at most.
    Rectangle {
        Layout.fillWidth: true
        visible: card.hasText
        implicitHeight: selectionLabel.implicitHeight + Kirigami.Units.largeSpacing * 2
        radius: Kirigami.Units.cornerRadius
        color: Qt.alpha(Kirigami.Theme.textColor, 0.06)

        PlasmaComponents3.Label {
            id: selectionLabel
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            text: card.fixing.text || ""
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            maximumLineCount: 6
            elide: Text.ElideRight
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: !card.hasText
        wrapMode: Text.Wrap
        opacity: 0.8
        text: card.fixing.loading ? i18n("Reading the selected text…")
            : i18n("Nothing is selected. Select some text in any application, then press the Fix selected text shortcut again.")
    }

    Flow {
        Layout.fillWidth: true
        visible: card.hasText
        spacing: Kirigami.Units.smallSpacing

        Repeater {
            model: [
                { style: "fix", label: i18n("Fix grammar"), icon: "tools-check-spelling" },
                { style: "shorter", label: i18n("Shorter"), icon: "format-text-strikethrough" },
                { style: "translate", label: i18n("Translate"), icon: "translate" },
                { style: "explain", label: i18n("Explain"), icon: "help-about" }
            ]

            PlasmaComponents3.Button {
                required property var modelData
                text: modelData.label
                icon.name: modelData.icon
                enabled: !card.session.fixBusy
                onClicked: card.session.fixSelection(modelData.style, "")
            }
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: card.hasText && card.session.fixResult.length === 0 && !card.session.fixBusy
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("Or type what to do with it below, for example “make it formal” or “translate into French”, and press Enter.")
    }

    RowLayout {
        Layout.fillWidth: true
        visible: card.session.fixBusy
        spacing: Kirigami.Units.largeSpacing

        PlasmaComponents3.BusyIndicator {
            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            running: card.session.fixBusy
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: i18n("Working on it…")
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: card.session.fixProblem.length > 0
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Icon {
            source: "dialog-warning"
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            text: card.session.fixProblem
        }
    }

    // The result, selectable, with what can be done with it.
    ColumnLayout {
        Layout.fillWidth: true
        visible: card.session.fixResult.length > 0 && !card.session.fixBusy
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: card.session.fixModel ? i18n("From %1", card.session.fixModel) : ""
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: resultText.implicitHeight + Kirigami.Units.largeSpacing * 2
            radius: Kirigami.Units.cornerRadius
            color: "transparent"
            border.width: 1
            border.color: Qt.alpha(card.accent, 0.6)

            QQC2.TextArea {
                id: resultText
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                text: card.session.fixResult
                background: null
                Accessible.name: i18n("Result")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Button {
                text: i18n("Replace")
                icon.name: "edit-paste"
                visible: card.session.fixReplaces && !card.fixing.terminal && (card.fixing.window || "").length > 0
                AssistantToolTip {
                    accent: card.accent
                    text: i18n("Put this in place of the selected text in %1", card.fixing.app || "")
                    visible: parent.hovered
                }
                onClicked: card.session.replaceSelection()
            }

            PlasmaComponents3.Button {
                text: i18n("Copy")
                icon.name: "edit-copy"
                onClicked: card.session.activateQuick({ kind: "quick", title: "", action: { type: "copy", target: card.session.fixResult } })
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: card.session.fixReplaces && card.fixing.terminal === true
                wrapMode: Text.Wrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: i18n("Happy Bot does not paste into terminals; copy it instead.")
            }
        }
    }
}
