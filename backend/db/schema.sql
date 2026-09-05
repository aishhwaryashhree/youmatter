-- YouMatter backend schema
-- conversations + messages tables (multi-session chat history)

CREATE TABLE IF NOT EXISTS public.conversations (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid        NOT NULL REFERENCES auth.users(id),
    title      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON public.conversations (user_id);

CREATE TABLE IF NOT EXISTS public.messages (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid        NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    role            text        NOT NULL,
    content         text        NOT NULL,
    safety_level    text,
    ai_score        numeric,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON public.messages (conversation_id);

-- profiles table (editable user info + guardian contact)

CREATE TABLE IF NOT EXISTS public.profiles (
    user_id         uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name    text,
    guardian_name   text,
    guardian_contact text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS current_concerns text,
ADD COLUMN IF NOT EXISTS medical_history text;