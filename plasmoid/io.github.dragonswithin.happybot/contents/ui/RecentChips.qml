/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * The empty panel bar's suggestions as chips: under a "Recent …" heading
 * for each kind (`Look.hitGroupTitle(group, true)`), one small framed button
 * per item with its icon and name, wrapping onto more rows as needed.
 * FileResults.qml shows it in place of its result rows while
 * `AssistantSession.showingRecent` is true.
 *
 * `hits` is `session.hits` (already grouped by `Look.groupHits`), and a
 * chip's place in it is the index `selectedIndex` refers to, so main.qml's
 * Down/Up and Enter work on chips as on rows; the selected chip is drawn
 * highlighted. A click emits `activated(hit)`, which FileResults passes on
 * as `resultActivated`. A file chip's tooltip shows where it is. The
 * component is purely visual and keeps no state of its own.
 */
ColumnLayout {
    id: chips

    property var hits: []
    property int selectedIndex: -1
    property bool nativeLook: false
    property color accent: Kirigami.Theme.highlightColor

    signal activated(var hit)
    signal removeRequested(var hit)

    AssistantMenu {
        nativeLook: chips.nativeLook
        id: recentMenu
        objectName: "recentEntryMenu"
        accent: chips.accent
        property var hit: null
        QQC2.MenuItem {
            text: i18n("Remove from recent")
            icon.name: "edit-clear-history"
            onTriggered: chips.removeRequested(recentMenu.hit)
        }
    }

    /** `hits` split into runs of one kind: `[{group, first, items}]`, `first` being the run's index in `hits`. */
    readonly property var groups: {
        const runs = [];
        chips.hits.forEach((hit, index) => {
            const group = Look.hitGroup(hit);
            if (runs.length === 0 || runs[runs.length - 1].group !== group) {
                runs.push({ group: group, first: index, items: [] });
            }
            runs[runs.length - 1].items.push(hit);
        });
        return runs;
    }

    spacing: 0

    Repeater {
        model: chips.groups

        ColumnLayout {
            id: run

            required property var modelData
            required property int index

            Layout.fillWidth: true
            spacing: 0

            Kirigami.Heading {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.topMargin: run.index === 0 ? Kirigami.Units.smallSpacing : Kirigami.Units.largeSpacing
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                level: 5
                text: Look.hitGroupTitle(run.modelData.group, true)
                opacity: 0.7
                Accessible.role: Accessible.Heading
            }

            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.smallSpacing
                Layout.rightMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: run.modelData.items

                    // A frame under a delegate: the delegate draws hover and selection, the frame the chip's edge.
                    Item {
                        id: chip

                        required property var modelData
                        required property int index
                        readonly property bool removable: modelData.kind === "file" || modelData.kind === "folder"
                            || modelData.action?.type === "visited"
                        function openMenu(x, y) {
                            if (removable) {
                                recentMenu.hit = modelData;
                                recentMenu.popup(button, x, y);
                            }
                        }
                        readonly property int position: run.modelData.first + index

                        implicitWidth: button.implicitWidth
                        implicitHeight: button.implicitHeight

                        Rectangle {
                            anchors.fill: parent
                            radius: Kirigami.Units.cornerRadius
                            color: "transparent"
                            border.width: 1
                            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.2)
                        }

                        PlasmaComponents3.ItemDelegate {
                            id: button
                            objectName: "recentChip-" + chip.position

                            anchors.fill: parent
                            highlighted: chip.position === chips.selectedIndex
                            background: AccentSelection { control: button; accent: chips.accent }
                            Accessible.name: Look.hitWhere(chip.modelData).length > 0
                                ? i18n("%1, in %2", chip.modelData.title, Look.hitWhere(chip.modelData)) : chip.modelData.title
                            AssistantToolTip {
                                nativeLook: chips.nativeLook
                                text: Look.hitWhere(chip.modelData)
                                visible: parent.hovered && chip.modelData.kind !== "quick"
                            }
                            onClicked: chips.activated(chip.modelData)
                            TapHandler {
                                enabled: chip.removable
                                acceptedButtons: Qt.RightButton
                                onTapped: point => chip.openMenu(point.position.x, point.position.y)
                            }
                            Keys.onMenuPressed: chip.openMenu(0, height)
                            Keys.onPressed: event => {
                                if (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier) && chip.removable) {
                                    chip.openMenu(0, height);
                                    event.accepted = true;
                                }
                            }

                            contentItem: RowLayout {
                                spacing: Kirigami.Units.smallSpacing

                                Kirigami.Icon {
                                    source: Look.hitIcon(chip.modelData)
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                }

                                PlasmaComponents3.Label {
                                    text: chip.modelData.title
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    Layout.maximumWidth: Kirigami.Units.gridUnit * 10
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
