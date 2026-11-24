// SPDX-License-Identifier: MIT
// Checks that AnswerBody.qml keeps the same text editor, at no less than its wrapped height, while
// an answer streams in piece by piece (more text, then a code block, then another paragraph):
// rebuilding its rows on every piece made a long answer collapse and jump.
// Run with the Qt 6 runner (the qmltestrunner on PATH can be Qt 5's, which fails on every file):
//   /usr/lib/qt6/bin/qmltestrunner -input tests/tst_StreamingAnswer.qml
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 360
    height: 260

    // Plasma supplies i18n in the applet's context.
    function i18n(message) { return message; }

    HappyBot.AnswerBody {
        id: answer
        width: parent.width
    }

    TestCase {
        name: "StreamingAnswer"
        when: windowShown

        function firstVisibleEditor(item) {
            if (item instanceof TextEdit && item.visible) return item;
            for (const child of item.children) {
                const editor = firstVisibleEditor(child);
                if (editor) return editor;
            }
            return null;
        }

        function test_streamKeepsWrappedEditor() {
            answer.text = "Enough words for several wrapped lines. ".repeat(25);
            tryVerify(() => firstVisibleEditor(answer) !== null);
            const editor = firstVisibleEditor(answer);
            const height = editor.implicitHeight;
            verify(height > 0);

            for (const chunk of ["Next", " words.", "\n\n~~~sh\n", "pwd", "\n~~~\n", "Last paragraph."]) {
                answer.text += chunk;
                waitForRendering(answer);
                compare(firstVisibleEditor(answer), editor);
                verify(editor.implicitHeight >= height);
            }
        }
    }
}
