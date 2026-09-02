const express = require('express');
const router = express.Router();
const { supabaseAdmin } = require('../config/supabaseClient');
const requireAuth = require('../middleware/requireAuth');

/**
 * GET /api/conversation/:user_id
 *
 * Returns all conversations (with their messages, ordered by created_at ASC)
 * that belong to the authenticated user.
 *
 * Authorization rule: the JWT subject (req.user.id set by requireAuth) must
 * match the :user_id URL parameter — users may only read their own history.
 */
router.get('/:user_id', requireAuth, async (req, res) => {
    const { user_id } = req.params;

    // --- Authorization check ---
    if (req.user.id !== user_id) {
        return res.status(403).json({ error: 'Forbidden: you may only access your own conversations.' });
    }

    // --- Fetch conversations + nested messages from Supabase ---
    const { data, error } = await supabaseAdmin
        .from('conversations')
        .select(`
            id,
            title,
            created_at,
            messages (
                id,
                role,
                content,
                safety_level,
                ai_score,
                created_at
            )
        `)
        .eq('user_id', user_id)
        .order('created_at', { ascending: true })                          // conversations: oldest first
        .order('created_at', { ascending: true, foreignTable: 'messages' }); // messages: oldest first

    if (error) {
        console.error('[GET /api/conversation/:user_id] Supabase error:', error);
        return res.status(500).json({ error: 'Failed to retrieve conversations. Please try again later.' });
    }

    // Normalise: guarantee messages is always an array (Supabase returns null when empty)
    const conversations = (data || []).map((conv) => ({
        ...conv,
        messages: conv.messages ?? [],
    }));

    return res.status(200).json({ conversations });
});

module.exports = router;
