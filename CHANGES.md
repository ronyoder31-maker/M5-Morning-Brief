Oct 30, 2026 manual changes. Don't revert them without asking Ronny.
• One scheduler only: Hermes cron 8565f2adb48b at 1 AM. The LaunchAgent com.ronyoder.m5-morning-brief-daily was deleted on purpose. Never recreate it.
• Script writing: qwen3.8:27b-mlx, think true, num_predict 20000, num_ctx 32768, 2400 s timeout. Ollama uses num_predict, not max_tokens.
• Validation checks MAYA: and ADAM: lines.
• Edge TTS rate: int(round(calc_rate)) with :+d, clamped to -10%..+10%.
• GitHub auth goes through gh in the Keychain. Never put tokens in plists, scripts or logs.

Nov 2, 2026 (Hark, approved by Ronny): script writing rewritten
• Why: on Nov 2 the 1 AM run was cancelled because the script was too short. The single 3,000-4,000-word call with think true used up its token budget on thinking.
• The script is now written one story at a time: the model picks the stories, then writes each one at ~360-440 words over 7-8 lines. Thinking is off (think false), with num_predict 2500, num_ctx 16384 and a 900 s timeout per call, keep_alive 15m.
• It keeps adding stories (8, plus one extra if still short) until ~3,200 words (about 19-21 min), and retries a story under 260 words up to 3 times.
• The greeting and sign-off are fixed text (Maya / Adam). The full script is saved to script.txt in the episode folder.
• RSS items now carry a short plain-text summary, so the hosts have facts beyond the headline (HN link-only descriptions are skipped).
• Model is still qwen3.8:27b-mlx. Validation is still MAYA:/ADAM: lines.

Nov 6, 2026 (Hark, approved by Ronny): feed keeps the last 7 episodes. get_last_7_episodes now calls gh with -R ronyoder31-maker/M5-Morning-Brief and --json. Before, the cron run did not start inside the repo, so gh returned nothing and feed.xml held only the newest episode. itunes:duration is left out when it is unknown. feed.xml was rebuilt by hand with 7 episodes.

Nov 10, 2026 (Hark, approved by Ronny): script writing uses MTPLX first
• Why: so only one 27B model is in RAM at 1 AM. Hermes and the script both use MTPLX (Qwen3.8-27B-MTPLX-Optimized-Speed, local port 8000), instead of MTPLX plus Ollama's qwen3.8:27b-mlx.
• _ollama() now calls MTPLX's OpenAI-style /v1/chat/completions (max_tokens, thinking off via chat_template_kwargs, <think> stripped). The model id is read from /v1/models unless M5_MTPLX_MODEL is set.
• If MTPLX is down or returns an error or empty text, the run logs a WARNING and uses Ollama qwen3.8:27b-mlx for the rest of that run (no switching back and forth).
• Turn MTPLX off for the script: M5_USE_MTPLX=0. Override URL: M5_MTPLX_URL.
• MTPLX must be running with its model started before 1 AM, or the run falls back to Ollama.
