/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import QtWebEngine

/**
 * An offline Wikipedia article as Wikipedia shows it: the archive's own page (pictures, infobox,
 * Wikipedia's styles) in a web view, loaded from the daemon's loopback page server
 * (src/happy_bot/wikipedia_pages.py). ArticleView.qml loads this file through a Loader, so where
 * QtWebEngine is missing or cannot start, it shows its text view instead.
 *
 * `pageUrl` is the article's address (`session.article.url`, set by ArticleView.qml). Links between
 * articles stay on the page server (`base`, the part of the address up to and including the secret)
 * and open here; anything else (a web address, an edit link) is refused here and opened in the
 * user's browser instead, and pages may not open windows of their own. As the user follows links,
 * `shown(title, path)` reports the article in view, so the header's title and "Ask about this"
 * follow. `back()` goes back one page and returns false when there is none, for ResultsView.qml's
 * Back button. The view uses the default off-the-record profile, so nothing
 * from it (history, cache, cookies) is written to disk; the page server's policy keeps the page
 * from contacting the internet.
 */
WebEngineView {
    id: web

    property url pageUrl
    readonly property string base: {
        const url = String(web.pageUrl);
        const match = url.match(/^(https?:\/\/[^\/]+\/[^\/]+\/)/);
        return match ? match[1] : "";
    }

    function back() {
        if (web.canGoBack) {
            web.goBack();
            return true;
        }
        return false;
    }

    signal shown(string title, string path)

    url: web.pageUrl
    settings.javascriptCanOpenWindows: false
    settings.localContentCanAccessRemoteUrls: false
    settings.focusOnNavigationEnabled: false  // typing stays in Happy Bot's field

    onNavigationRequested: request => {
        const target = String(request.url);
        if (web.base.length > 0 && !target.startsWith(web.base) && !target.startsWith("data:")) {
            request.reject();
            Qt.openUrlExternally(request.url);
        }
    }
    onNewWindowRequested: request => Qt.openUrlExternally(request.requestedUrl)
    onTitleChanged: {
        const address = String(web.url);
        if (web.base.length > 0 && address.startsWith(web.base) && web.title.length > 0) {
            web.shown(web.title, decodeURIComponent(address.substring(web.base.length)));
        }
    }
}
