// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC3

ColumnLayout {
    id: preview
    property var popup: null

    required property var session
    readonly property var draft: session.helpDraft
    readonly property bool hasImage: !!draft?.id
    readonly property bool selecting: session.helpAction === "point" || session.helpAction === "crop"
    readonly property bool working: session.helpAction === "applying" || session.helpAction === "reading"
    signal explainRequested()
    signal focusQuestion()
    spacing: Kirigami.Units.smallSpacing

    HelpScreenshotView {
        id: screenshot
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 0
        visible: preview.hasImage || preview.session.capturing
        source: preview.draft?.url || ""
        action: preview.session.helpAction
        busy: preview.session.capturing || preview.working
        onEditRequested: (action, coordinates) => preview.session.editHelp(action, coordinates)
    }

    // On short windows the tools can scroll independently of the picture.
    PopupScrollView {
        popup: preview.popup
        Layout.fillWidth: true
        Layout.fillHeight: !screenshot.visible
        Layout.minimumHeight: 0
        Layout.preferredHeight: screenshot.visible ? Math.min(toolsArea.contentHeight, preview.height * 0.43)
                                                   : toolsArea.contentHeight
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
        Flickable {
            acceptedButtons: Qt.NoButton
            id: toolsArea
            contentWidth: width
            contentHeight: controls.implicitHeight + 2 * Kirigami.Units.smallSpacing
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            Connections {
                target: preview.session
                function onReviewingErrorChanged() {
                    Qt.callLater(() => {
                        if (preview.session.reviewingError)
                            toolsArea.contentY = Math.max(0, toolsArea.contentHeight - toolsArea.height);
                    });
                }
            }
            ColumnLayout {
                id: controls
                x: Kirigami.Units.smallSpacing
                y: Kirigami.Units.smallSpacing
                width: Math.max(1, toolsArea.width - 2 * x)
                spacing: Kirigami.Units.smallSpacing
                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    visible: !!preview.draft
                    component EditButton: PC3.ToolButton {
                        enabled: !preview.working
                        display: controls.width < Kirigami.Units.gridUnit * 29 ? QQC2.AbstractButton.IconOnly : QQC2.AbstractButton.TextBesideIcon
                        AssistantToolTip {
                            accent: preview.popup?.accent ?? Kirigami.Theme.highlightColor
                            text: parent.text
                            visible: parent.hovered
                        }
                    }
                    EditButton {
                        text: i18n("Retake")
                        icon.name: "camera-photo"
                        visible: !preview.session.capturing
                        enabled: !preview.session.locatingApplication && !preview.working
                        onClicked: { preview.session.captureForHelp(); preview.focusQuestion(); }
                    }
                    EditButton {
                        text: i18n("Point")
                        icon.name: "draw-ellipse"
                        visible: preview.hasImage
                        checkable: true
                        checked: preview.session.helpAction === "point"
                        onClicked: preview.session.helpAction = checked ? "point" : ""
                    }
                    EditButton {
                        text: i18n("Crop")
                        icon.name: "transform-crop"
                        visible: preview.hasImage
                        checkable: true
                        checked: preview.session.helpAction === "crop"
                        onClicked: preview.session.helpAction = checked ? "crop" : ""
                    }
                    EditButton {
                        text: i18n("Undo edit")
                        icon.name: "edit-undo"
                        visible: !!preview.draft?.previous
                        onClicked: {
                            preview.session.resetHelpEditor();
                            preview.session.helpDraft = preview.draft.previous;
                        }
                    }
                    PC3.ToolButton {
                        text: i18n("Zoom out")
                        icon.name: "zoom-out"
                        display: QQC2.AbstractButton.IconOnly
                        visible: preview.hasImage
                        enabled: screenshot.zoom > 1
                        AssistantToolTip {
                            accent: preview.popup?.accent ?? Kirigami.Theme.highlightColor
                            text: parent.text
                            visible: parent.hovered
                        }
                        onClicked: screenshot.zoomAt(1 / 1.3, screenshot.width / 2, screenshot.height / 2)
                    }
                    PC3.ToolButton {
                        text: i18n("Zoom in")
                        icon.name: "zoom-in"
                        display: QQC2.AbstractButton.IconOnly
                        visible: preview.hasImage
                        enabled: screenshot.zoom < screenshot.maximumZoom
                        AssistantToolTip {
                            accent: preview.popup?.accent ?? Kirigami.Theme.highlightColor
                            text: parent.text
                            visible: parent.hovered
                        }
                        onClicked: screenshot.zoomAt(1.3, screenshot.width / 2, screenshot.height / 2)
                    }
                    PC3.ToolButton {
                        id: fitButton
                        text: i18n("Fit")
                        visible: preview.hasImage
                        Accessible.name: i18n("Fit screenshot to window")
                        AssistantToolTip {
                            accent: preview.popup?.accent ?? Kirigami.Theme.highlightColor
                            text: i18n("Fit the entire screenshot. Scroll over the picture to zoom.")
                            visible: parent.hovered
                        }
                        onClicked: screenshot.fit()
                    }
                    PC3.Label {
                        width: Math.min(implicitWidth, controls.width)
                        height: Math.max(implicitHeight, fitButton.height)
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.Wrap
                        visible: text.length > 0
                        text: {
                            if (!preview.draft) return "";
                            if (preview.draft.loading) return i18n("Taking a screenshot…");
                            if (preview.session.helpAction === "point") return i18n("Click the part you mean to circle it.");
                            if (preview.session.helpAction === "crop") return i18n("Drag across the part you want to keep.");
                            if (preview.session.helpEditProblem) return preview.session.helpEditProblem;
                            if (preview.draft.problem) return preview.draft.problem;
                            if (screenshot.imageStatus === Image.Error) return i18n("The screenshot preview couldn’t be opened.");
                            const models = preview.draft.models || [];
                            const canShare = preview.session.chatModel ? models.includes(preview.session.chatModel) : models.length > 0;
                            return canShare ? i18n("Scroll to zoom. Drag to pan.") : i18n("This screenshot is just for your reference with your current AI settings.");
                        }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing
                    visible: !!preview.draft && !preview.session.capturing
                    PC3.CheckBox {
                        text: i18n("Include screenshot with this request")
                        visible: preview.hasImage
                        checked: preview.session.includeHelpScreenshot
                        onToggled: {
                            preview.session.includeHelpScreenshot = checked;
                            if (!checked && preview.selecting) preview.session.helpAction = "";
                        }
                    }
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
        }
    }
}
