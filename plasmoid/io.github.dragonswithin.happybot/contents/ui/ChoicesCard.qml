/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * Buttons the assistant put under the conversation, drawn in place of the
 * step line by TranscriptEntry.qml: a short question with its answers
 * (`ask_user`), or "Next:" with likely next requests (`suggest_next`).
 *
 * `choices` is the card the daemon sends with either tool's result
 * (`choices_card` in src/happy_bot/tools/choices.py): `{question, choices:
 * [text], follow_up}`. A click emits `chosen(text)`, which the popup sends
 * as the user's next message; the buttons wrap onto more lines when they do
 * not fit. While the assistant is working (`enabled` false) they cannot be
 * clicked. The card keeps no state.
 */
ColumnLayout {
    id: card

    required property var choices

    signal chosen(string text)

    spacing: Kirigami.Units.smallSpacing

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: card.choices.follow_up ? i18n("Next:") : card.choices.question
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font.weight: card.choices.follow_up ? Font.Normal : Font.DemiBold
        opacity: card.choices.follow_up ? 0.7 : 1
    }

    Flow {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Repeater {
            model: card.choices.choices

            PlasmaComponents3.Button {
                required property string modelData
                text: modelData
                icon.name: card.choices.follow_up ? "go-next" : ""
                enabled: card.enabled
                onClicked: card.chosen(modelData)
            }
        }
    }
}
