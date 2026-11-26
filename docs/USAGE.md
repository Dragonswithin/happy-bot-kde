# Using Happy Bot

Click the Happy Bot icon in your Plasma panel to open the assistant. For a floating shortcut, launch **Happy Bot** from the application menu. Drag the shortcut to a convenient spot. Right-click either the panel widget or the floating shortcut and choose **Configure Happy Bot…** to open settings.

## Find something from the panel

On a horizontal panel, choose **Appearance → Panel widget → Search bar** to type directly into the panel. Vertical panels use the icon.

| What to do | What happens |
| --- | --- |
| Click the empty bar | Recent items appear. Right-click one and choose **Remove from recent** to hide it from the list. |
| Type an app name, a setting or a filename | Matches appear as you type. Use the arrow keys to pick one and Enter to open it. File results come from the index you chose in **Search & Tools**. |
| Type `volume 30`, `dark mode` or `timer 10m` | Choose the matching command to run it immediately. These commands work without an AI. |
| Type `emoji heart` or `euro sign` | Choose a character to copy it to the clipboard. |
| Choose **Ask Happy Bot about …** | The assistant opens with your request. When nothing matches, Enter selects this option. |

Right-click an application result for actions such as **Start at login**. A file's menu can send it to a paired phone through KDE Connect. KRunner also offers quick answers, file matches and an **Ask the assistant** entry that delivers its reply as a notification.

## Ask the assistant

In the assistant window, type a request and press Enter. Try “Put Firefox on the left half of the screen” or “Which files take up the most space in Downloads?” The conversation shows each tool the AI uses. Use **Stop** to interrupt the request. With multiple models configured, choose one next to the input field or leave **Automatic** selected to follow the order in **AI Model**.

- **Find a file** searches as you type. Choose a file to open it or use its menu to ask about it.
- **Search the web** opens with recent searches and frequent sites. Type a query to use your configured web search. Bookmarks and visited sites are separate opt-ins under **Search & Tools → Browser results**. Right-click a frequent site to search within it, pin it or hide it.
- **Offline Wikipedia** in **Search & Tools** lets you choose a local archive or download one from Kiwix. Articles appear in **Search the web** under their own heading and open inside Happy Bot. Qt WebEngine displays the archived page with its pictures when available. The text view works without it. The assistant can also consult the archive when answering.
- **Help with…** names the app you were using and previews its window. Scroll to zoom or choose **Fit** to see the whole picture. Use **Point** to mark a detail, **Crop** to keep an area, or **Retake** to capture the window again. Clear **Include screenshot with this request** to send just the question and any reviewed text. **Explain this error** lets you correct text recognized by local OCR. **Walk me through it** gives one step at a time.
- **System info** is optional. Enable it under **Appearance → Start screen**. The overview cards show live readings, with graphs for resources such as CPU and memory. Open a card for details. **Storage** lists disks and free space. **Processor** and **Memory** show the busiest programs and let you confirm stopping an eligible program you own.

## Use the microphone or selected text

Turn on **AI Model → Voice input → Show the microphone** and configure a speech-to-text service. Click the microphone and speak. A pause or another click ends the recording. Happy Bot sends the speech to that service and submits the transcript to your AI immediately.

Under **System Settings → Shortcuts → Happy Bot Shortcuts**, you can assign keys to **Talk to Happy Bot** and **Fix selected text**. For the latter, select text in another app and press your shortcut. Choose **Fix grammar**, **Shorter**, **Translate** or **Explain**, or type an instruction. Review the result and choose **Copy** or **Replace**. Terminals offer Copy only. Replacing text uses Plasma’s keyboard-control permission.

## Control what the assistant can do

**Behaviour** sets who can see details from the active application. By default, only local models receive this context. Sharing a Help screenshot also requires an allowed model with image support. When you use a hosted model, your messages and tool results such as file contents or clipboard text can reach that provider.

The default approval policy asks before built-in actions such as overwriting a file, moving it to the trash or installing a package. To review more, choose **Before any change** or **Before every action, including lookups**. Installs that need a password open a terminal where you enter it yourself. Ask “What did you do today?” to review the session’s action history, or “Undo that” to reverse the latest supported change, such as a file move or a volume adjustment.

## Personalize Happy Bot

- **AI Model** lets you reorder models and set prices and a monthly spending limit for a hosted model. When the configured limit is reached, automatic selection skips that model.
- **Appearance** controls the panel, floating shortcut, popup size and start-screen buttons. Enable **Dock to screen edge** for a tab that reveals the floating shortcut on hover. Choose a robot or **Wand** to use KDE’s colors and icons. **Sounds** lets you preview and enable individual event sounds.
- **Show helpful nudges** in Appearance adds a gold note for low battery, low disk space, available updates or a pending restart. Open Happy Bot to see the suggestion or dismiss it.
- **Routines & Reminders** lets you save a request by name, try it, or choose when it runs. You can also ask for a one-off reminder in chat.
- **History & Folders** sets how long to keep chats and where notes and to-dos go. By default, unpinned conversations expire after 30 days without use. Pin a chat in the sidebar to keep it or choose **Don't keep** to turn off saving. The same page lets you clear searches, conversations, action history or undo records separately.

## From a terminal

| Command | When to use it |
| --- | --- |
| `happy-bot ask --dry-run "Organize my Downloads folder"` | See what the assistant would do before letting it make changes. |
| `happy-bot history` | List saved conversations. Continue one with `happy-bot ask --conversation ID "…"`. |
| `happy-bot export FILE` and `happy-bot import FILE` | Transfer settings and saved conversations. The export leaves out configured secrets. |
| `happy-bot mcp-serve` | Give another AI program access to Happy Bot’s built-in tools over MCP. Enable tool sharing under **Behaviour** first. |

[Installation and command-line setup](INSTALL.md) · [Project overview](../README.md)
