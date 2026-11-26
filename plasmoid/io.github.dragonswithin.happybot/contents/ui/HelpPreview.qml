// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC3

ColumnLayout {
    id: preview

    required property var draft
    required property string chatModel
    spacing: Kirigami.Units.largeSpacing

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(width * 0.56, Kirigami.Units.gridUnit * 11)
        visible: picture.source.toString().length > 0 || indicator.running
        radius: Kirigami.Units.cornerRadius
        color: Qt.alpha(Kirigami.Theme.textColor, 0.05)
        Image {
            id: picture
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            source: preview.draft?.url || ""
            sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: false
            Accessible.role: Accessible.Graphic
            Accessible.name: i18n("Screenshot preview")
        }
        PC3.BusyIndicator {
            id: indicator
            anchors.centerIn: parent
            running: preview.draft?.loading === true || picture.status === Image.Loading
            visible: running
        }
    }

    PC3.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: {
            if (!preview.draft) return "";
            if (preview.draft.loading) return i18n("Taking a screenshot…");
            if (preview.draft.problem) return preview.draft.problem;
            if (picture.status === Image.Error) return i18n("The screenshot preview couldn’t be opened.");
            const models = preview.draft.models || [];
            const canShare = preview.chatModel ? models.includes(preview.chatModel) : models.length > 0;
            return canShare ? i18n("Your screenshot is ready. What would you like help with?")
                : i18n("This screenshot is just for your reference with your current AI settings. Describe what you’d like help with.");
        }
    }
}
