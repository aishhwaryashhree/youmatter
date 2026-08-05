from safety import combine_keyword_and_ai_score
import re
import json
import os
import asyncio
import logging
import time
from email_service import send_guardian_alert, send_helpline_alert
from dotenv import load_dotenv
from safety import (
    ai_danger_score,
    check_safety,
    get_safety_system_prompt,
    should_send_alert,
    get_guardian_message,
    is_blocked_request,
    get_blocked_response,
    HELPLINES
)
from memory import load_memory, save_message, load_user_profile, summarize_history
from prompts import CORE_PROMPT, TOPIC_PLAYBOOKS, KNOWN_TOPICS

load_dotenv()

# FIX BUG 1: Configure root logger so every logger.info/error call
# actually prints to console. Must be called before any logger is used.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("youmatter.ai_core")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_URL = "https://api.sarvam.ai/v1/chat/completions"


THINK_BLOCK_RE = re.compile(r'<think>.*?</think>', flags=re.DOTALL)


def _clean_reply(raw_reply: str) -> str:
    """Strips <think>...</think> reasoning traces some models emit."""
    reply = THINK_BLOCK_RE.sub('', raw_reply).strip()
    if reply.startswith('<think>'):
        reply = raw_reply.split('</think>')[-1].strip() if '</think>' in raw_reply else raw_reply
    return reply


async def _get_ai_reply(http_client, messages: list) -> str:
    """Calls Sarvam for the actual companion reply. Async + timeout so a slow
    upstream call can't block the whole event loop.
    The entire body is wrapped in try/except so any network failure or API
    error returns a safe fallback — this function must never crash, especially
    during crisis-level conversations."""
    try:
        payload = {
            "model": "sarvam-105b",
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.7,
            "reasoning_effort": None
        }
        headers = {
            "Authorization": f"Bearer {SARVAM_API_KEY}",
            "Content-Type": "application/json"
        }
        response = await http_client.post(SARVAM_URL, json=payload, headers=headers, timeout=25.0)
        response_data = response.json()
        logger.info(f"[DEBUG] Sarvam _get_ai_reply raw response: {response_data}")
        raw_reply = response_data["choices"][0]["message"]["content"]
        if not raw_reply:
            finish_reason = response_data["choices"][0].get("finish_reason")
            logger.error(f"Sarvam returned empty content, finish_reason={finish_reason}")
            return "Hey, I'm having a little trouble finding the right words right now — can you tell me a bit more about what's going on?"
        return _clean_reply(raw_reply)
    except Exception as e:
        logger.error(f"_get_ai_reply failed ({type(e).__name__}): {e}", exc_info=True)
        return (
            "I'm having trouble responding right now, but I don't want to leave you "
            "without a reply. If you're in crisis, please reach out: "
            "iCall 9152987821 or Vandrevala Foundation 1860-2662-345 (24/7)."
        )


# ---------------------------------------------------------------------------
# Topic classifier — decides which TOPIC_PLAYBOOKS entries (if any) actually
# apply to this message, so the reply-generation prompt only carries the
# relevant playbook(s) instead of every one of them every time.
#
# This is separate from safety.py's check_safety()/ai_danger_score(): those
# stay exactly as they are and keep deciding crisis/severe handling and
# alerts. This classifier only affects tone/content relevance for non-crisis
# topics. If it fails or returns nothing recognized, it fails safe to an
# empty list — the reply still has the full CORE_PROMPT (including the
# crisis pivot rule and safety rules), just no extra topic-specific script.
# ---------------------------------------------------------------------------

TOPIC_CLASSIFIER_SYSTEM_PROMPT = """You are a topic classifier for a mental health companion app.
Given a user's message, decide which topic(s) from the list below best describe what they are talking about.

casual_stress - everyday stress like exams, deadlines, minor daily problems
anxiety_trauma - anxiety, panic, trauma responses
emotional_breakup - heartbreak, breakup, grief over a relationship ending
relationship_issues - cheating, trust issues, one-sided relationships
bullying_disrespect - being bullied, used, disrespected, taken advantage of
financial_crisis - money problems, unable to pay for necessities
family_failure_pressure - feeling like a failure to family/society, family expectations
feeling_unworthy - feeling worthless, not good enough
loneliness - feeling left out, isolated, lonely
fomo - fear of missing out, comparing life to others
eating_disorders - disordered eating, relationship with food
body_image - body dysmorphia, body image issues
guilt_burden - guilt, feeling like a burden
chronic_illness - long term illness, chronic health conditions
sexuality_discovery - discovering/questioning sexual orientation or gender identity, fear around it
sexual_assault - sexual assault, molestation, rape disclosure
domestic_violence - domestic violence, abuse from partner or family
sacrifice_selferasure - self sacrifice for others at the cost of self
disability - disability and feeling enough
grief_loss - grief over losing a person (death)
adaptation_new_environment - struggling to adapt to a new city/country/environment
infertility - infertility, trying to conceive
severe_crisis - immediate danger, has a plan or means to harm themselves
crisis - self harm, suicide, hopelessness (not immediate/no plan)
confession - confessing something they did wrong, guilt over an action

Rules:
- Return at most 2 keys, comma-separated, most relevant first.
- If nothing applies, or it's casual/general conversation, return exactly: NONE
- Output ONLY the key(s) or NONE. No explanation, no extra text.

Examples:
"ugh exams are killing me this week" -> casual_stress
"he cheated and i still miss him" -> relationship_issues,emotional_breakup
"my dad hits me when he's drunk" -> domestic_violence
"hey how's it going" -> NONE
"""


async def classify_topic(message: str, http_client) -> list:
    """
    Async topic classifier. Returns a list of 0-2 topic keys (matching
    TOPIC_PLAYBOOKS) relevant to the message. Fails safe to [] on any
    error or unrecognized output — CORE_PROMPT alone is a safe fallback.
    """
    try:
        response = await http_client.post(
            SARVAM_URL,
            headers={
                "Authorization": f"Bearer {SARVAM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sarvam-105b",
                "messages": [
                    {"role": "system", "content": TOPIC_CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Classify this message: {message}"}
                ],
                # FIX BUG 2 (classify_topic): sarvam-30b has thinking mode ON by
                # default. With max_tokens=30 the model spent its entire budget on
                # reasoning tokens, leaving content empty and causing a KeyError on
                # 'choices' (the API returns an error JSON instead of a normal
                # response when no content is generated). Fix: disable thinking with
                # reasoning_effort=None and raise max_tokens to 50 for safety.
                "max_tokens": 50,
                "temperature": 0.1,
                "reasoning_effort": None
            },
            timeout=8.0
        )
        data = response.json()
        logger.info(f"[DEBUG] Sarvam classify_topic raw response: {data}")
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or "").strip()
        raw = content if content else reasoning

        if not raw or raw.upper().startswith("NONE"):
            return []

        keys = [k.strip() for k in raw.split(",")]
        valid_keys = [k for k in keys if k in KNOWN_TOPICS]
        return valid_keys[:2]

    except Exception as e:
        logger.error(f"Topic classifier failed, falling back to core prompt only: {e}", exc_info=True)
        return []


def _build_dynamic_prompt(topics: list, user_profile: str, keyword_result: dict) -> str:
    """Assembles the system prompt: core (always) + matched topic playbook(s)
    (only if relevant) + user profile + the existing safety-level addendum."""
    dynamic_prompt = CORE_PROMPT
    for topic in topics:
        dynamic_prompt += "\n\n" + TOPIC_PLAYBOOKS.get(topic, "")
    if user_profile:
        dynamic_prompt += f"\n\nUser Context:\n{user_profile}"
    dynamic_prompt += get_safety_system_prompt(keyword_result)
    return dynamic_prompt


async def chat(user_id: str, user_message: str, http_client, user_consent: dict = None):
    """
    Full pipeline:
    1. Block harmful requests immediately
    2. Load user profile + memory + classify topic (concurrently)
    3. Run reply generation and AI safety scoring CONCURRENTLY
       (base system prompt already carries the crisis-pivot instructions,
       so generation doesn't need to wait on the AI score first — the score
       is used afterward to decide alerts/helplines/escalation)
    4. Handle alerts based on consent
    5. Save to memory (concurrently)

    http_client: a shared httpx.AsyncClient, created once per app lifetime
    and passed in (not created per-request) so connections get reused.
    """

    if user_consent is None:
        user_consent = {
            "guardian_alert": False,
            "helpline_alert": False,
            "alerts_paused": False,
            "guardian_email": None,
            "guardian_name": None
        }

    # Step 1 — Block harmful requests BEFORE anything else (instant, keyword-based)
    if is_blocked_request(user_message):
        blocked_reply = get_blocked_response()

        # Still save to memory so we know this happened — concurrently, not sequentially
        await asyncio.gather(
            save_message(user_id, "user", user_message, http_client),
            save_message(user_id, "assistant", blocked_reply, http_client),
        )

        return {
            "reply": blocked_reply,
            "safety_level": "severe",
            "blocked": True,
            "alert_sent": False,
            "show_consent_prompt": not user_consent.get("guardian_alert", False)
        }

    # Step 2 — Fast keyword safety layer runs first (instant, no network call)
    keyword_result = check_safety(user_message)

    # Step 3 — Load profile + history + classify topic, all concurrently.
    # Topic classification has to finish before we build the prompt (it
    # decides what goes in the prompt), so it can't overlap with reply
    # generation the way ai_danger_score does — instead it overlaps with
    # the profile/memory fetch, which is already the slowest step.
    _t0 = time.perf_counter()
    user_profile, raw_history, topics = await asyncio.gather(
        load_user_profile(user_id, http_client),
        load_memory(user_id, http_client),
        classify_topic(user_message, http_client),
    )
    logger.info(f"[TIMING] profile+memory+topic load: {time.perf_counter() - _t0:.2f}s")
    history = summarize_history(raw_history)

    # Step 4 — Build system prompt: core + matched playbook(s) + profile +
    # the existing keyword-safety addendum. Crisis-pivot behavior lives in
    # CORE_PROMPT regardless of what the classifier returned.
    dynamic_prompt = _build_dynamic_prompt(topics, user_profile, keyword_result)

    messages = [{"role": "system", "content": dynamic_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_message})

    # Step 5 — Run reply generation and AI danger scoring CONCURRENTLY.
    # If the keyword layer already flagged "severe", skip the AI scoring call
    # entirely — it can't downgrade a severe result anyway.
    _t1 = time.perf_counter()
    if keyword_result["level"] == "severe":
        reply = await _get_ai_reply(http_client, messages)
        safety_result = keyword_result
    else:
        reply, ai_score = await asyncio.gather(
            _get_ai_reply(http_client, messages),
            ai_danger_score(user_message, http_client),
        )
        safety_result = combine_keyword_and_ai_score(keyword_result, ai_score)
    logger.info(f"[TIMING] reply+score: {time.perf_counter() - _t1:.2f}s")

    # Step 6 — Append helplines if crisis or severe
    if safety_result["level"] == "severe":
        reply += f"\n\n{HELPLINES}"

    # Step 7 — Decide whether to send alerts. Guardian email is a blocking
    # SMTP call, so it's offloaded to a thread instead of blocking the loop.
    alert_decision = should_send_alert(safety_result, user_consent)
    alert_sent = False
    alert_tasks = []
    if alert_decision.get("send_guardian") and user_consent.get("guardian_email"):
        urgent = safety_result["level"] == "severe"
        user_name = user_consent.get("user_name") or user_consent.get("guardian_name", "Unknown User")
        alert_tasks.append(asyncio.to_thread(
            send_guardian_alert,
            user_consent.get("guardian_email"),
            user_name,
            urgent
        ))
    if alert_decision.get("send_helpline") and safety_result["level"] == "severe":
        alert_tasks.append(asyncio.to_thread(
            send_helpline_alert,
            user_consent.get("guardian_name", "Unknown User")
        ))

    if alert_tasks:
        results = await asyncio.gather(*alert_tasks, return_exceptions=True)
        # First task is always the guardian alert when present
        if alert_decision.get("send_guardian") and user_consent.get("guardian_email"):
            first = results[0]
            alert_sent = first is True

    # Step 8 — Show consent prompt if no consent given but crisis detected
    show_consent_prompt = (
        safety_result["level"] in ["crisis", "severe"]
        and not user_consent.get("guardian_alert", False)
    )

    # Step 9 — Save both messages to memory concurrently
    await asyncio.gather(
        save_message(user_id, "user", user_message, http_client),
        save_message(user_id, "assistant", reply, http_client),
    )

    return {
        "reply": reply,
        "safety_level": safety_result["level"],
        "blocked": False,
        "alert_sent": alert_sent,
        "show_consent_prompt": show_consent_prompt,
        "ai_score": safety_result.get("ai_score", None)
    }


async def chat_stream(user_id: str, user_message: str, http_client, user_consent: dict = None):
    """
    Streaming variant of chat(). Same full pipeline (blocked-request check,
    keyword safety, profile/memory/topic load, prompt build, alerts, memory
    save) but yields events instead of returning a single dict:

      {"type": "token",  "content": "<piece of reply text>"}
      ...one per SSE chunk from Sarvam...
      {"type": "safety_result", "safety_level": ..., "blocked": ...,
       "alert_sent": ..., "show_consent_prompt": ..., "helplines": ...}

    The existing chat() function is NOT modified — this is an additive,
    independent function that reuses the same helpers.
    """

    if user_consent is None:
        user_consent = {
            "guardian_alert": False,
            "helpline_alert": False,
            "alerts_paused": False,
            "guardian_email": None,
            "guardian_name": None
        }

    # Step 1 — Block harmful requests BEFORE anything else (instant, keyword-based)
    if is_blocked_request(user_message):
        blocked_reply = get_blocked_response()

        await asyncio.gather(
            save_message(user_id, "user", user_message, http_client),
            save_message(user_id, "assistant", blocked_reply, http_client),
        )

        yield {"type": "token", "content": blocked_reply}
        yield {
            "type": "safety_result",
            "safety_level": "severe",
            "blocked": True,
            "alert_sent": False,
            "show_consent_prompt": not user_consent.get("guardian_alert", False),
            "helplines": HELPLINES,
        }
        return

    # Step 2 — Fast keyword safety layer (instant, no network call)
    keyword_result = check_safety(user_message)

    # Step 3 — Load profile + history + classify topic, all concurrently.
    _t0 = time.perf_counter()
    user_profile, raw_history, topics = await asyncio.gather(
        load_user_profile(user_id, http_client),
        load_memory(user_id, http_client),
        classify_topic(user_message, http_client),
    )
    logger.info(f"[TIMING] chat_stream profile+memory+topic load: {time.perf_counter() - _t0:.2f}s")
    history = summarize_history(raw_history)

    # Step 4 — Build system prompt: core + matched playbook(s) + profile +
    # keyword-safety addendum.
    dynamic_prompt = _build_dynamic_prompt(topics, user_profile, keyword_result)

    messages = [{"role": "system", "content": dynamic_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_message})

    # Step 5 — Stream the reply from Sarvam via SSE.
    # full_reply is initialised HERE (before try/except) so the except branch
    # can safely assign the fallback without any risk of NameError.
    full_reply = ""

    payload = {
        "model": "sarvam-105b",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.7,
        "reasoning_effort": None,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json",
    }

    _t1 = time.perf_counter()
    try:
        async with http_client.stream("POST", SARVAM_URL, json=payload, headers=headers, timeout=25.0) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    piece = (chunk["choices"][0]["delta"].get("content") or "")
                    if piece:
                        full_reply += piece
                        yield {"type": "token", "content": piece}
                except (json.JSONDecodeError, KeyError, IndexError):
                    # Malformed or unexpected chunk — skip silently and continue
                    logger.warning(f"chat_stream: skipping unparseable SSE chunk: {data_str!r}")
                    continue
    except Exception as e:
        logger.error(f"chat_stream SSE failed ({type(e).__name__}): {e}", exc_info=True)
        fallback = (
            "I'm having trouble responding right now, but I don't want to leave you "
            "without a reply. If you're in crisis, please reach out: "
            "iCall 9152987821 or Vandrevala Foundation 1860-2662-345 (24/7)."
        )
        full_reply = fallback
        yield {"type": "token", "content": fallback}

    logger.info(f"[TIMING] chat_stream SSE reply: {time.perf_counter() - _t1:.2f}s")

    # Step 6 — Resolve safety score exactly as chat() does.
    # If keyword layer already flagged "severe", skip AI scoring — it can't
    # downgrade a severe result anyway.
    if keyword_result["level"] == "severe":
        safety_result = keyword_result
    else:
        ai_score = await ai_danger_score(user_message, http_client)
        safety_result = combine_keyword_and_ai_score(keyword_result, ai_score)

    # Step 7 — Decide whether to send alerts. Guardian email is a blocking
    # SMTP call, so it's offloaded to a thread instead of blocking the loop.
    alert_decision = should_send_alert(safety_result, user_consent)
    alert_sent = False
    alert_tasks = []
    if alert_decision.get("send_guardian") and user_consent.get("guardian_email"):
        urgent = safety_result["level"] == "severe"
        user_name = user_consent.get("user_name") or user_consent.get("guardian_name", "Unknown User")
        alert_tasks.append(asyncio.to_thread(
            send_guardian_alert,
            user_consent.get("guardian_email"),
            user_name,
            urgent
        ))
    if alert_decision.get("send_helpline") and safety_result["level"] == "severe":
        alert_tasks.append(asyncio.to_thread(
            send_helpline_alert,
            user_consent.get("guardian_name", "Unknown User")
        ))

    if alert_tasks:
        results = await asyncio.gather(*alert_tasks, return_exceptions=True)
        if alert_decision.get("send_guardian") and user_consent.get("guardian_email"):
            first = results[0]
            alert_sent = first is True

    # Step 8 — Show consent prompt if no consent given but crisis detected
    show_consent_prompt = (
        safety_result["level"] in ["crisis", "severe"]
        and not user_consent.get("guardian_alert", False)
    )

    # Step 9 — Save both messages to memory concurrently using the
    # accumulated full_reply (same as chat() does with its reply variable).
    await asyncio.gather(
        save_message(user_id, "user", user_message, http_client),
        save_message(user_id, "assistant", full_reply, http_client),
    )

    # Final event — safety metadata that can't be merged into the token stream
    # because the tokens have already been sent to the client.
    yield {
        "type": "safety_result",
        "safety_level": safety_result["level"],
        "blocked": False,
        "alert_sent": alert_sent,
        "show_consent_prompt": show_consent_prompt,
        "helplines": HELPLINES if safety_result["level"] == "severe" else None,
    }


async def _interactive_main():
    import httpx

    print("YouMatter AI is ready. Type 'quit' to exit.")

    user_id = input("Enter your user ID (or press Enter for 'test-user'): ").strip()
    if not user_id:
        user_id = "test-user"

    print(f"\nLogged in as: {user_id}\n")

    # Test consent — set TEST_GUARDIAN_EMAIL in your .env to test guardian alerts locally.
    # Never hardcode a real email/name here — this file gets committed.
    test_consent = {
        "guardian_alert": True,
        "helpline_alert": True,
        "alerts_paused": False,
        "guardian_email": os.getenv("TEST_GUARDIAN_EMAIL"),
        "guardian_name": "Guardian"
    }

    async with httpx.AsyncClient() as http_client:
        while True:
            user_input = input("You: ")
            if user_input.lower() == "quit":
                break

            result = await chat(user_id, user_input, http_client, test_consent)

            level = result["safety_level"]
            if level == "severe":
                if result["alert_sent"]:
                    print("\n🚨 SEVERE CRISIS — Guardian alert sent\n")
                else:
                    print("\n🚨 SEVERE CRISIS — Alert NOT sent (check consent/config)\n")
            elif level == "crisis":
                print("\n⚠️  CRISIS DETECTED — Helplines shown, no guardian alert at this level\n")
            elif level == "distress":
                print("\n💛 Distress detected — AI in gentle mode\n")

            if result["show_consent_prompt"]:
                print("\n💬 [App would show: 'Can we contact someone you trust?']\n")

            if result["blocked"]:
                print("\n🚫 Harmful request blocked\n")

            print(f"\nYouMatter: {result['reply']}\n")


if __name__ == "__main__":
    asyncio.run(_interactive_main())