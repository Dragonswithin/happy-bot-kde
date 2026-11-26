// SPDX-License-Identifier: MIT
// Checks that ResultsView.qml keeps its layout when the field moves from the bottom to the top (the
// floating Happy Bot moved into the screen's top half, or the app starting before its saved place
// is known): the field band keeps its own height, below the title when at the top. Its anchors
// were once switched from the bottom to the top at run time, which left the band anchored to both
// for a moment: it stretched over the whole view and stayed so, and only the field showed.
// The view gets a real AssistantSession pointed at a closed port, so nothing is asked of a daemon.
// Run with the Qt 6 runner:
//   /usr/lib/qt6/bin/qmltestrunner -input tests/tst_FieldSide.qml
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 800
    height: 700

    // Plasma supplies i18n in the applet's context.
    function i18n(message) { return message; }
    function i18np(single, plural, count) { return count === 1 ? single : plural; }
    function i18nc(context, message) { return message; }

    HappyBot.ResultsView {
        id: view
        session: HappyBot.AssistantSession { configuredUrl: "http://127.0.0.1:9" }
        fieldAtBottom: true
    }

    TestCase {
        name: "FieldSide"
        when: windowShown

        // The field band is the child with `forceFieldFocus`.
        function band() {
            for (const child of view.children) {
                if (typeof child.forceFieldFocus === "function") return child;
            }
            return null;
        }

        function test_fieldMovesToTheTopWithItsOwnHeight() {
            const field = band();
            verify(field !== null);
            const height = field.implicitHeight;
            compare(Math.round(field.y + field.height), Math.round(view.height));   // at the bottom
            view.fieldAtBottom = false;
            const heading = findChild(view, "viewHeading");
            verify(field.y >= heading.mapToItem(view, 0, heading.height).y);
            compare(field.height, height);
            view.fieldAtBottom = true;
            compare(field.height, height);
            compare(Math.round(field.y + field.height), Math.round(view.height));
        }
    }
}
