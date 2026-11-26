// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

// The empty web finder. Sites and searches share the composer's selection order.
Item {
    id: page
    property var popup: null

    property var sites: []
    property var searches: []
    property bool historyEnabled: false
    property bool loading: false
    property string problem: ""
    property int selectedIndex: -1
    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor
    readonly property int itemCount: sites.length + searches.length
    readonly property int inset: Kirigami.Units.largeSpacing * 1.5
    readonly property real naturalHeight: Math.max(Kirigami.Units.gridUnit * 14, content.implicitHeight + 2 * inset)

    signal siteActivated(var site)
    signal siteSearchRequested(string host)
    signal searchActivated(string query)
    signal siteActionRequested(var site, string action)
    signal settingsRequested()

    function selectionItem() {
        if (selectedIndex < 0) return null;
        return selectedIndex < sites.length ? siteTiles.itemAt(selectedIndex)
            : searchChips.itemAt(selectedIndex - sites.length);
    }

    function keepInView(item) {
        if (!item || !visible) return;
        const top = item.mapToItem(flick.contentItem, 0, 0).y;
        if (top < flick.contentY)
            flick.contentY = top;
        else if (top + item.height > flick.contentY + flick.height)
            flick.contentY = top + item.height - flick.height;
        flick.returnToBounds();
    }

    function openSelectedMenu() {
        const tile = siteTiles.itemAt(selectedIndex);
        if (tile) tile.openMenu();
    }

    function activateSelected() {
        const item = selectionItem();
        if (item) item.clicked();
    }

    onSelectedIndexChanged: keepInView(selectionItem())
    onVisibleChanged: {
        if (visible) flick.contentY = 0;
        else siteMenu.close();
    }

    // Site tiles stay recognisable across sessions without asking any website for its icon.
    function siteTint(host) {
        const palette = ["#62bdb2", "#e59876", "#799fe1", "#b99ad7", "#90b46d", "#ce8eac"];
        let hash = 0;
        for (let i = 0; i < host.length; i++) hash = ((hash * 31) + host.charCodeAt(i)) | 0;
        return palette[Math.abs(hash) % palette.length];
    }

    WebSiteMenu {
        nativeLook: page.nativeLook
        accent: page.accent
        id: siteMenu
        objectName: "webSiteMenu"
        onSiteActionRequested: (site, action) => page.siteActionRequested(site, action)
        QQC2.MenuSeparator {}
        QQC2.MenuItem {
            text: i18n("Search this site")
            icon.name: "edit-find"
            onTriggered: page.siteSearchRequested(siteMenu.site.host)
        }
    }

    PopupScrollView {
        popup: page.popup
        anchors.fill: parent
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

        Flickable {

            acceptedButtons: Qt.NoButton
            id: flick
            contentWidth: width
            contentHeight: content.implicitHeight + 2 * page.inset
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            ColumnLayout {
                id: content
                x: page.inset
                y: page.inset
                width: Math.max(1, flick.width - 2 * page.inset)
                spacing: Kirigami.Units.largeSpacing

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: page.problem !== ""
                    text: page.problem
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Kirigami.Theme.negativeTextColor
                }

                Kirigami.Heading {
                    Layout.fillWidth: true
                    level: 4
                    text: i18n("Frequent sites")
                    Accessible.role: Accessible.Heading
                }

                Grid {
                    id: grid
                    Layout.fillWidth: true
                    visible: page.sites.length > 0
                    spacing: Kirigami.Units.smallSpacing * 2
                    columns: Math.max(1, Math.min(4, Math.floor((width + spacing) / (Kirigami.Units.gridUnit * 5.5 + spacing))))

                    Repeater {
                        id: siteTiles
                        model: page.sites

                        PlasmaComponents3.ItemDelegate {
                            id: tile
                            required property int index
                            required property var modelData
                            readonly property string domain: modelData.host
                            readonly property color tint: page.siteTint(domain)
                            objectName: "webSite-" + domain
                            text: modelData.title || domain
                            width: Math.max(1, Math.floor((grid.width - (grid.columns - 1) * grid.spacing) / grid.columns))
                            height: Math.max(contentItem.implicitHeight + 2 * padding, Kirigami.Units.gridUnit * 5.5)
                            padding: Kirigami.Units.smallSpacing * 1.5
                            highlighted: page.selectedIndex === index
                            Accessible.name: text
                            Accessible.description: modelData.pinned ? i18n("Pinned site. Open the context menu for options.") : i18n("Open the context menu to pin or hide this site.")
                            AssistantToolTip {
                                nativeLook: page.nativeLook
                                accent: page.accent
                                text: tile.text === tile.domain ? tile.domain : tile.text + "\n" + tile.domain
                                visible: parent.hovered
                            }
                            function openMenu() {
                                siteMenu.site = modelData;
                                siteMenu.popup(tile, 0, tile.height);
                            }
                            onClicked: page.siteActivated(modelData)
                            onActiveFocusChanged: if (activeFocus) page.keepInView(tile)
                            Keys.onMenuPressed: openMenu()
                            Keys.onPressed: event => {
                                if (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)) {
                                    openMenu();
                                    event.accepted = true;
                                }
                            }
                            TapHandler {
                                acceptedButtons: Qt.RightButton
                                onTapped: point => {
                                    siteMenu.site = tile.modelData;
                                    siteMenu.popup(tile, point.position.x, point.position.y);
                                }
                            }
                            background: Rectangle {
                                radius: Kirigami.Units.cornerRadius * 2
                                color: Qt.alpha(tile.hovered || tile.down || tile.highlighted ? page.accent : Kirigami.Theme.textColor,
                                                tile.hovered || tile.down || tile.highlighted ? 0.12 : 0.035)
                                border.color: tile.visualFocus || tile.highlighted ? page.accent : Qt.alpha(Kirigami.Theme.textColor, 0.16)
                                Kirigami.Icon {
                                    visible: tile.modelData.pinned === true
                                    anchors.top: parent.top
                                    anchors.right: parent.right
                                    anchors.margins: Kirigami.Units.smallSpacing
                                    width: Kirigami.Units.iconSizes.small
                                    height: width
                                    source: "pin"
                                    color: Kirigami.Theme.textColor
                                    Accessible.ignored: true
                                }
                            }
                            contentItem: ColumnLayout {
                                spacing: Kirigami.Units.smallSpacing
                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    implicitWidth: Kirigami.Units.iconSizes.medium + Kirigami.Units.smallSpacing * 2
                                    implicitHeight: implicitWidth
                                    radius: Kirigami.Units.cornerRadius * 2
                                    color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(tile.tint, 0.24))
                                    border.color: Qt.alpha(tile.tint, 0.4)
                                    Image {
                                        id: favicon
                                        objectName: "siteFavicon"
                                        anchors.centerIn: parent
                                        width: Kirigami.Units.iconSizes.medium
                                        height: width
                                        source: tile.modelData.favicon ?? ""
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        sourceSize.width: width
                                        sourceSize.height: height
                                        Accessible.ignored: true
                                    }
                                    PlasmaComponents3.Label {
                                        anchors.centerIn: parent
                                        visible: favicon.status !== Image.Ready
                                        text: tile.text.charAt(0).toLocaleUpperCase()
                                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.35
                                        font.weight: Font.DemiBold
                                        color: Qt.tint(Kirigami.Theme.textColor, Qt.alpha(tile.tint, 0.18))
                                        Accessible.ignored: true
                                    }
                                }
                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: tile.text
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    Accessible.ignored: true
                                }
                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    visible: tile.text !== tile.domain
                                    horizontalAlignment: Text.AlignHCenter
                                    text: tile.domain
                                    textFormat: Text.PlainText
                                    font: Kirigami.Theme.smallFont
                                    opacity: 0.75
                                    elide: Text.ElideRight
                                    Accessible.ignored: true
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    visible: page.sites.length === 0
                    implicitHeight: empty.implicitHeight + 2 * Kirigami.Units.largeSpacing
                    radius: Kirigami.Units.cornerRadius * 2
                    color: Qt.alpha(page.accent, 0.07)
                    border.color: Qt.alpha(page.accent, 0.2)
                    ColumnLayout {
                        id: empty
                        anchors.centerIn: parent
                        width: Math.max(1, parent.width - Kirigami.Units.largeSpacing * 2)
                        spacing: Kirigami.Units.smallSpacing
                        Kirigami.Icon {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                            Layout.preferredHeight: Layout.preferredWidth
                            source: "internet-web-browser"
                            color: page.accent
                            Accessible.ignored: true
                        }
                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            text: page.loading ? i18n("Loading frequent sites…")
                                : page.historyEnabled ? i18n("Sites you visit often will appear here.")
                                : i18n("Turn on recently visited websites to see your frequent sites.")
                        }
                        PlasmaComponents3.Button {
                            Layout.alignment: Qt.AlignHCenter
                            visible: !page.historyEnabled && !page.loading
                            text: i18n("Open settings")
                            icon.name: "configure"
                            onClicked: page.settingsRequested()
                        }
                    }
                }

                Kirigami.Heading {
                    Layout.topMargin: Kirigami.Units.smallSpacing
                    Layout.fillWidth: true
                    level: 4
                    text: i18n("Recent searches")
                    Accessible.role: Accessible.Heading
                }

                Flow {
                    id: recentFlow
                    Layout.fillWidth: true
                    visible: page.searches.length > 0
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        id: searchChips
                        model: page.searches
                        PlasmaComponents3.ItemDelegate {
                            id: chip
                            required property int index
                            required property string modelData
                            objectName: "webSearch-" + index
                            leftPadding: Kirigami.Units.largeSpacing
                            rightPadding: leftPadding
                            topPadding: Kirigami.Units.smallSpacing
                            bottomPadding: topPadding
                            width: Math.min(implicitWidth, recentFlow.width)
                            height: Math.max(implicitHeight, Kirigami.Units.gridUnit * 1.75)
                            text: modelData
                            highlighted: page.selectedIndex === page.sites.length + index
                            Accessible.name: i18n("Search again for %1", text)
                            onClicked: page.searchActivated(modelData)
                            onActiveFocusChanged: if (activeFocus) page.keepInView(chip)
                            background: Rectangle {
                                radius: Kirigami.Units.cornerRadius * 2
                                color: Qt.alpha(chip.hovered || chip.down || chip.highlighted ? page.accent : Kirigami.Theme.textColor,
                                                chip.hovered || chip.down || chip.highlighted ? 0.12 : 0.035)
                                border.color: chip.visualFocus || chip.highlighted ? page.accent : Qt.alpha(Kirigami.Theme.textColor, 0.16)
                            }
                            contentItem: RowLayout {
                                spacing: Kirigami.Units.smallSpacing
                                Kirigami.Icon {
                                    source: "view-history"
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Layout.preferredWidth
                                    Accessible.ignored: true
                                }
                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: chip.text
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    Accessible.ignored: true
                                }
                            }
                        }
                    }
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: !page.loading && page.searches.length === 0
                    text: i18n("Searches you use in Happy Bot will appear here.")
                    wrapMode: Text.Wrap
                    opacity: 0.75
                }
            }
        }
    }
}
