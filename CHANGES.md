Oct 30, 2026 manual changes. Don't revert them without asking Ronny.
• One scheduler only: Hermes cron 8565f2adb48b at 1 AM. The LaunchAgent com.ronyoder.m5-morning-brief-daily was deleted on purpose. Never recreate it.
• Script writing: qwen3.8:27b-mlx, think true, num_predict 20000, num_ctx 32768, 2400 s timeout. Ollama uses num_predict, not max_tokens.
• Validation checks MAYA: and ADAM: lines.
• Edge TTS rate: int(round(calc_rate)) with :+d, clamped to -10%..+10%.
• GitHub auth goes through gh in the Keychain. Never put tokens in plists, scripts or logs.
