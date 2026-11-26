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
    property bool soundsFollowMascot: true
    signal choiceRequested(var changes)

    Layout.minimumWidth: 0
    spacing: Kirigami.Units.smallSpacing

    readonly property string selectedTheme: useRobotMascot ? robotStyle : "wand"
    readonly property var themeChoices: Look.robotStyles.concat([{id: "wand", name: i18n("Wand")}])

    function chooseTheme(theme: string) {
        if (selectedTheme === theme)
            return;
        choiceRequested(theme === "wand" ? {robot_mascot: false}
                        : useRobotMascot ? {robot_style: theme}
                        : {robot_mascot: true, robot_style: theme});
    }

    QQC2.CheckBox {
        objectName: "followMascotSounds"
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        text: i18n("Also change sounds")
        QQC2.ToolTip.text: i18n("Choosing another robot changes the theme of every event sound. Each event keeps its on or off setting.")
        QQC2.ToolTip.visible: hovered || visualFocus
        checked: picker.soundsFollowMascot
        onToggled: picker.choiceRequested({sounds_follow_mascot: checked})
    }

    GridLayout {
        id: gallery
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        columns: Math.max(1, Math.min(5, Math.floor((width + columnSpacing)
                 / (Kirigami.Units.gridUnit * 4.5 + columnSpacing))))
        uniformCellWidths: true
        columnSpacing: Kirigami.Units.smallSpacing
        rowSpacing: columnSpacing

        Repeater {
            id: robots
            model: picker.themeChoices
            QQC2.RadioDelegate {
                id: tile
                required property var modelData
                required property int index
                objectName: "robot-" + modelData.id
                text: modelData.name
                Accessible.name: text
                checked: picker.selectedTheme === modelData.id
                readonly property bool wand: modelData.id === "wand"
                readonly property color accent: Look.assistantAccent(!wand, modelData.id, Kirigami.Theme.highlightColor)
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

                onClicked: picker.chooseTheme(modelData.id)
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
                        picker.chooseTheme(modelData.id);
                        event.accepted = true;
                        return;
                    default: return;
                    }
                    event.accepted = true;
                    next = Math.max(0, Math.min(next, robots.count - 1));
                    robots.itemAt(next).forceActiveFocus(Qt.TabFocusReason);
                    picker.chooseTheme(picker.themeChoices[next].id);
                }

                background: Rectangle {
                    radius: Kirigami.Units.cornerRadius * 2
                    color: Qt.alpha(tile.accent,
                                    tile.checked ? 0.14 : tile.hovered ? 0.07 : 0)
                    border.width: tile.visualFocus ? 2 : 1
                    border.color: tile.checked || tile.visualFocus ? tile.accent
                                 : Qt.alpha(Kirigami.Theme.textColor, 0.16)
                }

                contentItem: ColumnLayout {
                    spacing: 0
                    Image {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium * 1.25
                        Layout.preferredHeight: Layout.preferredWidth
                        visible: !tile.wand
                        source: visible ? Look.robotImage(tile.modelData.id) : ""
                        sourceSize.width: Math.ceil(width)
                        fillMode: Image.PreserveAspectFit
                        Accessible.ignored: true
                    }
                    Kirigami.Icon {
                        visible: tile.wand
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium * 1.25
                        Layout.preferredHeight: Layout.preferredWidth
                        source: "tools-wizard"
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
                    color: tile.accent
                    Accessible.ignored: true
                }
            }
        }
    }
}
