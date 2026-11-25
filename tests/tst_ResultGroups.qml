// SPDX-License-Identifier: MIT
// Checks how search results are grouped under headings (Look.qml: hitGroup, groupHits, hitWhere),
// as the panel bar's list and the popup's "Find a file" show them: each kind together, applications
// first and files last, the daemon's order kept within a kind, and a quick result's detail shown
// without the kind its heading already names.
// Run with the Qt 6 runner:
//   /usr/lib/qt6/bin/qmltestrunner -input tests/tst_ResultGroups.qml
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui"

TestCase {
    name: "ResultGroups"

    // Plasma supplies i18n in the applet's context.
    function i18n(message) { return message; }

    function quick(title, type, subtitle) {
        return { kind: "quick", title: title, subtitle: subtitle || "", icon: "", action: { type: type, target: title } };
    }

    function test_applicationsComeFirstAndFilesLast() {
        const hits = [quick("Sound", "settings", "System Settings · Audio devices"), { kind: "file", title: "a.txt", location: "/a.txt" },
                      quick("Prism Launcher", "launch", "Application · Minecraft launcher"),
                      quick("minecraft", "conversation", "Earlier conversation"), quick("Steam", "launch", "Application"),
                      quick("2+2 = 4", "copy", "Press Enter to copy"),
                      quick("KDE", "visited", "Visited · kde.org · Firefox"), quick("Arch Wiki", "bookmark", "Bookmark · wiki.archlinux.org · Firefox")];
        compare(Look.groupHits(hits).map(hit => hit.title),
                ["2+2 = 4", "Prism Launcher", "Steam", "Sound", "Arch Wiki", "KDE", "minecraft", "a.txt"]);
        compare(Look.groupHits(hits).map(hit => Look.hitGroup(hit)),
                ["answer", "applications", "applications", "settings", "bookmarks", "websites", "chats", "files"]);
    }

    function test_detailWithoutTheKind() {
        compare(Look.hitWhere(quick("Prism Launcher", "launch", "Application · Minecraft launcher")), "Minecraft launcher");
        compare(Look.hitWhere(quick("minecraft", "conversation", "Earlier conversation")), "");
        compare(Look.hitWhere(quick("KDE", "visited", "Visited · kde.org · Firefox")), "kde.org · Firefox");
        compare(Look.hitWhere(quick("2+2 = 4", "copy", "Press Enter to copy")), "Press Enter to copy");
    }
}
