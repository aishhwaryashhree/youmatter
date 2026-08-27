require('dotenv').config();
const express = require('express');
const authRoutes = require('./routes/auth');
const requireAuth = require('./middleware/requireAuth');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static('public'));
app.get('/', (req, res) => {
    res.json({ message: "Your backend is alive" });
});
app.get('/api/protected-test', requireAuth, (req, res) => {
    res.json({ message: 'You are authenticated!', user: req.user });
});
app.use('/auth', authRoutes);

app.listen(PORT, () => {
    console.log(`Server is running on localhost:${PORT}`);
});