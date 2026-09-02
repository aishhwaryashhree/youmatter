const express = require('express');
const router = express.Router();
const { supabaseAdmin } = require('../config/supabaseClient');
const requireAuth = require('../middleware/requireAuth');

router.post('/', requireAuth, async (req, res) => {
    const { user_id, conversation_id, role, content, safety_level, ai_score } = req.body;

    // --- Authorization check ---
    if (req.user.id !== user_id) {
        return res.status(403).json({ error: 'Forbidden: user_id does not match authenticated user.' });
    }

    // --- Validation check ---
    if (!role || !content) {
        return res.status(400).json({ error: 'Bad Request: role and content are required.' });
    }

    let target_conversation_id = conversation_id;

    if (target_conversation_id) {
        // Verify conversation exists and belongs to the user
        const { data: convData, error: convError } = await supabaseAdmin
            .from('conversations')
            .select('id')
            .eq('id', target_conversation_id)
            .eq('user_id', user_id)
            .single();

        if (convError || !convData) {
            // Note: single() returns an error if no row is found (PGRST116)
            if (convError && convError.code !== 'PGRST116') {
                console.error('[POST /message] Supabase error verifying conversation:', convError);
                return res.status(500).json({ error: 'Internal Server Error.' });
            }
            return res.status(404).json({ error: 'Not Found: Conversation does not exist or does not belong to you.' });
        }
    } else {
        // Create a new conversation for this user
        const { data: newConvData, error: newConvError } = await supabaseAdmin
            .from('conversations')
            .insert([{ user_id }])
            .select('id')
            .single();

        if (newConvError || !newConvData) {
            console.error('[POST /message] Supabase error creating conversation:', newConvError);
            return res.status(500).json({ error: 'Internal Server Error.' });
        }
        
        target_conversation_id = newConvData.id;
    }

    // Insert the new message
    const { data: msgData, error: msgError } = await supabaseAdmin
        .from('messages')
        .insert([{
            conversation_id: target_conversation_id,
            role,
            content,
            safety_level: safety_level !== undefined ? safety_level : null,
            ai_score: ai_score !== undefined ? ai_score : null
        }])
        .select()
        .single();

    if (msgError || !msgData) {
        console.error('[POST /message] Supabase error inserting message:', msgError);
        return res.status(500).json({ error: 'Internal Server Error.' });
    }

    return res.status(201).json({
        message: msgData,
        conversation_id: target_conversation_id
    });
});

module.exports = router;
