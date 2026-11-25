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
 * The panel popup and floating assistant share this frame, header and composer.
 * The field sits on the side nearest the launcher with the chat's AI picker.
 *
 * The body shows one thing at a time:
 *
 * - FILES in the file finder, or while there are results, a search under
 *   way (`session.searchedText`) or a search problem: FileResults.qml (the
 *   matches, scrolling, with an "Ask Happy Bot to find" row pinned below
 *   them). The panel bar's own results show above the bar instead
 *   (PanelResults.qml), never here.
 * - ASSISTANT otherwise: the welcome screen or the conversation,
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
 * - `queryEdited(text)`: the text changed. `accepted(text)`: Enter, trimmed.
 *   `askRequested(text)`: the Ask row under the results was clicked, which
 *   always asks the assistant whatever result is selected, or one of the
 *   answer buttons the assistant offered in the conversation.
 *   `talkRequested()`: the microphone in the field (shown when
 *   `session.voiceEnabled`), to start or stop listening. `selectionMove(delta)`: Down (+1) or Up (-1).
 *   `completeRequested()`: Tab, to complete the text from the top result. Escape
 *   clears the text, or closes when it is already empty (`closeRequested`).
 * - `resultActivated(hit)`: a clicked file match or quick result.
 * - `fileActionRequested(hit, action)`: a file match's menu (right-click,
 *   or the Menu key or Shift+F10 on the selected match):
 *   "reveal" (show in folder), "copy" (its path) or "ask" (about it). A
 *   file match can also be dragged into another application, and files
 *   dropped onto the popup emit `filesDropped(paths)`.
 * - `hitActivated(location)`: a link clicked in an answer.
 * - `closeRequested`, `settingsRequested`: the Close button, and the Settings
 *   (gear) button in the header or an "Open settings" button on a setup card.
 *
 * The view sets its own width and height: Plasma's popup window follows its
 * content's actual size, not its implicit size.
 */
Rectangle {
    id: view

    radius: Kirigami.Units.cornerRadius * 3
    color: Kirigami.Theme.backgroundColor
    border.color: Qt.alpha(Kirigami.Theme.textColor, 0.2)
    clip: true

    required property var session
    property bool useRobotMascot: false
    readonly property color accent: useRobotMascot ? "#72c8bf" : Kirigami.Theme.highlightColor
    readonly property int inset: Kirigami.Units.largeSpacing * 1.5
    readonly property string assistantIcon: Look.assistantIcon(useRobotMascot)
    property bool fieldAtBottom: false
    readonly property alias inputText: field.text
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26

    readonly property bool hasHits: session.hits.length > 0
    readonly property bool hasSearchError: session.searchError.length > 0
    readonly property bool filesVisible: hasHits || hasSearchError || session.findingFiles
        || session.searchedText.length > 0
    readonly property bool conversationVisible: !filesVisible
    readonly property bool sidebarVisible: session.history.length > 0
    readonly property int sidebarWidth: Kirigami.Units.gridUnit * 10
    readonly property string query: inputText.trim()
    readonly property int maximumHeight: Kirigami.Units.gridUnit * heightInGridUnits
    readonly property real contentHeight: filesVisible
        ? fileResults.naturalHeight
        : view.session.entries.count === 0
            ? welcome.implicitHeight + inset * 2
            : transcriptColumn.implicitHeight + view.inset * 2
    readonly property real bodyHeight: sidebarVisible
        ? Math.max(contentHeight, Math.min(historyHeader.height + historyColumn.implicitHeight, Kirigami.Units.gridUnit * 16))
        : contentHeight

    signal queryEdited(string text)
    signal accepted(string text)
    signal askRequested(string text)
    signal talkRequested()
    signal selectionMove(int delta)
    signal completeRequested()
    signal hitActivated(string location)
    signal resultActivated(var hit)
    signal fileActionRequested(var hit, string action)
    signal filesDropped(var paths)

    DropArea {
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: drop => {
            const paths = (drop.urls || []).map(url => decodeURIComponent(String(url).replace(/^file:\/\//, "")));
            if (paths.length > 0) {
                view.filesDropped(paths);
                drop.accept(Qt.CopyAction);
            }
        }
    }
    signal closeRequested()
    signal settingsRequested()

    width: implicitWidth
    height: implicitHeight
    implicitWidth: Kirigami.Units.gridUnit * widthInGridUnits + (sidebarVisible ? sidebarWidth : 0)
    // Rounded, and computed only from exact sizes (plain columns, never a
    // ListView's estimated contentHeight): the popup window resizes to this,
    // and anything that changed with the window's size would make it jump.
    implicitHeight: Math.round(Math.min(maximumHeight, inputBar.height
        + titleBar.implicitHeight + bodyHeight))

    function focusInput() {
        inputBar.forceFieldFocus();
    }

    function clearInput() {
        inputBar.text = "";
    }

    function setInput(text) {
        inputBar.text = text;
        inputBar.cursorPosition = text.length;
    }

    // The selected match's row answers this by opening its own menu.
    function openSelectedMenu() {
        fileResults.openSelectedMenu();
    }

    // --- header band: title, status and actions ---------------------------
    Item {
        id: titleBar

        anchors.left: parent.left
        anchors.right: parent.right
        // Placed by y, not by switching anchors (see inputBar).
        y: view.fieldAtBottom ? 0 : inputBar.height
        implicitHeight: headerRow.implicitHeight + Kirigami.Units.smallSpacing * 2
        height: implicitHeight

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Qt.alpha(Kirigami.Theme.textColor, 0.12)
        }
        RowLayout {
            id: headerRow
            anchors.fill: parent
            anchors.leftMargin: view.inset
            anchors.rightMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: view.filesVisible ? "folder-documents-symbolic" : view.assistantIcon
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            PlasmaComponents3.Label {
                text: view.filesVisible ? i18n("Find a file") : i18n("Happy Bot")
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.1
                font.weight: Font.DemiBold
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

            // Leaves this chat for the welcome screen; the chat stays in the saved ones.
            PlasmaComponents3.ToolButton {
                icon.name: "go-home"
                text: i18n("Close chat")
                visible: view.conversationVisible && view.session.hasTranscript
                PlasmaComponents3.ToolTip.text: i18n("Back to the start. This chat stays in your saved chats.")
                PlasmaComponents3.ToolTip.visible: hovered
                onClicked: view.session.newChat()
            }

            // Leaves the file finder for the welcome screen or the chat.
            PlasmaComponents3.ToolButton {
                icon.name: "go-previous"
                text: i18n("Back")
                visible: view.session.findingFiles
                onClicked: view.session.stopFindingFiles()
            }

            PlasmaComponents3.ToolButton {
                icon.name: "configure"
                text: i18n("Settings")
                display: QQC2.AbstractButton.IconOnly
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
                onClicked: view.settingsRequested()
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
    Item {
        id: inputBar

        property alias text: field.text
        property alias cursorPosition: field.cursorPosition

        function forceFieldFocus() {
            field.forceActiveFocus();
        }

        anchors.left: parent.left
        anchors.right: parent.right
        // At the bottom or the top by y. Switching anchors.top and anchors.bottom at run time
        // (the floating button moving across the screen's middle) left the band anchored to both
        // for a moment: it stretched over the whole view and kept that height, hiding everything
        // but the field (tests/tst_FieldSide.qml).
        y: view.fieldAtBottom ? view.height - height : 0
        height: implicitHeight
        implicitHeight: composer.implicitHeight + Kirigami.Units.largeSpacing * 2

        Rectangle {
            y: view.fieldAtBottom ? 0 : parent.height - height
            width: parent.width
            height: 1
            color: Qt.alpha(Kirigami.Theme.textColor, 0.12)
        }
        RowLayout {
            id: composer
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing

            PlasmaExtras.SearchField {
                id: field
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredHeight: Math.max(implicitHeight, Kirigami.Units.gridUnit * 2)
                background: Rectangle {
                    readonly property var margins: ({ left: Kirigami.Units.smallSpacing, right: Kirigami.Units.smallSpacing, top: 0, bottom: 0 })
                    color: Kirigami.Theme.backgroundColor
                    radius: Kirigami.Units.cornerRadius * 2
                    border.color: field.activeFocus ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.25)
                }
                rightActions: [
                    // Talk instead of typing: shown when voice is on in the settings; click again to stop.
                    Kirigami.Action {
                        text: view.session.listening ? i18n("Stop listening") : i18n("Talk to Happy Bot")
                        icon.name: view.session.listening ? "media-record" : "audio-input-microphone"
                        visible: view.session.voiceEnabled
                        checkable: true
                        checked: view.session.listening
                        onTriggered: view.talkRequested()
                    },
                    Kirigami.Action {
                        text: view.selectedIndex >= 0 ? i18n("Open selected result") : i18n("Send request")
                        icon.name: "go-next"
                        enabled: field.text.trim().length > 0
                        onTriggered: view.accepted(field.text.trim())
                    }
                ]
                placeholderText: view.session.listening ? i18n("Listening… talk, then pause")
                    : view.session.voiceProblem.length > 0 ? view.session.voiceProblem
                    : view.session.findingFiles ? i18n("Type an app or file name…") : i18n("Ask or search anything…")
                onTextChanged: view.queryEdited(text)
                Keys.onReturnPressed: view.accepted(text.trim())
                Keys.onEnterPressed: view.accepted(text.trim())
                Keys.onDownPressed: view.selectionMove(1)
                Keys.onUpPressed: view.selectionMove(-1)
                Keys.onTabPressed: view.completeRequested()
                // The Menu key (or Shift+F10) opens the selected match's actions, as a right-click does.
                Keys.onMenuPressed: view.openSelectedMenu()
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)) {
                        view.openSelectedMenu();
                        event.accepted = true;
                    }
                }
                Keys.onEscapePressed: {
                    if (text.length > 0) {
                        text = "";
                    } else if (view.session.findingFiles) {
                        view.session.stopFindingFiles();
                    } else {
                        view.closeRequested();
                    }
                }
            }

            // Which AI this chat uses; only when more than one is set up.
            ModelPicker {
                session: view.session
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
        clip: true

        // --- sidebar: saved conversations ---------------------------------
        Rectangle {
            id: sidebar
            color: Qt.alpha(Kirigami.Theme.textColor, 0.032)

            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: view.sidebarVisible ? view.sidebarWidth : 0
            visible: view.sidebarVisible

            PlasmaComponents3.Label {
                id: historyHeader
                anchors.left: parent.left
                anchors.right: parent.right
                leftPadding: view.inset
                topPadding: view.inset
                bottomPadding: Kirigami.Units.smallSpacing
                text: i18n("Conversations")
                font: Kirigami.Theme.smallFont
                opacity: 0.78
                elide: Text.ElideRight
            }

            PlasmaComponents3.ScrollView {
                anchors.top: historyHeader.bottom
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
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

                                x: Kirigami.Units.smallSpacing
                                width: historyColumn.width - x * 2
                                padding: Kirigami.Units.largeSpacing
                                background: Rectangle {
                                    radius: Kirigami.Units.cornerRadius * 2
                                    color: saved.highlighted ? Qt.alpha(view.accent, 0.14)
                                        : saved.hovered ? Qt.alpha(Kirigami.Theme.textColor, 0.07) : "transparent"
                                    border.color: saved.visualFocus ? Kirigami.Theme.highlightColor : "transparent"
                                }
                                Accessible.name: i18n("Conversation: %1", modelData.title)
                                highlighted: modelData.id === view.session.conversationId
                                onClicked: view.session.openConversation(modelData.id)
                                PlasmaComponents3.ToolTip.text: modelData.title
                                PlasmaComponents3.ToolTip.visible: hovered && titleLabel.truncated
                                PlasmaComponents3.ToolTip.delay: Kirigami.Units.toolTipDelay

                                contentItem: RowLayout {
                                    spacing: Kirigami.Units.smallSpacing

                                    Kirigami.Icon {
                                        source: "dialog-messages"
                                        Layout.alignment: Qt.AlignTop
                                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                        opacity: 0.65
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: Kirigami.Units.smallSpacing / 2

                                        PlasmaComponents3.Label {
                                            id: titleLabel
                                            Layout.fillWidth: true
                                            text: saved.modelData.title || i18n("Untitled")
                                            font.weight: saved.highlighted ? Font.DemiBold : Font.Normal
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
                                        icon.name: "pin"
                                        text: saved.modelData.pinned ? i18n("Unpin") : i18n("Pin: keep it at the top and never expire it")
                                        display: QQC2.AbstractButton.IconOnly
                                        checkable: true
                                        checked: saved.modelData.pinned === true
                                        visible: saved.hovered || saved.highlighted || checked
                                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                        PlasmaComponents3.ToolTip.text: text
                                        PlasmaComponents3.ToolTip.visible: hovered
                                        onToggled: view.session.pinConversation(saved.modelData.id, checked)
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
                opacity: 0.45
            }
        }

        // --- files or conversation -----------------------------------------
        Item {
            id: content

            anchors.left: sidebar.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom

            FileResults {
                id: fileResults

                anchors.fill: parent
                visible: view.filesVisible
                session: view.session
                query: view.query
                selectedIndex: view.selectedIndex
                assistantIcon: view.assistantIcon
                useRobotMascot: view.useRobotMascot
                onResultActivated: hit => view.resultActivated(hit)
                onFileActionRequested: (hit, action) => view.fileActionRequested(hit, action)
                onAskRequested: text => view.askRequested(text)
            }

            PlasmaComponents3.ScrollView {
                id: transcriptView
                anchors.fill: parent
                visible: view.conversationVisible && view.session.entries.count > 0
                // Keep the line width stable when the first overflowing line reveals the scrollbar.
                leftPadding: mirrored ? QQC2.ScrollBar.vertical.implicitWidth : 0
                rightPadding: mirrored ? 0 : QQC2.ScrollBar.vertical.implicitWidth
                QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

                Flickable {
                    id: transcript

                    contentWidth: width
                    contentHeight: transcriptColumn.implicitHeight + view.inset * 2
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true

                    property bool followingEnd: true
                    readonly property real bottomY: originY + Math.max(0, contentHeight - height)

                    function followEnd() {
                        if (followingEnd && !moving && !transcriptView.QQC2.ScrollBar.vertical.pressed) {
                            contentY = bottomY;
                        }
                    }

                    // A wheel, drag or scrollbar movement can leave the bottom.
                    // Incoming text alone changes the extent, not the reader's intent.
                    onContentYChanged: followingEnd = contentY >= bottomY - 1
                    onContentHeightChanged: Qt.callLater(followEnd)
                    onHeightChanged: Qt.callLater(followEnd)
                    onMovementEnded: Qt.callLater(followEnd)

                    function resumeFollowing() {
                        followingEnd = true;
                        Qt.callLater(followEnd);
                    }
                    Connections {
                        target: view.session
                        function onConversationIdChanged() { transcript.resumeFollowing(); }
                        function onBusyChanged() {
                            if (view.session.busy) transcript.resumeFollowing();
                        }
                    }

                    Column {
                        id: transcriptColumn

                        x: view.inset
                        y: view.inset
                        width: transcript.width - view.inset * 2
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: view.session.entries

                            TranscriptEntry {
                                useRobotMascot: view.useRobotMascot
                                width: transcriptColumn.width
                                onLinkActivated: link => view.hitActivated(link)
                                choicesEnabled: !view.session.busy
                                onChoiceChosen: text => view.askRequested(text)
                                onApprovalAnswered: (approvalId, decision, remember) =>
                                    view.session.answerApproval(approvalId, decision, remember)
                                onSettingsRequested: view.settingsRequested()
                            }
                        }
                    }
                }
            }

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                visible: view.conversationVisible && view.session.entries.count === 0

                Flickable {
                    id: welcomeArea
                    contentWidth: width
                    contentHeight: welcome.implicitHeight + view.inset * 2
                    clip: true

                    AssistantWelcome {
                        id: welcome
                        x: view.inset
                        y: Math.max(view.inset, (welcomeArea.height - height) / 2)
                        width: Math.max(1, welcomeArea.width - view.inset * 2)
                        assistantIcon: view.assistantIcon
                        accent: view.accent
                        helpWith: view.session.helpWith
                        helpWithIcon: view.session.helpWithIcon
                        onFindFilesChosen: {
                            view.session.startFindingFiles();
                            view.setInput("");
                            view.focusInput();
                        }
                        onHelpChosen: prompt => {
                            view.session.helpChat = true;
                            view.session.captureForHelp();
                            welcome.promptChosen(prompt);
                        }
                        onPromptChosen: prompt => {
                            view.setInput(prompt);
                            view.focusInput();
                        }
                    }
                }
            }
        }
    }
}
