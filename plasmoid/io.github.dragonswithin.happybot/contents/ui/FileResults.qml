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
 * The file matches in Happy Bot's popup (ResultsView.qml shows it in place
 * of the conversation while files are shown, mostly in the file finder,
 * `AssistantSession.findingFiles`): one row per match in `session.hits`
 * (file-type icon, name, folder), a hint while the finder has nothing yet, a
 * problem line when the search failed (`session.searchError`), and below
 * them an "Ask Happy Bot to find" row for the typed `query`. The matches
 * scroll; the ask row is pinned under them so it always shows whole, however
 * many matches there are. It is highlighted while no match is selected, so
 * it is plain that Enter asks rather than opens a file.
 *
 * `selectedIndex` (owned by main.qml) is only drawn, and the scroll follows
 * it; new matches start at the top. A match can be clicked
 * (`resultActivated(hit)`), dragged into another application, or given a
 * menu action with a right-click or `openSelectedMenu` (the Menu key):
 * `fileActionRequested(hit, action)` with "reveal", "copy" or "ask". The
 * ask row emits `askRequested(query)`. `naturalHeight` is the exact height
 * of everything unscrolled, from plain columns, so the window can size to
 * it without jumping. The component keeps no other state.
 */
Item {
    id: results

    required property var session
    property string query: ""
    property int selectedIndex: -1
    property string assistantIcon: ""
    property bool useRobotMascot: false

    readonly property bool hasHits: session.hits.length > 0
    readonly property bool hasSearchError: session.searchError.length > 0
    readonly property real naturalHeight: filesColumn.implicitHeight + (askRow.visible ? askRow.implicitHeight : 0)

    signal resultActivated(var hit)
    signal fileActionRequested(var hit, string action)
    signal askRequested(string text)
    signal selectedMenuRequested()

    /** Opens the selected match's actions menu, as a right-click does. */
    function openSelectedMenu() {
        results.selectedMenuRequested();
    }


    PlasmaComponents3.ScrollView {
        id: filesView

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: askRow.visible ? askRow.top : parent.bottom
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

        Flickable {
            id: filesFlick

            contentWidth: width
            contentHeight: filesColumn.implicitHeight
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            // New matches start at the top; Down and Up keep the selected one in sight.
            Connections {
                target: results.session
                function onHitsChanged() {
                    filesFlick.contentY = 0;
                }
            }
            Connections {
                target: results
                function onSelectedIndexChanged() {
                    const row = hitRows.itemAt(results.selectedIndex);
                    if (!row) {
                        return;
                    }
                    if (row.y < filesFlick.contentY) {
                        filesFlick.contentY = row.y;
                    } else if (row.y + row.height > filesFlick.contentY + filesFlick.height) {
                        filesFlick.contentY = row.y + row.height - filesFlick.height;
                    }
                }
            }

            ColumnLayout {
                id: filesColumn

                width: filesFlick.width
                spacing: 0

                Repeater {
                    id: hitRows
                    model: results.session.hits

                        PlasmaComponents3.ItemDelegate {
                            id: row

                            required property int index
                            required property var modelData

                            Connections {
                                target: results
                                function onSelectedMenuRequested() {
                                    if (row.index === results.selectedIndex && row.modelData.kind !== "quick") {
                                        fileMenu.popup(row, 0, row.height);
                                    }
                                }
                            }

                            Layout.fillWidth: true
                            highlighted: index === results.selectedIndex
                            Accessible.name: Look.hitWhere(modelData).length > 0
                                ? i18n("%1, in %2", modelData.title, Look.hitWhere(modelData)) : modelData.title
                            onClicked: results.resultActivated(modelData)

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
                                    onTriggered: results.resultActivated(row.modelData)
                                }
                                QQC2.MenuItem {
                                    text: i18n("Show in folder")
                                    icon.name: "document-open-folder"
                                    enabled: row.modelData.kind !== "link"
                                    onTriggered: results.fileActionRequested(row.modelData, "reveal")
                                }
                                QQC2.MenuItem {
                                    text: row.modelData.kind === "link" ? i18n("Copy link") : i18n("Copy path")
                                    icon.name: "edit-copy"
                                    onTriggered: results.fileActionRequested(row.modelData, "copy")
                                }
                                QQC2.MenuItem {
                                    text: i18n("Ask about this")
                                    icon.name: results.useRobotMascot ? "" : results.assistantIcon
                                    icon.source: results.useRobotMascot ? Look.robotIcon : ""
                                    icon.color: "transparent"
                                    onTriggered: results.fileActionRequested(row.modelData, "ask")
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

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        Layout.margins: Kirigami.Units.largeSpacing
                        visible: results.session.findingFiles && !results.hasHits && !results.hasSearchError
                        wrapMode: Text.Wrap
                        opacity: 0.7
                        text: i18n("Type part of a file's name and matching files show here; click one to open it. Enter asks Happy Bot to look for it.")
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: Kirigami.Units.smallSpacing
                        visible: results.hasSearchError
                        spacing: Kirigami.Units.largeSpacing

                        Kirigami.Icon {
                            source: "dialog-warning"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        }

                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            text: results.session.searchErrorCode === "not_configured"
                                ? i18n("File search is not set up yet.")
                                : i18n("File search is not responding. Try again in a moment.")
                            wrapMode: Text.Wrap
                            PlasmaComponents3.ToolTip.text: results.session.searchError
                            PlasmaComponents3.ToolTip.visible: errorHover.hovered && results.session.searchErrorCode !== "not_configured"

                            HoverHandler {
                                id: errorHover
                            }
                        }
                    }
            }
        }
    }

    PlasmaComponents3.ItemDelegate {
        id: askRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: results.query.length > 0
        highlighted: results.selectedIndex < 0
        Accessible.name: i18n("Ask the assistant: %1", results.query)
        onClicked: results.askRequested(results.query)

        contentItem: RowLayout {
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: results.assistantIcon
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: results.session.findingFiles ? i18n("Ask Happy Bot to find “%1”", results.query)
                        : i18n("Ask the assistant: “%1”", results.query)
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
