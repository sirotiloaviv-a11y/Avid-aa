# Shadow AI Shield

Manifest V3 Chrome extension that masks personal and sensitive data in prompts
before they reach ChatGPT, Claude or Gemini. Detected values are replaced in
place with placeholders such as `[EMAIL]` or `[CREDIT_CARD]`.

## Install (unpacked)

1. Open `chrome://extensions` and enable **Developer mode**.
2. Click **Load unpacked** and select this `shadow-ai-shield/` folder.

No build step and no dependencies.

## Layout

| File | Role |
| --- | --- |
| `manifest.json` | MV3 manifest: `activeTab`, `storage`, host access to chatgpt.com, chat.openai.com, claude.ai, gemini.google.com |
| `pii.js` | Detection rules (`ShadowPII` global), shared by the content script and tests |
| `content.js` | Watches `<textarea>` and contenteditable prompt boxes; masks on typing pause, on paste, and on Enter |
| `background.js` | Service worker: owns state, daily counter rollover, activity log, toolbar badge |
| `popup/` | ON/OFF toggle, "PII Masked Today" counter, per-type breakdown, recent activity log |

## Detected data types

Email, credit card (Luhn-checked), phone number, US SSN, Israeli ID
(checksum-validated), IBAN, IPv4 address, and API keys/secrets (OpenAI,
Anthropic, AWS, GitHub, Google, Slack).

## Behaviour

- Masking runs 400 ms after typing stops, immediately after a paste, and
  synchronously when Enter is pressed. If Enter triggers masking, the send is
  held so the user can review the masked prompt and press Enter again.
- Contenteditable editors are edited through `execCommand("insertText")` so the
  page's editor state (ProseMirror, Quill) stays in sync.
- Only the data **type**, site and time are logged — never the masked value.
- The counter resets at local midnight.

## Tests

```bash
node --test shadow-ai-shield/tests/pii.test.js
```
