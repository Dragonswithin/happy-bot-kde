/* SPDX-License-Identifier: MIT */
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: tray
    required property var session
    readonly property bool hasContent: !!session.staged?.length || !!session.attachmentError || !!session.checkingFiles

    ListView {
        id: files
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, Kirigami.Units.gridUnit * 5)
        clip: true
        model: tray.session.staged || []
        QQC2.ScrollBar.vertical: QQC2.ScrollBar {}
        delegate: RowLayout {
            id: row
            required property var modelData
            required property int index
            width: files.width
            height: Kirigami.Units.gridUnit * 2.25
            Image {
                visible: row.modelData.kind === "image"
                Layout.preferredWidth: row.height
                Layout.preferredHeight: row.height
                sourceSize.width: 80
                sourceSize.height: 80
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                source: visible ? "file://" + row.modelData.path.split("/").map(encodeURIComponent).join("/") : ""
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                QQC2.Label {
                    Layout.fillWidth: true
                    text: row.modelData.name
                    textFormat: Text.PlainText
                    elide: Text.ElideMiddle
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    visible: !!row.modelData.preview
                    text: (row.modelData.preview || "").replace(/\s+/g, " ")
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    font: Kirigami.Theme.smallFont
                }
            }
            QQC2.ToolButton {
                objectName: "removeAttachment"
                text: i18n("Remove %1", row.modelData.name)
                display: QQC2.AbstractButton.IconOnly
                icon.name: "list-remove"
                enabled: !tray.session.busy && !tray.session.checkingFiles
                onClicked: {
                    tray.session.setStaged(tray.session.stagingKey, tray.session.staged.filter((_, i) => i !== row.index))
                    tray.session.attachmentError = ""
                }
            }
        }
    }
    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: !!text
        type: tray.session.checkingFiles ? Kirigami.MessageType.Information : Kirigami.MessageType.Warning
        text: tray.session.attachmentError || (tray.session.incompatibleImage ? i18n("Choose a model with vision or remove the image.")
            : tray.session.checkingFiles ? i18n("Checking attachments…") : "")
        actions: Kirigami.Action {
            visible: !!tray.session.attachmentError
            text: i18n("Dismiss")
            onTriggered: tray.session.attachmentError = ""
        }
    }
}
