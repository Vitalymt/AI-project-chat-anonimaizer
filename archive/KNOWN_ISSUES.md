# Known Issues

## Current non-blocking limitations

1. API key validation is strict and expects provider-compatible formats; unusual key formats may be rejected.
2. Context size limiting uses message-count and character-budget heuristics, not tokenizer-accurate token counting.
3. Client-side markdown sanitization is minimal and should be strengthened if untrusted HTML is expected.
4. `crypto.py` obfuscates secrets for storage compatibility but is not strong cryptographic protection for high-security environments.
