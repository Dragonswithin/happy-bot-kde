// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: picker
    required property bool useRobotMascot
    required property string robotStyle
    signal choiceRequested(var changes)

    Layout.minimumWidth: 0
    spacing: Kirigami.Units.smallSpacing

    function chooseRobot(style: string) {
        if (robotStyle !== style) choiceRequested({robot_style: style});
    }

    RowLayout {
        spacing: Kirigami.Units.largeSpacing
        QQC2.RadioButton {
            objectName: "useRobot"
            text: i18n("Robot")
            checked: picker.useRobotMascot
            onClicked: if (!picker.useRobotMascot) picker.choiceRequested({robot_mascot: true})
        }
        QQC2.RadioButton {
            objectName: "useWand"
            text: i18n("Wand")
            icon.name: "tools-wizard"
            checked: !picker.useRobotMascot
            onClicked: if (picker.useRobotMascot) picker.choiceRequested({robot_mascot: false})
        }
    }

    GridLayout {
        id: gallery
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        visible: picker.useRobotMascot
        columns: Math.max(1, Math.min(5, Math.floor((width + columnSpacing)
                 / (Kirigami.Units.gridUnit * 4.5 + columnSpacing))))
        uniformCellWidths: true
        columnSpacing: Kirigami.Units.smallSpacing
        rowSpacing: columnSpacing

        Repeater {
            id: robots
            model: Look.robotStyles
            QQC2.RadioDelegate {
                id: tile
                required property var modelData
                required property int index
                objectName: "robot-" + modelData.id
                text: modelData.name
                Accessible.name: text
                checked: picker.robotStyle === modelData.id
                activeFocusOnTab: checked || activeFocus
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                padding: Kirigami.Units.smallSpacing
                leftPadding: padding
                rightPadding: padding
                leftInset: 0
                rightInset: 0
                topInset: 0
                bottomInset: 0

                onClicked: picker.chooseRobot(modelData.id)
                Keys.onPressed: event => {
                    let next = index;
                    switch (event.key) {
                    case Qt.Key_Right: next += mirrored ? -1 : 1; break;
                    case Qt.Key_Left: next += mirrored ? 1 : -1; break;
                    case Qt.Key_Down: next += gallery.columns; break;
                    case Qt.Key_Up: next -= gallery.columns; break;
                    case Qt.Key_Home: next = 0; break;
                    case Qt.Key_End: next = robots.count - 1; break;
                    case Qt.Key_Return:
                    case Qt.Key_Enter:
                        picker.chooseRobot(modelData.id);
                        event.accepted = true;
                        return;
                    default: return;
                    }
                    event.accepted = true;
                    next = Math.max(0, Math.min(next, robots.count - 1));
                    robots.itemAt(next).forceActiveFocus(Qt.TabFocusReason);
                    picker.chooseRobot(Look.robotStyles[next].id);
                }

                background: Rectangle {
                    radius: Kirigami.Units.cornerRadius * 2
                    color: Qt.alpha(Kirigami.Theme.highlightColor,
                                    tile.checked ? 0.14 : tile.hovered ? 0.07 : 0)
                    border.width: tile.visualFocus ? 2 : 1
                    border.color: tile.checked || tile.visualFocus ? Kirigami.Theme.highlightColor
                                 : Qt.alpha(Kirigami.Theme.textColor, 0.16)
                }

                contentItem: ColumnLayout {
                    spacing: 0
                    Image {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium * 1.25
                        Layout.preferredHeight: Layout.preferredWidth
                        source: Look.robotImage(tile.modelData.id)
                        sourceSize.width: Math.ceil(width)
                        fillMode: Image.PreserveAspectFit
                        Accessible.ignored: true
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: tile.text
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        font.weight: tile.checked ? Font.DemiBold : Font.Normal
                        Accessible.ignored: true
                    }
                }
                indicator: Kirigami.Icon {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Kirigami.Units.smallSpacing
                    width: Kirigami.Units.iconSizes.small
                    height: width
                    visible: tile.checked
                    source: "emblem-checked"
                    isMask: true
                    color: Kirigami.Theme.highlightColor
                    Accessible.ignored: true
                }
            }
        }
    }
}
