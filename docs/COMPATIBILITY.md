# Phase 14 desktop compatibility

Checked on November 27, 2026 in isolated KDE Plasma 6 Wayland sessions. The tests used synthetic documents, images and speech. The configured providers received test questions. The desktop playback device stayed muted.

## Models

| Configuration | What was checked | Outcome |
| --- | --- | --- |
| Local llama.cpp, vision enabled | Local discovery, chat model selection, PDF question dictated through the local transcription service, project search, Settings compatibility test | Answered from the PDF and found the matching source line. The parallel-tool probe returned no calls. |
| Local FastFlowLM model | Settings compatibility test | Answered and handled tools. Its service advertised image support while its configuration had vision turned off. |
| Hosted OpenAI Responses | Settings compatibility test, model switching, PDF grounding, combined text and image question, sourced web answer, retry after a failed service | Passed. The assistant identified the synthetic image color and text-file contents. |
| Hosted Gemini and Claude, through the configured endpoints | Settings compatibility test for streaming, tools, results, handover and vision | Both passed all probe cases. The full attachment workflow was exercised with OpenAI and the local vision model. |
| OpenRouter, LM Studio, Ollama and other custom endpoints | Available through compatible service addresses | No configured instance of these services was exercised in this pass. Use **AI Model → Test** to check a particular endpoint. |

## Speech and files

| Workflow | Outcome |
| --- | --- |
| Local Whisper-compatible transcription endpoint | The microphone workflow accepted a prerecorded synthetic question through a substitute recorder. The real configured service transcribed it. Both the local and hosted model answered the question from the PDF, and the reply’s Read aloud and Stop controls were exercised in each chat. |
| Hosted Whisper-compatible transcription and LM Studio speech input | The multipart request and optional bearer key were exercised with a test service. A live hosted speech account and an LM Studio speech endpoint still need setup for independent verification. |
| Local whisper.cpp CLI | The adapter, model arguments and temporary WAV handling were exercised with a test double. Live transcription requires an installed whisper-cli and a matching model. |
| Live Whisper over D-Bus | A private session-bus service delivered a synthetic final phrase through the real subscription. End-to-end recognition requires a running speech service that emits the supported signal. |
| Speech Dispatcher | A private Speech Dispatcher instance completed synthesis to a WAV and accepted request-scoped cancellation. The desktop's current system voice uses the dummy module and needs a synthesizer configured. |
| Piper | Downloaded and checked a voice against the upstream catalog. The chat’s Read aloud action and Settings voice preview both generated WAV output. The visible Stop control interrupted the file-only test player. Audible quality was not assessed. |
| Attachments | A real Qt window drop staged a PDF, text file and image together. The file picker staged files, removal worked, and a PDF without extractable text produced a warning. Image compatibility is checked before submission. |
| Service recovery | An unreachable daemon and an unreachable model were exercised separately. The composer retained the draft and attachment selection. Switching to an available model and retrying sent the attachment successfully. |

## Search

| Workflow | Outcome |
| --- | --- |
| Project search | Both local and hosted models searched a chosen project through ripgrep. Clicking a match opened Kate. A test edit in a temporary fixture confirmed the cursor was on the matching line. |
| SearXNG through the configured MCP tool | Both local and hosted models used the search tool and linked to the official Kate site. The clickable search result delivered the source URL, which returned HTTP 200. |
| DuckDuckGo, Google and Tavily integrations | These require a configured compatible web-search tool. They were not individually exercised in this pass. |

The tests used a synthetic microphone input and file-only speech output so they could run silently. Personal microphone hardware, speaker loudness and voice quality remain listening checks.
