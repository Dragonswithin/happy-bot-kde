/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * An offline Wikipedia article in Happy Bot (ResultsView.qml shows it while
 * `session.article` is set): its title and "Ask about this", then the
 * article itself.
 *
 * Normally that is the archive's own page, as Wikipedia shows it, in
 * ArticleWebView.qml (`webMode`): it fills the body, scrolls itself and
 * follows links in place; `back()` steps back through the pages followed.
 * The page view is loaded through a Loader because it needs QtWebEngine:
 * where that is missing or fails, the article is fetched as light Markdown
 * instead (`session.loadArticleText`, src/happy_bot/wikipedia_reader.py, no
 * infoboxes or pictures) and drawn by AnswerBody.qml, where a link to
 * another article opens it here (`session.openArticle`) and a web address
 * goes out through `linkActivated`, and a very long article ends with a
 * note that the rest is not shown. "Ask about this" emits
 * `askRequested(title)`, and ResultsView.qml starts a request about the
 * article. While it loads, it says so; a reader problem shows in its place.
 * `naturalHeight` is the text view's exact height, for the popup to size
 * to. The component keeps no state of its own beyond whether the page view
 * could be used.
 */
ColumnLayout {
    id: view

    required property var session
    readonly property var article: session.article || ({})
    readonly property real naturalHeight: implicitHeight
    property bool webFailed: false  // QtWebEngine is missing or could not start: the text view is used
    readonly property bool webMode: !webFailed && (article.url || "").length > 0

    property var webView: page.item  // the loaded ArticleWebView.qml, or null

    function back() {
        return view.webMode && view.webView ? view.webView.back() : false;
    }

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
        visible: view.article.loading === true || (view.webMode && !!view.webView && view.webView.loading === true)
        spacing: Kirigami.Units.largeSpacing

        PlasmaComponents3.BusyIndicator {
            running: parent.visible
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

    Loader {
        id: page
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: view.webMode
        active: view.webMode
        source: "ArticleWebView.qml"
        onStatusChanged: {
            if (status === Loader.Error) {
                view.webFailed = true;
                view.session.loadArticleText();
            }
        }
    }

    Binding {
        target: page.item
        property: "pageUrl"
        value: view.article.url || ""
        when: page.status === Loader.Ready
    }

    Connections {
        target: page.item
        ignoreUnknownSignals: true
        function onShown(title, path) {
            view.session.articleShown(title, path);
        }
    }

    AnswerBody {
        Layout.fillWidth: true
        visible: !view.webMode && !view.article.loading && (view.article.text || "").length > 0
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
