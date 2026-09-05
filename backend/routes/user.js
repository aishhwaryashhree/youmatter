const express = require('express');
const router = express.Router();
const { supabaseAdmin } = require('../config/supabaseClient');
const requireAuth = require('../middleware/requireAuth');

router.get('/:user_id', requireAuth, async (req, res) => {
    const { user_id } = req.params;

    // --- Authorization check ---
    if (req.user.id !== user_id) {
        return res.status(403).json({ error: 'Forbidden: you may only access your own profile.' });
    }

    try {
        // 1. Fetch user's auth data to get the email
        const { data: authData, error: authError } = await supabaseAdmin.auth.admin.getUserById(user_id);
        
        if (authError || !authData.user) {
            console.error('[GET /api/user/:user_id] Supabase auth error:', authError);
            return res.status(500).json({ error: 'Internal Server Error.' });
        }

        const email = authData.user.email;

        // 2. Fetch user's profile from the public.profiles table
        const { data: profileData, error: profileError } = await supabaseAdmin
            .from('profiles')
            .select('display_name, guardian_name, guardian_contact, current_concerns, medical_history')
            .eq('user_id', user_id)
            .single();

        // Note: single() returns PGRST116 if no rows are returned, which is fine (user might not have a profile set up yet)
        if (profileError && profileError.code !== 'PGRST116') {
            console.error('[GET /api/user/:user_id] Supabase profiles error:', profileError);
            return res.status(500).json({ error: 'Internal Server Error.' });
        }

        // Merge results
        const result = {
            user_id,
            email,
            display_name: profileData?.display_name || null,
            guardian_name: profileData?.guardian_name || null,
            guardian_contact: profileData?.guardian_contact || null,
            current_concerns: profileData?.current_concerns || null,
            medical_history: profileData?.medical_history || null
        };

        return res.status(200).json(result);

    } catch (err) {
        console.error('[GET /api/user/:user_id] Unexpected error:', err);
        return res.status(500).json({ error: 'Internal Server Error.' });
    }
});

module.exports = router;
