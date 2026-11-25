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
 * The search results, in the popup's finders (ResultsView.qml,
 * `AssistantSession.finder`: "Find a file", and "Search the web", whose
 * pages show under "On the web" with their address and snippet) and above
 * the panel's search bar
 * (PanelResults.qml): one row per result in `session.hits`, each kind under
 * a heading where it starts (Answer, Applications, Settings, Bookmarks, Recent websites,
 * Saved chats, Files: `Look.hitGroup`), applications first; quick results
 * show their icon and kind, files their file-type icon, name and folder; "Searching…", a "nothing matches" line or
 * the finder's hint while there are none; a problem line when the finder's
 * search failed (`session.searchError`); and below them an "Ask Happy Bot
 * about …" row (in the finder, "Ask Happy Bot to find …") for the typed
 * `query`. The results scroll; the ask row is pinned under them so it
 * always shows whole, however many results there are. It is highlighted
 * while no result is selected (`selectedIndex` -1), so it is plain when
 * Enter asks rather than opens.
 *
 * Characters (emoji, symbols) show their glyph in place of an icon. While
 * the empty bar's suggestions are shown (`session.showingRecent`), the same
 * hits are drawn as chips, a row of small buttons under each "Recent …"
 * heading (`RecentChips`), in the same order, so `selectedIndex` means the
 * same thing in both forms.
 *
 * `selectedIndex` (owned by main.qml) is only drawn, and the scroll follows
 * it; new matches start at the top. A match can be clicked
 * (`resultActivated(hit)`), dragged into another application, or given a
 * menu action with a right-click or `openSelectedMenu` (the Menu key): a
 * file's `fileActionRequested(hit, action)` with "reveal", "copy", "phone"
 * (send it to the phone) or "ask"; an application's Update, Uninstall and
 * Start at login, which this component asks the daemon about and carries
 * out itself (`session.appInfo`, `session.appAction`: the first two open a
 * terminal where the user confirms). The ask row emits `askRequested(query)`. `naturalHeight` is the exact height
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
    readonly property bool chips: session.showingRecent
    readonly property bool web: session.finder === "web"
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

                RecentChips {
                    Layout.fillWidth: true
                    visible: results.chips
                    hits: results.chips ? results.session.hits : []
                    selectedIndex: results.selectedIndex
                    onActivated: hit => results.resultActivated(hit)
                }

                Repeater {
                    id: hitRows
                    model: results.chips ? [] : results.session.hits

                        // One result, under a heading where a new kind of result starts (Applications, Files...).
                        ColumnLayout {
                            id: entry

                            required property int index
                            required property var modelData
                            readonly property string group: Look.hitGroup(modelData)
                            readonly property bool isFile: modelData.kind !== "quick"
                            readonly property bool isApp: modelData.kind === "quick" && modelData.action.type === "launch"
                            readonly property bool startsGroup: index === 0
                                || Look.hitGroup(results.session.hits[index - 1]) !== group

                            Layout.fillWidth: true
                            spacing: 0

                            Kirigami.Heading {
                                Layout.fillWidth: true
                                Layout.leftMargin: Kirigami.Units.largeSpacing
                                Layout.topMargin: entry.index === 0 ? Kirigami.Units.smallSpacing : Kirigami.Units.largeSpacing
                                Layout.bottomMargin: Kirigami.Units.smallSpacing
                                visible: entry.startsGroup
                                level: 5
                                text: Look.hitGroupTitle(entry.group)
                                opacity: 0.7
                                Accessible.role: Accessible.Heading
                            }

                            PlasmaComponents3.ItemDelegate {
                                id: row

                                Connections {
                                    target: results
                                    function onSelectedMenuRequested() {
                                        if (entry.index !== results.selectedIndex) {
                                            return;
                                        }
                                        if (entry.isFile) {
                                            fileMenu.popup(row, 0, row.height);
                                        } else if (entry.isApp) {
                                            appMenu.show(row, 0, row.height);
                                        }
                                    }
                                }

                                Layout.fillWidth: true
                                highlighted: entry.index === results.selectedIndex
                                Accessible.name: Look.hitWhere(entry.modelData).length > 0
                                    ? i18n("%1, in %2", entry.modelData.title, Look.hitWhere(entry.modelData)) : entry.modelData.title
                                onClicked: results.resultActivated(entry.modelData)

                                // A file match can be dragged into another application.
                                Drag.dragType: Drag.Automatic
                                Drag.supportedActions: Qt.CopyAction
                                Drag.mimeData: entry.modelData.kind === "quick" ? ({})
                                    : ({ "text/uri-list": entry.modelData.location.indexOf("://") > 0 ? entry.modelData.location
                                                          : "file://" + encodeURI(entry.modelData.location),
                                         "text/plain": entry.modelData.location })
                                Drag.active: rowDrag.active
                                DragHandler {
                                    id: rowDrag
                                    enabled: entry.modelData.kind !== "quick"
                                    target: null
                                }

                                // A file's or an application's own actions, on right-click.
                                TapHandler {
                                    acceptedButtons: Qt.RightButton
                                    enabled: entry.isFile || entry.isApp
                                    onTapped: entry.isFile ? fileMenu.popup() : appMenu.show()
                                }

                                QQC2.Menu {
                                    id: appMenu

                                    property var info: null  // from session.appInfo; null until it answers
                                    readonly property string path: entry.isApp ? entry.modelData.action.target : ""

                                    /** Opens the menu (at the pointer, or at `x`,`y` in `item`) and asks what it can offer. */
                                    function show(item, x, y) {
                                        appMenu.info = null;
                                        results.session.appInfo(appMenu.path, info => appMenu.info = info);
                                        if (item) {
                                            appMenu.popup(item, x, y);
                                        } else {
                                            appMenu.popup();
                                        }
                                    }

                                    QQC2.MenuItem {
                                        text: i18n("Open")
                                        icon.name: "system-run"
                                        onTriggered: results.resultActivated(entry.modelData)
                                    }
                                    QQC2.MenuItem {
                                        text: i18n("Update…")
                                        icon.name: "update-none"
                                        enabled: !!(appMenu.info && appMenu.info.update)
                                        onTriggered: results.session.appAction(appMenu.path, "update")
                                    }
                                    QQC2.MenuItem {
                                        text: i18n("Uninstall…")
                                        icon.name: "edit-delete-remove"
                                        enabled: !!(appMenu.info && appMenu.info.uninstall)
                                        onTriggered: results.session.appAction(appMenu.path, "uninstall")
                                    }
                                    QQC2.MenuItem {
                                        text: i18n("Start at login")
                                        checkable: true
                                        checked: !!(appMenu.info && appMenu.info.autostart)
                                        enabled: appMenu.info !== null
                                        onTriggered: results.session.appAction(appMenu.path, checked ? "autostart_on" : "autostart_off")
                                    }
                                }

                                QQC2.Menu {
                                    id: fileMenu

                                    QQC2.MenuItem {
                                        text: i18n("Open")
                                        icon.name: "document-open"
                                        onTriggered: results.resultActivated(entry.modelData)
                                    }
                                    QQC2.MenuItem {
                                        text: i18n("Show in folder")
                                        icon.name: "document-open-folder"
                                        enabled: entry.modelData.kind !== "link"
                                        onTriggered: results.fileActionRequested(entry.modelData, "reveal")
                                    }
                                    QQC2.MenuItem {
                                        text: entry.modelData.kind === "link" ? i18n("Copy link") : i18n("Copy path")
                                        icon.name: "edit-copy"
                                        onTriggered: results.fileActionRequested(entry.modelData, "copy")
                                    }
                                    QQC2.MenuItem {
                                        text: i18n("Send to phone")
                                        icon.name: "kdeconnect"
                                        enabled: entry.modelData.kind === "file" || entry.modelData.kind === "link"
                                        onTriggered: results.fileActionRequested(entry.modelData, "phone")
                                    }
                                    QQC2.MenuItem {
                                        text: i18n("Ask about this")
                                        icon.name: results.useRobotMascot ? "" : results.assistantIcon
                                        icon.source: results.useRobotMascot ? Look.robotIcon : ""
                                        icon.color: "transparent"
                                        onTriggered: results.fileActionRequested(entry.modelData, "ask")
                                    }
                                }

                                contentItem: RowLayout {
                                    spacing: Kirigami.Units.largeSpacing

                                    Kirigami.Icon {
                                        visible: !entry.modelData.glyph
                                        source: Look.hitIcon(entry.modelData)
                                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                    }

                                    // An emoji or symbol shows itself.
                                    PlasmaComponents3.Label {
                                        visible: !!entry.modelData.glyph
                                        text: entry.modelData.glyph || ""
                                        textFormat: Text.PlainText
                                        horizontalAlignment: Text.AlignHCenter
                                        font.pixelSize: Math.round(Kirigami.Units.iconSizes.medium * 0.8)
                                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                        Accessible.ignored: true
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0

                                        PlasmaComponents3.Label {
                                            Layout.fillWidth: true
                                            text: entry.modelData.title
                                            elide: Text.ElideRight
                                            textFormat: Text.PlainText
                                        }

                                        PlasmaComponents3.Label {
                                            Layout.fillWidth: true
                                            text: Look.hitWhere(entry.modelData)
                                            elide: entry.group === "web" ? Text.ElideRight : Text.ElideMiddle
                                            textFormat: Text.PlainText
                                            font: Kirigami.Theme.smallFont
                                            opacity: 0.65
                                        }
                                    }
                                }
                            }
                        }
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        Layout.margins: Kirigami.Units.largeSpacing
                        visible: !results.hasHits && !results.hasSearchError
                            && (results.session.finding || results.session.searchedText.length > 0)
                        wrapMode: Text.Wrap
                        opacity: 0.7
                        text: results.session.searching ? i18n("Searching…")
                            : results.web && results.session.searchedText.length > 0 ? i18n("Nothing found on the web. Ask Happy Bot below.")
                            : results.session.searchedText.length > 0 ? i18n("Nothing on this computer matches. Ask Happy Bot below.")
                            : results.web ? i18n("Type what to look up; pages from the web show here. Enter opens the top one.")
                            : i18n("Type the name of an application, a setting or a file; what matches shows here. Enter opens the top one.")
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
                                ? (results.web ? i18n("Web search is not set up yet.") : i18n("File search is not set up yet."))
                                : results.web ? i18n("Web search is not responding. Try again in a moment.")
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
                    text: results.web ? i18n("Ask Happy Bot to search the web for “%1”", results.query)
                        : results.session.finding ? i18n("Ask Happy Bot to find “%1”", results.query)
                        : i18n("Ask Happy Bot about “%1”", results.query)
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: askRow.highlighted ? i18n("Press Enter") : i18n("Click to ask")
                    font: Kirigami.Theme.smallFont
                    opacity: 0.65
                }
            }
        }
    }
}
