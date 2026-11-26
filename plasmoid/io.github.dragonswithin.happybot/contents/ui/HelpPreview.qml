// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC3

ColumnLayout {
    id: preview

    required property var session
    readonly property var draft: session.helpDraft
    readonly property bool hasImage: !!draft?.id
    readonly property bool selecting: session.helpAction === "point" || session.helpAction === "crop"
    readonly property bool working: session.helpAction === "applying" || session.helpAction === "reading"
    signal explainRequested()
    signal focusQuestion()
    spacing: Kirigami.Units.smallSpacing

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(width * 0.56, Kirigami.Units.gridUnit * 11)
        visible: preview.hasImage || indicator.running
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

            MouseArea {
                id: selection
                anchors.centerIn: parent
                width: picture.paintedWidth
                height: picture.paintedHeight
                enabled: preview.selecting && picture.status === Image.Ready
                preventStealing: true
                cursorShape: Qt.CrossCursor
                property point start
                property point end
                function position(mouse) {
                    return Qt.point(Math.max(0, Math.min(width, mouse.x)), Math.max(0, Math.min(height, mouse.y)));
                }
                onPressed: mouse => { start = position(mouse); end = start; }
                onPositionChanged: mouse => { if (pressed) end = position(mouse); }
                onReleased: mouse => {
                    end = position(mouse);
                    if (preview.session.helpAction === "point") {
                        preview.session.editHelp("point", [end.x / width, end.y / height]);
                    } else if (Math.abs(end.x - start.x) >= 3 && Math.abs(end.y - start.y) >= 3) {
                        preview.session.editHelp("crop", [Math.min(start.x, end.x) / width,
                            Math.min(start.y, end.y) / height, Math.max(start.x, end.x) / width,
                            Math.max(start.y, end.y) / height]);
                    }
                }
                Rectangle {
                    visible: selection.pressed && preview.session.helpAction === "crop"
                    x: Math.min(selection.start.x, selection.end.x)
                    y: Math.min(selection.start.y, selection.end.y)
                    width: Math.abs(selection.end.x - selection.start.x)
                    height: Math.abs(selection.end.y - selection.start.y)
                    border.color: "white"
                    border.width: 2
                    color: Qt.alpha(Kirigami.Theme.highlightColor, 0.25)
                }
            }
        }
        PC3.BusyIndicator {
            id: indicator
            anchors.centerIn: parent
            running: preview.draft?.loading === true || picture.status === Image.Loading || preview.working
            visible: running
        }
    }

    Flow {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        visible: !!preview.draft && !preview.session.capturing
        enabled: !preview.working
        PC3.Button {
            text: i18n("Retake")
            icon.name: "camera-photo"
            enabled: !preview.session.locatingApplication
            onClicked: { preview.session.captureForHelp(); preview.focusQuestion(); }
        }
        PC3.Button {
            text: i18n("Point")
            icon.name: "draw-ellipse"
            visible: preview.hasImage
            checkable: true
            checked: preview.session.helpAction === "point"
            onClicked: preview.session.helpAction = checked ? "point" : ""
        }
        PC3.Button {
            text: i18n("Crop")
            icon.name: "transform-crop"
            visible: preview.hasImage
            checkable: true
            checked: preview.session.helpAction === "crop"
            onClicked: preview.session.helpAction = checked ? "crop" : ""
        }
        PC3.ToolButton {
            text: i18n("Undo edit")
            icon.name: "edit-undo"
            visible: !!preview.draft?.previous
            onClicked: {
                preview.session.resetHelpEditor();
                preview.session.helpDraft = preview.draft.previous;
            }
        }
    }
    PC3.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        visible: text.length > 0
        text: {
            if (!preview.draft) return "";
            if (preview.draft.loading) return i18n("Taking a screenshot…");
            if (preview.session.helpAction === "point") return i18n("Click the part you mean to circle it.");
            if (preview.session.helpAction === "crop") return i18n("Drag across the part you want to keep.");
            if (preview.session.helpEditProblem) return preview.session.helpEditProblem;
            if (preview.draft.problem) return preview.draft.problem;
            if (picture.status === Image.Error) return i18n("The screenshot preview couldn’t be opened.");
            const models = preview.draft.models || [];
            const canShare = preview.session.chatModel ? models.includes(preview.session.chatModel) : models.length > 0;
            return canShare ? "" : i18n("This screenshot is just for your reference with your current AI settings.");
        }
    }
    PC3.CheckBox {
        text: i18n("Include screenshot with this request")
        visible: preview.hasImage
        checked: preview.session.includeHelpScreenshot
        onToggled: {
            preview.session.includeHelpScreenshot = checked;
            if (!checked && preview.selecting) preview.session.helpAction = "";
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing
        visible: !!preview.draft && !preview.session.capturing
        PC3.CheckBox {
            text: i18n("Walk me through it")
            checked: preview.session.walkthrough
            onToggled: { preview.session.walkthrough = checked; preview.focusQuestion(); }
        }
        PC3.Button {
            text: i18n("Explain this error")
            enabled: !preview.session.helpPending && !preview.session.reviewingError
            onClicked: {
                if (preview.hasImage) preview.session.editHelp("read", []);
                else preview.session.reviewingError = true;
                preview.explainRequested();
            }
        }
    }
    PC3.Label {
        visible: preview.session.reviewingError
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: {
            const allowed = preview.draft?.textModels || [];
            if (preview.hasImage && !(preview.session.chatModel ? allowed.includes(preview.session.chatModel) : allowed.length))
                return i18n("Your AI settings keep this text local. You can describe the error in your question.");
            return i18n("Error text to explain");
        }
    }
    QQC2.ScrollView {
        visible: preview.session.reviewingError
        Layout.fillWidth: true
        Layout.preferredHeight: Kirigami.Units.gridUnit * 4
        QQC2.TextArea {
            Accessible.name: i18n("Error text to explain")
            wrapMode: TextEdit.Wrap
            enabled: preview.session.helpAction !== "reading"
            placeholderText: enabled ? i18n("Paste or type the error message…") : i18n("Reading text…")
            text: preview.session.helpErrorText
            onTextChanged: if (activeFocus) preview.session.helpErrorText = text
        }
    }
}
