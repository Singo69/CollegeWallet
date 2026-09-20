package com.example.collegedigitalwallet.model

data class OnlineTokenConsumeRequest(
    val token_id: String,
    val nonce: String,
    val expires_at: String,
    val signature: String
)