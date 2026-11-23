/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

/**
 * Everything inside the assistant's popup, laid out like Plasma's own
 * launcher: a header band (title, status, Stop, New, Close), a body, and the
 * input field in a footer band on the side facing the panel. With nothing
 * to show the view is just the field.
 *
 * The body shows one thing at a time:
 *
 * - FILES while there are file matches (or a search problem) for the typed
 *   text: one row per match (file-type icon, name, folder), then an "Ask the
 *   assistant" row. That row is highlighted while no match is selected, so
 *   it is visible that Enter will ask rather than open a file.
 * - ASSISTANT otherwise, when `showConversation` is set: the conversation,
 *   whose rows are TranscriptEntry.qml. It sizes to its content up to
 *   `heightInGridUnits` and then scrolls, keeping the newest part in view.
 *
 * Saved conversations are listed in a sidebar on the left whenever the body
 * is showing and there are any: title and when it was last used, the open
 * one highlighted, a delete button on hover. Clicking one reopens it
 * (`session.openConversation`); the box widens by the sidebar's width.
 *
 * ResultsPopup.qml wraps this in the popup window; keeping the content in
 * its own item lets it be rendered and checked outside Plasma. `session` is
 * the AssistantSession.qml instance. Selection and visibility rules belong
 * to main.qml; this view only draws `selectedIndex` and reports intent:
 *
 * - `queryEdited(text)`: the text changed. `accepted(text)`: Enter (or the
 *   Ask row), trimmed. `selectionMove(delta)`: Down (+1) or Up (-1). Escape
 *   clears the text, or closes when it is already empty (`closeRequested`).
 * - `hitActivated(location)`: a clicked result or a link in an answer.
 * - `closeRequested`, `settingsRequested`: the Close and Open settings buttons.
 *
 * The view sets its own width and height: Plasma's popup window follows its
 * content's actual size, not its implicit size.
 */
Item {
    id: view

    required property var session
    property bool fieldAtBottom: false
    property bool showConversation: false
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26

    readonly property bool hasHits: session.hits.length > 0
    readonly property bool hasSearchError: session.searchError.length > 0
    readonly property bool filesVisible: hasHits || hasSearchError
    readonly property bool conversationVisible: showConversation && !filesVisible
    readonly property bool bodyHasContent: filesVisible || conversationVisible
    readonly property bool sidebarVisible: bodyHasContent && session.history.length > 0
    readonly property int sidebarWidth: Kirigami.Units.gridUnit * 10
    readonly property string query: inputBar.text.trim()
    readonly property int maximumHeight: Kirigami.Units.gridUnit * heightInGridUnits
    readonly property real contentHeight: filesVisible
        ? filesColumn.implicitHeight
        : view.session.entries.count === 0
            ? Kirigami.Units.gridUnit * 12
            : transcriptColumn.implicitHeight + Kirigami.Units.smallSpacing * 2
    readonly property real bodyHeight: sidebarVisible
        ? Math.max(contentHeight, Math.min(historyColumn.implicitHeight, Kirigami.Units.gridUnit * 16))
        : contentHeight

    signal queryEdited(string text)
    signal accepted(string text)
    signal selectionMove(int delta)
    signal hitActivated(string location)
    signal closeRequested()
    signal settingsRequested()

    width: implicitWidth
    height: implicitHeight
    implicitWidth: Kirigami.Units.gridUnit * widthInGridUnits + (sidebarVisible ? sidebarWidth : 0)
    // Rounded, and computed only from exact sizes (plain columns, never a
    // ListView's estimated contentHeight): the popup window resizes to this,
    // and anything that changed with the window's size would make it jump.
    implicitHeight: Math.round(Math.min(maximumHeight, inputBar.implicitHeight
        + (bodyHasContent ? titleBar.implicitHeight + bodyHeight : 0)))

    function focusInput() {
        inputBar.forceFieldFocus();
    }

    function clearInput() {
        inputBar.text = "";
    }

    // --- header band: title, status and actions ---------------------------
    PlasmaExtras.PlasmoidHeading {
        id: titleBar

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: view.fieldAtBottom ? parent.top : inputBar.bottom
        visible: view.bodyHasContent
        position: view.fieldAtBottom ? QQC2.ToolBar.Header : QQC2.ToolBar.Footer

        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: view.filesVisible ? "folder-documents-symbolic" : Look.assistantIcon
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                opacity: 0.7
            }

            PlasmaExtras.Heading {
                level: 5
                text: view.filesVisible ? i18n("Files") : i18n("Assistant")
                opacity: 0.8
            }

            PlasmaComponents3.BusyIndicator {
                running: view.conversationVisible && view.session.busy
                visible: running
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: view.conversationVisible && view.session.busy ? view.session.statusText : ""
                elide: Text.ElideRight
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            // The actions keep their space in Files mode so the band's height
            // does not change when the body switches.
            PlasmaComponents3.ToolButton {
                text: i18n("Stop")
                visible: view.session.busy
                enabled: view.conversationVisible
                opacity: view.conversationVisible ? 1 : 0
                onClicked: view.session.cancel()
            }

            PlasmaComponents3.ToolButton {
                icon.name: "edit-clear-history"
                text: i18n("New conversation")
                display: QQC2.AbstractButton.IconOnly
                enabled: view.conversationVisible
                opacity: view.conversationVisible ? 1 : 0
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
                onClicked: view.session.newChat()
            }

            PlasmaComponents3.ToolButton {
                icon.name: "window-close"
                text: i18n("Close (Esc)")
                display: QQC2.AbstractButton.IconOnly
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
                onClicked: view.closeRequested()
            }
        }
    }

    // --- footer band: the field --------------------------------------------
    PlasmaExtras.PlasmoidHeading {
        id: inputBar

        property alias text: field.text

        function forceFieldFocus() {
            field.forceActiveFocus();
        }

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: view.fieldAtBottom ? undefined : parent.top
        anchors.bottom: view.fieldAtBottom ? parent.bottom : undefined
        position: view.fieldAtBottom ? QQC2.ToolBar.Footer : QQC2.ToolBar.Header

        contentItem: PlasmaExtras.SearchField {
            id: field
            placeholderText: i18n("Ask or search anything…")
            onTextChanged: view.queryEdited(text)
            Keys.onReturnPressed: view.accepted(text.trim())
            Keys.onEnterPressed: view.accepted(text.trim())
            Keys.onDownPressed: view.selectionMove(1)
            Keys.onUpPressed: view.selectionMove(-1)
            Keys.onEscapePressed: {
                if (text.length > 0) {
                    text = "";
                } else {
                    view.closeRequested();
                }
            }
        }
    }

    // --- body -----------------------------------------------------------------
    Item {
        id: body

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        anchors.bottom: view.fieldAtBottom ? inputBar.top : parent.bottom
        visible: view.bodyHasContent
        clip: true

        // --- sidebar: saved conversations ---------------------------------
        Item {
            id: sidebar

            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: view.sidebarVisible ? view.sidebarWidth : 0
            visible: view.sidebarVisible

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                anchors.rightMargin: 1

                Flickable {
                    contentWidth: width
                    contentHeight: historyColumn.implicitHeight
                    clip: true

                    Column {
                        id: historyColumn

                        width: parent.width
                        topPadding: Kirigami.Units.smallSpacing
                        bottomPadding: Kirigami.Units.smallSpacing

                        Repeater {
                            model: view.session.history

                            PlasmaComponents3.ItemDelegate {
                                id: saved

                                required property var modelData

                                width: historyColumn.width
                                highlighted: modelData.id === view.session.conversationId
                                onClicked: view.session.openConversation(modelData.id)
                                PlasmaComponents3.ToolTip.text: modelData.title
                                PlasmaComponents3.ToolTip.visible: hovered && titleLabel.truncated
                                PlasmaComponents3.ToolTip.delay: Kirigami.Units.toolTipDelay

                                contentItem: RowLayout {
                                    spacing: Kirigami.Units.smallSpacing

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0

                                        PlasmaComponents3.Label {
                                            id: titleLabel
                                            Layout.fillWidth: true
                                            text: saved.modelData.title || i18n("Untitled")
                                            elide: Text.ElideRight
                                            textFormat: Text.PlainText
                                        }

                                        PlasmaComponents3.Label {
                                            Layout.fillWidth: true
                                            text: Look.when(saved.modelData.updated)
                                            elide: Text.ElideRight
                                            font: Kirigami.Theme.smallFont
                                            opacity: 0.6
                                        }
                                    }

                                    PlasmaComponents3.ToolButton {
                                        icon.name: "edit-delete"
                                        text: i18n("Delete this conversation")
                                        display: QQC2.AbstractButton.IconOnly
                                        visible: saved.hovered || saved.highlighted
                                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                        PlasmaComponents3.ToolTip.text: text
                                        PlasmaComponents3.ToolTip.visible: hovered
                                        onClicked: view.session.deleteConversation(saved.modelData.id)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Kirigami.Separator {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
            }
        }

        // --- files or conversation -----------------------------------------
        Item {
            id: content

            anchors.left: sidebar.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: view.sidebarVisible ? Kirigami.Units.smallSpacing : 0

            ColumnLayout {
                id: filesColumn

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                visible: view.filesVisible
                spacing: 0

                Repeater {
                    model: view.session.hits

                    PlasmaComponents3.ItemDelegate {
                        id: row

                        required property int index
                        required property var modelData

                        Layout.fillWidth: true
                        highlighted: index === view.selectedIndex
                        onClicked: view.hitActivated(modelData.location)

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.largeSpacing

                            Kirigami.Icon {
                                source: Look.hitIcon(row.modelData)
                                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: row.modelData.title
                                    elide: Text.ElideRight
                                    textFormat: Text.PlainText
                                }

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: Look.hitWhere(row.modelData)
                                    elide: Text.ElideMiddle
                                    textFormat: Text.PlainText
                                    font: Kirigami.Theme.smallFont
                                    opacity: 0.65
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: Kirigami.Units.smallSpacing
                    visible: view.hasSearchError
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Icon {
                        source: "dialog-warning"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: view.session.searchErrorCode === "not_configured"
                            ? i18n("File search is not set up yet.")
                            : i18n("File search is not responding. Try again in a moment.")
                        wrapMode: Text.Wrap
                        PlasmaComponents3.ToolTip.text: view.session.searchError
                        PlasmaComponents3.ToolTip.visible: errorHover.hovered && view.session.searchErrorCode !== "not_configured"

                        HoverHandler {
                            id: errorHover
                        }
                    }
                }

                PlasmaComponents3.ItemDelegate {
                    Layout.fillWidth: true
                    visible: view.query.length > 0
                    highlighted: view.selectedIndex < 0
                    onClicked: view.accepted(view.query)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.largeSpacing

                        Kirigami.Icon {
                            source: Look.assistantIcon
                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                text: i18n("Ask the assistant: “%1”", view.query)
                                elide: Text.ElideRight
                                textFormat: Text.PlainText
                            }

                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                text: i18n("Press Enter")
                                font: Kirigami.Theme.smallFont
                                opacity: 0.65
                            }
                        }
                    }
                }
            }

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                visible: view.conversationVisible

                Flickable {
                    id: transcript

                    contentWidth: width
                    contentHeight: transcriptColumn.implicitHeight + Kirigami.Units.smallSpacing * 2
                    clip: true

                    // Keep the newest part of the conversation in view.
                    function followEnd() {
                        Qt.callLater(function() {
                            transcript.contentY = Math.max(0, transcript.contentHeight - transcript.height);
                        });
                    }
                    onContentHeightChanged: followEnd()
                    onHeightChanged: followEnd()

                    Column {
                        id: transcriptColumn

                        y: Kirigami.Units.smallSpacing
                        width: transcript.width - Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: view.session.entries

                            TranscriptEntry {
                                width: transcriptColumn.width
                                onLinkActivated: link => view.hitActivated(link)
                                onApprovalAnswered: (approvalId, decision, remember) =>
                                    view.session.answerApproval(approvalId, decision, remember)
                                onSettingsRequested: view.settingsRequested()
                            }
                        }
                    }
                }
            }

            PlasmaExtras.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 2
                visible: view.conversationVisible && view.session.entries.count === 0
                iconName: Look.assistantIcon
                text: i18n("Ask anything")
                explanation: i18n("Find files, look things up on the web, or have the computer do something for you.")
            }
        }
    }
}
