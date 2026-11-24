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
 * input field in a footer band on the side facing the panel, with the
 * chat's AI picker (ModelPicker.qml) beside it when two or more AIs are set
 * up (`alwaysShowHeader`, set by the floating Happy Bot, keeps the header and
 * its close button even when only the field shows); the picker goes in the
 * header instead when the field is hidden. With nothing
 * to show the view is just the field. When the user types in the panel's
 * search bar instead (PanelBar.qml), `showField` is false, the field is
 * hidden, and `barText` is the text typed there.
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
 *   Ask row), trimmed. `selectionMove(delta)`: Down (+1) or Up (-1).
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
Item {
    id: view

    required property var session
    property bool useRobotMascot: false
    readonly property string assistantIcon: Look.assistantIcon(useRobotMascot)
    property bool fieldAtBottom: false
    property bool showField: true
    // The header (title, Stop, New, Settings, Close) even when nothing else shows: the floating
    // Happy Bot is a window of its own, so its close button must always be there.
    property bool alwaysShowHeader: false
    readonly property bool headerVisible: bodyHasContent || alwaysShowHeader
    property string barText: ""
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
    readonly property string query: (showField ? inputBar.text : barText).trim()
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
        + (headerVisible ? titleBar.implicitHeight : 0) + (bodyHasContent ? bodyHeight : 0)))

    function focusInput() {
        inputBar.forceFieldFocus();
    }

    function clearInput() {
        inputBar.text = "";
    }

    function setInput(text) {
        inputBar.text = text;
    }

    // The selected match's row answers this by opening its own menu.
    signal selectedMenuRequested()

    function openSelectedMenu() {
        view.selectedMenuRequested();
    }

    // --- header band: title, status and actions ---------------------------
    PlasmaExtras.PlasmoidHeading {
        id: titleBar

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: view.fieldAtBottom ? parent.top : inputBar.bottom
        visible: view.headerVisible
        position: view.fieldAtBottom ? QQC2.ToolBar.Header : QQC2.ToolBar.Footer

        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: view.filesVisible ? "folder-documents-symbolic" : view.assistantIcon
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                opacity: 0.7
            }

            PlasmaExtras.Heading {
                level: 5
                text: view.filesVisible ? i18n("Files") : view.bodyHasContent ? i18n("Assistant") : i18n("Happy Bot")
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

            // When the user types in the panel's search bar this view has no field,
            // so the chat's AI picker sits here instead.
            ModelPicker {
                session: view.session
                visible: !view.showField && view.conversationVisible && view.session.models.length > 1
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
        height: view.showField ? implicitHeight : 0
        visible: view.showField
        position: view.fieldAtBottom ? QQC2.ToolBar.Footer : QQC2.ToolBar.Header

        contentItem: ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                PlasmaExtras.SearchField {
                    id: field
                    Layout.fillWidth: true
                    placeholderText: i18n("Ask or search anything…")
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
                                Accessible.name: i18n("Conversation: %1", modelData.title)
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

                        Connections {
                            target: view
                            function onSelectedMenuRequested() {
                                if (row.index === view.selectedIndex && row.modelData.kind !== "quick") {
                                    fileMenu.popup(row, 0, row.height);
                                }
                            }
                        }

                        Layout.fillWidth: true
                        highlighted: index === view.selectedIndex
                        Accessible.name: Look.hitWhere(modelData).length > 0
                            ? i18n("%1, in %2", modelData.title, Look.hitWhere(modelData)) : modelData.title
                        onClicked: view.resultActivated(modelData)

                        // A file match can be dragged into another application.
                        Drag.dragType: Drag.Automatic
                        Drag.supportedActions: Qt.CopyAction
                        Drag.mimeData: row.modelData.kind === "quick" ? ({})
                            : ({ "text/uri-list": row.modelData.location.indexOf("://") > 0 ? row.modelData.location
                                                  : "file://" + encodeURI(row.modelData.location),
                                 "text/plain": row.modelData.location })
                        Drag.active: rowDrag.active
                        DragHandler {
                            id: rowDrag
                            enabled: row.modelData.kind !== "quick"
                            target: null
                        }

                        // A file match's own actions, on right-click.
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            enabled: row.modelData.kind !== "quick"
                            onTapped: fileMenu.popup()
                        }

                        QQC2.Menu {
                            id: fileMenu

                            QQC2.MenuItem {
                                text: i18n("Open")
                                icon.name: "document-open"
                                onTriggered: view.resultActivated(row.modelData)
                            }
                            QQC2.MenuItem {
                                text: i18n("Show in folder")
                                icon.name: "document-open-folder"
                                enabled: row.modelData.kind !== "link"
                                onTriggered: view.fileActionRequested(row.modelData, "reveal")
                            }
                            QQC2.MenuItem {
                                text: row.modelData.kind === "link" ? i18n("Copy link") : i18n("Copy path")
                                icon.name: "edit-copy"
                                onTriggered: view.fileActionRequested(row.modelData, "copy")
                            }
                            QQC2.MenuItem {
                                text: i18n("Ask about this")
                                icon.name: view.useRobotMascot ? "" : view.assistantIcon
                                icon.source: view.useRobotMascot ? Look.robotIcon : ""
                                icon.color: "transparent"
                                onTriggered: view.fileActionRequested(row.modelData, "ask")
                            }
                        }

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
                    Accessible.name: i18n("Ask the assistant: %1", view.query)
                    onClicked: view.accepted(view.query)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.largeSpacing

                        Kirigami.Icon {
                            source: view.assistantIcon
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
                                useRobotMascot: view.useRobotMascot
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
                iconName: view.assistantIcon
                text: i18n("Ask anything")
                explanation: i18n("Find files, look things up on the web, or have the computer do something for you.")
            }
        }
    }
}
