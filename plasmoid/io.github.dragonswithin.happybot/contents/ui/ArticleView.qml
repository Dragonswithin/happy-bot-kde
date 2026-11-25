/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * An offline Wikipedia article in Happy Bot's own view (ResultsView.qml
 * shows it while `session.article` is set): its title, "Ask about this"
 * and the article's text as light Markdown drawn by AnswerBody.qml, the
 * same renderer as answers. The daemon already cleaned it
 * (src/happy_bot/wikipedia_reader.py: no infoboxes, tables, reference marks
 * or pictures).
 *
 * Links: a link to another article (no address scheme) opens that article
 * here (`session.openArticle`); a web address goes out through
 * `linkActivated`, which ResultsView.qml passes on like an answer's links.
 * "Ask about this" emits `askRequested(title)`, and main.qml starts a request
 * about the article. While it loads, it says so; a reader problem shows in
 * its place; a very long article ends with a note that the rest is not shown.
 * `naturalHeight` is its exact height, for the popup to size to. The
 * component keeps no state of its own.
 */
ColumnLayout {
    id: view

    required property var session
    readonly property var article: session.article || ({})
    readonly property real naturalHeight: implicitHeight

    signal linkActivated(string link)
    signal askRequested(string title)

    spacing: Kirigami.Units.largeSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 2
            wrapMode: Text.Wrap
            text: view.article.title || ""
        }

        PlasmaComponents3.Button {
            visible: !view.article.loading && !view.article.error
            text: i18n("Ask about this")
            icon.name: "help-contents"
            onClicked: view.askRequested(view.article.title)
        }
    }

    RowLayout {
        visible: view.article.loading === true
        spacing: Kirigami.Units.largeSpacing

        PlasmaComponents3.BusyIndicator {
            running: view.article.loading === true
            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
        }

        PlasmaComponents3.Label {
            text: i18n("Opening the article…")
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: (view.article.error || "").length > 0
        type: Kirigami.MessageType.Warning
        text: view.article.error || ""
    }

    AnswerBody {
        Layout.fillWidth: true
        visible: !view.article.loading && (view.article.text || "").length > 0
        text: view.article.text || ""
        onLinkActivated: link => {
            if (/^[a-z][a-z0-9+.-]*:/i.test(link)) {
                view.linkActivated(link);
            } else {
                view.session.openArticle(link, "");
            }
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: view.article.cut === true
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: i18n("This article is very long; the rest is not shown here.")
    }
}
