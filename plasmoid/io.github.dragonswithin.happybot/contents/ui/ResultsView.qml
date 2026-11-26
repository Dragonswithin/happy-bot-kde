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
 * - The empty web finder shows WebStartPage.qml. Both finders, Help and System info
 *   keep the user's configured popup dimensions while their contents change.
 *
 * - FILES in the file finder, or while there are results, a search under
 *   way (`session.searchedText`) or a search problem: FileResults.qml (the
 *   matches, scrolling, with an "Ask Happy Bot to find" row pinned below
 *   them). The panel bar's own results show above the bar instead
 *   (PanelResults.qml), never here.
 * - ARTICLE while `session.article` is set (an offline Wikipedia article
 *   opened from "Search the web"'s Wikipedia results): ArticleView.qml. Back returns to the
 *   matches; "Ask about this" starts a request about the article.
 * - SYSTEM while `session.showingSystem` is true (the start screen's
 *   System info button): SystemInfoView.qml, which fills the body and
 *   scrolls. Back or Escape returns to the start screen.
 * - FIX while `session.fixing` is set (the "Fix selected text" shortcut):
 *   SelectionFixCard.qml, the selected text with its rewrite buttons and
 *   the result. The field then takes an instruction for the text (main.qml),
 *   and Back or Escape ends it.
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
    // A full desktop capture includes overlays. Let the desktop draw through the
    // transparent popup while keeping its window open and its draft intact.
    opacity: session.capturing && !session.helpWindow ? 0 : 1
    property bool useRobotMascot: false
    readonly property string robotStyle: session.ui?.robot_style ?? "pip"
    readonly property color accent: useRobotMascot ? Look.mascotAccent : Kirigami.Theme.highlightColor
    readonly property int inset: Kirigami.Units.largeSpacing * 1.5
    readonly property string assistantIcon: Look.assistantIcon(useRobotMascot, robotStyle)
    property bool fieldAtBottom: false
    readonly property alias inputText: field.text
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26

    readonly property bool hasHits: session.hits.length > 0
    readonly property bool helpVisible: !!session.helpDraft
    readonly property bool hasSearchError: session.searchError.length > 0
    readonly property bool fixVisible: session.fixing !== null
    readonly property bool articleVisible: !fixVisible && session.article !== null
    readonly property bool systemVisible: !fixVisible && !articleVisible && session.showingSystem
    readonly property bool filesVisible: !fixVisible && !articleVisible && !systemVisible && (hasHits || hasSearchError || session.finding
        || session.searchedText.length > 0)
    readonly property bool conversationVisible: !filesVisible && !fixVisible && !articleVisible && !systemVisible
    readonly property bool sidebarVisible: session.history.length > 0 && !helpVisible
    readonly property int sidebarWidth: Kirigami.Units.gridUnit * 10
    readonly property string query: inputText.trim()
    readonly property bool webStartVisible: filesVisible && session.finder === "web" && !query.length
    property int webStartIndex: -1
    onWebStartVisibleChanged: webStartIndex = -1
    readonly property int maximumHeight: Kirigami.Units.gridUnit * heightInGridUnits
    readonly property bool fullSizeTool: session.finding || articleVisible || systemVisible
        || helpVisible || (conversationVisible && session.helpChat)
    readonly property real contentHeight: fixVisible
        ? fixCard.naturalHeight + inset * 2
        : filesVisible
        ? fileResults.naturalHeight
        : view.session.entries.count === 0
            ? welcomeArea.contentHeight
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
    implicitWidth: Kirigami.Units.gridUnit * widthInGridUnits + (session.history.length > 0 ? sidebarWidth : 0)
    // Rounded, and computed only from exact sizes (plain columns, never a
    // ListView's estimated contentHeight): the popup window resizes to this,
    // and anything that changed with the window's size would make it jump.
    implicitHeight: fullSizeTool ? maximumHeight : Math.round(Math.min(maximumHeight, inputBar.height
        + titleBar.implicitHeight + nudge.height + bodyHeight))

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
        if (webStartVisible) webStart.openSelectedMenu();
        else fileResults.openSelectedMenu();
    }

    function moveInField(delta) {
        if (webStartVisible)
            webStartIndex = Math.max(-1, Math.min(webStart.itemCount - 1, webStartIndex + delta));
        else
            selectionMove(delta);
    }

    function acceptField() {
        if (webStartVisible) webStart.activateSelected();
        else accepted(query);
    }

    // --- header band: title, status and actions ---------------------------
    Item {
        id: titleBar

        readonly property var heading: {
            if (view.fixVisible)
                return { text: i18n("Fix selected text"), icon: "document-edit" };
            if (view.articleVisible)
                return { text: i18n("Wikipedia"), icon: "documentation" };
            if (view.systemVisible)
                return { text: i18n("System info"), icon: "speedometer" };
            if (view.filesVisible) {
                return view.session.finder === "web"
                    ? { text: i18n("Search the web"), icon: "globe" }
                    : { text: i18n("Find a file"), icon: "folder-open-symbolic" };
            }
            if (view.helpVisible || view.session.helpChat) {
                const app = view.session.helpWindow?.app;
                return { text: app ? i18n("Help with %1", app) : i18n("Desktop help"), icon: "help-contents" };
            }
            if (view.session.hasTranscript) {
                const chat = view.session.history.find(item => item.id === view.session.conversationId);
                return { text: chat?.title || i18n("Chat with Happy Bot"), icon: view.assistantIcon };
            }
            return { text: i18n("Start screen"), icon: view.assistantIcon };
        }

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
                source: titleBar.heading.icon
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }

            PlasmaComponents3.Label {
                objectName: "viewHeading"
                Layout.maximumWidth: view.width * 0.5
                elide: Text.ElideRight
                text: titleBar.heading.text
                textFormat: Text.PlainText
                Accessible.role: Accessible.Heading
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

            // Leaves the file finder, or fixing selected text, for the welcome screen or the chat.
            PlasmaComponents3.ToolButton {
                icon.name: "go-previous"
                text: i18n("Back")
                visible: view.session.finding || view.fixVisible || view.systemVisible || view.helpVisible
                onClicked: {
                    if (view.helpVisible) {
                        view.session.dismissHelpDraft();
                        view.clearInput();
                        view.focusInput();
                    } else if (view.fixVisible) {
                        view.session.stopFixing();
                    } else if (view.systemVisible) {
                        view.session.closeSystemInfo();
                    } else if (view.articleVisible) {
                        if (!articleView.back()) {  // back through the pages followed, then to the matches
                            view.session.closeArticle();
                        }
                    } else {
                        view.session.stopFinding();
                    }
                }
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
                    readonly property bool buttonsOnLeft: field.effectiveHorizontalAlignment === TextInput.AlignRight
                    readonly property var margins: ({
                        left: Kirigami.Units.smallSpacing + (buttonsOnLeft ? fieldButtons.width : 0),
                        right: Kirigami.Units.smallSpacing + (buttonsOnLeft ? 0 : fieldButtons.width),
                        top: 0, bottom: 0
                    })
                    color: Kirigami.Theme.backgroundColor
                    radius: Kirigami.Units.cornerRadius * 2
                    border.color: field.activeFocus ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.25)
                }
                rightActions: []
                // Draw the microphone as full-colour artwork in the field. Plasma's
                // action delegate can render a themed, monochrome microphone.
                Row {
                    id: fieldButtons
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.margins: 1
                    spacing: Kirigami.Units.smallSpacing
                    LayoutMirroring.enabled: field.effectiveHorizontalAlignment === TextInput.AlignRight

                    component FieldButton: PlasmaComponents3.ToolButton {
                        height: fieldButtons.height
                        width: implicitHeight
                        focusPolicy: Qt.TabFocus
                        PlasmaComponents3.ToolTip.text: text
                        PlasmaComponents3.ToolTip.visible: hovered || activeFocus
                        PlasmaComponents3.ToolTip.delay: Kirigami.Units.toolTipDelay
                    }
                    FieldButton {
                        display: QQC2.AbstractButton.IconOnly
                        icon.name: "go-next"
                        icon.width: Kirigami.Units.iconSizes.sizeForLabels
                        icon.height: Kirigami.Units.iconSizes.sizeForLabels
                        text: view.selectedIndex >= 0 ? i18n("Open selected result") : i18n("Send request")
                        enabled: field.text.trim().length > 0 && !view.session.helpPending
                        onClicked: view.accepted(field.text.trim())
                    }
                    FieldButton {
                        visible: view.session.voiceEnabled
                        enabled: !view.session.helpPending
                        text: view.session.listening ? i18n("Stop listening") : i18n("Talk to Happy Bot")
                        Accessible.name: text
                        Accessible.checkable: true
                        Accessible.checked: view.session.listening
                        onClicked: view.talkRequested()
                        contentItem: Item {
                            implicitWidth: Kirigami.Units.iconSizes.sizeForLabels
                            implicitHeight: implicitWidth
                            Image {
                                anchors.centerIn: parent
                                width: parent.implicitWidth
                                height: width
                                source: view.session.listening ? Look.activeMicrophoneIcon : Look.microphoneIcon
                            }
                        }
                    }
                }
                placeholderText: view.session.listening ? i18n("Listening… talk, then pause")
                    : view.session.voiceProblem.length > 0 ? view.session.voiceProblem
                    : view.helpVisible ? i18n("Ask your question…")
                    : view.fixVisible ? i18n("Or say what to do with the text…")
                    : view.session.finder === "web" ? i18n("Search the web…")
                    : view.session.finding ? i18n("Type an app or file name…") : i18n("Ask or search anything…")
                onTextChanged: view.queryEdited(text)
                Keys.onReturnPressed: view.acceptField()
                Keys.onEnterPressed: view.acceptField()
                Keys.onDownPressed: view.moveInField(1)
                Keys.onUpPressed: view.moveInField(-1)
                Keys.onTabPressed: event => {
                    if (view.webStartVisible) event.accepted = false;
                    else view.completeRequested();
                }
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
                    } else if (view.helpVisible) {
                        view.session.dismissHelpDraft();
                    } else if (view.fixVisible) {
                        view.session.stopFixing();
                        view.closeRequested();
                    } else if (view.articleVisible) {
                        view.session.closeArticle();
                    } else if (view.systemVisible) {
                        view.session.closeSystemInfo();
                    } else if (view.session.finding) {
                        view.session.stopFinding();
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

    MascotNudge {
        id: nudge
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        kind: view.session.nudges?.[0] || ""
        needsSetup: view.session.needsSetup
        accent: view.accent
        visible: suggestion !== null && view.conversationVisible && !view.helpVisible && !view.session.busy && !view.session.listening
                 && !view.session.pendingApprovals && view.inputText.length === 0
        height: visible ? implicitHeight : 0
        onChosen: message => view.askRequested(message)
        onSetupRequested: view.settingsRequested()
        onDismissRequested: kind => {
            view.session.request("POST", "/icon/nudge/dismiss", { kind: kind }, () => {}, data => {
                if (nudge.kind === kind) nudge.problem = data.error || i18n("Could not dismiss this nudge.");
            });
        }
    }

    // --- body -----------------------------------------------------------------
    Item {
        id: body

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: nudge.bottom
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
                                onClicked: {
                                    view.session.openConversation(modelData.id);  // leaves a search or article first
                                    view.setInput("");
                                }
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
                visible: view.filesVisible && !view.webStartVisible
                session: view.session
                query: view.query
                selectedIndex: view.selectedIndex
                assistantIcon: view.assistantIcon
                useRobotMascot: view.useRobotMascot
                onResultActivated: hit => view.resultActivated(hit)
                onFileActionRequested: (hit, action) => view.fileActionRequested(hit, action)
                onAskRequested: text => view.askRequested(text)
            }

            WebStartPage {
                id: webStart
                anchors.fill: parent
                visible: view.webStartVisible
                sites: view.session.webStartData.sites ?? []
                searches: view.session.webStartData.searches ?? []
                historyEnabled: view.session.webStartData.history_enabled ?? view.session.ui.search_history ?? false
                loading: view.session.webStartLoading
                problem: view.session.webStartProblem
                accent: view.accent
                selectedIndex: view.webStartIndex
                onSitesChanged: view.webStartIndex = -1
                onSearchesChanged: view.webStartIndex = -1
                onSiteActivated: site => view.hitActivated(site.location)
                onSiteSearchRequested: host => {
                    view.setInput("site:" + host + " ");
                    view.focusInput();
                }
                onSiteActionRequested: (site, action) => view.session.changeWebSite(site.location, action)
                onSearchActivated: query => {
                    view.setInput(query);
                    view.focusInput();
                    view.session.rememberWebSearch(query);
                }
                onSettingsRequested: view.settingsRequested()
            }

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                visible: view.systemVisible
                QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

                Flickable {
                    contentWidth: width
                    contentHeight: systemInfo.implicitHeight + view.inset * 2
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true

                    SystemInfoView {
                        id: systemInfo
                        x: view.inset
                        y: view.inset
                        width: parent.width - view.inset * 2
                        visible: view.systemVisible  // it reads the system only while shown
                        session: view.session
                    }
                }
            }

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                visible: view.articleVisible
                QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

                Flickable {
                    id: articleFlick
                    contentWidth: width
                    // The page view scrolls itself and fills the body; the text view scrolls here.
                    contentHeight: articleView.webMode ? height : articleView.naturalHeight + view.inset * 2
                    interactive: !articleView.webMode
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true

                    // Each article opens at its top.
                    Connections {
                        target: view.session
                        function onArticleChanged() {
                            if (view.session.article && view.session.article.loading) {
                                articleFlick.contentY = 0;
                            }
                        }
                    }

                    ArticleView {
                        id: articleView
                        x: view.inset
                        y: view.inset
                        width: parent.width - view.inset * 2
                        height: webMode ? articleFlick.height - view.inset * 2 : implicitHeight
                        session: view.session
                        onLinkActivated: link => view.hitActivated(link)
                        onAskRequested: title => {
                            view.session.stopFinding();
                            view.setInput(i18n("About the Wikipedia article “%1”: ", title));
                            view.focusInput();
                        }
                    }
                }
            }

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                visible: view.fixVisible
                QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

                Flickable {
                    contentWidth: width
                    contentHeight: fixCard.naturalHeight + view.inset * 2
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true

                    SelectionFixCard {
                        id: fixCard
                        x: view.inset
                        y: view.inset
                        width: parent.width - view.inset * 2
                        session: view.session
                    }
                }
            }

            PlasmaComponents3.ScrollView {
                id: transcriptView
                anchors.fill: parent
                visible: view.conversationVisible && !view.helpVisible && view.session.entries.count > 0
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
                                robotStyle: view.robotStyle
                                width: transcriptColumn.width
                                onLinkActivated: link => view.hitActivated(link)
                                choicesEnabled: !view.session.busy
                                onChoiceChosen: text => view.askRequested(text)
                                onApprovalAnswered: (approvalId, decision, remember) =>
                                    view.session.answerApproval(approvalId, decision, remember)
                                onSettingsRequested: view.settingsRequested()
                            }
                        }
                        Flow {
                            width: parent.width
                            visible: view.session.helpChat && !view.session.busy && view.session.hasTranscript
                            spacing: Kirigami.Units.smallSpacing
                            PlasmaComponents3.Button {
                                text: i18n("Next step")
                                visible: view.session.walkthrough
                                onClicked: view.askRequested(text)
                            }
                            PlasmaComponents3.Button {
                                text: i18n("I don’t see that")
                                visible: view.session.walkthrough
                                onClicked: {
                                    if (!view.inputText.trim()) view.setInput(text);
                                    view.session.captureForHelp();
                                    view.focusInput();
                                }
                            }
                            PlasmaComponents3.Button {
                                text: i18n("Update screenshot")
                                icon.name: "camera-photo"
                                onClicked: { view.session.captureForHelp(); view.focusInput(); }
                            }
                        }
                    }
                }
            }

            HelpPreview {
                id: helpPreview
                anchors.fill: parent
                visible: view.conversationVisible && view.helpVisible
                session: view.session
                onFocusQuestion: view.focusInput()
                onExplainRequested: {
                    if (!view.inputText.trim()) view.setInput(i18n("What does this error mean and how can I fix it?"));
                    view.focusInput();
                }
            }

            PlasmaComponents3.ScrollView {
                anchors.fill: parent
                visible: view.conversationVisible && !view.helpVisible && view.session.entries.count === 0

                Flickable {
                    id: welcomeArea
                    contentWidth: width
                    contentHeight: welcome.implicitHeight + view.inset * 2
                    clip: true

                    AssistantWelcome {
                        id: welcome
                        visible: !view.helpVisible
                        locatingApplication: view.session.locatingApplication
                        x: view.inset
                        y: Math.max(view.inset, (welcomeArea.height - height) / 2)
                        width: Math.max(1, welcomeArea.width - view.inset * 2)
                        assistantIcon: view.assistantIcon
                        robotStyle: view.robotStyle
                        accent: view.accent
                        animateGreeting: view.useRobotMascot && view.session.ui.mascot_animations !== false
                        helpWith: view.session.helpWith
                        helpWithIcon: view.session.helpWithIcon
                        onFindFilesChosen: {
                            view.session.startFinding("files");
                            view.setInput("");
                            view.focusInput();
                        }
                        buttons: view.session.ui.start_screen || ["files", "web", "help"]
                        onSystemInfoChosen: view.session.showSystemInfo()
                        onWebSearchChosen: {
                            view.session.startFinding("web");
                            view.setInput("");
                            view.focusInput();
                        }
                        onHelpChosen: {
                            view.session.captureForHelp();
                            view.focusInput();
                        }
                    }
                }
            }
        }
    }
}
