/*
    SPDX-License-Identifier: MIT
*/

/**
 * Splits an answer's Markdown into the parts AnswerBody.qml draws
 * differently, so code can be copied with one press and files opened with
 * one click:
 *
 * - `{kind: "text", text}`: ordinary Markdown (paragraphs, lists, tables,
 *   links), drawn as Markdown.
 * - `{kind: "code", language, code}`: a fenced code block (``` or ~~~, with
 *   an optional language word), drawn in a box with a Copy button. A fence
 *   that is not closed yet, while an answer is still arriving, runs to the
 *   end.
 * - `{kind: "files", paths}`: two or more lines in a row that each hold only
 *   a path on this computer (starting with `/` or `~/`, optionally as a list
 *   item or in backticks), drawn as rows that open the file. `~` becomes
 *   `home`. A single path stays in the text.
 *
 * `split(markdown, home)` returns the parts in order; empty text parts are
 * dropped. Pure function, no Qt: tests/test_answer_parts.py runs it in
 * Node.
 */
.pragma library

const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const PATH_LINE = /^\s*(?:[-*+]\s+|\d+[.)]\s+)?`?((?:~\/|\/)[^`]*?)`?\s*$/;

function pathOf(line, home) {
    const match = PATH_LINE.exec(line);
    if (!match || match[1].indexOf("://") !== -1 || match[1].length < 2) {
        return "";
    }
    const path = match[1].trim();
    return path.startsWith("~/") ? home + path.substring(1) : path;
}

function split(markdown, home) {
    const lines = String(markdown || "").split("\n");
    const parts = [];
    let text = [];

    function flushText() {
        const joined = text.join("\n");
        if (joined.trim().length > 0) {
            parts.push({ kind: "text", text: joined });
        }
        text = [];
    }

    let index = 0;
    while (index < lines.length) {
        const fence = FENCE.exec(lines[index]);
        if (fence) {
            flushText();
            const closing = fence[1];
            const code = [];
            index += 1;
            while (index < lines.length && !(lines[index].trim().startsWith(closing.charAt(0).repeat(closing.length))
                                              && lines[index].trim().replace(/[`~]/g, "").length === 0)) {
                code.push(lines[index]);
                index += 1;
            }
            parts.push({ kind: "code", language: fence[2] || "", code: code.join("\n") });
            index += 1;
            continue;
        }
        const paths = [];
        let next = index;
        while (next < lines.length && pathOf(lines[next], home)) {
            paths.push(pathOf(lines[next], home));
            next += 1;
        }
        if (paths.length >= 2) {
            flushText();
            parts.push({ kind: "files", paths: paths });
            index = next;
            continue;
        }
        text.push(lines[index]);
        index += 1;
    }
    flushText();
    return parts;
}
