const express = require('express');
const app=express();
const PORT=3000;
app.get('/',(req,res)=>{
    res.json({message:"Your backend is alive"});
})

app.listen(PORT,()=>{
    console.log(`Server is running on localhost:${PORT}`);
});