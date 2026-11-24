/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

import "answerParts.js" as AnswerParts

/**
 * The body of an answer card in TranscriptEntry.qml: the answer's Markdown
 * split by answerParts.js and drawn part by part.
 *
 * - Text is Markdown in a selectable, read-only TextEdit; links are passed
 *   out through `linkActivated`.
 * - Code is a tinted box in the fixed-width font with its language (when
 *   the answer named one) and a Copy button for just that block.
 * - A list of files is a row per file with its type's icon (a picture's
 *   own thumbnail for images), name and folder; a click opens it through
 *   `linkActivated("file://…")`, the same route as a link.
 *
 * `copyAll()` copies the whole answer as readable text (the Markdown
 * rendered, without its symbols), for the card's "Copy answer" button. The
 * component keeps no state; parts are recomputed when `text` changes, which
 * happens as an answer streams in.
 */
ColumnLayout {
    id: body

    property string text: ""

    signal linkActivated(string link)

    readonly property var parts: AnswerParts.split(text, Look.homePath)
    readonly property var imageExtensions: ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"]

    spacing: Kirigami.Units.smallSpacing

    function copyAll() {
        wholeAnswer.text = body.text;
        wholeAnswer.selectAll();
        wholeAnswer.copy();
        wholeAnswer.text = "";
    }

    function extension(path) {
        const dot = path.lastIndexOf(".");
        return dot > path.lastIndexOf("/") ? path.substring(dot + 1).toLowerCase() : "";
    }

    // Holds the whole answer only so "Copy answer" copies it as plain, readable text.
    TextEdit {
        id: wholeAnswer
        visible: false
        textFormat: TextEdit.MarkdownText
    }

    // A new JS array (or a new integer count) resets a Repeater. Append and
    // remove only the affected rows so existing editors keep their wrapped height.
    component IndexModel: ListModel {
        required property int length
        onLengthChanged: {
            if (count > length) {
                remove(length, count - length);
            }
            while (count < length) {
                append({});
            }
        }
    }

    Repeater {
        model: IndexModel { length: body.parts.length }

        Loader {
            id: part

            required property int index
            readonly property var block: body.parts[index]

            Layout.fillWidth: true
            sourceComponent: !block ? null
                : block.kind === "code" ? codePart
                : block.kind === "files" ? filesPart : textPart

            Component {
                id: textPart

                TextEdit {
                    text: part.block?.text ?? ""
                    textFormat: TextEdit.MarkdownText
                    wrapMode: TextEdit.Wrap
                    readOnly: true
                    selectByMouse: true
                    color: Kirigami.Theme.textColor
                    selectionColor: Kirigami.Theme.highlightColor
                    selectedTextColor: Kirigami.Theme.highlightedTextColor
                    font: Kirigami.Theme.defaultFont
                    onLinkActivated: link => body.linkActivated(link)

                    HoverHandler {
                        cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
                    }
                }
            }

            Component {
                id: codePart

                Rectangle {
                    implicitHeight: codeColumn.implicitHeight + Kirigami.Units.smallSpacing * 2
                    radius: Kirigami.Units.cornerRadius
                    color: Qt.alpha(Kirigami.Theme.textColor, 0.06)

                    ColumnLayout {
                        id: codeColumn

                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.smallSpacing
                        spacing: 0

                        RowLayout {
                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                text: part.block?.language ?? ""
                                font: Kirigami.Theme.smallFont
                                opacity: 0.6
                            }

                            PlasmaComponents3.ToolButton {
                                icon.name: "edit-copy"
                                text: i18n("Copy")
                                font: Kirigami.Theme.smallFont
                                onClicked: {
                                    code.selectAll();
                                    code.copy();
                                    code.deselect();
                                    text = i18n("Copied");
                                }
                            }
                        }

                        TextEdit {
                            id: code
                            Layout.fillWidth: true
                            text: part.block?.code ?? ""
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.WrapAnywhere
                            readOnly: true
                            selectByMouse: true
                            color: Kirigami.Theme.textColor
                            selectionColor: Kirigami.Theme.highlightColor
                            selectedTextColor: Kirigami.Theme.highlightedTextColor
                            font: Kirigami.Theme.fixedWidthFont
                        }
                    }
                }
            }

            Component {
                id: filesPart

                ColumnLayout {
                    spacing: 0

                    Repeater {
                        model: IndexModel { length: part.block?.paths?.length ?? 0 }

                        PlasmaComponents3.ItemDelegate {
                            id: fileRow

                            required property int index
                            readonly property string path: part.block?.paths?.[index] ?? ""
                            readonly property bool isImage: body.imageExtensions.indexOf(body.extension(fileRow.path)) !== -1

                            Layout.fillWidth: true
                            onClicked: body.linkActivated("file://" + path)
                            Accessible.name: i18n("Open %1", fileRow.path)

                            contentItem: RowLayout {
                                spacing: Kirigami.Units.smallSpacing

                                Kirigami.Icon {
                                    source: fileRow.isImage ? "file://" + fileRow.path
                                        : Look.hitIcon({ kind: "file", location: fileRow.path })
                                    fallback: "text-x-generic"
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0

                                    PlasmaComponents3.Label {
                                        Layout.fillWidth: true
                                        text: fileRow.path.substring(fileRow.path.lastIndexOf("/") + 1)
                                        elide: Text.ElideMiddle
                                    }

                                    PlasmaComponents3.Label {
                                        Layout.fillWidth: true
                                        text: Look.hitWhere({ kind: "file", location: fileRow.path })
                                        elide: Text.ElideMiddle
                                        font: Kirigami.Theme.smallFont
                                        opacity: 0.6
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
