// SPDX-License-Identifier: MIT
// Groups one settings task, using the start screen's rounded surfaces and mascot tint.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

QQC2.Control {
    id: card

    required property string title
    required property string iconName
    property string description: ""
    property Component headerArtwork
    default property alias contents: body.data

    Layout.fillWidth: true
    Layout.minimumWidth: 0
    padding: Kirigami.Units.largeSpacing * 1.5
    topPadding: padding
    bottomPadding: padding
    leftPadding: padding
    rightPadding: padding
    background: Rectangle {
        radius: Kirigami.Units.cornerRadius * 2
        color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(Kirigami.Theme.textColor, 0.025))
        border.color: Qt.alpha(Kirigami.Theme.textColor, 0.15)
    }
    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing
            Rectangle {
                visible: !card.headerArtwork
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Layout.preferredWidth
                radius: Kirigami.Units.cornerRadius * 2
                color: Qt.alpha(Look.mascotAccent, 0.18)
                Kirigami.Icon {
                    anchors.centerIn: parent
                    width: Kirigami.Units.iconSizes.smallMedium
                    height: width
                    source: card.iconName
                    isMask: true
                    color: Qt.tint(Kirigami.Theme.textColor, Qt.alpha(Look.mascotAccent, 0.42))
                    Accessible.ignored: true
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Heading {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    level: 3
                    font.weight: Font.DemiBold
                    text: card.title
                    wrapMode: Text.Wrap
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: card.description.length > 0
                    text: card.description
                    color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(Kirigami.Theme.textColor, 0.80))
                    wrapMode: Text.Wrap
                }
            }
            Loader {
                visible: active
                active: card.headerArtwork !== null
                sourceComponent: card.headerArtwork
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                Layout.preferredHeight: Layout.preferredWidth
            }
        }
        ColumnLayout {
            id: body
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: Kirigami.Units.smallSpacing
        }
    }
}
