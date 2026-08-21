from safety import combine_keyword_and_ai_score
import re
import json
import os
import random
import asyncio
import logging
import time
from email_service import send_guardian_alert, send_helpline_alert
from dotenv import load_dotenv
from safety import (
    check_safety,
    get_safety_system_prompt,
    should_send_alert,
    get_guardian_message,
    is_blocked_request,
    get_blocked_response,
    HELPLINES,
    CRISIS_SCORE_THRESHOLD,   # shared escalation floor — see safety.py
)
from memory import load_memory, save_message, load_user_profile, summarize_history
from prompts import CORE_PROMPT, TOPIC_PLAYBOOKS, KNOWN_TOPICS
from rate_limiter import per_user_rate_limiter, PerUserRateLimitExceeded, sarvam_rate_limiter

load_dotenv()

# Domain-relevance filter toggle.
# Set ENABLE_DOMAIN_FILTER=false in .env to disable without touching code.
# Defaults to True so the filter is on unless explicitly turned off.
ENABLE_DOMAIN_FILTER = os.getenv("ENABLE_DOMAIN_FILTER", "true").strip().lower() != "false"

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


async def _get_ai_reply(http_client, messages: list, bypass_rate_limit: bool = False) -> str:
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
        await sarvam_rate_limiter.acquire(bypass=bypass_rate_limit)
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
# Topic classifier + danger scorer — MERGED into one call.
#
# Previously these were two separate Sarvam round-trips: classify_topic()
# (decides which TOPIC_PLAYBOOKS entries apply, so the reply prompt only
# carries relevant playbook(s)) and safety.ai_danger_score() (the AI-side
# half of the two-layer safety check, alongside the instant keyword layer
# in safety.check_safety()). Both are small, structured, single-purpose
# calls that only need the raw user message — neither needs conversation
# history or the system prompt — so there's no reason they need to be two
# network round-trips. classify_topic_and_score() asks for both in one
# call and parses a strict two-line format out of the response.
#
# This does NOT change what safety.py decides — check_safety() (keyword
# layer) and combine_keyword_and_ai_score() (score -> level upgrade logic)
# are untouched. This only changes how the AI-side score gets produced.
# If it fails or returns something unparseable, it fails safe exactly like
# the two functions it replaces: topics -> [] (CORE_PROMPT alone is a safe
# fallback), score -> 1 (keyword layer still runs, so a scorer outage
# doesn't block chat).
# ---------------------------------------------------------------------------

TOPIC_AND_SCORE_SYSTEM_PROMPT = """You are a message analyzer for an Indian mental health companion app.
Given a user's message, do THREE things:

1. TOPIC — decide which topic(s) from the list below best describe what they are talking about.

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

Return at most 2 keys, comma-separated, most relevant first. If nothing applies, or it's casual/general conversation, use NONE.

2. SCORE — rate ONLY the self-harm or suicide risk from 1-10. Assume the worst plausible interpretation for ambiguous messages. Exception: if the ENTIRE message is anger, annoyance, frustration, or refusal to engage, with no separate self-harm or suicide content present, that tone alone is NOT a self-harm signal — score these 1-3. If risk content is present alongside the anger, score based on the risk content as normal.

1-3 = Safe (general stress, sadness)
4-6 = Distress (emotional pain, hopelessness)
7-8 = Crisis (self harm or suicide mentioned)
9-10 = Severe (immediate danger, has plan or means)

"i bought a blade today" = 9 (means acquired)
"kash main hoti hi nahi" = 8 (wishing non-existence)
"i want to drink this bottle of poison" = 10
"i feel sad" = 2

3. IN_DOMAIN — decide if this message is relevant for a mental health companion.

CLASSIFY BY THE USER'S UNDERLYING EMOTIONAL INTENT, NOT BY SURFACE KEYWORDS LIKE NUMBERS,
CODE, OR TASK-SOUNDING PHRASING. If real distress, stress, or a personal/emotional need is
present alongside a task request, IN_DOMAIN is yes.

Answer YES if the message is about: emotions, feelings, mental health, relationships, personal
struggles, daily life check-ins, stress, grief, loneliness, identity, self-worth, crisis, trauma,
casual small-talk with the companion, or any emotionally/personally relevant topic — even if a
task is also mentioned as a coping or avoidance behaviour.

Answer NO only if the message is PURELY a task request with NO emotional context — math problems,
coding/programming tasks, general trivia, factual questions, homework help, writing code or essays
for the user, mild politeness wrapping a task (e.g. "hey can you quickly...", "no big deal but...").

When in doubt, answer yes.

--- Clearly IN-DOMAIN (yes) ---
"I feel really lonely today" → yes (direct emotional disclosure)
"I can't sleep because I'm stressed about a coding deadline at work" → yes
  (task-shaped surface, but actual topic is stress/sleep — emotional need is real)
"I'm so anxious about my exam tomorrow, I don't know what to do" → yes
"my parents keep fighting and I don't know how to deal with it" → yes
"hi how are you" → yes
"main theek nahi hoon" → yes
"I'm scared of coming out" → yes

--- Clearly OUT-OF-DOMAIN (no) ---
"what is 2+2" → no (pure math, no emotional context)
"write python code to add two numbers" → no (pure technical task)
"who is the president of France" → no (pure trivia, no emotional context)

--- Borderline — must resolve to IN-DOMAIN because emotional distress is present,
    even though a task is also mentioned ---
"I'm so stressed about this exam, can you just give me the answer to question 5" → yes
  (stress is real; the task-request is a coping/avoidance behaviour — respond to the stress)
"I'm panicking, can you just write this code for me so I stop failing" → yes
  (panic and fear of failing are real emotional content; the code request is a symptom)

--- Borderline — must resolve to OUT-OF-DOMAIN because no emotional content is present,
    just a task wrapped in mild politeness ---
"hey can you quickly help me solve this math problem, thanks" → no
  (polite framing but purely task-shaped, no emotional signal)
"no big deal but can you write a function for me" → no
  ("no big deal" is a filler, not a distress signal — still a pure task request)

Output EXACTLY three lines, nothing else, no explanation:
TOPICS: <key(s) or NONE>
SCORE: <number 1-10>
IN_DOMAIN: <yes|no>

Examples:
"ugh exams are killing me this week" ->
TOPICS: casual_stress
SCORE: 2
IN_DOMAIN: yes

"he cheated and i still miss him" ->
TOPICS: relationship_issues,emotional_breakup
SCORE: 3
IN_DOMAIN: yes

"my dad hits me when he's drunk" ->
TOPICS: domestic_violence
SCORE: 5
IN_DOMAIN: yes

"what is the capital of France?" ->
TOPICS: NONE
SCORE: 1
IN_DOMAIN: no

"write me a Python script to scrape websites" ->
TOPICS: NONE
SCORE: 1
IN_DOMAIN: no

"mujhe nahi batana kuch i am hating this interrogation" ->
TOPICS: NONE
SCORE: 2
IN_DOMAIN: yes

"leave me alone" ->
TOPICS: NONE
SCORE: 1
IN_DOMAIN: yes
"""

TOPICS_LINE_RE = re.compile(r'TOPICS:\s*(.*)', re.IGNORECASE)
# Deliberately \d+ (not [1-9]|10) so an out-of-spec model output like
# "SCORE: 15" still gets captured and clamped down to 10 below, instead of
# failing to match and silently defaulting to score=1 ("safe"). Defaulting
# to "safe" on a malformed *high* number would be the wrong fail-soft
# direction for a crisis-scoring path.
SCORE_LINE_RE = re.compile(r'SCORE:\s*(\d+)', re.IGNORECASE)
# Fail-safe: if this line is missing or unparseable, in_domain defaults to
# True so a classifier outage never accidentally blocks a real user.
IN_DOMAIN_LINE_RE = re.compile(r'IN_DOMAIN:\s*(yes|no)', re.IGNORECASE)


async def classify_topic_and_score(message: str, http_client, bypass_rate_limit: bool = False) -> dict:
    """
    Merged async call: topic classification AND danger scoring in a single
    Sarvam round-trip (see comment block above for why). Returns:
        {"topics": [...0-2 keys from KNOWN_TOPICS...], "score": int 1-10}

    Parsing is fail-soft PER FIELD, independently — a malformed/missing
    TOPICS line and a malformed/missing SCORE line are handled separately,
    so a bug in one can't silently take the other down with it. On total
    failure (e.g. the network call itself errors), falls back to the same
    safe defaults the two functions this replaces used: topics=[] and
    score=1.

    Note: bypass_rate_limit is accepted for API compatibility but is not
    used — this call ALWAYS bypasses the Sarvam rate limiter (bypass=True)
    because it has no way to know the danger score before it runs, so it
    can never determine upfront whether queuing is warranted. Only the
    heavier _get_ai_reply call (which runs after the score is known)
    enforces the normal rate limit.
    """
    try:
        await sarvam_rate_limiter.acquire(bypass=True)
        response = await http_client.post(
            SARVAM_URL,
            headers={
                "Authorization": f"Bearer {SARVAM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sarvam-105b",
                "messages": [
                    {"role": "system", "content": TOPIC_AND_SCORE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze this message: {message}"}
                ],
                # Same thinking-mode trap as the old classify_topic/ai_danger_score
                # calls (see their history) — reasoning_effort=None disables it
                # entirely. max_tokens raised to 80 (from 60) to comfortably fit
                # all three output lines: TOPICS, SCORE, and IN_DOMAIN.
                "max_tokens": 80,
                "temperature": 0.1,
                "reasoning_effort": None
            },
            timeout=8.0
        )
        data = response.json()
        logger.info(f"[DEBUG] Sarvam classify_topic_and_score raw response: {data}")
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or "").strip()
        raw = content if content else reasoning

        # --- TOPICS (fail-soft) ---
        topics = []
        try:
            topics_match = TOPICS_LINE_RE.search(raw)
            if topics_match:
                topics_str = topics_match.group(1).strip()
                if topics_str and not topics_str.upper().startswith("NONE"):
                    keys = [k.strip() for k in topics_str.split(",")]
                    topics = [k for k in keys if k in KNOWN_TOPICS][:2]
        except Exception as e:
            logger.warning(f"classify_topic_and_score: TOPICS parse failed, defaulting to []: {e}")
            topics = []

        # --- SCORE (fail-soft) ---
        score = 1
        try:
            score_match = SCORE_LINE_RE.search(raw)
            if score_match:
                score = max(1, min(10, int(score_match.group(1))))
            else:
                # Lenient fallback: same "find any number anywhere in the
                # response" approach the old ai_danger_score used, in case the
                # model didn't follow the exact "SCORE: N" format. \d+ (not a
                # 1-10-only pattern) for the same out-of-spec-number reason
                # noted on SCORE_LINE_RE above.
                numbers = re.findall(r'\d+', raw)
                if numbers:
                    score = max(1, min(10, int(numbers[-1])))
        except Exception as e:
            logger.warning(f"classify_topic_and_score: SCORE parse failed, defaulting to 1: {e}")
            score = 1

        # --- IN_DOMAIN (fail-soft) ---
        # Defaults to True so a parse failure or missing line never blocks
        # a real user. Crisis safety is a separate, independent check.
        in_domain = True
        try:
            domain_match = IN_DOMAIN_LINE_RE.search(raw)
            if domain_match:
                in_domain = domain_match.group(1).strip().lower() == "yes"
        except Exception as e:
            logger.warning(f"classify_topic_and_score: IN_DOMAIN parse failed, defaulting to True: {e}")
            in_domain = True

        logger.info(
            f"[DEBUG] classify result: score={score}, in_domain={in_domain}, topics={topics} | "
            f"raw_output={raw!r}"
        )
        return {"topics": topics, "score": score, "in_domain": in_domain}

    except Exception as e:
        logger.error(f"classify_topic_and_score failed entirely, falling back to safe defaults: {e}", exc_info=True)
        return {"topics": [], "score": 1, "in_domain": True}


# ---------------------------------------------------------------------------
# Domain-filter redirect message pools.
#
# YouMatter is a mental health companion, not a general-purpose assistant.
# When a message is clearly off-domain (math, coding, trivia, etc.) AND
# shows no safety/crisis signals, the pipeline returns one of these warm
# redirect messages instead of calling _get_ai_reply().
#
# Two pools: English and Hinglish (used when the message contains common
# Hindi/Hinglish words). random.choice() picks a different one each time
# so it never feels like a canned bot response.
# ---------------------------------------------------------------------------

_DOMAIN_REDIRECT_EN = [
    "Oh love, that's not really something I can help with — but I'd so much rather know how you're doing. How are you feeling today? 💛",
    "Dear, I'm not quite the right one for that — but I genuinely care about you. What's been going on with you lately?",
    "That one's a little beyond what I can do, love — but I'm right here for you. How have you been holding up?",
    "Aww, I wish I could help with that! But honestly, I'd love to just check in — how are you doing, really?",
    "I can't really help with that one, dear — but you have my full attention. How are you feeling right now? 🤍",
]

_DOMAIN_REDIRECT_HI = [
    "Yeh to mai nahi kar payunga, ye meri area se bahar hai — par main tumhare baare mein sunna chahta hoon. Aaj kaisa feel ho raha hai? 💛",
    "Dear, iske liye main sahi nahi hoon, par main tumse baat karna chahta hoon. Kya chal raha hai zindagi mein?",
    "Yeh main nahi kar sakta, par tumhari baat sunne ke liye main yahan hoon hamesha. Sab theek hai na? 🤍",
    "Woh toh main nahi bata sakta — par tumhara haal jaanna chahta hoon. Kuch dil mein hai jo share karna chahte ho?",
    "Iske liye toh koi aur chahiye, dear — par main tumhare liye hoon poori tarah. Aaj kaisa feel ho raha hai tumhe?",
]

# Common Hinglish/Hindi signal words — if any appear in the message we pick
# from the Hindi redirect pool for language consistency.
_HINGLISH_SIGNALS = {
    "hai", "hoon", "nahi", "kya", "mujhe", "meri", "mera", "kuch", "yaar",
    "bhai", "kal", "aaj", "kyun", "theek", "accha", "bas", "hota", "kar",
    "log", "sab", "toh", "phir", "abhi", "bahut", "main", "tumhara",
}


def _pick_domain_redirect(message: str) -> str:
    """Return a random warm domain-redirect message in the user's language.

    Language detection is intentionally lightweight: if any known
    Hindi/Hinglish signal word appears in the message we use the Hinglish
    pool, otherwise English. This matches the same pragmatic approach used
    elsewhere in the codebase (CORE_PROMPT's "match the user" rule).
    """
    words = set(message.lower().split())
    if words & _HINGLISH_SIGNALS:
        return random.choice(_DOMAIN_REDIRECT_HI)
    return random.choice(_DOMAIN_REDIRECT_EN)


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
    2. Load user profile + memory + classify topic & score, all concurrently
       (topic + AI danger score come from one merged Sarvam call — see
       classify_topic_and_score — instead of two separate ones)
    3. Generate the reply (score is already in hand from step 2, so nothing
       needs to run concurrently with generation anymore)
    4. Handle alerts based on consent
    5. Save to memory (concurrently)

    http_client: a shared httpx.AsyncClient, created once per app lifetime
    and passed in (not created per-request) so connections get reused.
    Sarvam call rate is governed by sarvam_rate_limiter from rate_limiter.py.
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

    # Step 2a — Per-user rate limit.
    # SAFETY INVARIANT: this entire block is skipped when keyword_result["level"]
    # is "crisis" or "severe". Crisis and severe traffic always falls through to
    # the full pipeline below, unaffected by the limiter.
    if keyword_result["level"] not in ("crisis", "severe"):
        # Rate limit: bail out before any Sarvam call if this user is flooding.
        try:
            await per_user_rate_limiter.check(user_id)
        except PerUserRateLimitExceeded:
            rate_reply = (
                "Hey, that's a lot of messages really fast — "
                "I'm still here, just give me a moment to catch up."
            )
            await asyncio.gather(
                save_message(user_id, "user", user_message, http_client),
                save_message(user_id, "assistant", rate_reply, http_client),
            )
            return {
                "reply": rate_reply,
                "safety_level": "safe",
                "blocked": False,
                "alert_sent": False,
                "show_consent_prompt": False,
                "ai_score": None,
            }

    # Step 3 — Load profile + history + classify topic & score, all
    # concurrently. Topic classification has to finish before we build the
    # prompt (it decides what goes in the prompt), so it can't overlap with
    # reply generation — instead it overlaps with the profile/memory fetch,
    # which is already the slowest step. The danger score now rides along
    # in this same call (see classify_topic_and_score), so it no longer
    # needs its own separate round-trip later.
    _t0 = time.perf_counter()
    user_profile, raw_history, classification = await asyncio.gather(
        load_user_profile(user_id, http_client),
        load_memory(user_id, http_client),
        classify_topic_and_score(user_message, http_client),
    )
    logger.info(f"[TIMING] profile+memory+topic+score load: {time.perf_counter() - _t0:.2f}s")
    history = summarize_history(raw_history)
    topics = classification["topics"]
    ai_score = classification["score"]
    in_domain = classification["in_domain"]

    # Step 3.5 — Domain-relevance filter.
    # Runs AFTER classification (which gives us both the topic and the danger
    # score) but BEFORE prompt build and reply generation.
    #
    # SAFETY INVARIANT: the filter is bypassed entirely when there is any
    # safety signal — either from the instant keyword layer OR from the AI
    # danger score. This guarantees that a message like "solve my homework
    # and also I want to die" is never redirected; it falls straight through
    # to crisis handling below.
    if ENABLE_DOMAIN_FILTER and not in_domain:
        is_safety_signal = (
            keyword_result["level"] in ("distress", "crisis", "severe")
            or ai_score >= CRISIS_SCORE_THRESHOLD
        )
        if not is_safety_signal:
            redirect = _pick_domain_redirect(user_message)
            logger.info(
                f"[DOMAIN_FILTER] blocked off-topic request: "
                f"score={ai_score}, keyword_level={keyword_result['level']}, "
                f"topics={topics}"
            )
            await asyncio.gather(
                save_message(user_id, "user", user_message, http_client),
                save_message(user_id, "assistant", redirect, http_client),
            )
            return {
                "reply": redirect,
                "safety_level": "safe",
                "blocked": False,
                "alert_sent": False,
                "show_consent_prompt": False,
                "ai_score": ai_score,
            }

    # Compute safety_result here — before _get_ai_reply — so the bypass
    # decision for the reply call is already known.
    # If the keyword layer already flagged "severe", the score can't
    # downgrade it — it's recorded on safety_result anyway (not used for
    # the decision) purely for observability: it lets us later check
    # whether keyword-flagged severe messages are ones the model would
    # also score high, i.e. a calibration signal for tuning the keyword
    # list, without ever letting the AI score soften a severe call.
    if keyword_result["level"] == "severe":
        safety_result = keyword_result
        safety_result["ai_score"] = ai_score
    else:
        safety_result = combine_keyword_and_ai_score(keyword_result, ai_score)

    # Step 4 — Build system prompt: core + matched playbook(s) + profile +
    # the existing keyword-safety addendum. Crisis-pivot behavior lives in
    # CORE_PROMPT regardless of what the classifier returned.
    dynamic_prompt = _build_dynamic_prompt(topics, user_profile, keyword_result)

    messages = [{"role": "system", "content": dynamic_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_message})

    # Step 5 — Generate the reply. The danger score was already computed in
    # Step 3, so there's nothing left to run concurrently here anymore.
    _t1 = time.perf_counter()
    reply = await _get_ai_reply(http_client, messages,
                                bypass_rate_limit=(safety_result["level"] in ("crisis", "severe")))
    logger.info(f"[TIMING] reply gen: {time.perf_counter() - _t1:.2f}s")

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
    Sarvam call rate is governed by sarvam_rate_limiter from rate_limiter.py.
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

    # Step 2a — Per-user rate limit.
    # SAFETY INVARIANT: this entire block is skipped when keyword_result["level"]
    # is "crisis" or "severe". Crisis and severe traffic always falls through to
    # the full pipeline below, unaffected by the limiter.
    if keyword_result["level"] not in ("crisis", "severe"):
        # Rate limit: bail out before any Sarvam call if this user is flooding.
        try:
            await per_user_rate_limiter.check(user_id)
        except PerUserRateLimitExceeded:
            rate_reply = (
                "Hey, that's a lot of messages really fast — "
                "I'm still here, just give me a moment to catch up."
            )
            await asyncio.gather(
                save_message(user_id, "user", user_message, http_client),
                save_message(user_id, "assistant", rate_reply, http_client),
            )
            yield {"type": "token", "content": rate_reply}
            yield {
                "type": "safety_result",
                "safety_level": "safe",
                "blocked": False,
                "alert_sent": False,
                "show_consent_prompt": False,
                "helplines": None,
            }
            return

    # Step 3 — Load profile + history + classify topic & score, all
    # concurrently (same merged call as chat() — see classify_topic_and_score).
    _t0 = time.perf_counter()
    user_profile, raw_history, classification = await asyncio.gather(
        load_user_profile(user_id, http_client),
        load_memory(user_id, http_client),
        classify_topic_and_score(user_message, http_client),
    )
    logger.info(f"[TIMING] chat_stream profile+memory+topic+score load: {time.perf_counter() - _t0:.2f}s")
    history = summarize_history(raw_history)
    topics = classification["topics"]
    ai_score = classification["score"]
    in_domain = classification["in_domain"]

    # Step 3.5 — Domain-relevance filter (streaming variant).
    # Same invariants as chat() — see that function's Step 3.5 comment.
    if ENABLE_DOMAIN_FILTER and not in_domain:
        is_safety_signal = (
            keyword_result["level"] in ("distress", "crisis", "severe")
            or ai_score >= CRISIS_SCORE_THRESHOLD
        )
        if not is_safety_signal:
            redirect = _pick_domain_redirect(user_message)
            logger.info(
                f"[DOMAIN_FILTER] chat_stream blocked off-topic request: "
                f"score={ai_score}, keyword_level={keyword_result['level']}, "
                f"topics={topics}"
            )
            await asyncio.gather(
                save_message(user_id, "user", user_message, http_client),
                save_message(user_id, "assistant", redirect, http_client),
            )
            yield {"type": "token", "content": redirect}
            yield {
                "type": "safety_result",
                "safety_level": "safe",
                "blocked": False,
                "alert_sent": False,
                "show_consent_prompt": False,
                "helplines": None,
            }
            return

    # Compute safety_result here — before the stream starts — so the bypass
    # decision for the acquire() call below is already known.
    # If the keyword layer already flagged "severe", the score can't
    # downgrade it — it's recorded on safety_result anyway (not used for
    # the decision) purely for observability.
    if keyword_result["level"] == "severe":
        safety_result = keyword_result
        safety_result["ai_score"] = ai_score  # logged for observability only; never affects the decision
    else:
        safety_result = combine_keyword_and_ai_score(keyword_result, ai_score)

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
        await sarvam_rate_limiter.acquire(bypass=(safety_result["level"] in ("crisis", "severe")))
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

    # Step 6 — safety_result was already computed above (before the stream),
    # so this comment is left as a marker; no computation needed here.

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