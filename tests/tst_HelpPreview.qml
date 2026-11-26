// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 800
    height: 700
    function i18n(message, arg) { return arg === undefined ? message : message.replace("%1", arg); }
    function i18np(single, plural, count) { return count === 1 ? single : plural; }
    function i18nc(context, message) { return message; }

    HappyBot.ResultsView {
        id: view
        session: HappyBot.AssistantSession {
            id: session
            property var capture
            property var edit
            property var sent
            function request(method, path, body, success, failure) {
                if (path === "/context/screenshot") capture = { body, success, failure };
                if (path === "/context/screenshot/edit") edit = { body, success, failure };
            }
            function startStream(body, mayReload, xhr) { sent = body; }
        }
        onAccepted: text => session.ask(text)
        onAskRequested: text => session.ask(text)
    }

    TestCase {
        name: "HelpPreview"
        when: windowShown

        function findVisible(item, predicate) {
            if (!item.visible) return null;
            if (predicate(item)) return item;
            for (const child of item.children) {
                const match = findVisible(child, predicate);
                if (match) return match;
            }
            return null;
        }

        function init() {
            view.heightInGridUnits = 26;
            session.history = [];
            session.busy = false;
            session.resetTranscript();
            session.helpWith = { app: "Kate", window: "{kate}" };
            session.capture = null;
            session.edit = null;
            session.sent = null;
            view.clearInput();
        }

        function clickTile(label) {
            wait(35);  // Flow and the popup resize on the next frame.
            const button = findVisible(view, item => item.text === label && typeof item.clicked === "function");
            verify(!!button);
            mouseClick(button);
        }

        function ready(id) {
            session.capture.success({ id, url: Qt.resolvedUrl(
                "../plasmoid/io.github.dragonswithin.happybot/contents/images/happy-bot.svg").toString(), models: ["Vision"] });
            tryVerify(() => !!findVisible(view, item => item.Accessible.name === "Screenshot preview" && item.status === Image.Ready));
        }

        function fixtureUrl(width, height, fill) {
            const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + width
                + '" height="' + height + '"><rect width="100%" height="100%" fill="' + fill + '"/></svg>';
            return "data:image/svg+xml," + encodeURIComponent(svg);
        }

        function captureImage(id, width, height) {
            session.capture.success({ id, url: fixtureUrl(width, height, "teal"), models: ["Vision"] });
            const image = findVisible(view, item => item.Accessible.name === "Screenshot preview");
            tryCompare(image, "status", Image.Ready);
            wait(35);  // let the tool row and preview receive their final sizes
            return image;
        }

        function verifyFit(image) {
            const frame = image.parent;
            compare(frame.zoom, 1);
            verify(image.width <= frame.width + 1 && image.height <= frame.height + 1);
            verify(Math.abs(image.width - frame.width) < 1 || Math.abs(image.height - frame.height) < 1);
            fuzzyCompare(image.x + image.width / 2, frame.width / 2, 0.5);
            fuzzyCompare(image.y + image.height / 2, frame.height / 2, 0.5);
        }

        function originalPoint(image, x, y) {
            const point = image.mapFromItem(image.parent, x, y);
            return Qt.point(point.x / image.width, point.y / image.height);
        }

        function test_wheelPanAndMarkOriginalPixels() {
            session.history = [{ id: "test", title: "Test" }];
            const windowWidth = view.width;
            clickTile("Help with Kate");
            const image = captureImage("wide", 1920, 1080);
            const frame = image.parent;
            verifyFit(image);
            compare(frame.width, windowWidth); // the picture can use the saved-chat sidebar's space
            compare(image.sourceSize.width, 1920);
            const initialWidth = image.width;
            const x = Math.round(frame.width * 0.59), y = Math.round(frame.height * 0.43);
            const anchor = originalPoint(image, x, y);
            mouseWheel(frame, x, y, 0, 480);
            verify(image.width > 2 * initialWidth);
            const after = originalPoint(image, x, y);
            fuzzyCompare(anchor.x, after.x, 0.002);
            fuzzyCompare(anchor.y, after.y, 0.002);
            mouseDrag(frame, x, y, -55, 25);
            const panned = originalPoint(image, x, y);
            verify(panned.x > anchor.x && panned.y < anchor.y);
            clickTile("Point");
            const target = originalPoint(image, x, y);
            mouseClick(frame, x, y);
            fuzzyCompare(session.edit.body.coordinates[0], target.x, 0.002);
            fuzzyCompare(session.edit.body.coordinates[1], target.y, 0.002);
            const magnification = frame.zoom;
            session.edit.success({ id: "marked", url: fixtureUrl(1920, 1080, "red") });
            tryCompare(image, "status", Image.Ready);
            compare(frame.zoom, magnification);
            clickTile("Crop");
            wait(35);
            const topLeft = originalPoint(image, x - 24, y - 18);
            const bottomRight = originalPoint(image, x, y);
            mouseDrag(frame, x, y, -24, -18);
            const crop = session.edit.body.coordinates;
            compare(session.edit.body.action, "crop");
            fuzzyCompare(crop[0], topLeft.x, 0.002);
            fuzzyCompare(crop[1], topLeft.y, 0.002);
            fuzzyCompare(crop[2], bottomRight.x, 0.002);
            fuzzyCompare(crop[3], bottomRight.y, 0.002);
            session.edit.failure({error: "Test"});
            clickTile("Fit");
            verifyFit(image);
            clickTile("Zoom in");
            verify(frame.zoom > 1);
            clickTile("Zoom out");
            verifyFit(image);
            clickTile("Zoom in");
            clickTile("Retake");
            captureImage("portrait", 900, 1600);
            verifyFit(image);
            view.heightInGridUnits = 16;
            wait(35);
            verifyFit(image);
        }

        function test_retakeErrorAndPerRequestChoice() {
            clickTile("Help with Kate");
            ready("one");
            view.setInput("Why did this fail?");
            clickTile("Include screenshot with this request");
            clickTile("Retake");
            ready("two");
            compare(view.inputText, "Why did this fail?");
            compare(session.includeHelpScreenshot, false);
            clickTile("Walk me through it");
            clickTile("Explain this error");
            compare(session.edit.body.id, "two");
            session.edit.success({ text: "Permission denied" });
            const editor = findVisible(view, item => item.Accessible.name === "Error text to explain"
                && typeof item.selectAll === "function");
            verify(!!editor);
            editor.forceActiveFocus();
            editor.selectAll();
            keyClick(Qt.Key_X);
            compare(view.inputText, "Why did this fail?");
            view.accepted(view.inputText);
            tryVerify(() => !!session.sent);
            compare(session.sent.screenshot_id, "");
            compare(session.sent.include_screenshot, false);
            compare(session.sent.help_error_text, "x");
            verify(session.sent.walkthrough);
            session.busy = false;
            view.clearInput();
            clickTile("I don’t see that");
            ready("three");
            verify(session.includeHelpScreenshot);
            compare(view.inputText, "I don’t see that");
            clickTile("Back");
            verify(session.walkthrough);
            clickTile("Next step");
            tryVerify(() => session.sent.message === "Next step");
            verify(!session.sent.include_screenshot);
        }

        function test_pointCropAndUndo() {
            clickTile("Help with Kate");
            ready("original");
            clickTile("Point");
            const picture = findVisible(view, item => item.Accessible.name === "Screenshot preview");
            mouseClick(picture, picture.width / 2, picture.height / 2);
            compare(session.edit.body.action, "point");
            fuzzyCompare(session.edit.body.coordinates[0], 0.5, 0.01);
            fuzzyCompare(session.edit.body.coordinates[1], 0.5, 0.01);
            session.edit.success({ id: "marked", url: session.helpDraft.url });
            clickTile("Crop");
            const x = picture.width / 2, y = picture.height / 2;
            mousePress(picture, x, y);
            mouseMove(picture, x + 20, y + 25);
            mouseRelease(picture, x + 20, y + 25);
            compare(session.edit.body.action, "crop");
            compare(session.edit.body.id, "marked");
            session.edit.success({ id: "smaller", url: session.helpDraft.url });
            verify(session.helpDraft.cropped);
            clickTile("Undo edit");
            compare(session.helpDraft.id, "marked");
            view.accepted("What is circled?");
            tryVerify(() => !!session.sent);
            compare(session.sent.screenshot_id, "marked");
        }

        function test_clickPreviewThenAsk() {
            verify(!session.capture);
            clickTile("Help with Kate");
            compare(session.capture.body.window, "{kate}");
            compare(session.capture.body.desktop, false);
            verify(view.helpVisible);
            compare(view.inputText, "");
            verify(!findVisible(view, item => item.text === "How can I help?"));
            view.setInput("How do I split the view?");
            keyClick(Qt.Key_Return);
            compare(session.entries.count, 0);
            session.capture.success({ id: "sample", url: Qt.resolvedUrl(
                "../plasmoid/io.github.dragonswithin.happybot/contents/images/happy-bot.svg").toString(), models: [] });
            tryVerify(() => !!findVisible(view, item => item.fillMode === Image.PreserveAspectFit && item.status === Image.Ready));
            verify(findVisible(view, item => String(item.text).includes("just for your reference")));
            compare(session.entries.count, 0);
            session.helpWith = { app: "Another window", window: "{other}" };
            keyClick(Qt.Key_Return);
            tryVerify(() => !!session.sent);
            compare(session.sent.message, "How do I split the view?");
            compare(session.sent.about_window.window, "{kate}");
            compare(session.sent.screenshot_id, "sample");
            verify(!view.helpVisible);
        }

        function test_backDiscardsLateCapture() {
            clickTile("Help with Kate");
            const previous = session.capture;
            clickTile("Back");
            verify(!view.helpVisible);
            session.helpWith = null;
            clickTile("Desktop help");
            compare(session.capture.body.desktop, true);
            previous.success({ id: "old", url: "file:///old.png" });
            verify(session.capturing);
            session.capture.success({ taken: false, reason: "disabled" });
            verify(!session.capturing);
            verify(findVisible(view, item => String(item.text).includes("turned off")));
            keyClick(Qt.Key_Escape);
            verify(!view.helpVisible);
            verify(!session.helpChat);
        }
    }
}
